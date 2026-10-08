"""Run native stability/note duration/uncertainty and explicit Windows playback experience checks."""
import argparse
import json
import math
from pathlib import Path
import random
import subprocess
import time
import wave
import struct
from test_audio import RATE, wav, run, tones


def native(exe, folder):
    path = folder / 'events.wav'
    reports = []
    def check(name, audio, expected, *args):
        wav(path, audio)
        frames, _ = run(exe, path, *args)
        ons = [e for e in frames if e.get('type') == 'note-on']
        offs = [e for e in frames if e.get('type') == 'note-off']
        assert [e['midi'] for e in ons] == expected, (name, ons)
        assert len(ons) == len(offs), (name, ons, offs)
        for on, off in zip(ons, offs):
            assert on['id'] == off['id'] and on['voiced'] and not off['voiced']
            assert on['offsetMs'] is None and off['offsetMs'] >= off['onsetMs']
            assert abs(off['durationMs'] - off['offsetMs'] + off['onsetMs']) < .00001
            assert on['confidence'] >= .9
        reports.append({'case': name, 'notes': ons, 'releases': offs})
        return frames, ons, offs
    _, ons, offs = check('held_tone_and_true_release', [0.] * 4800 + tones(440, [1], .4) + [0.] * 4800, [69])
    assert abs(ons[0]['onsetMs'] - 100) <= 10 and abs(offs[0]['offsetMs'] - 500) <= 10
    assert any(True for _ in offs)
    repeated = [(.2 if i < 16800 or i >= 26400 else .03) * math.sin(2 * math.pi * 440 * i / RATE) for i in range(RATE)]
    _, ons, offs = check('same_pitch_rearticulation', repeated, [69,69])
    assert abs(ons[1]['onsetMs'] - 550) <= 10 and offs[0]['reason'] == 'rearticulation'
    ramp = tones(880,[1],.4) + [0.] * 11040
    for i in range(24960):
        amplitude = .005 + .16 * min(1,i/(RATE*.18))
        ramp.append(amplitude*math.sin(2*math.pi*440*i/RATE))
    check('soft_rising_attack_after_louder_note_is_one_attack',ramp,[81,69])
    rapid=[]
    for beat in range(6):
        for i in range(6000):
            # Sixteenth-note amplitude valleys, with no digital silence and
            # no broad debounce interval that could merge these real attacks.
            amp=.16*math.exp(-i/(RATE*.025))+.004
            rapid.append(amp*math.sin(2*math.pi*440*(beat*6000+i)/RATE))
    check('fast_same_pitch_rearticulations_preserved',rapid,[69]*6)
    quiet = [.002 * math.sin(2 * math.pi * 440 * i / RATE) for i in range(19200)] + [0.] * 4800
    _, ons, offs = check('quiet_periodic_note_releases', quiet, [69])
    assert abs(offs[0]['offsetMs'] - 400) <= 10
    phase = 0
    legato = [0.] * 4800
    for i in range(38400):
        hz = 440 if i < 19200 else 440 * 2 ** (3/12)
        legato.append(.15 * math.sin(phase)); phase += 2 * math.pi * hz / RATE
    _, ons, offs = check('continuous_legato_note_identity', legato, [69,72], '--window', 8192)
    assert ons[1]['reason'] == 'pitch-change' and offs[0]['reason'] == 'pitch-change'
    phase = 0
    octave = []
    for i in range(38400):
        hz = 440 if i < 19200 else 880
        octave.append(.15 * math.sin(phase)); phase += 2 * math.pi * hz / RATE
    _, ons, _ = check('strong_continuous_octave_legato_is_allowed', octave, [69,81])
    assert ons[1]['reason'] == 'pitch-change'
    fading = []
    for i in range(RATE):
        t = i / RATE
        fundamental = .2 if t < .3 else .2 * max(0, 1 - (t - .3) / .2)
        overtone = .003
        fading.append(fundamental * math.sin(2*math.pi*440*t) + overtone * math.sin(2*math.pi*880*t))
    frames, _, _ = check('fading_fundamental_leaves_uncertain_overtone', fading, [69])
    assert any(e.get('type') == 'uncertainty' and e['reason'] == 'octave-ambiguity' for e in frames)
    phase = 0; vibrato = []
    for i in range(38400):
        hz = 440 * 2 ** ((.54 * math.sin(2 * math.pi * 5 * i / RATE)) / 12)
        vibrato.append(.15 * math.sin(phase)); phase += 2 * math.pi * hz / RATE
    check('intonation_boundary_hysteresis', vibrato, [69])
    frames, ons, _ = check('custom_concert_tuning', tones(442,[1],.4), [69], '--a4',442)
    assert abs(ons[0]['cents']) < 1
    rand = random.Random(7826)
    frames, _, _ = check('aperiodic_audio_is_uncertain', [rand.uniform(-.08,.08) for _ in range(24000)], [])
    uncertain = [e for e in frames if e.get('type') == 'uncertainty']
    assert len(uncertain) == 2 and uncertain[0]['offsetMs'] is None and uncertain[-1]['offsetMs'] == 500
    assert uncertain[0]['id'] == uncertain[1]['id'] and uncertain[0]['voiced'] is None
    frames, _, _ = check('digital_rest_is_rest_not_uncertainty', [0.] * 24000, [])
    assert not any(e.get('type') == 'uncertainty' for e in frames)
    return reports


