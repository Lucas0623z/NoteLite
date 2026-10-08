"""Exercise the actual local HTTP, Partitura, judge, recording archive and native playback.

Run against an explicitly launched diagnostic studio, never a user's active practice:
python tools/windows-practice-smoke.py --url http://127.0.0.1:PORT/TOKEN/ --output work/windows-e2e.json
"""
import argparse
import io
import json
from pathlib import Path
import time
import urllib.request
import wave
import zipfile


def xml(pitches, instrument="Flute"):
    body=[]
    for index,chord in enumerate(pitches):
        notes=[]
        for i,(step,alter,octave) in enumerate(chord):
            notes.append(f'<note>{"<chord/>" if i else ""}<pitch><step>{step}</step><alter>{alter}</alter><octave>{octave}</octave></pitch><duration>1</duration><type>quarter</type></note>')
        body.append(f'<measure number="{index+1}"><attributes><divisions>1</divisions><time><beats>1</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes>{"".join(notes)}</measure>')
    return '<?xml version="1.0"?><score-partwise version="4.0"><work><work-title>Windows 陪练实测</work-title></work><part-list><score-part id="P1"><part-name>'+instrument+'</part-name></score-part></part-list><part id="P1">'+''.join(body)+'</part></score-partwise>'


class Service:
    def __init__(self,url):self.url=url;self.origin=url.split('/')[0]+'//'+url.split('/')[2]
    def request(self,route,body=None,raw=None):
        headers={'Origin':self.origin}
        if raw is not None:data=raw;headers['Content-Type']='application/octet-stream'
        elif body is not None:data=json.dumps(body).encode();headers['Content-Type']='application/json'
        else:data=None
        with urllib.request.urlopen(urllib.request.Request(self.url+route,data=data,headers=headers),timeout=300) as response:
            content=response.read()
            return json.loads(content) if response.headers.get_content_type()=='application/json' else content


def run(url,output):
    service=Service(url);results=[]
    config={'verified':True,'part':'P1','from':1,'to':3,'bpm':240,'a4':440,'mode':'wait','input':'keyboard','instrument':'flute','variant':'concert','feedbackPolicy':'active'}
    sequence=[[('C',0,4)],[('D',0,4)],[('E',0,4)]]
    service.request('score/prepare',{'xml':xml(sequence),'title':'Windows 陪练实测'})
    state=service.request('practice/start',config)
    assert state['total']==3 and state['groups'][0]['notes'][0]['sourceNoteId']=='P1:0'
    state=service.request('practice/event',{'type':'note-on','id':'wrong','midi':61})
    assert state['currentIndex']==0 and any(e['kind']=='wrong' for e in state['errors'])
    service.request('practice/event',{'type':'note-off','id':'wrong','midi':61})
    for midi in (60,62,64):
        state=service.request('practice/event',{'type':'note-on','id':f'k{midi}','midi':midi})
        if midi==64:assert state['active'] and state['awaitingRelease']
        state=service.request('practice/event',{'type':'note-off','id':f'k{midi}','midi':midi})
    report=service.request('practice/finish',{})
    assert report['completed'] and len(report['errors'])==1
    take=report['takeId'];assert service.request(f'takes/report?id={take}')['errors']==report['errors']
    with zipfile.ZipFile(io.BytesIO(service.request(f'takes/package?id={take}'))) as package:
        assert {'source.musicxml','practice.json','report.json'}<=set(package.namelist())
        assert json.loads(package.read('practice.json'))['format']=='notelite-practice-package'
    results.append({'case':'wrong note does not advance; correct recovery; last release; persistent package','passed':True,'takeId':take})

    service.request('score/prepare',{'xml':xml([[('C',0,4)],[('C',0,4)],[('C',0,4)]])})
    service.request('practice/start',config)
    first=service.request('practice/event',{'type':'note-on','id':'hold','midi':60})
    duplicate=service.request('practice/event',{'type':'note-on','id':'hold','midi':60})
    assert first['currentIndex']==duplicate['currentIndex']==1
    service.request('practice/event',{'type':'note-off','id':'hold','midi':60})
    for i in (2,3):
        service.request('practice/event',{'type':'note-on','id':f'repeat{i}','midi':60})
        service.request('practice/event',{'type':'note-off','id':f'repeat{i}','midi':60})
    report=service.request('practice/finish',{});assert report['completed'] and not report['errors']
    results.append({'case':'held note cannot satisfy three repeated attacks','passed':True})

    service.request('score/prepare',{'xml':xml([[('C',0,4),('E',0,4)],[('G',0,4)]],'Piano')})
    strict={**config,'to':2,'mode':'tempo','instrument':'piano'}
    service.request('practice/start',strict);time.sleep(1.025)
    service.request('practice/event',{'type':'note-on','id':'chordC','midi':60});time.sleep(.24)
    service.request('practice/event',{'type':'note-off','id':'chordC','midi':60})
    state=service.request('practice/event',{'type':'note-on','id':'nextG','midi':67})
    service.request('practice/event',{'type':'note-off','id':'nextG','midi':67})
    report=service.request('practice/finish',{})
    assert any(e['kind']=='missing' and 64 in e['expected'] for e in report['errors'])
    assert not any(e['kind']=='wrong' and e.get('played')==67 for e in report['errors'])
    results.append({'case':'missing chord tone retains identity; following G recovers without cascade','passed':True,'errors':report['errors']})

    # Actual Windows device capture and native file playback are exercised, but
    # room silence cannot serve as musical accuracy ground truth.
    service.request('score/prepare',{'xml':xml(sequence)})
    service.request('practice/start',{**config,'input':'microphone'})
    service.request('audio/start?min=55&max=2000&window=8192&record=true&a4=440',{})
    time.sleep(.8);service.request('audio/stop',{})
    report=service.request('practice/finish',{});assert report['hasRecording']
    audio=service.request(f'takes/recording?id={report["takeId"]}')
    with wave.open(io.BytesIO(audio)) as wav:assert wav.getnframes()>0 and wav.getsampwidth()==2
    state=service.request('playback/take',{'id':report['takeId'],'startMs':0,'endMs':300});assert state['playing']
    time.sleep(.45);assert not service.request('playback/state')['playing']
    results.append({'case':'actual microphone retained WAV; native 300ms take replay stops','passed':True,'takeId':report['takeId'],'recordingBytes':len(audio)})

    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({'schemaVersion':1,'passed':len(results),'results':results,'limitations':'Device lifecycle and controlled event behavior; no human musician accuracy claim.'},ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'passed':len(results),'output':str(output)},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--url',required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();run(args.url,args.output)
