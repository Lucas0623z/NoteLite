import test from 'node:test';
import assert from 'node:assert/strict';
import {DOMParser} from '@xmldom/xmldom';
import {readScoreInstruments,resolveInstrument,resolveInstrumentForNote} from '../src/instruments.js';
import {planNoteWise} from '../src/engine-policy.js';
import {parseScore,selectGroups} from '../src/score.js';

test('GM program numbering identifies harpsichord, clavinet and accordion rather than piano or organ',()=>{
  for(const [program,id] of [[7,'harpsichord'],[8,'clavinet'],[22,'accordion'],[23,'harmonica'],[24,'accordion']])
    assert.equal(resolveInstrument({name:'Part 1',program,programExplicit:true}).profileId,id);
});
test('unknown manual IDs never become confirmed generic instruments',()=>{
  for(const id of ['drumkit','__proto__','piano-missing']){
    const instrument=resolveInstrument({},id);
    assert.equal(instrument.reliable,false);
    assert.deepEqual(planNoteWise([instrument]).requiresConfirmation,['instrument']);
  }
});
test('instrument identity and sounding notation confirmation remain independent',()=>{
  assert.throws(()=>resolveInstrument({},'clarinet',{variant:'nonexistent'}),/谱制无效/);
  assert.equal(resolveInstrument({name:'Clarinet'},'auto',{transpose:-2}).transpositionConfirmed,true);
  assert.ok(planNoteWise([{profileId:'flute',reliable:true}]).requiresConfirmation.includes('transposition'));
  assert.ok(planNoteWise([resolveInstrument({},'flute'),resolveInstrument({},'violin')]).requiresConfirmation.includes('instrument'));
  const unknownNotation=resolveInstrument({name:'Clarinet'});
  assert.equal(unknownNotation.profileId,'clarinet');
  assert.equal(unknownNotation.transpose,0);
  assert.equal(unknownNotation.transpositionConfirmed,false);
  assert.deepEqual(planNoteWise([unknownNotation]).requiresConfirmation,['transposition']);
  assert.equal(resolveInstrument({name:'Clarinet',notes:[{transposeExplicit:true}]}).transpositionConfirmed,true);
  assert.equal(resolveInstrument({name:'Clarinet',concertScore:true}).transpositionConfirmed,true);
  for(const [id,variant,value] of [['english-horn','f',-7],['piccolo','octave',12],['guitar','octave',-12],['sax','eb-alto',-9]])
    assert.equal(resolveInstrument({},id,{variant}).transpose,value);
});
test('automatic dispatch preserves actual platform adapters and MIDI without acoustic inference',()=>{
  const flute=resolveInstrument({name:'Flute'}),piano=resolveInstrument({name:'Piano'});
  assert.equal(planNoteWise([flute]).primary,'pyin');
  assert.deepEqual(planNoteWise([flute]).validators,['crepe']);
  assert.equal(planNoteWise([flute],{platform:'apple'}).primary,'native-mpm-yin');
  assert.deepEqual(planNoteWise([flute],{platform:'apple'}).validators,['basic-pitch']);
  for(const instrument of [piano,resolveInstrument({},'guitar')]){
    const plan=planNoteWise([instrument]);
    assert.equal(plan.primary,'basic-pitch');assert.equal(plan.mode,'poly');
  }
  assert.equal(planNoteWise([flute],{polyphonic:true}).primary,'basic-pitch');
  const midi=planNoteWise([piano],{inputKind:'midi',phase:'realtime'});
  assert.equal(midi.primary,'midi-stream');assert.deepEqual(midi.validators,[]);
  const live=planNoteWise([piano],{phase:'realtime'});
  assert.equal(live.realtimePolyphonySupported,false);assert.equal(live.needsRecordedReview,true);
  assert.equal(live.scorePitchUsedForDetection,false);
});
test('namespaced MusicXML retains explicit note instrument references and rejects unresolved references',()=>{
  const xml='<s:score-partwise xmlns:s="urn:musicxml"><s:part-list><s:score-part id="P1"><s:part-name>Part 1</s:part-name><s:score-instrument id="I1"><s:instrument-name>Flute</s:instrument-name></s:score-instrument><s:score-instrument id="I2"><s:instrument-name>Piccolo</s:instrument-name></s:score-instrument></s:score-part></s:part-list><s:part id="P1"><s:measure number="1"><s:attributes><s:divisions>1</s:divisions><s:transpose><s:chromatic>0</s:chromatic></s:transpose></s:attributes><s:note><s:pitch><s:step>C</s:step><s:octave>5</s:octave></s:pitch><s:duration>1</s:duration><s:instrument id="I2"/></s:note></s:measure></s:part></s:score-partwise>';
  const part=readScoreInstruments(xml,DOMParser).parts[0];
  assert.deepEqual(part.notes[0].instrumentIds,['I2']);assert.equal(part.notes[0].transposeExplicit,true);
  assert.equal(resolveInstrumentForNote(part,part.notes[0]).profileId,'piccolo');
  assert.equal(resolveInstrumentForNote(part,{instrumentIds:['gone']}).reliable,false);
  assert.equal(resolveInstrumentForNote(part,{instrumentIds:[]}).reliable,false);
  const parsed=parseScore(xml,DOMParser);
  assert.deepEqual(parsed.parts[0].notes[0].instrumentIds,['I2']);
  assert.equal(selectGroups(parsed,'P1',1,1,{instrument:'auto'})[0].notes[0].midi,72);
});