def hardware(exe, folder):
    listing = subprocess.run([str(exe),'--list-devices'], capture_output=True, text=True, encoding='utf-8', timeout=10)
    assert listing.returncode == 0, listing.stdout
    devices = json.loads(listing.stdout)
    assert devices['capture'] and devices['playback']
    path = folder / 'native-reference.wav'
    # Known synthetic reference: no user sound or speech is recorded/interpreted.
    wav(path, tones(440,[1],1.0))
    process = subprocess.Popen([str(exe),'--play',str(path),'--start-ms','200','--end-ms','800'],
                               stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    ready = json.loads(process.stdout.readline())
    assert ready.get('type') == 'ready' and ready.get('mode') == 'playback', ready
    time.sleep(.8)
    stdout, _ = process.communicate(input='STOP\n',timeout=8)
    frames = [ready,*[json.loads(line) for line in stdout.splitlines() if line.strip()]]
    assert process.returncode == 0 and frames[-1]['type'] == 'stopped'
    assert frames[-1]['sampleCount'] == 28800, frames[-1]
    # Verify the actual Windows renderer output using WASAPI loopback, rather
    # than accepting only a process status as proof that playback works.
    recording = folder / 'loopback-reference.wav'
    capture = subprocess.Popen([str(exe),'--loopback','--record',str(recording)],
                               stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    first = json.loads(capture.stdout.readline())
    assert first.get('type') == 'ready', first
    player = subprocess.Popen([str(exe),'--play',str(path)],stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    play_ready = json.loads(player.stdout.readline())
    assert play_ready.get('type') == 'ready', play_ready
    time.sleep(1.2)
    player_output, _ = player.communicate(input='STOP\n',timeout=8)
    time.sleep(.1)
    capture_output, _ = capture.communicate(input='STOP\n',timeout=8)
    assert player.returncode == 0 and capture.returncode == 0, (player_output,capture_output)
    captured_frames, _ = run(exe,recording)
    notes = [e for e in captured_frames if e.get('type') == 'note-on']
    assert any(e['midi'] == 69 for e in notes), notes
    with wave.open(str(recording),'rb') as saved:
        assert saved.getnframes() > RATE and saved.getsampwidth() == 2
    report={'devices': {'capture':len(devices['capture']),'playback':len(devices['playback'])},
            'rangePlaybackSamples':28800,'loopbackDetectedMidi':[e['midi'] for e in notes],
            'verified': 'Actual Windows renderer output captured through WASAPI loopback and native note events'}
    recording.unlink()
    # A continuous click uses the same renderer; verify four measured beat
    # spacings in recorded output, not just that its process remains alive.
    recording = folder / 'loopback-metronome.wav'
    capture = subprocess.Popen([str(exe),'--loopback','--record',str(recording)],
                               stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    assert json.loads(capture.stdout.readline())['type'] == 'ready'
    player = subprocess.Popen([str(exe),'--metronome','120'],stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    assert json.loads(player.stdout.readline())['mode'] == 'metronome'
    time.sleep(2.25)
    player_output, _ = player.communicate(input='STOP\n', timeout=8)
    capture_output, _ = capture.communicate(input='STOP\n', timeout=8)
    assert player.returncode == capture.returncode == 0, (player_output,capture_output)
    lines=[json.loads(line) for line in player_output.splitlines() if line.strip()]
    assert lines[-1]['type']=='stopped' and lines[-1]['sampleCount'] >= 96000
    with wave.open(str(recording),'rb') as saved:
        pcm=struct.unpack('<'+'h'*saved.getnframes(),saved.readframes(saved.getnframes()))
    envelope=[math.sqrt(sum(s*s for s in pcm[i:i+480])/len(pcm[i:i+480])) for i in range(0,len(pcm),480)]
    attacks=[]
    for i, energy in enumerate(envelope):
        if energy > max(envelope)*.2 and (not attacks or i-attacks[-1] > 20): attacks.append(i)
    intervals=[(b-a)*10 for a,b in zip(attacks,attacks[1:])]
    assert len(intervals)>=3 and all(480<=ms<=520 for ms in intervals), intervals
    report['metronomeBeatIntervalsMs']=intervals
    report['metronomeSamples']=lines[-1]['sampleCount']
    recording.unlink()
    recording = folder / 'loopback-resumed-metronome.wav'
    capture=subprocess.Popen([str(exe),'--loopback','--record',str(recording)],
                             stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    assert json.loads(capture.stdout.readline())['type']=='ready'
    player=subprocess.Popen([str(exe),'--metronome','120','--start-ms','250'],
                            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    ready=json.loads(player.stdout.readline())
    assert ready['mode']=='metronome' and ready['startMs']==250
    time.sleep(1.4)
    data,_=player.communicate(input='STOP\n',timeout=8)
    capture_data,_=capture.communicate(input='STOP\n',timeout=8)
    assert player.returncode==capture.returncode==0,(data,capture_data)
    with wave.open(str(recording),'rb') as saved:
        pcm=struct.unpack('<'+'h'*saved.getnframes(),saved.readframes(saved.getnframes()))
    envelope=[math.sqrt(sum(s*s for s in pcm[i:i+480])/len(pcm[i:i+480])) for i in range(0,len(pcm),480)]
    attacks=[]
    for i,energy in enumerate(envelope):
        if energy>max(envelope)*.2 and (not attacks or i-attacks[-1]>20):attacks.append(i)
    intervals=[(b-a)*10 for a,b in zip(attacks,attacks[1:])]
    assert len(attacks)>=3 and 230<=attacks[0]*10<=340 and all(480<=ms<=520 for ms in intervals),(attacks,intervals)
    report['resumedMetronomeFirstClickMs']=attacks[0]*10
    report['resumedMetronomeBeatIntervalsMs']=intervals
    progress=[json.loads(line) for line in data.splitlines() if line.strip()]
    assert all(abs(e['positionMs']-e['timeMs']-250)<.00001 for e in progress if e['type']=='playback')
    recording.unlink()
    # STOP and EOF both terminate a partially played file, preserving rendered
    # sample totals and releasing the same device for the next invocation.
    for control in ('STOP\n',''):
        player=subprocess.Popen([str(exe),'--play',str(path)],stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        assert json.loads(player.stdout.readline())['type']=='ready'
        time.sleep(.12)
        data,_=player.communicate(input=control,timeout=8)
        last=json.loads(data.splitlines()[-1])
        assert player.returncode==0 and last['type']=='stopped' and 0<last['sampleCount']<24000,last
    report['stopAndEofPartialPlayback']=True
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--exe',type=Path,default=Path(__file__).parent/'build'/'NoteLiteAudio.exe')
    p.add_argument('--output',type=Path,default=Path(__file__).parent/'test-output'/'events')
    p.add_argument('--hardware',action='store_true')
    a=p.parse_args(); folder=a.output.resolve(); folder.mkdir(parents=True,exist_ok=True)
    report={'syntheticEvents':native(a.exe.resolve(),folder)}
    if a.hardware: report['windowsExperience']=hardware(a.exe.resolve(),folder)
    target=folder/'events-results.json'; target.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'cases':len(report['syntheticEvents']),'hardware':report.get('windowsExperience'),'report':str(target)}))
if __name__=='__main__':main()
