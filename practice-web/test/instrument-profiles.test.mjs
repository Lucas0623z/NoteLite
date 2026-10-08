import test from 'node:test';
import assert from 'node:assert/strict';
import {DOMParser} from '@xmldom/xmldom';
import {INSTRUMENT_PROFILES, resolveInstrument, resolveProfile} from '../src/instruments.js';
import {parseScore, inferInstrument, selectGroups} from '../src/score.js';

const note = (staff='1', step='C', octave=4) => `<note><pitch><step>${step}</step><octave>${octave}</octave></pitch><duration>4</duration><staff>${staff}</staff></note>`;
const measure = (body, number=1) => `<measure number="${number}">${body}</measure>`;
const attributes = content => `<attributes><divisions>4</divisions>${content}</attributes>`;
const transpose = (value, staff='') => `<transpose${staff ? ` number="${staff}"` : ''}><chromatic>${value}</chromatic></transpose>`;
const parse = (body, metadata='<part-name>Part 1</part-name>') => parseScore(`<score-partwise><part-list><score-part id="P1">${metadata}</score-part></part-list><part id="P1">${body}</part></score-partwise>`, DOMParser);

test('all architecture instruments expose bounded independent sounding ranges and engine routing', () => {
  assert.deepEqual(INSTRUMENT_PROFILES.map(p=>p.id), ['piano','violin','viola','cello','contrabass','harp','flute','clarinet','bassoon','oboe','horn','trumpet','trombone','tuba','euphonium','voice']);
  for(const p of INSTRUMENT_PROFILES) {
    assert.ok(p.minMidi < p.maxMidi && p.minHz > 0 && p.minHz < p.maxHz, p.id);
    assert.ok([4096,8192].includes(p.windowSize),p.id);
    assert.equal(p.realtimeEngine,'mpm');
    assert.equal(p.recordingEngine,'basic-pitch');
  }
  assert.equal(resolveProfile('piano').recommendedInput,'midi');
  for(const id of ['cello','contrabass','bassoon','horn','trombone','tuba','euphonium']) assert.equal(resolveProfile(id).windowSize,8192,id);
  assert.ok(resolveProfile('contrabass').minMidi<=24);
  assert.ok(resolveProfile('bassoon').minMidi<=34);
  assert.ok(resolveProfile('tuba').minMidi<=28);
});

test('score-instrument names precede generic names and exporter piano programs', () => {
  const score=parse(measure(attributes('')+note()), '<part-name>Piano</part-name><score-instrument id="I1"><instrument-name>Viola</instrument-name></score-instrument><midi-instrument id="I1"><midi-program>1</midi-program></midi-instrument>');
  const p=score.parts[0], info=resolveInstrument(p);
  assert.deepEqual(p.instrumentNames,['Viola']);
  assert.equal(info.profileId,'viola');
  assert.equal(info.metadataName,'Viola');
  assert.equal(info.reliable,true);
  assert.match(inferInstrument(p).name,/中提琴/);
});

test('part and instrument abbreviations identify instruments when full names are generic', () => {
  for(const [metadata,id] of [
    ['<part-name>Part 1</part-name><part-abbreviation>Cl.</part-abbreviation>','clarinet'],
    ['<part-name>Part 1</part-name><score-instrument id="I1"><instrument-name>Instrument 1</instrument-name><instrument-abbreviation>Bsn.</instrument-abbreviation></score-instrument>','bassoon'],
  ])assert.equal(resolveInstrument(parse(measure(attributes('')+note()),metadata).parts[0]).profileId,id);
});

test('specific GM programs are a fallback while unknown named export placeholders stay unconfirmed', () => {
  assert.equal(resolveInstrument({name:'Part 1',program:59,programExplicit:true}).profileId,'tuba');
  assert.equal(resolveInstrument({name:'Part 1',program:61}).profileId,'horn');
  assert.equal(resolveInstrument({name:'Mystery reed',program:1}).profileId,null);
  assert.equal(resolveInstrument({name:'Part 1',program:0}).profileId,null);
  assert.equal(resolveInstrument({name:'Part 1',program:72,programExplicit:false}).profileId,null);
  assert.equal(resolveInstrument({name:'Part 1',program:129}).profileId,null);
});

test('unconfirmed local OMR metadata cannot turn synthesized piano or voice defaults into reliable instruments', () => {
  for(const part of [
    {name:'Piano',instrumentNames:['Acoustic Grand Piano'],program:1},
    {name:'Voice',instrumentNames:['Choir Aahs'],program:54},
  ]) {
    part.instrumentConfirmed=false;
    assert.equal(resolveInstrument(part).reliable,false);
    assert.equal(resolveInstrument(part).profileId,null);
    assert.equal(inferInstrument(part).reliable,false);
    const chosen=resolveInstrument(part,'clarinet',{variant:'a'});
    assert.equal(chosen.reliable,true);
    assert.equal(chosen.profileId,'clarinet');
    assert.equal(chosen.transpose,-3);
  }
});

