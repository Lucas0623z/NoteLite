import test from 'node:test';
import assert from 'node:assert/strict';
import {analyzeRecording} from '../src/recorded-analysis.js';
const group=(onset,pitches)=>({onset,measure:String(Math.floor(onset/4)+1),mi:Math.floor(onset/4),beat:onset%4+1,
  notes:pitches.map((midi,i)=>({id:`${onset}-${i}`,midi,onset,duration:1,part:'P1'}))});
const note=(midi,onset,duration=.4)=>({midi,onset,duration,confidence:.9});

test('whole chord is required and missing tone retains original score identity',()=>{
  const report=analyzeRecording([group(0,[60,64,67])],[note(60,2),note(67,2.02)],{bpm:60});
  assert.equal(report.results[0].correct,2);assert.equal(report.firstTryCorrect,0);
  assert.deepEqual(report.errors[0].expected,[64]);assert.equal(report.errors[0].notes[0].id,'0-1');
  assert.equal(report.played[0].time,2000);assert.equal(report.results[0].notes[2].actual.onset,2.02);
});
test('wrong octave is a wrong note plus missing original pitch, never accepted',()=>{
  const r=analyzeRecording([group(0,[60])],[note(72,1)],{bpm:60});
  assert.equal(r.results[0].correct,0);assert.deepEqual(r.errors.map(e=>e.kind),['wrong','missing']);
});
test('one sustained event cannot satisfy a repeated attack',()=>{
  const r=analyzeRecording([group(0,[60]),group(1,[60])],[note(60,3,2)],{bpm:60});
  assert.equal(r.results[0].correct,1);assert.equal(r.results[1].correct,0);assert.equal(r.errors[0].index,1);
});
test('distinct repeated attacks match even with overlapping durations',()=>{
  const r=analyzeRecording([group(0,[60]),group(1,[60])],[note(60,3,1.4),note(60,4,1)],{bpm:60});
  assert.equal(r.firstTryCorrect,2);
});
test('constant offset preserves onset rhythm mismatch without time warping',()=>{
  const r=analyzeRecording([group(0,[60]),group(1,[62]),group(2,[64])],
    [note(60,2),note(62,3.35),note(64,4)],{bpm:60,toleranceMs:180});
  assert.equal(r.firstTryCorrect,2);assert.equal(r.errors[0].kind,'late');assert.equal(r.errors[0].index,1);
  assert.ok(Math.abs(r.errors[0].delta-350)<.001);
});
test('missing and inserted attacks recover at the original later score positions',()=>{
  const r=analyzeRecording([group(0,[60]),group(1,[62]),group(2,[64]),group(3,[65])],
    [note(60,1),note(61,1.6),note(64,3),note(65,4)],{bpm:60,offsetSeconds:1});
  assert.equal(r.results[1].status,'missing');assert.equal(r.results[2].status,'correct');assert.equal(r.results[3].status,'correct');
  assert.equal(r.errors.find(e=>e.played===61).index,1);
});
test('explicit offset makes first-note lateness observable and early extras visible',()=>{
  const r=analyzeRecording([group(0,[60]),group(1,[62])],[note(70,.1),note(60,1.3),note(62,2)],
    {bpm:60,offsetSeconds:1});
  assert.ok(r.errors.some(e=>e.kind==='late'&&e.index===0));assert.ok(r.errors.some(e=>e.kind==='extra'&&e.played===70));
});
test('ordered same-pitch alignment handles deletion instead of consuming a later attack twice',()=>{
  const r=analyzeRecording([group(0,[60]),group(1,[60]),group(2,[60]),group(3,[60])],
    [note(60,0),note(60,2.1),note(60,3)],{bpm:60,offsetSeconds:0});
  assert.deepEqual(r.results.map(g=>g.correct),[1,0,1,1]);
});
test('unisons keep both score identities but require a single physical attack',()=>{
  const r=analyzeRecording([group(0,[60,60])],[note(60,1)],{bpm:60});
  assert.equal(r.results[0].expected,1);assert.equal(r.firstTryCorrect,1);assert.equal(r.results[0].notes.length,2);
});
test('weak transcription extras are unjudged and do not penalize a strong correct chord',()=>{
  const r=analyzeRecording([group(0,[60,64,67])],[note(60,1),note(64,1),note(67,1),{...note(86,1.03),confidence:.32}],{bpm:60});
  assert.equal(r.firstTryCorrect,1);assert.equal(r.errors.length,0);assert.equal(r.unjudged[0].midi,86);
  assert.equal(r.played.length,4);assert.equal(r.notes.length,4);
});
test('expected weak-only pitch is uncertain, with original identity, instead of missing',()=>{
  const r=analyzeRecording([group(0,[60,64])],[note(60,2),{...note(64,2.01),confidence:.35}],{bpm:60});
  assert.equal(r.results[0].status,'uncertain');assert.equal(r.results[0].notes[1].uncertain,true);
  assert.deepEqual(r.errors.map(e=>e.kind),['uncertain']);assert.equal(r.errors[0].notes[0].id,'0-1');
  assert.equal(r.firstTryCorrect,0);
});
test('weak held event cannot make repeated expected attacks all uncertain',()=>{
  const r=analyzeRecording([group(0,[60]),group(1,[60])],[{...note(60,1,2),confidence:.3}],{bpm:60});
  assert.deepEqual(r.results.map(g=>g.status),['uncertain','missing']);
});
