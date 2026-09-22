/** A deterministic note-on matcher shared by live inputs and regression tests. */
export class PracticeSession {
  constructor(groups, {mode='wait',bpm=100,toleranceMs=180}={}) {
    if(!groups.length)throw new Error('所选范围没有可练习的音符。');
    this.groups=groups;this.mode=mode;this.bpm=bpm;this.toleranceMs=toleranceMs;
    this.index=0;this.matched=new Set();this.results=[];this.errors=[];this.startedAt=null;this.played=[];
    this.firstOnset=groups[0].onset;this.badGroups=new Set();this.active=true;
  }
  get current(){return this.groups[this.index];}
  expectedAt(group){return this.startedAt+(group.onset-this.firstOnset)*60000/this.bpm;}
  begin(time){this.startedAt=time;}
  tick(time){
    if(!this.active||this.mode!=='tempo'||this.startedAt===null)return;
    while(this.current) {
      const due=this.expectedAt(this.current),next=this.groups[this.index+1];
      const gap=next?this.expectedAt(next)-due:Infinity;
      // At rapid passages a fixed 300ms window would mislabel the next played
      // note as the missing predecessor. Bound the window by the next onset.
      const deadline=due+Math.min(Math.max(300,this.toleranceMs),gap*.6);
      if(time<=deadline)break;
      this.advance(true);
    }
  }
  noteOn(midi,time,cents=0) {
    if(!this.active||!Number.isFinite(midi))return null;
    if(this.mode==='tempo'&&this.startedAt!==null&&time<this.startedAt)return null;
    this.tick(time);
    const g=this.current;if(!g)return null;
    if(this.startedAt===null)this.begin(time);
    this.played.push({midi,time,cents});
    const n=g.notes.find(n=>n.midi===midi && !this.matched.has(n.midi));
    const delta=time-this.expectedAt(g);
    if(this.mode==='tempo'&&delta < -Math.max(300,this.toleranceMs)) {
      const err=this.error('extra',g,{played:midi,delta});return {kind:'extra',group:g,error:err};
    }
    if(!n) {
      if(this.matched.has(midi))return {kind:'duplicate',group:g};
      const err=this.error('wrong',g,{played:midi,expected:g.notes.filter(n=>!this.matched.has(n.midi)).map(n=>n.midi)});
      return {kind:'wrong',group:g,error:err};
    }
    this.matched.add(midi);
    if(Math.abs(cents)>35)this.error('intonation',g,{played:midi,cents});
    if(this.mode==='tempo' && Math.abs(delta)>this.toleranceMs)this.error(delta<0?'early':'late',g,{played:midi,delta});
    const complete=g.notes.every(n=>this.matched.has(n.midi));
    if(complete)this.advance(false);
    return {kind:'correct',group:g,complete};
  }
  error(kind,g,data={}) {
    const error={kind,index:this.index,measure:g.measure,mi:g.mi,beat:g.beat,...data};
    this.errors.push(error);this.badGroups.add(this.index);return error;
  }
  advance(missing=false) {
    const g=this.current;if(!g)return;
    const remaining=g.notes.filter(n=>!this.matched.has(n.midi));
    if(missing&&remaining.length)this.error('missing',g,{expected:remaining.map(n=>n.midi)});
    this.results.push({index:this.index,measure:g.measure,beat:g.beat,correct:this.matched.size,expected:new Set(g.notes.map(n=>n.midi)).size,status:missing?'missing':this.badGroups.has(this.index)?'corrected':'correct'});
    this.index++;this.matched.clear();if(!this.current)this.active=false;
  }
  finish(){this.active=false;return this.report();}
  report(){
    return {mode:this.mode,bpm:this.bpm,completed:this.index,total:this.groups.length,firstTryCorrect:this.results.filter(r=>r.status==='correct').length,errors:this.errors,results:this.results,played:this.played};
  }
}

/** Gate stable monophonic estimates; held notes do not count as repeated attacks. */
export class PitchGate {
  constructor(){this.reset();}
  reset(){this.candidate=null;this.frames=0;this.last=null;this.silentFrames=0;}
  push(frequency,clarity,rms) {
    // A momentary loss of periodicity during a sustained bow/blown note is not
    // a new attack. Release only on genuinely quiet audio, not on low clarity.
    if(!Number.isFinite(rms)||rms<0.008){
      this.candidate=null;this.frames=0;
      if(++this.silentFrames>=3)this.last=null;
      return null;
    }
    this.silentFrames=0;
    if(!(frequency>=27.5&&frequency<=4200)||!Number.isFinite(clarity)||clarity<0.9){
      this.candidate=null;this.frames=0;return null;
    }
    const raw=69+12*Math.log2(frequency/440),midi=Math.round(raw),cents=(raw-midi)*100;
    if(this.candidate!==midi){this.candidate=midi;this.frames=1;return null;}
    if(++this.frames<3||this.last===midi)return null;
    this.last=midi;return {midi,cents};
  }
}
