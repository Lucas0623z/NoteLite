"""Actual HTTP model inference -> common judge -> saved package and replay evidence.

Use only a diagnostic Studio with an isolated notelite.practice.home.
Audio fixture manifest describes edited real instrument excerpts, not live players.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from urllib.parse import urlencode


def run(url,manifest_path,output):
    spec=importlib.util.spec_from_file_location('studio_smoke',Path(__file__).with_name('windows-practice-smoke.py'))
    smoke=importlib.util.module_from_spec(spec);spec.loader.exec_module(smoke)
    service=smoke.Service(url);manifest=json.loads(manifest_path.read_text(encoding='utf8'));results=[]
    capabilities=service.request('engines.json')
    assert all(capabilities['capabilities'][x] for x in ('partitura','basic-pitch','pyin','crepe','aubio','parangonar','nakamura'))
    spell=[('C',0),('C',1),('D',0),('D',1),('E',0),('F',0),('F',1),('G',0),('G',1),('A',0),('A',1),('B',0)]
    for case in manifest['cases']:
        notes=[]
        for midi in case['expected']:
            step,alter=spell[midi%12]
            notes.append(f'<note><pitch><step>{step}</step><alter>{alter}</alter><octave>{midi//12-1}</octave></pitch><duration>52</duration><type>quarter</type></note><note><rest/><duration>23</duration></note>')
        xml='<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Flute</part-name></score-part></part-list><part id="P1"><measure number="1"><attributes><divisions>75</divisions><time><beats>6</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes>'+''.join(notes)+'</measure></part></score-partwise>'
        for engine in ('basic-pitch','pyin','crepe','aubio'):
            service.request('score/prepare',{'xml':xml,'title':case['name']})
            options={'verified':True,'part':'P1','from':1,'to':1,'bpm':case['bpm'],'a4':440,'mode':'tempo','input':'recording','instrument':'flute','variant':'concert','engine':engine,'baseline':'parangonar','feedbackPolicy':'active','minHz':130.8,'maxHz':4186}
            report=service.request('analysis?'+urlencode({'options':json.dumps(options)}),raw=Path(case['file']).read_bytes())
            assert report['takeId'] and report['hasRecording']
            assert report['transcription']['engine']==engine and report['baseline']['engine']=='parangonar'
            assert all(e.get('sourceNoteIds') and e.get('occurrenceIds') and 'replayMs' in e for e in report['errors'] if e['kind']!='extra')
            assert service.request('takes/report?id='+report['takeId'])['errors']==report['errors']
            counts={kind:sum(e['kind']==kind and not e.get('resolved') for e in report['errors']) for kind in ('wrong','missing','extra','early','late','short','long','intonation','uncertain')}
            # Recognition uncertainty is recorded, not hidden behind a success assertion.
            expected_feedback={key:0 for key in counts}
            if case['name']=='wrong_octave_flute':expected_feedback['wrong']=1
            if case['name']=='missed_flute':expected_feedback['missing']=1
            assert counts==expected_feedback,(case['name'],engine,counts)
            expected_attacks=5 if case['name']=='missed_flute' else 6
            assert len(report['transcription']['notes'])==expected_attacks,(case['name'],engine)
            entry={'case':case['name'],'engine':engine,'takeId':report['takeId'],'completed':report['completed'],'feedback':counts,'notes':len(report['transcription']['notes']),'errors':report['errors']}
            results.append(entry);print(json.dumps({k:v for k,v in entry.items() if k!='errors'}),flush=True)
    # Exercise the persisted JSON boundary, not just a fresh inference request.
    take=next(item for item in results if item['engine']=='aubio' and item['case']=='correct_repeated_flute')['takeId']
    before=service.request('takes/recording?id='+take)
    original_plan=service.request('takes/plan?id='+take)
    rechecked=service.request('takes/recheck',{'id':take,'engine':'pyin','baseline':'nakamura'})
    assert rechecked['takeId']==take and rechecked['transcription']['engine']=='pyin' and rechecked['baseline']['engine']=='nakamura'
    assert not any(not error.get('resolved') for error in rechecked['errors'])
    assert before==service.request('takes/recording?id='+take)
    assert [g['notes'][0]['sourceNoteId'] for g in original_plan['groups']]==[g['notes'][0]['sourceNoteId'] for g in service.request('takes/plan?id='+take)['groups']]
    recheck={'passed':True,'takeId':take,'engine':'pyin','baseline':'nakamura','recordingSha256':hashlib.sha256(before).hexdigest(),'sourceNoteIdsPreserved':True}
    print(json.dumps({'persistedRecheck':recheck}),flush=True)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({'method':manifest['method'],'capabilities':capabilities,'cases':results,'persistedRecheck':recheck},ensure_ascii=False,indent=2),encoding='utf8')


if __name__=='__main__':
    root=Path(__file__).resolve().parent.parent
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--url',required=True);parser.add_argument('--manifest',type=Path,default=root/'work/windows-performances/manifest.json');parser.add_argument('--output',type=Path,default=root/'work/windows-recorded-e2e.json')
    args=parser.parse_args();run(args.url,args.manifest,args.output)
