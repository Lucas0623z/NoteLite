import {inferInstrumentMetadata, resolveInstrument, soundingMidi} from './instruments.js';

const children = (node, name) => Array.from(node?.childNodes || []).filter(n => n.nodeType === 1 && (!name || n.localName === name || n.nodeName === name));
const child = (node,name) => children(node,name)[0];
const text = (node,name,fallback='') => child(node,name)?.textContent?.trim() || fallback;
const num = (node,name,fallback=0) => Number(text(node,name,String(fallback)));
const pitches = {C:0,D:2,E:4,F:5,G:7,A:9,B:11};
export const noteName = midi => ['C','C♯','D','E♭','E','F','F♯','G','A♭','A','B♭','B'][((midi%12)+12)%12] + (Math.floor(midi/12)-1);

/** Parse written-order MusicXML. Keep bar, beat, voice and staff for feedback. */
export function parseScore(xml, Parser = globalThis.DOMParser) {
  const doc = new Parser().parseFromString(xml,'application/xml');
  const root = doc.documentElement;
  if (root.nodeName !== 'score-partwise' || doc.getElementsByTagName('parsererror').length) throw new Error('请选择有效的 MusicXML 乐谱（score-partwise）。');
  const catalog = new Map(children(child(root,'part-list'),'score-part').map(p=>[p.getAttribute('id'),p]));
  const warnings = new Set();
  const issues=[];
  if (doc.getElementsByTagName('repeat').length || doc.getElementsByTagName('ending').length || doc.getElementsByTagName('segno').length || doc.getElementsByTagName('coda').length) warnings.add('含反复或跳转：此练习按谱面顺序进行，暂不展开反复。');
  const parts = children(root,'part').map((part,pi)=>{
    const id=part.getAttribute('id'), meta=catalog.get(id), notes=[], lengths=[], meters=[];
    const name=text(meta,'part-name',`声部 ${pi+1}`), abbreviation=text(meta,'part-abbreviation');
    const instrumentNames=children(meta,'score-instrument').map(i=>text(i,'instrument-name')).filter(Boolean);
    const instrumentAbbreviations=children(meta,'score-instrument').map(i=>text(i,'instrument-abbreviation')).filter(Boolean);
    const midiInstrument=children(meta,'midi-instrument').find(i=>child(i,'midi-program'));
    const program=num(midiInstrument,'midi-program',0), programExplicit=!!child(midiInstrument,'midi-program');
    let divisions=1, beats=4, beatType=4, transpose=0, transposeExplicit=false, ties=new Map(), noteIndex=0,knownTime=false;
    const staffTransposes=new Map();
    for (const [mi,measure] of children(part,'measure').entries()) {
      let cursor=0,maxEnd=0,chordStart=0;
      for (const item of children(measure)) {
        if(item.nodeName==='attributes') {
          divisions=num(item,'divisions',divisions);
          if(!(divisions>0)) throw new Error('乐谱中的 divisions 必须大于零。');
          const time=child(item,'time');
          if(time){beats=text(time,'beats',String(beats)).split('+').reduce((sum,n)=>sum+Number(n),0);beatType=num(time,'beat-type',beatType);knownTime=true;}
          for(const trans of children(item,'transpose')) {
            const value=num(trans,'chromatic')+12*num(trans,'octave-change'),staff=trans.getAttribute('number');
            if(staff)staffTransposes.set(staff,value);else{transpose=value;transposeExplicit=true;staffTransposes.clear();}
          }
        } else if(item.nodeName==='backup') cursor-=num(item,'duration')/divisions;
        else if(item.nodeName==='forward'){cursor+=num(item,'duration')/divisions;maxEnd=Math.max(maxEnd,cursor);}
        else if(item.nodeName==='note') {
          const ni=noteIndex++, duration=num(item,'duration')/divisions, chord=!!child(item,'chord');
          const onset=chord?chordStart:cursor;
          if(!chord)chordStart=cursor;
          const pitch=child(item,'pitch');
          if(child(item,'grace')) warnings.add('装饰音暂不计入练习评分。');
          else if(pitch && duration>0) {
            const voice=text(item,'voice','1'),staff=text(item,'staff','1');
            const writtenMidi=12*(num(pitch,'octave')+1)+(pitches[text(pitch,'step')]??NaN)+num(pitch,'alter');
            const transposeSemitones=staffTransposes.get(staff)??transpose, noteTransposeExplicit=staffTransposes.has(staff)||transposeExplicit;
            const midi=writtenMidi+transposeSemitones;
            if(!Number.isInteger(midi)||midi<0||midi>127)throw new Error('暂不支持微分音或超出 MIDI 范围的乐谱。');
            const key=`${voice}/${staff}/${midi}`, types=children(item,'tie').map(t=>t.getAttribute('type'));
            if(types.includes('stop') && ties.has(key)) {ties.get(key).duration+=duration;if(!types.includes('start'))ties.delete(key);}
            else {const n={id:`${id}:${ni}`,part:id,mi,measure:measure.getAttribute('number')||String(mi+1),beat:onset*beatType/4+1,onset,duration,midi,writtenMidi,transposeSemitones,transposeExplicit:noteTransposeExplicit,voice,staff,xmlIndex:ni};notes.push(n);if(types.includes('start'))ties.set(key,n);}
          } else if(child(item,'unpitched')) warnings.add('检测到无固定音高的打击乐：暂不支持音高评分。');
          if(!chord)cursor+=duration;
          maxEnd=Math.max(maxEnd,onset+duration,cursor);
        }
      }
      const nominal=beats*4/beatType;
      if(!(nominal>0))throw new Error('乐谱拍号无效。');
      const implicit=measure.getAttribute('implicit')==='yes',pickup=mi===0&&maxEnd>0&&maxEnd<nominal;
      if(knownTime&&!implicit&&maxEnd>nominal+0.01) {
        issues.push({part:id,mi,measure:measure.getAttribute('number')||String(mi+1),kind:'overfull'});
        warnings.add('有小节的音符时值超过拍号，请先在识谱软件中校对该小节，再用于评分。');
      }
      lengths.push((implicit||pickup)&&maxEnd>0?maxEnd:knownTime?nominal:Math.max(maxEnd,nominal));
      meters.push({beats,beatType,number:measure.getAttribute('number')||String(mi+1)});
    }
    return {id,name,abbreviation,instrumentName:instrumentNames[0]||'',instrumentNames,instrumentAbbreviations,program,programExplicit,notes,lengths,meters,transpose};
  });
  const lengths=Array.from({length:Math.max(0,...parts.map(p=>p.lengths.length))},(_,i)=>Math.max(...parts.map(p=>p.lengths[i]||0)));
  let offset=0;const starts=lengths.map(l=>{const start=offset;offset+=l;return start;});
  for(const p of parts) for(const n of p.notes)n.onset+=starts[n.mi];
  const sound=doc.getElementsByTagName('sound');
  const soundTempi=Array.from(sound).map(s=>Number(s.getAttribute('tempo'))).filter(t=>t>0);
  const unitBeats={whole:4,half:2,quarter:1,eighth:.5,'16th':.25,'32nd':.125};
  const metronomeTempi=Array.from(doc.getElementsByTagName('metronome')).map(m=>{
    const unit=unitBeats[text(m,'beat-unit')],dots=children(m,'beat-unit-dot').length;
    return num(m,'per-minute')*unit*(2-2**(-dots));
  }).filter(t=>t>0&&Number.isFinite(t));
  const tempo=soundTempi[0]||metronomeTempi[0]||100;
  if(new Set([...soundTempi,...metronomeTempi]).size>1)warnings.add('练习使用所选固定速度，暂不跟随谱中速度变化。');
  return {xml,doc,parts,lengths,starts,tempo,title:text(child(root,'work'),'work-title',text(root,'movement-title','未命名乐谱')),warnings:[...warnings],issues};
}

