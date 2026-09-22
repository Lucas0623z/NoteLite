import test from 'node:test';
import assert from 'node:assert/strict';
import {PracticeSession,PitchGate} from '../src/session.js';

const group=(onset,pitches,measure='1')=>({onset,mi:Number(measure)-1,measure,beat:onset+1,notes:pitches.map(midi=>({midi,onset,duration:1,part:'P1'}))});

test('pausing freezes tempo grading and shifts the beat clock on resume',()=>{
  const s=new PracticeSession([group(0,[60]),group(1,[62])],{mode:'tempo',bpm:60});s.begin(1000);s.noteOn(60,1000);s.pause(1200);
  s.tick(12000);assert.equal(s.noteOn(62,12000),null);assert.equal(s.index,1);assert.equal(s.errors.length,0);
  s.resume(5200);assert.equal(s.expectedAt(s.current),6000);assert.equal(s.noteOn(62,6000).kind,'correct');assert.equal(s.errors.length,0);
});
test('pause preserves a partially played chord and a not-yet-started wait session',()=>{
  const s=new PracticeSession([group(0,[60,64])]);s.pause(100);s.resume(900);assert.equal(s.startedAt,null);
  s.noteOn(60,1000);s.pause(1100);s.resume(2000);assert.equal(s.matched.has(60),true);assert.equal(s.noteOn(64,2001).complete,true);
  s.finish();s.resume(3000);assert.equal(s.active,false);
});

test('wait mode keeps the cursor on a wrong note and remembers correction location',()=>{
  const s=new PracticeSession([group(0,[60]),group(1,[62])]);
  assert.equal(s.noteOn(61,1000).kind,'wrong');
  assert.equal(s.index,0);
  assert.equal(s.noteOn(60,1400).kind,'correct');
  assert.equal(s.index,1);
  assert.deepEqual(s.errors[0],{kind:'wrong',index:0,measure:'1',mi:0,beat:1,played:61,expected:[60]});
  s.noteOn(62,3000);
  assert.equal(s.report().firstTryCorrect,1);
  assert.equal(s.results[0].status,'corrected');
  assert.equal(s.active,false);
});

test('MIDI chords accept any note order and ignore duplicate held-note messages',()=>{
  const s=new PracticeSession([group(0,[60,64,67])]);
  assert.equal(s.noteOn(67,0).complete,false);
  assert.equal(s.noteOn(67,3).kind,'duplicate');
  s.noteOn(60,10);
  assert.equal(s.index,0);
  assert.equal(s.noteOn(64,20).complete,true);
  assert.equal(s.results[0].correct,3);
  assert.equal(s.errors.length,0);
});

test('unison notes shared by multiple parts require only one MIDI attack',()=>{
  const s=new PracticeSession([group(0,[60,60,64])]);
  s.noteOn(60,0);s.noteOn(64,12);
  assert.equal(s.results[0].expected,2);
  assert.equal(s.results[0].correct,2);
});

test('skip records only missing chord notes and preserves previously correct notes',()=>{
  const s=new PracticeSession([group(0,[60,64,67])]);
  s.noteOn(60,100);
  s.advance(true);
  assert.deepEqual(s.errors[0].expected,[64,67]);
  assert.equal(s.results[0].correct,1);
  assert.equal(s.results[0].status,'missing');
});

test('tempo mode distinguishes early and late notes without losing their score position',()=>{
  const s=new PracticeSession([group(0,[60]),group(1,[62]),group(2,[64])],{mode:'tempo',bpm:60});
  s.begin(1000);s.noteOn(60,1000);s.noteOn(62,1770);s.noteOn(64,3230);
  assert.deepEqual(s.errors.map(e=>[e.kind,e.index,e.delta]),[['early',1,-230],['late',2,230]]);
  assert.equal(s.report().firstTryCorrect,1);
});

test('a very early extra note does not advance to the future score group',()=>{
  const s=new PracticeSession([group(0,[60]),group(1,[62])],{mode:'tempo',bpm:60});
  s.begin(1000);s.noteOn(60,1000);
  assert.equal(s.noteOn(62,1200).kind,'extra');
  assert.equal(s.index,1);
});

test('count-in input is ignored without errors, cursor movement or recorded attacks',()=>{
  const s=new PracticeSession([group(0,[60])],{mode:'tempo',bpm:100});
  s.begin(3400);
  assert.equal(s.noteOn(61,1000),null);
  assert.equal(s.noteOn(60,3399),null);
  assert.equal(s.played.length,0);
  assert.equal(s.errors.length,0);
  assert.equal(s.index,0);
  assert.equal(s.noteOn(60,3400).kind,'correct');
});

