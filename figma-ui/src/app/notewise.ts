import { createUUID, isNativeCloud, nativeRequest } from "./cloud.ts";
import type { PracticeOwner } from "./practice-owner.ts";
import { createScoreTimeline, noteKey, type NoteKey } from "./score-position.ts";
import { resolveInstrument, soundingMidi } from "./instrument-profiles.ts";

export type InputKind = "timer" | "midi" | "microphone";
export type NoteWiseMode = "follow" | "strict" | "wait";
export type ActualEvent = { eventId: string; type: "on" | "off" | "update" | "uncertainty"; timeMs: number; onsetMs?: number; offsetMs?: number; frequency?: number; midi?: number; channel?: number; velocity?: number; sourceId?: number; confidence: number; timingConfidence: number; cents?: number; centsEvidence?: string; releaseReliable?: boolean; reason?: string; sampleCount?: number; sampleRate?: number };
export type ExpectedNote = NoteKey & { sourceNoteId: string; occurrenceId: string; occurrenceOrdinal: number; midi: number; writtenMidi: number; step: string; alter: number; octave: number; transpose: number; transposeExplicit: boolean; voice: string; staff: string; startMs: number; durationMs: number; onsetBeat: number; durationBeat: number };
type Dimension = { eligible: boolean; outcome: "correct" | "wrong" | "pending" | "unavailable"; error?: number; reason?: string };
export type Opportunity = { opportunityId: string; attemptId: string; occurrenceId: string; sourceNoteIds: string[]; expectedMidi: number; entered: boolean; terminal: boolean; completed: boolean; evaluated: boolean; outcome: "correct" | "wrong" | "missed" | "pending"; actualEventIds: string[]; dimensions: { pitch: Dimension; onset: Dimension; duration: Dimension; intonation: Dimension }; measureIndex: number; noteIndex: number; partId: string; staff: string; voice: string; onsetBeat: number; durationBeat: number; firstTryCorrect: boolean };
export type NoteWiseError = { type: "wrong" | "missed" | "extra" | "rhythm" | "uncertain"; kind: string; opportunityId?: string; eventId?: string; attemptId: string; noteId?: string; measure?: number; expectedMidi?: number; playedMidi?: number; cents?: number; confidence?: number; resolved?: boolean };
export type NoteWiseAnalysis = {
  schemaVersion: 2; contract: "notewise-history-1"; status: "analysed" | "uncertain"; source: "client-reported"; verifiedByServer: false;
  takeId: string; eventId: string; sourceScoreSha256: string; scoreRevision: number; inputKind: Exclude<InputKind, "timer">;
  instrument?: { profileId: string; variant: string; transpose: number; source: "manual" };
  detectorVersion: string; matcherVersion: string; judgeRulesVersion: string; normalizerVersion: string;
  mode: NoteWiseMode; bpm: number; tuning: number; captureClock: { source: string; unit: "ms"; timingCalibrated: boolean; sampleRate?: number; phaseAnchor?: string };
  capabilities: { pitch: boolean; onset: boolean; duration: boolean; intonation: boolean; polyphony: boolean; recording: boolean };
  attempts: { attemptId: string; startMs: number; endMs: number | null; interrupted: boolean }[];
  expected: ExpectedNote[]; actualEvents: ActualEvent[]; opportunities: Opportunity[]; errors: NoteWiseError[];
  coverageByDimension: Record<string, { eligible: number; evaluated: number; failed: number; pending: number }>;
  uncertainty: { timeMs: number; offsetMs?: number; reason: string }[]; completed: boolean; terminal: boolean; performanceDurationMs: number;
  recording?: { takeId: string; available: boolean; mime?: string; durationMs?: number; sampleRate?: number; sampleCount?: number; size?: number; interrupted?: boolean };
};
export type NoteWiseSettings = { mode: NoteWiseMode; inputKind: Exclude<InputKind,"timer">; bpm: number; tuning: number; first: number; last: number; part: string; scoreRevision?: number; instrument?: string; instrumentVariant?: string };
export type NoteWiseFeedback = { position: NoteKey[]; noteStates: { key: NoteKey; state: "correct" | "wrong" | "pending" }[]; correct: number; wrong: number; pending: number; message: string; complete: boolean };