export function inferInstrument(part) {
  return inferInstrumentMetadata(part);
}

export function selectGroups(score, partId, from=1, to=score.lengths.length, options={}) {
  const notes=score.parts.filter(p=>partId==='all'||p.id===partId).flatMap(p=>{
    const settings=options.byPart?.[p.id]||options;
    if(!settings.instrument&&!settings.profileId&&!settings.id&&settings.transpose===undefined)return p.notes;
    const instrument=resolveInstrument(p,settings.instrument||settings.profileId||settings.id||'auto',settings);
    return p.notes.map(n=>{
      const midi=soundingMidi(n,instrument);
      if(!Number.isInteger(midi)||midi<0||midi>127)throw new Error('选择的乐器移调后，音符超出 MIDI 范围。');
      return midi===n.midi?n:{...n,midi,manualTranspose:instrument.transpose};
    });
  }).filter(n=>n.mi>=from-1&&n.mi<to).sort((a,b)=>a.onset-b.onset||a.midi-b.midi);
  const groups=[];
  for(const n of notes) {let g=groups.at(-1);if(!g||Math.abs(g.onset-n.onset)>1e-6){g={onset:n.onset,notes:[],measure:n.measure,mi:n.mi,beat:n.beat};groups.push(g);}g.notes.push(n);}
  return groups;
}

export function isPolyphonic(groups) {
  let end=-Infinity;
  for(const g of groups) {if(g.notes.length>1||g.onset<end-0.04)return true;end=Math.max(...g.notes.map(n=>n.onset+n.duration));}
  return false;
}
