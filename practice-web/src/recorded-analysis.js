/** Match completed local transcription against the score at its chosen tempo.
 * Onsets are seconds from WAV start; score onsets and durations are quarter beats.
 * Only a constant recording offset is removed. Rhythm is never time-warped.
 */
export function analyzeRecording(groups, detectedNotes, {
  bpm=100, toleranceMs=180, offsetSeconds, alignmentWindowMs=700,confidenceThreshold=.4,
}={}) {
  if(!Array.isArray(groups)||!groups.length)throw new Error('所选范围没有可练习的音符。');
  if(!Number.isFinite(bpm)||bpm<20||bpm>400)throw new Error('练习速度须为 20–400 BPM。');
  if(!Number.isFinite(toleranceMs)||toleranceMs<0||toleranceMs>2000)throw new Error('无效的节奏容差。');
  if(!Number.isFinite(confidenceThreshold)||confidenceThreshold<0||confidenceThreshold>1)throw new Error('无效的置信度阈值。');
  if(!Number.isFinite(alignmentWindowMs)||alignmentWindowMs<0||alignmentWindowMs>3000)throw new Error('无效的对齐窗口。');
  const notes=detectedNotes.map((n,i)=>({...n,detectionIndex:i})).filter(n=>
    Number.isInteger(n.midi)&&n.midi>=0&&n.midi<=127&&
    Number.isFinite(n.onset)&&n.onset>=0&&Number.isFinite(n.duration)&&n.duration>0)
    .sort((a,b)=>a.onset-b.onset||a.midi-b.midi);
  const firstOnset=groups[0].onset, beatSeconds=60/bpm;
  const strong=n=>!Number.isFinite(n.confidence)||n.confidence>=confidenceThreshold;
  const offset=offsetSeconds===undefined?(notes.find(strong)?.onset??notes[0]?.onset??0):offsetSeconds;
  if(!Number.isFinite(offset))throw new Error('无效的录音起点。');
  const errors=[],results=[],matched=new Map(),used=new Set(),usedWeak=new Set();
  const unjudged=notes.filter(n=>!strong(n)).map(n=>({...n,kind:'low-confidence',time:n.onset*1000}));
  const due=groups.map(g=>(g.onset-firstOnset)*beatSeconds+offset);
  const expected=new Map(),actual=new Map();
  const add=(map,key,value)=>{if(!map.has(key))map.set(key,[]);map.get(key).push(value);};
  groups.forEach((g,index)=>{
    matched.set(index,new Map());
    for(const midi of new Set(g.notes.map(n=>n.midi)))add(expected,midi,{index,time:due[index]});
  });
  notes.forEach((n,index)=>{if(strong(n))add(actual,n.midi,{...n,index});});
  // Each MIDI pitch has its own ordered attacks. A sustained note can satisfy
  // one attack only; insertions/deletions do not move the remaining beat clock.
  for(const [midi,wanted] of expected){
    const played=actual.get(midi)??[];
    const window=Math.max(toleranceMs/1000*1.5,Math.min(alignmentWindowMs/1000,beatSeconds*.75));
    for(const [wi,pi] of alignAttacks(wanted,played,window)){
      const w=wanted[wi],p=played[pi];matched.get(w.index).set(midi,p);used.add(p.index);
    }
  }
  const error=(kind,index,data={})=>{
    const g=groups[index];errors.push({kind,index,measure:g.measure,mi:g.mi,beat:g.beat,...data});
  };
  // Unmatched pitches at the time of a score attack are wrong notes. Otherwise
  // they are extra attacks; wrong notes retain the expected score location.
  notes.forEach((n,ni)=>{
    if(used.has(ni)||!strong(n))return;
    let index=0;for(let i=1;i<due.length;i++)if(Math.abs(n.onset-due[i])<Math.abs(n.onset-due[index]))index=i;
    const missing=[...new Set(groups[index].notes.map(v=>v.midi))].filter(m=>!matched.get(index).has(m));
    const delta=(n.onset-due[index])*1000;
    error(missing.length&&Math.abs(delta)<=Math.max(toleranceMs,Math.min(alignmentWindowMs,beatSeconds*750))?'wrong':'extra',index,
      {played:n.midi,expected:missing,delta,time:n.onset*1000,duration:n.duration*1000,detectionIndex:n.detectionIndex});
  });
  groups.forEach((g,index)=>{
    const pitches=[...new Set(g.notes.map(n=>n.midi))],found=matched.get(index);
    for(const [midi,n] of found){
      const delta=(n.onset-due[index])*1000;
      if(Math.abs(delta)>toleranceMs)error(delta<0?'early':'late',index,{played:midi,delta,time:n.onset*1000,detectionIndex:n.detectionIndex});
    }
    const uncertain=pitches.filter(p=>!found.has(p)).filter(midi=>{
      const n=unjudged.find(n=>n.midi===midi&&!usedWeak.has(n.detectionIndex)&&
        Math.abs(n.onset-due[index])<=Math.max(toleranceMs/1000*1.5,Math.min(alignmentWindowMs/1000,beatSeconds*.75)));
      if(!n)return false;usedWeak.add(n.detectionIndex);return true;
    });
    const missing=pitches.filter(p=>!found.has(p)&&!uncertain.includes(p));
    if(missing.length)error('missing',index,{expected:missing,time:due[index]*1000,
      notes:g.notes.filter(n=>missing.includes(n.midi))});
    if(uncertain.length)error('uncertain',index,{expected:uncertain,time:due[index]*1000,
      notes:g.notes.filter(n=>uncertain.includes(n.midi)),confidenceThreshold});
    const bad=errors.some(e=>e.index===index);
    results.push({index,measure:g.measure,beat:g.beat,correct:found.size,expected:pitches.length,
      status:missing.length?'missing':uncertain.length?'uncertain':bad?'corrected':'correct',
      notes:g.notes.map(n=>({...n,matched:found.has(n.midi),uncertain:uncertain.includes(n.midi),actual:found.has(n.midi)?
        {midi:n.midi,onset:found.get(n.midi).onset,duration:found.get(n.midi).duration,confidence:found.get(n.midi).confidence}:null}))});
  });
  return {mode:'recorded',bpm,completed:groups.length,total:groups.length,
    firstTryCorrect:results.filter(r=>r.status==='correct').length,errors,results,
    played:notes.map(n=>({midi:n.midi,time:n.onset*1000,duration:n.duration*1000,confidence:n.confidence})),
    alignment:{offsetSeconds:offset,kind:offsetSeconds===undefined?'first-onset':'explicit',toleranceMs},notes,unjudged,confidenceThreshold};
}

