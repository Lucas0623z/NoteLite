import test from 'node:test';
import assert from 'node:assert/strict';
import {DOMParser} from '@xmldom/xmldom';
import {parseScore,inferInstrument} from '../src/score.js';
const wrap=body=>`<score-partwise><part-list><score-part id="P1"><part-name>Unknown</part-name></score-part></part-list><part id="P1">${body}</part></score-partwise>`;
const note=(duration,staff='1')=>`<note><pitch><step>C</step><octave>4</octave></pitch><duration>${duration}</duration><staff>${staff}</staff></note>`;
const attrs='<attributes><divisions>8</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>';
test('an OMR overfull bar cannot shift the next bar and is flagged for correction',()=>{
  const score=parseScore(wrap(`<measure number="1">${attrs}${note(32)}</measure><measure number="2">${note(33)}</measure><measure number="3">${note(32)}</measure>`),DOMParser);
  assert.deepEqual(score.parts[0].notes.map(n=>n.onset),[0,4,8]);
  assert.deepEqual(score.issues,[{part:'P1',mi:1,measure:'2',kind:'overfull'}]);
});
test('a pickup keeps its actual length while later ordinary bars use the meter',()=>{
  const score=parseScore(wrap(`<measure number="0" implicit="yes">${attrs}${note(8)}</measure><measure number="1">${note(32)}</measure>`),DOMParser);
  assert.deepEqual(score.parts[0].notes.map(n=>n.onset),[0,1]);assert.equal(score.issues.length,0);
});
test('numbered transposition stays on its staff',()=>{
  const score=parseScore(wrap(`<measure number="1"><attributes><divisions>8</divisions><transpose number="1"><chromatic>-2</chromatic></transpose><transpose number="2"><chromatic>0</chromatic></transpose></attributes>${note(8,'1')}<backup><duration>8</duration></backup>${note(8,'2')}</measure>`),DOMParser);
  assert.deepEqual(score.parts[0].notes.map(n=>n.midi),[58,60]);
});
test('6/8 beat labels count eighth-note beats',()=>{
  const score=parseScore(wrap(`<measure number="1"><attributes><divisions>8</divisions><time><beats>6</beats><beat-type>8</beat-type></time></attributes>${note(4)}${note(4)}</measure>`),DOMParser);
  assert.deepEqual(score.parts[0].notes.map(n=>n.beat),[1,2]);
});
test('specific woodwind and Chinese names override default GM piano and broad horn matching',()=>{
  for(const [name,expected] of [['English horn','英国管'],['Bassoon','巴松'],['Erhu','二胡'],['Guzheng','古筝'],['Oboe','双簧管']])assert.equal(inferInstrument({name,program:1}).name,expected);
});
test('printed dotted-quarter metronome tempo is converted to quarter-note BPM',()=>{
  const score=parseScore(wrap(`<measure number="1">${attrs}<direction><direction-type><metronome><beat-unit>quarter</beat-unit><beat-unit-dot/><per-minute>80</per-minute></metronome></direction-type></direction>${note(32)}</measure>`),DOMParser);
  assert.equal(score.tempo,120);
});