export function expectedPerformance(xml: string, settings: NoteWiseSettings): ExpectedNote[] {
  const timeline = createScoreTimeline(xml), ratio=timeline.initialTempo/settings.bpm, instrument=resolveInstrument({},settings.instrument||"piano",{variant:settings.instrumentVariant});
  const selected=timeline.notes.filter(n=>n.key.measureIndex>=settings.first-1 && n.key.measureIndex<=settings.last-1 && (settings.part==="全部声部" || n.key.partId===settings.part));
  if (!selected.length) throw new Error("所选小节或声部没有可评估的有音高音符。");
  if (selected.length>10000) throw new Error("练习范围过长，请分段练习。");
  const offset=Math.min(...selected.map(n=>n.start));
  return selected.map(n=>({ ...n.key, sourceNoteId:noteKey(n.key), occurrenceId:`${noteKey(n.key)}@${n.occurrenceOrdinal||1}`, occurrenceOrdinal:n.occurrenceOrdinal||1,
    midi:soundingMidi(n,instrument),writtenMidi:n.writtenMidi??n.midi,step:n.step||"",alter:n.alter||0,octave:n.octave??Math.floor(n.midi/12)-1,transpose:n.transposeExplicit?(n.transpose||0):instrument.transpose,transposeExplicit:!!n.transposeExplicit,
    voice:n.voice||"1",staff:n.staff||"1",startMs:(n.start-offset)*1000*ratio,durationMs:(n.end-n.start)*1000*ratio,onsetBeat:n.onsetBeat??0,durationBeat:n.durationBeat??0 }));
}
export function validActualEvent(value: unknown): value is ActualEvent {
  if (!value || typeof value!=="object") return false;
  const e=value as ActualEvent;
  return typeof e.eventId==="string" && e.eventId.length>0 && e.eventId.length<=128 && ["on","off","update","uncertainty"].includes(e.type) && Number.isFinite(e.timeMs) && e.timeMs>=0 && e.timeMs<=86400000 && Number.isFinite(e.confidence) && e.confidence>=0 && e.confidence<=1 && Number.isFinite(e.timingConfidence) && e.timingConfidence>=0 && e.timingConfidence<=1 && (e.type==="uncertainty" || (Number.isInteger(e.midi) && e.midi!>=0 && e.midi!<=127)) && (e.cents===undefined || (Number.isFinite(e.cents)&&Math.abs(e.cents)<=1200));
}
const unavailable=(reason:string): Dimension=>({eligible:false,outcome:"unavailable",reason});

