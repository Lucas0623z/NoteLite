import test from 'node:test';
import assert from 'node:assert/strict';
import {DOMParser} from '@xmldom/xmldom';
import {parseScore,selectGroups,isPolyphonic} from '../src/score.js';
import {selectedWindowsInstruments} from '../src/windows-engine-selection.js';
import {planNoteWise} from '../src/engine-policy.js';

const attributes=trans=>`<attributes><divisions>1</divisions><time><beats>1</beats><beat-type>4</beat-type></time>${trans===null?'':`<transpose><chromatic>${trans}</chromatic></transpose>`}</attributes>`;
const note=instrument=>`<note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>${instrument?`<instrument id="${instrument}"/>`:''}</note>`;
const make=(body,header='<part-name>Clarinet</part-name>',defaults='')=>parseScore(`<score-partwise><part-list><score-part id="P1">${header}</score-part></part-list>${defaults}<part id="P1">${body}</part></score-partwise>`,DOMParser);
const plan=(score,from,to,options={instrument:'auto'})=>{const groups=selectGroups(score,'all',from,to,options);return planNoteWise(selectedWindowsInstruments(score,groups,()=>options),{phase:'recorded',inputKind:'recording',platform:'windows',polyphonic:isPolyphonic(groups)});};

test('Windows actual selected excerpt does not inherit earlier unconfirmed transposition',()=>{
  const score=make(`<measure number="1">${attributes(null)}${note()}</measure><measure number="2">${attributes(-2)}${note()}</measure>`);
  assert.deepEqual(plan(score,1,1).requiresConfirmation,['transposition']);
  assert.deepEqual(plan(score,2,2).requiresConfirmation,[]);
  assert.equal(plan(score,2,2).primary,'pyin');
});

test('Windows selected note references expose both explicit sounds rather than part first sound',()=>{
  const header='<part-name>Flute</part-name><score-instrument id="I1"><instrument-name>Flute</instrument-name></score-instrument><score-instrument id="I2"><instrument-name>Clarinet</instrument-name></score-instrument>';
  const score=make(`<measure number="1">${attributes(0)}${note('I1')}</measure><measure number="2">${note('I2')}</measure>`,header);
  assert.deepEqual(plan(score,1,1).instrumentIds,['flute']);
  assert.deepEqual(plan(score,2,2).instrumentIds,['clarinet']);
  assert.deepEqual(plan(score,1,2).instrumentIds,['flute','clarinet']);
  assert.deepEqual(plan(score,1,2).requiresConfirmation,[]);
  const unresolved=make(`<measure number="1">${attributes(0)}${note()}</measure>`,header);
  assert.ok(plan(unresolved,1,1).requiresConfirmation.includes('instrument'));
});

test('Windows acoustic routing rejects short overlaps and distinct simultaneous sources',()=>{
  const header='<part-name>Wind</part-name><score-instrument id="I1"><instrument-name>Flute</instrument-name></score-instrument><score-instrument id="I2"><instrument-name>Clarinet</instrument-name></score-instrument>';
  const score=make(`<measure number="1"><attributes><divisions>50</divisions><time><beats>2</beats><beat-type>4</beat-type></time><transpose><chromatic>0</chromatic></transpose></attributes>${note('I1').replace('<duration>1</duration>','<duration>51</duration>')}<backup><duration>1</duration></backup>${note('I2').replace('<duration>1</duration>','<duration>49</duration>')}</measure>`,header);
  assert.equal(isPolyphonic(selectGroups(score,'all',1,1)),true);
  assert.ok(plan(score,1,1).requiresConfirmation.includes('instrument'));
  const values=selectedWindowsInstruments(make(`<measure number="1">${attributes(0)}${note('I1')}</measure><measure number="2">${note('I2')}</measure>`,header),selectGroups(make(`<measure number="1">${attributes(0)}${note('I1')}</measure><measure number="2">${note('I2')}</measure>`,header),'all',1,2));
  assert.ok(planNoteWise(values.map((v,i)=>({...v,sourcePartId:'P'+i})),{platform:'windows',inputKind:'recording'}).requiresConfirmation.includes('instrument'));
  assert.ok(planNoteWise(values,{platform:'apple',inputKind:'recording'}).requiresConfirmation.includes('instrument'));
});

test('Windows concert-score and explicit octave notation cannot acquire a second manual transpose',()=>{
  const score=make(`<measure number="1">${attributes(null)}${note()}</measure>`,undefined,'<defaults><concert-score/></defaults>');
  assert.equal(selectGroups(score,'all',1,1,{instrument:'clarinet',variant:'bb'})[0].notes[0].midi,60);
  assert.deepEqual(plan(score,1,1).requiresConfirmation,[]);
  assert.throws(()=>plan(score,1,1,{instrument:'clarinet',variant:'invalid'}),/变体|谱制/);
});
