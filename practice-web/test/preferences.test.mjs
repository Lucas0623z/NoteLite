import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {DOMParser} from '@xmldom/xmldom';
import {PitchDetector} from 'pitchy';
import {unzipSync,strFromU8} from 'fflate';
import {parseScore,selectGroups,inferInstrument,isPolyphonic,noteName} from '../src/score.js';
import {PracticeSession,PitchGate} from '../src/session.js';
import {NativeInputBridge} from '../src/native-bridge.js';

// Execute the production bridge, settings and transport together. Only browser
// drawing/audio devices are replaced; MusicXML parsing and note grading are real.
const appSource=readFileSync(new URL('../src/app.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'');
const note=(step,chord=false)=>`<note>${chord?'<chord/>':''}<pitch><step>${step}</step><octave>4</octave></pitch><duration>1</duration></note>`;
const xml=(chord=false)=>`<score-partwise><part-list><score-part id="P1"><part-name>Unknown</part-name></score-part></part-list><part id="P1"><measure number="1"><attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>${note('C')}${note(chord?'E':'D',chord)}</measure></part></score-partwise>`;

function harness(){
  const nodes=new Map(),timeouts=[],intervals=[],oscillators=[];
  let time=1000,audioContexts=0;
  const labels={auto:'按谱面自动判断',piano:'钢琴 / 键盘',guitar:'吉他 / 弹拨乐',strings:'提琴',winds:'管乐',other:'其他有固定音高乐器'};
  function element(id){
    if(!nodes.has(id)){
      const node={value:'',textContent:'',open:false,checked:false,clientWidth:800,options:[],dataset:{},classList:{toggle(){}},
        setAttribute(){},addEventListener(){},append(){},querySelector(){return{src:''};},focus(){},
        showModal(){this.open=true;},close(){this.open=false;},
        replaceChildren(...options){this.options=options;},add(option){this.options.push(option);}};
      Object.defineProperty(node,'selectedOptions',{get(){return node.options.filter(option=>option.value===node.value).length?
        node.options.filter(option=>option.value===node.value):[{textContent:labels[node.value]||node.value}];}});
      nodes.set(id,node);
    }
    return nodes.get(id);
  }
  for(const [id,value] of Object.entries({input:'keyboard',mode:'wait',bpm:'60',a4:'440',from:'1',to:'1'}))element(id).value=value;
  const cursor={reset(){},show(){},hide(){},Iterator:{EndReached:true,CurrentSourceTimestamp:{RealValue:0}}};
  class Renderer{constructor(){this.cursor=cursor;}async load(){}setOptions(){}render(){}}
  class Audio{
    constructor(){audioContexts++;this.currentTime=0;this.state='running';this.destination={};}
    createOscillator(){const oscillator={frequency:{value:0},connect(){},disconnect(){},start(){},stop(){}};oscillators.push(oscillator);return oscillator;}
    createGain(){return{gain:{setValueAtTime(){},linearRampToValueAtTime(){},exponentialRampToValueAtTime(){}},connect(){},disconnect(){}};}
    async resume(){}close(){}
  }
  const window={webkit:{messageHandlers:{noteLite:{postMessage(){}}}},addEventListener(){}};
  runInNewContext(appSource,{
    OSMD:{OpenSheetMusicDisplay:Renderer},PitchDetector,unzipSync,strFromU8,
    parseScore:(text)=>parseScore(text,DOMParser),selectGroups,inferInstrument,isPolyphonic,noteName,
    PracticeSession,PitchGate,NativeInputBridge,collectScoreNotes:()=>[],colorScoreGroup(){},resetScoreColors(){},
    window,document:{getElementById:element,body:element('body'),querySelectorAll:()=>[],createElement:()=>element(Symbol()),addEventListener(){}},
    navigator:{},AudioContext:Audio,performance:{now:()=>time},matchMedia:()=>({matches:false}),
    Option:class{constructor(text,value){this.textContent=text;this.value=value;}},ResizeObserver:class{observe(){}},
    requestAnimationFrame:()=>0,cancelAnimationFrame(){},
    setTimeout:(callback,delay)=>{timeouts.push({callback,delay});return timeouts.length;},clearTimeout(){},
    setInterval:(callback,delay)=>{intervals.push({callback,delay});return intervals.length;},clearInterval(){},
    atob:(text)=>Buffer.from(text,'base64').toString('binary'),TextDecoder,Date,DOMParser
  });
  return{api:window.NoteLiteNative,element,oscillators,timeouts,intervals,
    get audioContexts(){return audioContexts;},setTime(value){time=value;},
    async load(chord=false){await window.NoteLiteNative.loadScore(Buffer.from(xml(chord)).toString('base64'),'Test','score-1');}};
}

test('silent and audible tempo preferences keep the same four-beat grading clock',async()=>{
  for(const soundEnabled of [false,true]){
    const app=harness();await app.load();app.api.applyPreferences({soundEnabled});
    app.element('input').value='keyboard';app.element('mode').value='tempo';app.element('bpm').value='60';app.element('verified').checked=true;
    await app.element('start').onclick();
    assert.equal(app.audioContexts,soundEnabled?1:0,'Silent timing must not require an audio device');
    assert.equal(app.oscillators.length,soundEnabled?4:0,'Only audible preparation schedules tones');
    const firstBeat=app.timeouts.find(timer=>timer.delay===4000);assert.ok(firstBeat,'The first beat remains four seconds after start at 60 BPM');
    app.setTime(4500);app.api.noteOn(60);
    app.setTime(5000);firstBeat.callback();
    const metronome=app.intervals.find(timer=>timer.delay===1000);assert.ok(metronome);metronome.callback();
    assert.equal(app.oscillators.length,soundEnabled?6:0,'Both initial and repeated metronome beats honor silence');
    app.api.noteOn(60);app.setTime(6000);app.api.noteOn(62);
    const report=app.api.finish();
    assert.equal(report.completed,true);assert.equal(report.firstTryCorrect,2);assert.equal(report.errors.length,0);
    assert.deepEqual(report.played.map(note=>note.time),[5000,6000],'The count-in note is ignored and intended onset times stay correct');
  }
});

test('instrument preferences preserve MIDI requirements for piano and polyphonic scores',async()=>{
  const mono=harness();await mono.load();
  mono.api.applyPreferences({instrument:'strings'});assert.equal(mono.element('input').value,'microphone');
  mono.api.applyPreferences({instrument:'piano'});assert.equal(mono.element('input').value,'midi');
  mono.api.applyPreferences({instrument:'unrecognized'});assert.equal(mono.element('instrument-choice').value,'piano');
  mono.api.applyPreferences({instrument:'auto'});assert.equal(mono.element('input').value,'microphone');
  const chord=harness();await chord.load(true);chord.api.applyPreferences({instrument:'strings'});
  assert.equal(chord.element('instrument-choice').value,'strings');assert.equal(chord.element('input').value,'midi');
});

test('disabled encouragement shows the current position while keeping correction feedback',async()=>{
  const app=harness();await app.load();app.api.applyPreferences({encouragementEnabled:false});
  app.element('input').value='keyboard';app.element('verified').checked=true;await app.element('start').onclick();
  app.api.noteOn(61);assert.match(app.element('message').textContent,/应弹 C4/);
  app.api.noteOn(60);assert.equal(app.element('message').textContent,'第 1 小节 · 第 2 拍');
  app.api.applyPreferences({instrument:'piano'});assert.equal(app.element('input').value,'keyboard','A late preference update must not switch a live input');
});

test('silent transport preference leaves deliberate score audition audible',async()=>{
  const app=harness();await app.load();app.api.applyPreferences({soundEnabled:false});
  await app.element('listen').onclick();assert.equal(app.audioContexts,1);assert.equal(app.oscillators.length,2);
});