/** One immutable opportunity per attempt, chord occurrence and distinct sounding pitch. */
export class NoteWiseMatcher {
  readonly report: NoteWiseAnalysis;
  private groups: { startMs:number; notes:ExpectedNote[]; opportunities:Opportunity[] }[]=[];
  private index=0;
  private phase: number|null=null;
  private latestTime=0;
  private seen=new Set<string>();
  private noteOpportunity=new Map<string,Opportunity>();
  private attacks=new Map<string,ActualEvent>();
  private continuous=new Map<string,{time:number;cents:number}[]>();
  private interrupted=false;
  private feedback:(value:NoteWiseFeedback)=>void;
  constructor(expected:ExpectedNote[], settings:NoteWiseSettings, identity:{takeId:string;sourceScoreSha256:string}, feedback:(value:NoteWiseFeedback)=>void=()=>{}) {
    this.feedback=feedback;
    const instrument=resolveInstrument({},settings.instrument||"piano",{variant:settings.instrumentVariant});
    const attemptId=`${identity.takeId}:1`;
    this.report={schemaVersion:2,contract:"notewise-history-1",status:"analysed",source:"client-reported",verifiedByServer:false,takeId:identity.takeId,eventId:identity.takeId,sourceScoreSha256:identity.sourceScoreSha256,scoreRevision:settings.scoreRevision||1,inputKind:settings.inputKind,
      instrument:{profileId:instrument.profile.id,variant:instrument.variant,transpose:instrument.transpose,source:"manual"},detectorVersion:settings.inputKind==="midi"?"midi-stream-2":"native-mpm-yin-1",matcherVersion:"online-occurrence-2",judgeRulesVersion:"active-feedback-2",normalizerVersion:"musicxml-repeat-tie-2",mode:settings.mode,bpm:settings.bpm,tuning:settings.tuning,
      captureClock:{source:settings.inputKind==="midi"?"host-monotonic":"audio-sample",unit:"ms",timingCalibrated:false},capabilities:{pitch:true,onset:true,duration:true,intonation:settings.inputKind==="microphone",polyphony:settings.inputKind==="midi",recording:settings.inputKind==="microphone"},
      attempts:[{attemptId,startMs:0,endMs:null,interrupted:false}],expected:structuredClone(expected),actualEvents:[],opportunities:[],errors:[],coverageByDimension:{},uncertainty:[],completed:false,terminal:false,performanceDurationMs:0};
    for (const n of expected.sort((a,b)=>a.startMs-b.startMs)) {
      let group=this.groups[this.groups.length-1];
      if (!group || Math.abs(group.startMs-n.startMs)>1) { group={startMs:n.startMs,notes:[],opportunities:[]}; this.groups.push(group); }
      group.notes.push(n);
      const same=group.opportunities.find(o=>o.expectedMidi===n.midi);
      if (same) { same.sourceNoteIds.push(n.sourceNoteId); same.staff="unknown"; same.voice="unknown"; continue; }
      const opportunity:Opportunity={opportunityId:`${attemptId}:${n.occurrenceId}:${n.midi}`,attemptId,occurrenceId:n.occurrenceId,sourceNoteIds:[n.sourceNoteId],expectedMidi:n.midi,entered:false,terminal:false,completed:false,evaluated:false,outcome:"pending",actualEventIds:[],
        dimensions:{pitch:unavailable("尚未进入此演奏机会"),onset:unavailable(settings.mode==="strict"?"尚未匹配起音":"自由跟谱不按目标速度判断起音"),duration:unavailable("尚无完整释放"),intonation:unavailable(settings.inputKind==="midi"?"MIDI不提供连续音准证据":"尚无稳定连续音高")},
        partId:n.partId,measureIndex:n.measureIndex,noteIndex:n.noteIndex,voice:n.voice,staff:n.staff,onsetBeat:n.onsetBeat,durationBeat:n.durationBeat,firstTryCorrect:false};
      group.opportunities.push(opportunity); this.report.opportunities.push(opportunity);
    }
    this.enter(0); this.publish("已连接演奏输入，准备开始。");
  }
  private enter(index:number) { const group=this.groups[index]; if (!group) return; for (const o of group.opportunities) { o.entered=true; o.dimensions.pitch={eligible:true,outcome:"pending"}; } }
  private error(type:NoteWiseError["type"],kind:string,o?:Opportunity,e?:ActualEvent) {
    this.report.errors.push({type,kind,attemptId:this.report.attempts[0].attemptId,...(o?{opportunityId:o.opportunityId,noteId:o.sourceNoteIds[0],measure:o.measureIndex+1,expectedMidi:o.expectedMidi}:{}),...(e?{eventId:e.eventId,playedMidi:e.midi,confidence:e.confidence,...(e.cents!==undefined?{cents:e.cents}:{})}:{})});
  }
  accept(raw:unknown): boolean {
    if (this.report.terminal || !validActualEvent(raw) || this.report.actualEvents.length>=20000) return false;
    const e={...raw}, key=`${e.eventId}:${e.type}:${e.timeMs}`;
    if (this.seen.has(key)) return false; this.seen.add(key); this.report.actualEvents.push(e); this.latestTime=Math.max(this.latestTime,e.timeMs);
    if (e.sampleRate) this.report.captureClock.sampleRate=e.sampleRate;
    if (e.type==="uncertainty") { this.report.uncertainty.push({timeMs:e.timeMs,...(e.offsetMs!==undefined?{offsetMs:e.offsetMs}:{}),reason:e.reason||"输入不可靠"}); this.report.status="uncertain"; this.publish("疑似声音不清晰，请再弹一次；保留待复核。"); return true; }
    if (e.type==="off") { this.release(e); return true; }
    if (e.type==="update") { this.intonation(e); return true; }
    if (e.confidence<(this.report.detectorVersion==="basic-pitch-coreml-0.4.0"?.5:.9) || e.timingConfidence<.5) { this.report.uncertainty.push({timeMs:e.timeMs,reason:"音高或起音置信度不足"}); this.error("uncertain","low-confidence",this.groups[this.index]?.opportunities[0],e); this.report.status="uncertain"; this.publish("疑似错音，声音证据不足，请再弹一次。"); return true; }
    this.tick(e.timeMs);
    let group=this.groups[this.index];
    if (!group) { this.error("extra","extra",undefined,e); this.publish("乐谱已弹完，本次多弹音已记录。"); return true; }
    let o=group.opportunities.find(o=>o.expectedMidi===e.midi && !o.completed);
    if (!o && (this.report.mode==="follow" || this.report.attempts[0].interrupted)) {
      const future=this.groups.slice(this.index+1,this.index+7).findIndex(g=>g.opportunities.some(o=>o.expectedMidi===e.midi));
      if (future>=0) { for (let i=0;i<=future;i++) this.closeCurrent("missed"); group=this.groups[this.index]; o=group.opportunities.find(o=>o.expectedMidi===e.midi && !o.completed); }
    }
    if (!o) {
      const waiting=group.opportunities.find(o=>!o.completed) || group.opportunities[0];
      waiting.firstTryCorrect=false; waiting.outcome="wrong"; waiting.evaluated=true; waiting.dimensions.pitch={eligible:true,outcome:"wrong"}; waiting.actualEventIds.push(e.eventId);
      this.error("wrong","wrong",waiting,e); this.publish(`第 ${waiting.measureIndex+1} 小节疑似错音：应弹 ${midiName(waiting.expectedMidi)}，收到 ${midiName(e.midi!)}。`); return true;
    }
    if (this.phase===null) { this.phase=e.timeMs-group.startMs; this.report.captureClock.phaseAnchor=e.eventId; }
    const hadWrong=o.outcome==="wrong";
    o.actualEventIds.push(e.eventId); o.completed=true; o.evaluated=true; o.outcome=hadWrong?"wrong":"correct"; o.firstTryCorrect=!hadWrong; o.dimensions.pitch={eligible:true,outcome:hadWrong?"wrong":"correct"};
    this.noteOpportunity.set(e.eventId,o); this.attacks.set(e.eventId,e);
    if (this.report.mode==="strict" && !this.report.attempts[0].interrupted && e.timingConfidence>=.9) { const delta=e.timeMs-(group.startMs+this.phase); o.dimensions.onset={eligible:true,outcome:Math.abs(delta)>Math.max(100,60000/this.report.bpm*.15)?"wrong":"correct",error:delta}; if(o.dimensions.onset.outcome==="wrong")this.error("rhythm",delta<0?"early":"late",o,e); }
    this.intonation(e);
    if (group.opportunities.every(o=>o.completed)) this.closeCurrent();
    this.publish(hadWrong?"已改正并继续，首次错音保留在记录中。":"已跟上演奏。"); return true;
  }
  private intonation(e:ActualEvent) {
    const o=this.noteOpportunity.get(e.eventId);
    if (!o || e.cents===undefined || e.centsEvidence!=="continuous-mpm-yin" || e.confidence<.95) return;
    const samples=this.continuous.get(e.eventId)||[];samples.push({time:e.timeMs,cents:e.cents});this.continuous.set(e.eventId,samples);
    if(samples.length<3 || samples[samples.length-1].time-samples[0].time<100)return;
    const cents=[...samples].sort((a,b)=>a.cents-b.cents)[Math.floor(samples.length/2)].cents;
    o.dimensions.intonation={eligible:true,outcome:Math.abs(cents)>35?"wrong":"correct",error:cents};
    if (o.dimensions.intonation.outcome==="wrong" && !this.report.errors.some(error=>error.opportunityId===o.opportunityId&&error.kind==="intonation")) this.error("wrong","intonation",o,e);
  }
  private release(e:ActualEvent) {
    const o=this.noteOpportunity.get(e.eventId),attack=this.attacks.get(e.eventId);
    if (!o || !attack) return;
    if (!e.releaseReliable || this.report.mode!=="strict" || this.report.attempts[0].interrupted || attack.timingConfidence<.9 || e.timingConfidence<.9) { o.dimensions.duration=unavailable(!e.releaseReliable||this.report.attempts[0].interrupted?"释放或时间来源跨越暂停、停止或断开":"自由跟谱的时值不按目标速度评分"); return; }
    const expected=this.report.expected.find(n=>n.occurrenceId===o.occurrenceId)!, delta=e.timeMs-attack.timeMs-expected.durationMs;
    o.dimensions.duration={eligible:true,outcome:Math.abs(delta)>Math.max(160,expected.durationMs*.3)?"wrong":"correct",error:delta};
    if (o.dimensions.duration.outcome==="wrong") this.error("rhythm",delta<0?"short":"long",o,e);
  }
  tick(timeMs:number) {
    if(this.report.terminal || this.report.mode!=="strict" || this.phase===null || this.interrupted || this.report.attempts[0].interrupted)return;
    while(this.groups[this.index] && timeMs>this.groups[this.index].startMs+this.phase+Math.max(350,60000/this.report.bpm*.65))this.closeCurrent("missed");
  }
  private closeCurrent(missing?:"missed") {
    const group=this.groups[this.index]; if(!group)return;
    for(const o of group.opportunities) { o.terminal=true; if(!o.completed && missing){ const at=group.startMs+(this.phase||0);const uncertain=this.report.uncertainty.some(u=>u.timeMs-500<=at&&(u.offsetMs??u.timeMs)+500>=at) || (!this.report.capabilities.polyphony&&this.report.inputKind==="microphone"&&group.opportunities.length>1); o.outcome=uncertain?"pending":"missed";o.evaluated=!uncertain;o.dimensions.pitch={eligible:true,outcome:uncertain?"pending":"wrong",...(uncertain?{reason:"输入不清晰或单音检测无法覆盖和弦"}:{})}; this.error(uncertain?"uncertain":"missed",uncertain?"ambiguous-input":"missing",o); } }
    this.index++; this.enter(this.index);this.report.completed=this.index===this.groups.length;
  }
  pause() { this.interrupted=true;this.report.attempts[0].interrupted=true;for(const o of this.report.opportunities){o.dimensions.onset=unavailable("起音时钟跨越暂停");o.dimensions.duration=unavailable("释放跨越暂停");}this.attacks.clear(); }
  resume(){ this.interrupted=false; }
  finish(timeMs:number,interrupted=false):NoteWiseAnalysis {
    this.report.terminal=true;this.report.performanceDurationMs=Math.max(this.latestTime,timeMs);this.report.attempts[0].endMs=this.report.performanceDurationMs;this.report.attempts[0].interrupted=this.report.attempts[0].interrupted||interrupted;
    // Stopping never creates misses in untouched future groups.
    for(const o of this.report.opportunities)if(o.entered&&!o.terminal){o.terminal=true;if(!o.completed){o.outcome="pending";o.dimensions.pitch={eligible:true,outcome:"pending",reason:"本次在此机会结束，不能确定漏音"};}}
    this.updateCoverage();return structuredClone(this.report);
  }
  private updateCoverage(){for(const d of ["pitch","onset","duration","intonation"] as const){const values=this.report.opportunities.map(o=>o.dimensions[d]).filter(v=>v.eligible);this.report.coverageByDimension[d]={eligible:values.length,evaluated:values.filter(v=>["correct","wrong"].includes(v.outcome)).length,failed:values.filter(v=>v.outcome==="wrong").length,pending:values.filter(v=>v.outcome==="pending").length};}if(this.report.opportunities.some(o=>o.entered&&o.outcome==="pending"))this.report.status="uncertain";}
  private publish(message:string){this.updateCoverage();const current=this.groups[this.index];const notes=new Map<string,{key:NoteKey;state:"correct"|"wrong"|"pending"}>();for(const o of this.report.opportunities.filter(o=>o.entered)){for(const id of o.sourceNoteIds){const n=this.report.expected.find(n=>n.sourceNoteId===id);if(n)notes.set(id,{key:{partId:n.partId,measureIndex:n.measureIndex,noteIndex:n.noteIndex},state:o.outcome==="correct"?"correct":o.outcome==="wrong"||o.outcome==="missed"?"wrong":"pending"});}}this.feedback({position:current?.notes.map(n=>({partId:n.partId,measureIndex:n.measureIndex,noteIndex:n.noteIndex}))||[],noteStates:[...notes.values()],correct:this.report.opportunities.filter(o=>o.firstTryCorrect).length,wrong:this.report.errors.filter(e=>e.type!=="uncertain").length,pending:this.report.errors.filter(e=>e.type==="uncertain").length,message,complete:this.report.completed});}
}
export const midiName=(midi:number)=>`${["C","C♯","D","E♭","E","F","F♯","G","A♭","A","B♭","B"][midi%12]}${Math.floor(midi/12)-1}`;
export async function scoreDigest(xml:string):Promise<string>{ if(isNativeCloud())return(await nativeRequest<{sha256:string}>("notewise/score-digest",{musicxml:xml})).sha256; const value=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(xml));return Array.from(new Uint8Array(value),b=>b.toString(16).padStart(2,"0")).join(""); }

