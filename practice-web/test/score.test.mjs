import test from 'node:test';
import assert from 'node:assert/strict';
import {DOMParser} from '@xmldom/xmldom';
import {parseScore, inferInstrument, selectGroups, isPolyphonic, noteName} from '../src/score.js';

const note = (step, octave=4, duration=4, extra='') => `<note>${extra}<pitch><step>${step}</step><octave>${octave}</octave></pitch><duration>${duration}</duration></note>`;
const measure = (body, number='1', attributes='<divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time>') => `<measure number="${number}"><attributes>${attributes}</attributes>${body}</measure>`;
const document = (parts) => `<?xml version="1.0"?><score-partwise version="4.0"><work><work-title>Practice fixture</work-title></work><part-list>${parts.map(p=>`<score-part id="${p.id}"><part-name>${p.name}</part-name>${p.program?`<midi-instrument id="${p.id}-I1"><midi-program>${p.program}</midi-program></midi-instrument>`:''}</score-part>`).join('')}</part-list>${parts.map(p=>`<part id="${p.id}">${p.body}</part>`).join('')}</score-partwise>`;
const parse = parts => parseScore(document(parts), DOMParser);

test('multi-staff chords and voice backups keep pitches, positions and source identity', () => {
  const score = parse([{id:'P1',name:'Piano',program:1,body:measure(
    note('C',4,4,'<voice>1</voice><staff>1</staff>')+
    note('E',4,4,'<chord/><voice>1</voice><staff>1</staff>')+
    note('D',4,4,'<voice>1</voice><staff>1</staff>')+
    '<backup><duration>8</duration></backup>'+
    note('C',3,8,'<voice>2</voice><staff>2</staff>'))}]);
  const groups = selectGroups(score,'P1');
  assert.deepEqual(groups.map(g=>[g.onset,g.notes.map(n=>n.midi)]), [[0,[48,60,64]],[1,[62]]]);
  assert.equal(groups[0].notes[0].staff,'2');
  assert.equal(new Set(score.parts[0].notes.map(n=>n.id)).size,4);
  assert.equal(isPolyphonic(groups),true);
});

test('B-flat transposition applies to sounding pitches without altering written XML', () => {
  const score=parse([{id:'P1',name:'Clarinet',program:72,body:measure(note('C'), '1',
    '<divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time><transpose><diatonic>-1</diatonic><chromatic>-2</chromatic></transpose>')}]);
  assert.equal(score.parts[0].notes[0].midi,58);
  assert.equal(score.parts[0].notes[0].beat,1);
  assert.match(score.xml,/<step>C<\/step>/);
});

test('octave transpose and later transpose reset are applied at their own measure', () => {
  const body=measure(note('C'), '1','<divisions>4</divisions><transpose><chromatic>0</chromatic><octave-change>1</octave-change></transpose>')+
    measure(note('C'),'2','<transpose><chromatic>0</chromatic><octave-change>0</octave-change></transpose>');
  const score=parse([{id:'P1',name:'Piccolo',program:73,body}]);
  assert.deepEqual(score.parts[0].notes.map(n=>n.midi),[72,60]);
});

test('a three-segment tie is scored as one attack and retains its full duration', () => {
  const body=measure(note('C',4,16,'<tie type="start"/>'))+
    measure(note('C',4,16,'<tie type="stop"/><tie type="start"/>'),'2')+
    measure(note('C',4,16,'<tie type="stop"/>'),'3');
  const score=parse([{id:'P1',name:'Violin',program:41,body}]);
  assert.equal(score.parts[0].notes.length,1);
  assert.equal(score.parts[0].notes[0].duration,12);
  assert.equal(selectGroups(score,'P1').length,1);
});

test('ties in different voices remain independent even at identical pitch', () => {
  const body=measure(note('C',4,4,'<voice>1</voice><tie type="start"/>')+
    '<backup><duration>4</duration></backup>'+note('C',4,4,'<voice>2</voice>')+
    note('C',4,4,'<voice>1</voice><tie type="stop"/>'));
  const score=parse([{id:'P1',name:'Piano',program:1,body}]);
  assert.equal(score.parts[0].notes.length,2);
  assert.deepEqual(score.parts[0].notes.map(n=>[n.voice,n.duration]),[['1',2],['2',1]]);
});

