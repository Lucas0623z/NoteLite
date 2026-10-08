"""Reproducible real-engine comparison on controlled actual-instrument excerpts.

Run with the installed runtime's Python. No network or score-assisted detection:
  local-analysis/runtime/python/python.exe tools/recorded-engine-quality.py
Expected and performed MIDI labels come from the input manifest, not a detector.
Actual samples have no calibrated cents ground truth; a synthetic +25c check in
the installation marker is reported separately. This does not exercise HTTP/UI.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import time


def call(home, operation, source, output, options):
    config = output.with_suffix('.options.json')
    config.write_text(json.dumps(options),encoding='utf8')
    started=time.monotonic()
    process=subprocess.run([str(home/'python/python.exe'),str(home/'analyze.py'),
                            '--operation',operation,'--input',str(source.resolve()),
                            '--output',str(output.resolve()),'--options',str(config.resolve())],
                           capture_output=True,timeout=300)
    output.with_suffix('.log').write_bytes(process.stdout+process.stderr)
    if process.returncode:
        raise RuntimeError(f'{operation} failed ({process.returncode}): {(process.stdout+process.stderr).decode("utf8",errors="replace")[-1200:]}')
    return json.loads(output.read_text(encoding='utf8')),round(time.monotonic()-started,3)


def music_xml(pitches,bpm):
    spells=[('C',0),('C',1),('D',0),('D',1),('E',0),('F',0),('F',1),('G',0),('G',1),('A',0),('A',1),('B',0)]
    notes=[]
    for midi in pitches:
        step,alter=spells[midi%12]
        notes.append(f'<note><pitch><step>{step}</step><alter>{alter}</alter><octave>{midi//12-1}</octave></pitch><duration>1</duration><type>quarter</type></note>')
    return ('<score-partwise version="3.1"><part-list><score-part id="P1"><part-name>Flute</part-name></score-part></part-list><part id="P1"><measure number="1"><attributes><divisions>1</divisions><time><beats>'+str(len(pitches))+'</beats><beat-type>4</beat-type></time></attributes><direction><sound tempo="'+str(bpm)+'"/></direction>'+''.join(notes)+'</measure></part></score-partwise>')


def detection_metrics(truth,notes,tolerance=.2):
    """One exact MIDI attack can satisfy one manifest attack, never two repeats."""
    from scipy.optimize import linear_sum_assignment
    import numpy as np
    if not truth or not notes:
        return {'expectedPerformedAttacks':len(truth),'detectedAttacks':len(notes),'exactPitchAttacks':0,
                'missedPerformedAttacks':list(range(len(truth))),'extraDetectedAttacks':list(range(len(notes))),'pairs':[]}
    costs=np.full((len(truth),len(notes)),1e6)
    for i,expected in enumerate(truth):
        for j,detected in enumerate(notes):
            error=abs(expected['onset']-detected['onset'])
            if expected['midi']==detected['midi'] and error<=tolerance:
                costs[i,j]=error
    rows,columns=linear_sum_assignment(costs)
    pairs=[]
    for i,j in zip(rows,columns):
        if costs[i,j]>=1e6:continue
        expected,detected=truth[i],notes[j]
        pair={'performedIndex':int(i),'detectionIndex':int(j),'midi':detected['midi'],
              'onsetErrorMs':round((detected['onset']-expected['onset'])*1000,3),
              'durationErrorMs':round((detected['duration']-expected['duration'])*1000,3)}
        for field in ('cents','confidence','frequency','centsSampleCount','centsSpread','centsSpreadStatistic','centsReliability','pitchSource','centsResolution'):
            if field in detected:pair[field]=detected[field]
        pairs.append(pair)
    matched_truth={p['performedIndex'] for p in pairs};matched_detection={p['detectionIndex'] for p in pairs}
    return {'expectedPerformedAttacks':len(truth),'detectedAttacks':len(notes),'exactPitchAttacks':len(pairs),
            'missedPerformedAttacks':[i for i in range(len(truth)) if i not in matched_truth],
            'extraDetectedAttacks':[i for i in range(len(notes)) if i not in matched_detection],
            'medianAbsoluteOnsetErrorMs':round(statistics.median(abs(p['onsetErrorMs']) for p in pairs),3) if pairs else None,
            'medianAbsoluteDurationErrorMs':round(statistics.median(abs(p['durationErrorMs']) for p in pairs),3) if pairs else None,'pairs':pairs}


def alignment_metrics(score,notes,baseline):
    lookup={n['occurrenceId']:n for n in score['notes']}
    pairs=[]
    for item in baseline['pairs']:
        expected=lookup[item['occurrenceId']];detected=notes[item['detectionIndex']]
        difference=detected['midi']-expected['midi']
        pairs.append(item|{'expectedMidi':expected['midi'],'detectedMidi':detected['midi'],
                          'exactMidi':difference==0,'octaveSubstitution':difference!=0 and difference%12==0,
                          'semitoneDifference':difference,'detectedOnset':detected['onset']})
    return {'algorithm':baseline['metadata'],'correspondences':len(pairs),'exactMidiPairs':sum(p['exactMidi'] for p in pairs),
            'substitutions':sum(not p['exactMidi'] for p in pairs),'octaveSubstitutions':sum(p['octaveSubstitution'] for p in pairs),
            'missing':baseline['missing'],'extra':baseline['extra'],'pairs':pairs}


def run(home,manifest_path,folder):
    manifest=json.loads(manifest_path.read_text(encoding='utf8'));folder.mkdir(parents=True,exist_ok=True)
    proof=json.loads((home/'runtime-ready.json').read_text(encoding='utf8'))
    report={'schemaVersion':1,'method':manifest['method'],
            'runtimeManifest':proof,
            'codeSha256':{name:hashlib.sha256((home/name).read_bytes()).hexdigest() for name in
                          ('analyze.py','mono_analysis.py','onset_evidence.py','pitch_refinement.py','score_tools.py','crepe_onnx.py')},
            'limits':['Controlled excerpts assembled from actual instrument samples, not a live musician test.',
                      'Manifest pitches/onsets/durations are assembly labels; actual sample cents have no calibrated ground truth.',
                      'Detection exact-pitch/onset matching and baseline identity matching are evaluated separately.',
                      'A baseline correspondence is not counted correct unless its detected MIDI equals expected MIDI.',
                      'This comparison does not validate the application HTTP/common grading or UI.'],
            'groundTruthCents':None,'known25CentSyntheticCalibration':proof['smoke'],'cases':[]}
    for case in manifest['cases']:
        result={'name':case['name'],'expectedScoreMidi':case['expected'],'performed':case['performed'],'sources':case['sources'],
                'bpm':case['bpm'],'engines':{}}
        wave=Path(case['file']);result['waveSha256']=hashlib.sha256(wave.read_bytes()).hexdigest()
        score_file=folder/(case['name']+'.musicxml');score_file.write_text(music_xml(case['expected'],case['bpm']),encoding='utf8')
        score,_=call(home,'normalize',score_file,folder/(case['name']+'.score.json'),{'instrument':'flute','variant':'concert','expandRepeats':False})
        assert [n['sourceNoteId'] for n in score['notes']]==[f'P1:{i}' for i in range(len(case['expected']))]
        assert [n['midi'] for n in score['notes']]==case['expected']
        for engine in ('basic-pitch','pyin','crepe','aubio'):
            threshold=.4 if engine=='basic-pitch' else .5
            audio,elapsed=call(home,'analyze',wave,folder/(case['name']+'.'+engine+'.notes.json'),
                               {'engine':engine,'a4':440,'minHz':130.8,'maxHz':4186,'threshold':threshold,
                                'input':'recording','verified':True,'instrument':'flute'})
            notes=[n for n in audio['notes'] if n['confidence']>=threshold and not n.get('reviewRequired')]
            measured=detection_metrics(case['performed'],notes)
            evaluation={'secondsToAnalyze':elapsed,'rawNoteCount':len(audio['notes']),'confidentNoteCount':len(notes),
                        'unjudgedLowConfidenceOrOnsetCount':len(audio['notes'])-len(notes),'detection':measured,
                        'originalModelNoteCount':len(audio.get('rawNotes',audio['notes'])),'postprocessing':audio.get('postprocessing'),
                        'warnings':audio.get('warnings',[]),'supportedPitchRange':audio.get('supportedPitchRange'),'baselines':{}}
            for baseline in ('parangonar','nakamura'):
                payload=folder/(case['name']+'.'+engine+'.alignment-input.json')
                payload.write_text(json.dumps({'score':score,'performance':notes}),encoding='utf8')
                matched,_=call(home,'align',payload,folder/(case['name']+'.'+engine+'.'+baseline+'.json'),{'backend':baseline})
                evaluation['baselines'][baseline]=alignment_metrics(score,notes,matched)
            result['engines'][engine]=evaluation
            print(json.dumps({'case':case['name'],'engine':engine,'detected':len(notes),
                              'exactPerformedAttacks':measured['exactPitchAttacks'],'truthAttacks':len(case['performed']),
                              'baselineExactMidi':{b:x['exactMidiPairs'] for b,x in evaluation['baselines'].items()} }),flush=True)
        report['cases'].append(result)
    (folder/'quality-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    lines=['# Recorded engine comparison','',manifest['method'],'',
           'Cents ground truth for these samples is unavailable. Synthetic +25c calibration is recorded separately. A correspondence with the wrong MIDI is a substitution, not a correct note.','',
           '|Case|Engine|Exact performed attacks|Confident detected|Extra detections|Onset median abs ms|Parangonar exact/substitution|Nakamura exact/substitution|',
           '|---|---|---:|---:|---:|---:|---:|---:|']
    for case in report['cases']:
        for engine,data in case['engines'].items():
            d=data['detection'];p=data['baselines']['parangonar'];n=data['baselines']['nakamura']
            lines.append(f"|{case['name']}|{engine}|{d['exactPitchAttacks']}/{d['expectedPerformedAttacks']}|{data['confidentNoteCount']}|{len(d['extraDetectedAttacks'])}|{d.get('medianAbsoluteOnsetErrorMs')}|{p['exactMidiPairs']}/{p['substitutions']}|{n['exactMidiPairs']}/{n['substitutions']}|")
    (folder/'quality-summary.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    return report


if __name__=='__main__':
    repository=Path(__file__).resolve().parent.parent
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,default=repository/'local-analysis/runtime')
    parser.add_argument('--manifest',type=Path,default=repository/'work/windows-performances/manifest.json')
    parser.add_argument('--output',type=Path,default=repository/'work/recorded-engine-quality')
    args=parser.parse_args()
    run(args.runtime.resolve(),args.manifest.resolve(),args.output.resolve())
