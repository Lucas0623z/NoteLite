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
    const name=text(meta,'part-name',`声部 ${pi+1}`), program=num(child(meta,'midi-instrument'),'midi-program',0);
    let divisions=1, beats=4, beatType=4, transpose=0, ties=new Map(), noteIndex=0,knownTime=false;
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
            if(staff)staffTransposes.set(staff,value);else{transpose=value;staffTransposes.clear();}
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
            const midi=12*(num(pitch,'octave')+1)+(pitches[text(pitch,'step')]??NaN)+num(pitch,'alter')+(staffTransposes.get(staff)??transpose);
            if(!Number.isInteger(midi)||midi<0||midi>127)throw new Error('暂不支持微分音或超出 MIDI 范围的乐谱。');
            const key=`${voice}/${staff}/${midi}`, types=children(item,'tie').map(t=>t.getAttribute('type'));
            if(types.includes('stop') && ties.has(key)) {ties.get(key).duration+=duration;if(!types.includes('start'))ties.delete(key);}
            else {const n={id:`${id}:${ni}`,part:id,mi,measure:measure.getAttribute('number')||String(mi+1),beat:onset*beatType/4+1,onset,duration,midi,voice,staff,xmlIndex:ni};notes.push(n);if(types.includes('start'))ties.set(key,n);}
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
    return {id,name,program,notes,lengths,meters,transpose};
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
  const n=part.name.toLowerCase();
  // Named instruments take precedence over the default GM piano program.
  const moreNames=[[/harpsichord|羽管键琴|大键琴/,'羽管键琴','midi'],[/english horn|cor anglais|英国管/,'英国管','microphone'],[/oboe|双簧管/,'双簧管','microphone'],[/bassoon|巴松|大管/,'巴松','microphone'],[/contrabass|double bass|低音提琴/,'低音提琴','microphone'],[/\b(?:electric bass|acoustic bass|bass guitar)\b|^bass$|贝斯/,'贝斯','microphone'],[/\bharp\b|竖琴/,'竖琴','microphone'],[/organ|管风琴/,'管风琴','midi'],[/accordion|手风琴/,'手风琴','midi'],[/harmonica|口琴/,'口琴','microphone'],[/piccolo|短笛/,'短笛','microphone'],[/recorder|竖笛/,'竖笛','microphone'],[/二胡|erhu/,'二胡','microphone'],[/古筝|guzheng/,'古筝','microphone'],[/琵琶|pipa/,'琵琶','microphone'],[/古琴|guqin/,'古琴','microphone'],[/唢呐|suona/,'唢呐','microphone']];
  for(const [pattern,name,input] of moreNames)if(pattern.test(n))return {name,source:'谱面乐器名称',input};
  const names=[[/piano|keyboard|钢琴|电子琴|键盘/,'钢琴 / 键盘','midi'],[/guitar|吉他/,'吉他','microphone'],[/violin|小提琴/,'小提琴','microphone'],[/viola|中提琴/,'中提琴','microphone'],[/cello|大提琴/,'大提琴','microphone'],[/flute|长笛|笛子/,'长笛 / 笛类','microphone'],[/clarinet|单簧管/,'单簧管','microphone'],[/sax|萨克斯/,'萨克斯','microphone'],[/trumpet|horn|trombone|小号|圆号|长号/,'铜管','microphone'],[/voice|vocal|soprano|tenor|声乐|人声/,'人声','microphone']];
  for(const [pattern,name,input] of names)if(pattern.test(n))return {name,source:'谱面乐器名称',input};
  const p=part.program;
  const morePrograms={69:'双簧管',70:'英国管',71:'巴松',44:'低音提琴',47:'竖琴',73:'短笛',75:'竖笛',23:'口琴'};
  if(morePrograms[p])return {name:morePrograms[p],source:'谱面 MIDI 音色',input:'microphone'};
  if(p>=33&&p<=40)return {name:'贝斯',source:'谱面 MIDI 音色',input:'microphone'};
  if(p>=17&&p<=24)return {name:'管风琴 / 手风琴',source:'谱面 MIDI 音色',input:'midi'};
  if(/piano|keyboard|钢琴|电子琴|键盘/.test(n)||(p>=1&&p<=8))return {name:'钢琴 / 键盘',source:'谱面乐器信息',input:'midi'};
  if(/guitar|吉他/.test(n)||(p>=25&&p<=32))return {name:'吉他',source:'谱面乐器信息',input:'microphone'};
  if(/violin|小提琴/.test(n)||p===41)return {name:'小提琴',source:'谱面乐器信息',input:'microphone'};
  if(/viola|中提琴/.test(n)||p===42)return {name:'中提琴',source:'谱面乐器信息',input:'microphone'};
  if(/cello|大提琴/.test(n)||p===43)return {name:'大提琴',source:'谱面乐器信息',input:'microphone'};
  if(/flute|长笛|笛子/.test(n)||(p>=73&&p<=80))return {name:'长笛 / 笛类',source:'谱面乐器信息',input:'microphone'};
  if(/clarinet|单簧管/.test(n)||p===72)return {name:'单簧管',source:'谱面乐器信息',input:'microphone'};
  if(/sax|萨克斯/.test(n)||(p>=65&&p<=68))return {name:'萨克斯',source:'谱面乐器信息',input:'microphone'};
  if(/trumpet|horn|trombone|小号|圆号|长号/.test(n)||(p>=57&&p<=64))return {name:'铜管',source:'谱面乐器信息',input:'microphone'};
  if(/voice|vocal|soprano|tenor|声乐|人声/.test(n)||(p>=53&&p<=55))return {name:'人声',source:'谱面乐器信息',input:'microphone'};
  return {name:'乐器未标明',source:'请手动确认；谱号和音域不足以确定乐器',input:'microphone'};
}

export function selectGroups(score, partId, from=1, to=score.lengths.length) {
  const notes=score.parts.filter(p=>partId==='all'||p.id===partId).flatMap(p=>p.notes).filter(n=>n.mi>=from-1&&n.mi<to).sort((a,b)=>a.onset-b.onset||a.midi-b.midi);
  const groups=[];
  for(const n of notes) {let g=groups.at(-1);if(!g||Math.abs(g.onset-n.onset)>1e-6){g={onset:n.onset,notes:[],measure:n.measure,mi:n.mi,beat:n.beat};groups.push(g);}g.notes.push(n);}
  return groups;
}

export function isPolyphonic(groups) {
  let end=-Infinity;
  for(const g of groups) {if(g.notes.length>1||g.onset<end-0.04)return true;end=Math.max(...g.notes.map(n=>n.onset+n.duration));}
  return false;
}