test('part selection and bar range preserve global onset and printed measure labels', () => {
  const body=measure(note('C',4,16),'0')+measure(note('D',4,16),'12')+measure(note('E',4,16),'13');
  const score=parse([{id:'P1',name:'Flute',program:74,body},{id:'P2',name:'Violin',program:41,body}]);
  const groups=selectGroups(score,'P2',2,2);
  assert.equal(groups.length,1);
  assert.equal(groups[0].onset,4);
  assert.equal(groups[0].measure,'12');
  assert.equal(groups[0].mi,1);
  assert.equal(groups[0].notes[0].part,'P2');
});

test('part bar lengths stay aligned when voices have different written durations', () => {
  const score=parse([
    {id:'P1',name:'Flute',body:measure(note('C',4,4))+measure(note('D',4,4),'2')},
    {id:'P2',name:'Piano',body:measure(note('C',3,16))+measure(note('D',3,16),'2')}
  ]);
  assert.deepEqual(score.parts.map(p=>p.notes[1].onset),[4,4]);
});

test('sustained overlapping voices are polyphonic even without a chord tag', () => {
  const groups=[{onset:0,notes:[{midi:60,onset:0,duration:2}]},{onset:1,notes:[{midi:64,onset:1,duration:1}]}];
  assert.equal(isPolyphonic(groups),true);
  groups[0].notes[0].duration=1;
  assert.equal(isPolyphonic(groups),false);
});

test('grace and unpitched percussion are excluded with visible capability warnings', () => {
  const score=parse([{id:'P1',name:'Drums',body:measure(
    '<note><grace/><pitch><step>D</step><octave>4</octave></pitch></note>'+
    '<note><unpitched><display-step>C</display-step><display-octave>5</display-octave></unpitched><duration>4</duration></note>'+note('C'))}]);
  assert.equal(score.parts[0].notes.length,1);
  assert.equal(score.warnings.length,2);
  assert.match(score.warnings.join(' '),/装饰音/);
  assert.match(score.warnings.join(' '),/打击乐/);
});

test('repeat instructions and multiple score tempi are disclosed rather than silently promised', () => {
  const score=parse([{id:'P1',name:'Flute',body:measure('<direction><sound tempo="92"/></direction>'+note('C')+
    '<direction><sound tempo="108"/></direction><barline><repeat direction="backward"/></barline>')}]);
  assert.equal(score.tempo,92);
  assert.equal(score.warnings.length,2);
});

test('microtonal pitches, zero divisions and invalid score roots fail explicitly', () => {
  assert.throws(()=>parse([{id:'P1',name:'Flute',body:measure('<note><pitch><step>C</step><alter>0.5</alter><octave>4</octave></pitch><duration>4</duration></note>')}]),/微分音/);
  assert.throws(()=>parse([{id:'P1',name:'Flute',body:measure(note('C'),'1','<divisions>0</divisions>')}]),/divisions/);
  assert.throws(()=>parseScore('<score-timewise/>',DOMParser),/score-partwise/);
});

test('explicit known instrument names win over a generic exporter piano program', () => {
  for(const name of ['Flute','小提琴','Clarinet','Saxophone','Cello','Guitar','Trumpet']) {
    const result=inferInstrument({name,program:1});
    assert.notEqual(result.name,'钢琴 / 键盘',name);
    assert.equal(result.input,'microphone',name);
  }
});

test('General MIDI programs provide common instrument inference when names are generic', () => {
  for(const [program,expected] of [[1,'钢琴'],[25,'吉他'],[41,'小提琴'],[42,'中提琴'],[43,'大提琴'],[65,'萨克斯'],[72,'单簧管'],[74,'笛'],[57,'铜管'],[54,'人声']]) {
    assert.ok(inferInstrument({name:'Part 1',program}).name.includes(expected),String(program));
  }
});

test('unknown metadata asks for confirmation instead of guessing from staff or register', () => {
  const result=inferInstrument({name:'Part 1',program:0});
  assert.match(result.name,/未标明/);
  assert.match(result.source,/手动确认/);
});

test('instrument name qualifiers do not mistake bass woodwinds or harpsichord for other families',()=>{
  assert.match(inferInstrument({name:'Bass Clarinet',program:72}).name,/单簧管/);
  assert.match(inferInstrument({name:'Bass Flute',program:74}).name,/笛/);
  assert.match(inferInstrument({name:'Bass Trombone',program:58}).name,/铜管/);
  assert.equal(inferInstrument({name:'Harpsichord',program:7}).input,'midi');
  assert.match(inferInstrument({name:'English Horn',program:70}).name,/英国管/);
});

test('pitch labels preserve octaves and accidental pitch classes', () => {
  assert.deepEqual([21,48,60,61,69,108].map(noteName),['A0','C3','C4','C♯4','A4','C8']);
});