/** Sparse, ordered pitch matching with an absolute time window. */
function alignAttacks(wanted,played,window){
  // The sequence is ordered by time. Dynamic programming within the eligible
  // window maximizes matched attacks, then minimizes onset error.
  const candidates=[];
  let low=0,high=0;
  for(let wi=0;wi<wanted.length;wi++){
    const time=wanted[wi].time;
    while(low<played.length&&played[low].onset<time-window)low++;
    high=Math.max(high,low);while(high<played.length&&played[high].onset<=time+window)high++;
    for(let pi=low;pi<high;pi++)candidates.push({wi,pi,cost:Math.abs(played[pi].onset-time)});
  }
  // Fenwick tree stores the best path ending before this played attack. Update
  // only after processing a score attack to prevent reusing that attack.
  const tree=new Array(played.length+1).fill(null),better=(a,b)=>!a?b:!b?a:
    a.count>b.count||a.count===b.count&&a.cost<=b.cost?a:b;
  const query=p=>{let best=null;for(;p>0;p-=p&-p)best=better(best,tree[p]);return best;};
  const update=(p,value)=>{for(p++;p<tree.length;p+=p&-p)tree[p]=better(tree[p],value);};
  for(let c=0;c<candidates.length;){
    const wi=candidates[c].wi,pending=[];
    while(c<candidates.length&&candidates[c].wi===wi){
      const candidate=candidates[c++],previous=query(candidate.pi);
      pending.push({...candidate,count:(previous?.count??0)+1,cost:(previous?.cost??0)+candidate.cost,previous});
    }
    for(const value of pending)update(value.pi,value);
  }
  const path=[];for(let best=query(played.length);best;best=best.previous)path.push([best.wi,best.pi]);
  return path.reverse();
}