test('specific explicit part names override a generated playback instrument name on imports', () => {
  const part=parse(measure(attributes('')+note()), '<part-name>Violin</part-name><score-instrument id="I1"><instrument-name>Acoustic Grand Piano</instrument-name></score-instrument><midi-instrument id="I1"><midi-program>1</midi-program></midi-instrument>').parts[0];
  const inferred=resolveInstrument(part);
  assert.equal(inferred.profileId,'violin');
  assert.equal(inferred.metadataName,'Violin');
});

test('existing suggestions outside the main architecture remain available without guessing from register', () => {
  for(const [name,expected] of [['English Horn','英国管'],['Harpsichord','羽管键琴'],['Saxophone','萨克斯'],['Erhu','二胡'],['Guzheng','古筝']]) assert.equal(inferInstrument({name,program:1}).name,expected);
  assert.equal(resolveInstrument({name:'Unknown',program:0,notes:[{midi:24}]}).profileId,null);
  assert.equal(resolveInstrument({name:'Unknown',program:0,notes:[{midi:96}]}).profileId,null);
});

test('auto instrument detection never silently adds transposition', () => {
  const score=parse(measure(attributes('')+note()), '<part-name>Clarinet</part-name>');
  assert.equal(resolveInstrument(score.parts[0]).transpose,0);
  assert.equal(selectGroups(score,'P1',1,1,{instrument:'auto'}).at(0).notes[0].midi,60);
});

test('manual variants transform only selected copies, preserving original MusicXML and notes', () => {
  const score=parse(measure(attributes('')+note()));
  for(const [instrument,variant,expected] of [['clarinet','bb',58],['clarinet','a',57],['clarinet','eb',63],['horn','f',53],['trumpet','bb',58],['contrabass','octave',48],['euphonium','bass',60],['euphonium','bb-treble',46]]) {
    const selected=selectGroups(score,'P1',1,1,{instrument,variant});
    assert.equal(selected[0].notes[0].midi,expected,`${instrument}/${variant}`);
    assert.equal(selected[0].notes[0].writtenMidi,60);
  }
  assert.equal(score.parts[0].notes[0].midi,60);
  assert.equal(score.parts[0].notes[0].transposeExplicit,false);
  assert.match(score.xml,/<step>C<\/step>/);
});

test('explicit MusicXML transposes including zero prevent double transposition', () => {
  for(const [trans,expected] of [[-2,58],[0,60],[-12,48]]) {
    const score=parse(measure(attributes(transpose(trans))+note()));
    const n=score.parts[0].notes[0];
    assert.equal(n.writtenMidi,60);
    assert.equal(n.transposeSemitones,trans);
    assert.equal(n.transposeExplicit,true);
    assert.equal(selectGroups(score,'P1',1,1,{instrument:'clarinet',variant:'a',transpose:-7})[0].notes[0].midi,expected);
  }
});

test('numbered MusicXML transposes and changes track explicitness independently by staff and time', () => {
  const body=measure(attributes(transpose(-2,'1'))+note('1')+'<backup><duration>4</duration></backup>'+note('2'))+
    measure(attributes(transpose(0,'1'))+note('1')+'<backup><duration>4</duration></backup>'+note('2'),2)+
    measure(attributes(transpose(-7))+note('1')+'<backup><duration>4</duration></backup>'+note('2'),3);
  const score=parse(body), notes=score.parts[0].notes;
  assert.deepEqual(notes.map(n=>[n.staff,n.writtenMidi,n.midi,n.transposeExplicit]), [['1',60,58,true],['2',60,60,false],['1',60,60,true],['2',60,60,false],['1',60,53,true],['2',60,53,true]]);
  const groups=selectGroups(score,'P1',1,3,{instrument:'clarinet',variant:'a'});
  assert.deepEqual(groups.flatMap(g=>g.notes.map(n=>[n.staff,n.midi])),[['2',57],['1',58],['2',57],['1',60],['1',53],['2',53]]);
});

test('a user transpose override applies to unmarked notes and rejects invalid sounding pitches', () => {
  const score=parse(measure(attributes('')+note()));
  assert.equal(selectGroups(score,'P1',1,1,{instrument:'clarinet',variant:'bb',transpose:0})[0].notes[0].midi,60);
  assert.equal(selectGroups(score,'P1',1,1,{instrument:'horn',transpose:2})[0].notes[0].midi,62);
  assert.throws(()=>resolveInstrument({},'piano',{transpose:.5}),/整数半音/);
  const low=parse(measure(attributes('')+note('1','C',0)));
  assert.throws(()=>selectGroups(low,'P1',1,1,{instrument:'euphonium',variant:'bb-treble'}),/MIDI 范围/);
});

test('instrument settings can be scoped to each part when practicing all parts', () => {
  const score=parse(measure(attributes('')+note()));
  score.parts.push({...score.parts[0],id:'P2',notes:score.parts[0].notes.map(n=>({...n,id:'P2:0',part:'P2'}))});
  assert.deepEqual(selectGroups(score,'all',1,1,{byPart:{P1:{instrument:'clarinet',variant:'bb'}}})[0].notes.map(n=>[n.part,n.midi]),[['P1',58],['P2',60]]);
});