type RecordedTranscription={notes:{id:string;midi:number;onsetMs:number;offsetMs:number;confidence:number;cents?:number;centsEvidence:string;releaseReliable:boolean}[];uncertaintyIntervals:{onsetMs:number;offsetMs:number;reason:string}[];sampleRate:number;durationMs:number;detectorVersion:string;warnings:string[]};
export async function refineRecording(original:NoteWiseAnalysis):Promise<NoteWiseAnalysis>{
  if(!original.recording?.available)return original;
  const detected=await nativeRequest<RecordedTranscription>("notewise/refine",{takeId:original.takeId,tuning:original.tuning},300000);
  const settings:NoteWiseSettings={inputKind:"microphone",mode:original.mode,bpm:original.bpm,tuning:original.tuning,first:1,last:Number.MAX_SAFE_INTEGER,part:"全部声部",scoreRevision:original.scoreRevision,instrument:original.instrument?.profileId,instrumentVariant:original.instrument?.variant};
  const matcher=new NoteWiseMatcher(structuredClone(original.expected),settings,{takeId:original.takeId,sourceScoreSha256:original.sourceScoreSha256});
  matcher.report.detectorVersion=detected.detectorVersion;matcher.report.capabilities.polyphony=true;matcher.report.capabilities.intonation=false;
  if(original.attempts.some(a=>a.interrupted)){matcher.pause();matcher.resume();}
  const events:ActualEvent[]=[];
  for(const n of detected.notes){events.push({eventId:`review-${n.id}`,type:"on",midi:n.midi,timeMs:n.onsetMs,confidence:n.confidence,timingConfidence:.75,cents:n.cents,centsEvidence:n.centsEvidence,sampleRate:detected.sampleRate});events.push({eventId:`review-${n.id}`,type:"off",midi:n.midi,timeMs:n.offsetMs,confidence:n.confidence,timingConfidence:.75,releaseReliable:n.releaseReliable,cents:n.cents,centsEvidence:n.centsEvidence,sampleRate:detected.sampleRate});}
  for(const u of detected.uncertaintyIntervals)events.push({eventId:createUUID(),type:"uncertainty",timeMs:u.onsetMs,offsetMs:u.offsetMs,confidence:0,timingConfidence:0,reason:u.reason});
  if(events.length>20000)throw new Error("录后音符事件超过可复核上限，请分段练习；实时记录已保留。");
  for(const e of events.sort((a,b)=>a.timeMs-b.timeMs||(a.type==="off"?-1:1)))if(!matcher.accept(e))throw new Error("录后结果含重复或无效事件，实时记录已保留。");
  const report=matcher.finish(detected.durationMs,original.attempts.some(a=>a.interrupted));report.detectorVersion=detected.detectorVersion;report.capabilities.polyphony=true;report.capabilities.intonation=false;report.recording=original.recording;
  // Coarse model contour does not establish precise intonation or calibrated attacks.
  report.captureClock={source:"audio-sample",unit:"ms",timingCalibrated:false,sampleRate:detected.sampleRate};
  return report;
}