test('tempo timer records missed notes and automatically completes an unattended passage',()=>{
  const s=new PracticeSession([group(0,[60]),group(1,[62]),group(2,[64])],{mode:'tempo',bpm:60});
  s.begin(1000);s.noteOn(60,1000);s.tick(3400);
  assert.equal(s.active,false);
  assert.deepEqual(s.errors.map(e=>[e.kind,e.index]),[['missing',1],['missing',2]]);
});

test('omitting a fast sixteenth note does not mark the next on-time note wrong',()=>{
  const s=new PracticeSession([group(0,[60]),group(.25,[62]),group(.5,[64]),group(.75,[65])],{mode:'tempo',bpm:100});
  s.begin(1000);s.noteOn(60,1000);
  const third=s.noteOn(64,1300);
  assert.equal(third.kind,'correct');
  assert.equal(s.index,3);
  assert.deepEqual(s.errors.map(e=>[e.kind,e.index]),[['missing',1]]);
  assert.equal(s.noteOn(65,1450).kind,'correct');
});

test('intonation feedback applies at the same MIDI pitch and affects first-try correctness',()=>{
  const s=new PracticeSession([group(0,[69])]);
  s.noteOn(69,0,42);
  assert.equal(s.errors[0].kind,'intonation');
  assert.equal(s.errors[0].cents,42);
  assert.equal(s.results[0].status,'corrected');
});

test('finishing early does not award unperformed notes or invent missing-note errors',()=>{
  const s=new PracticeSession([group(0,[60]),group(1,[62])]);
  s.noteOn(60,0);
  const report=s.finish();
  assert.equal(report.completed,1);
  assert.equal(report.total,2);
  assert.equal(report.firstTryCorrect,1);
  assert.equal(report.errors.length,0);
  assert.equal(s.noteOn(62,1000),null);
});

test('stable pitch gate emits one attack, then rearms after three silent frames',()=>{
  const gate=new PitchGate();
  assert.equal(gate.push(440,1,.1),null);
  assert.equal(gate.push(440,1,.1),null);
  assert.equal(gate.push(440,1,.1).midi,69);
  for(let i=0;i<20;i++)assert.equal(gate.push(440,1,.1),null);
  for(let i=0;i<3;i++)assert.equal(gate.push(0,0,0),null);
  gate.push(440,1,.1);gate.push(440,1,.1);
  assert.equal(gate.push(440,1,.1).midi,69);
});

test('stable pitch gate rejects noise, low volume and frequencies outside its range',()=>{
  for(const [hz,clarity,rms] of [[440,.4,.1],[440,1,.001],[20,1,.1],[5000,1,.1]]) {
    const gate=new PitchGate();
    for(let i=0;i<10;i++)assert.equal(gate.push(hz,clarity,rms),null);
  }
});

test('stable gate tracks semitone changes and measures cents',()=>{
  const gate=new PitchGate(),frequency=440*2**(20/1200);
  gate.push(frequency,1,.1);gate.push(frequency,1,.1);
  const event=gate.push(frequency,1,.1);
  assert.equal(event.midi,69);
  assert.ok(Math.abs(event.cents-20)<1e-8);
  for(let i=0;i<2;i++)assert.equal(gate.push(466.1637615,1,.1),null);
  assert.equal(gate.push(466.1637615,1,.1).midi,70);
});

test('audible but low-clarity sustain does not release and create a duplicate attack',()=>{
  const gate=new PitchGate();
  gate.push(440,1,.1);gate.push(440,1,.1);
  assert.equal(gate.push(440,1,.1).midi,69);
  for(let i=0;i<5;i++)assert.equal(gate.push(440,.7,.1),null);
  for(let i=0;i<6;i++)assert.equal(gate.push(440,1,.1),null);
});

test('unreliable estimates reset candidates so attacks need consecutive stable frames',()=>{
  const gate=new PitchGate();
  gate.push(440,1,.1);gate.push(440,1,.1);
  gate.push(440,.7,.1);
  assert.equal(gate.push(440,1,.1),null);
  assert.equal(gate.push(440,1,.1),null);
  assert.equal(gate.push(440,1,.1).midi,69);
});

test('legitimate stable octave jumps are still accepted without requiring silence',()=>{
  const gate=new PitchGate();
  gate.push(220,1,.1);gate.push(220,1,.1);
  assert.equal(gate.push(220,1,.1).midi,57);
  gate.push(440,1,.1);gate.push(440,1,.1);
  assert.equal(gate.push(440,1,.1).midi,69);
});