export class NoteWiseInput {
  private sequence=-1;
  private active=false;
  private request=0;
  private takeId:string;
  private accept:(value:ActualEvent)=>void;
  private interrupted:(message:string)=>void;
  private owner?:PracticeOwner;
  constructor(takeId:string,accept:(value:ActualEvent)=>void,interrupted:(message:string)=>void,owner?:PracticeOwner){this.takeId=takeId;this.accept=accept;this.interrupted=interrupted;this.owner=owner?{...owner}:undefined;}
  private payload(){return{takeId:this.takeId,...(this.owner?{expectedUserId:this.owner.owner,expectedSessionId:this.owner.sessionId}:{})};}
  private receive=(message:Event)=>{const e=(message as CustomEvent).detail;if(!this.active||e?.type!=="notewiseInput"||e.takeId!==this.takeId||!Number.isInteger(e.sequence)||e.sequence<=this.sequence)return;this.sequence=e.sequence;if(e.status==="interrupted")this.interrupted(typeof e.message==="string"?e.message:"演奏输入中断");else if(validActualEvent(e.event))this.accept(e.event);};
  async start(settings:NoteWiseSettings,instrument:string){if(!isNativeCloud())throw new Error("请在 Apple 应用中连接 MIDI 或使用麦克风；浏览器可继续自由计时。");const request=++this.request;this.active=true;window.addEventListener("notelite-cloud-event",this.receive);try{const result=await nativeRequest("notewise/start",{...this.payload(),inputKind:settings.inputKind,tuning:settings.tuning,instrument},60000);if(request!==this.request){await nativeRequest("notewise/stop",this.payload());throw new Error("开始演奏输入已取消。");}return result;}catch(error){this.active=false;window.removeEventListener("notelite-cloud-event",this.receive);throw error;}}
  async pause(){await nativeRequest("notewise/pause",this.payload());}
  async stop(){++this.request;this.active=false;window.removeEventListener("notelite-cloud-event",this.receive);return nativeRequest<NonNullable<NoteWiseAnalysis["recording"]>>("notewise/stop",this.payload());}
}
