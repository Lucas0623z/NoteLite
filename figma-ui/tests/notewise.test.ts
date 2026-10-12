import test from "node:test";
import assert from "node:assert/strict";
import {attributesXML,noteXML,scoreXML} from "./xml-dom.ts";
import {expectedPerformance,NoteWiseMatcher,NoteWiseInput,validActualEvent,type ActualEvent,type NoteWiseSettings} from "../src/app/notewise.ts";
const settings:NoteWiseSettings={inputKind:"midi",mode:"follow",bpm:60,tuning:440,first:1,last:1,part:"全部声部"};
const xml=(body:string)=>scoreXML(`<measure number="1">${attributesXML(1,"4")}<sound tempo="60"/>${body}</measure>`);
const identity={takeId:"11111111-1111-4111-8111-111111111111",sourceScoreSha256:"a".repeat(64)};
const event=(midi:number,timeMs:number,id=`${midi}-${timeMs}`,fields:Partial<ActualEvent>={}):ActualEvent=>({type:"on",eventId:id,midi,timeMs,confidence:1,timingConfidence:1,centsEvidence:"none",...fields});
test("actual note-on moves written cursor, wrong then correction retains first-attempt failure",()=>{
 const changes:unknown[]=[];const m=new NoteWiseMatcher(expectedPerformance(xml(noteXML()+noteXML(1,"","D")),settings),settings,identity,f=>changes.push(f.position));
 m.accept(event(61,100));m.accept(event(60,200));m.accept(event(62,500));const report=m.finish(900);
 assert.deepEqual(report.opportunities.map(o=>[o.outcome,o.firstTryCorrect]),[["wrong",false],["correct",true]]);
 assert.equal(report.coverageByDimension.pitch.eligible,2);assert.equal(report.coverageByDimension.pitch.failed,1);assert.equal(report.completed,true);
 assert.deepEqual(changes[2],[{partId:"P1",measureIndex:0,noteIndex:1}]);
 assert.equal(report.errors.filter(e=>e.type==="wrong").length,1);
});
test("strict relative onset and real note-off duration use capture clock; MIDI zero cents never becomes intonation",()=>{
 const s={...settings,mode:"strict" as const};const m=new NoteWiseMatcher(expectedPerformance(xml(noteXML()+noteXML(1,"","D")),s),s,identity);
 m.accept(event(60,150,"n1",{cents:0}));m.accept(event(60,1150,"n1",{type:"off",releaseReliable:true,cents:0}));
 m.accept(event(62,1350,"n2"));m.accept(event(62,1650,"n2",{type:"off",releaseReliable:true}));const r=m.finish(2000);
 assert.equal(r.opportunities[0].dimensions.duration.outcome,"correct");assert.equal(r.opportunities[1].dimensions.onset.error,200);assert.equal(r.opportunities[1].dimensions.duration.outcome,"wrong");
 assert.equal(r.coverageByDimension.intonation.eligible,0);assert.equal(r.captureClock.timingCalibrated,false);
 assert.deepEqual(r.errors.map(e=>e.kind),["late","short"]);
});
test("finish keeps untouched future opportunities outside denominator and does not invent misses",()=>{
 const m=new NoteWiseMatcher(expectedPerformance(xml(noteXML()+noteXML(1,"","D")+noteXML(1,"","E")),settings),settings,identity);
 m.accept(event(60,100));const r=m.finish(300,true);
 assert.equal(r.errors.length,0);assert.equal(r.opportunities[2].entered,false);assert.equal(r.opportunities[2].terminal,false);
 assert.equal(r.coverageByDimension.pitch.evaluated,1);assert.equal(r.coverageByDimension.pitch.pending,1);assert.equal(r.completed,false);
});
test("follow skips missed groups; wait stays until correct; free timing cannot be scored against BPM",()=>{
 const music=xml(noteXML()+noteXML(1,"","D")+noteXML(1,"","E"));
 const free=new NoteWiseMatcher(expectedPerformance(music,settings),settings,identity);free.accept(event(64,3000));const r=free.finish(4000);
 assert.deepEqual(r.opportunities.map(o=>o.outcome),["missed","missed","correct"]);assert.equal(r.coverageByDimension.onset.eligible,0);
 const s={...settings,mode:"wait" as const};const wait=new NoteWiseMatcher(expectedPerformance(music,s),s,identity);wait.accept(event(64,3000));wait.accept(event(60,5000));
 assert.equal(wait.finish(6000).opportunities[2].entered,false);
});
test("repeated written occurrences remain distinct while unison chord produces one opportunity",()=>{
 const music=scoreXML(`<measure number="1">${attributesXML(1,"1")}<barline><repeat direction="forward"/></barline>${noteXML()+noteXML(1,"<chord/>")}<barline><repeat direction="backward"/></barline></measure>`);
 const e=expectedPerformance(music,settings),m=new NoteWiseMatcher(e,settings,identity);m.accept(event(60,100));m.accept(event(60,1000));const r=m.finish(1800);
 assert.equal(r.expected.length,4);assert.equal(r.opportunities.length,2);assert.notEqual(r.opportunities[0].occurrenceId,r.opportunities[1].occurrenceId);
 assert.equal(r.opportunities[0].sourceNoteIds.length,2);assert.equal(r.opportunities[0].staff,"unknown");assert.equal(r.coverageByDimension.pitch.evaluated,2);
});
test("low confidence and microphone chord gaps stay pending, continuous reliable pitch can support intonation",()=>{
 const s={...settings,inputKind:"microphone" as const};const m=new NoteWiseMatcher(expectedPerformance(xml(noteXML()+noteXML(1,"<chord/>","E")+noteXML(1,"","F")),s),s,identity);
 m.accept(event(60,100,"a1",{cents:45,centsEvidence:"continuous-mpm-yin"}));m.accept(event(60,200,"a1",{type:"update",cents:46,centsEvidence:"continuous-mpm-yin"}));m.accept(event(60,300,"a1",{type:"update",cents:44,centsEvidence:"continuous-mpm-yin"}));m.accept(event(65,1200,"a2"));const r=m.finish(2000);
 assert.equal(r.opportunities[1].outcome,"pending");assert.equal(r.coverageByDimension.intonation.failed,1);assert.ok(r.errors.some(e=>e.type==="uncertain"));
 const low=new NoteWiseMatcher(expectedPerformance(xml(noteXML()),s),s,identity);low.accept(event(61,100,"weak",{confidence:.7}));const q=low.finish(400);assert.equal(q.coverageByDimension.pitch.failed,0);assert.equal(q.coverageByDimension.pitch.pending,1);
});
test("deduplication and event validation reject replay, NaN, forged MIDI and stale terminal events",()=>{
 const m=new NoteWiseMatcher(expectedPerformance(xml(noteXML()),settings),settings,identity),e=event(60,100);
 assert.equal(m.accept(e),true);assert.equal(m.accept(e),false);assert.equal(validActualEvent({...e,midi:128}),false);assert.equal(validActualEvent({...e,timeMs:NaN}),false);
 m.finish(500);assert.equal(m.accept(event(61,600)),false);assert.equal(m.report.actualEvents.length,1);
});
test("expected range and transposition preserve spelling, beat duration and sounding pitch",()=>{
 const music=scoreXML(`<measure number="1">${attributesXML(1,"1")}<attributes><transpose><chromatic>-2</chromatic></transpose></attributes>${noteXML()}</measure><measure number="2">${noteXML(1,"","D")}</measure>`);
 const e=expectedPerformance(music,{...settings,first:2,last:2});assert.equal(e.length,1);assert.equal(e[0].midi,60);assert.equal(e[0].writtenMidi,62);assert.equal(e[0].step,"D");assert.equal(e[0].transpose,-2);assert.equal(e[0].startMs,0);assert.equal(e[0].durationBeat,1);
});
test("pause prevents strict misses and makes incomplete release ineligible",()=>{
 const s={...settings,mode:"strict" as const};const m=new NoteWiseMatcher(expectedPerformance(xml(noteXML()+noteXML(1,"","D")),s),s,identity);m.accept(event(60,100,"n1"));m.pause();m.tick(10000);m.accept(event(60,11000,"n1",{type:"off",releaseReliable:true}));const r=m.finish(12000,true);
 assert.equal(r.errors.length,0);assert.equal(r.opportunities[0].dimensions.duration.eligible,false);
});
test("shared manual instrument variants apply only when the XML has no explicit transpose",()=>{
 const s={...settings,instrument:"clarinet",instrumentVariant:"bb"};
 const bare=expectedPerformance(xml(noteXML()),s);assert.equal(bare[0].midi,58);assert.equal(bare[0].transposeExplicit,false);assert.equal(bare[0].transpose,-2);
 const marked=expectedPerformance(xml(`<attributes><transpose><chromatic>-2</chromatic></transpose></attributes>${noteXML()}`),s);assert.equal(marked[0].midi,58);assert.equal(marked[0].transposeExplicit,true);
 const concert=expectedPerformance(xml(`<attributes><transpose><chromatic>0</chromatic></transpose></attributes>${noteXML()}`),s);assert.equal(concert[0].midi,60);
 const m=new NoteWiseMatcher(bare,s,identity);assert.equal(m.report.instrument?.variant,"bb");m.accept(event(58,100));assert.equal(m.finish(1000).opportunities[0].outcome,"correct");
});
test("recorded polyphonic activation supports missing chord members; unknown models do not lower the threshold",()=>{
 const s={...settings,inputKind:"microphone" as const};const music=xml(noteXML()+noteXML(1,"<chord/>","E")+noteXML(1,"","F"));
 const m=new NoteWiseMatcher(expectedPerformance(music,s),s,identity);m.report.detectorVersion="basic-pitch-coreml-0.4.0";m.report.capabilities.polyphony=true;m.report.capabilities.intonation=false;
 m.accept(event(60,100,"a",{confidence:.6,timingConfidence:.75,cents:40,centsEvidence:"coarse-basic-pitch-contour"}));m.accept(event(65,1200,"b",{confidence:.6,timingConfidence:.75}));
 const r=m.finish(2000);assert.equal(r.opportunities[1].outcome,"missed");assert.equal(r.coverageByDimension.intonation.eligible,0);assert.equal(r.coverageByDimension.onset.eligible,0);
 const unknown=new NoteWiseMatcher(expectedPerformance(xml(noteXML()),s),s,identity);unknown.report.detectorVersion="basic-pitch-unrecognized";unknown.accept(event(60,100,"x",{confidence:.6,timingConfidence:.75}));assert.equal(unknown.finish(2000).coverageByDimension.pitch.evaluated,0);
});
test("long uncertainty intervals retain their end and keep every covered opportunity pending",()=>{
 const m=new NoteWiseMatcher(expectedPerformance(xml(noteXML()+noteXML(1,"","D")+noteXML(1,"","E")),settings),settings,identity);
 m.accept(event(0,0,"noise",{type:"uncertainty",offsetMs:5000,confidence:0,timingConfidence:0,reason:"model-noise"}));m.accept(event(64,3000));const r=m.finish(4000);
 assert.equal(r.actualEvents[0].offsetMs,5000);assert.equal(r.uncertainty[0].offsetMs,5000);assert.deepEqual(r.opportunities.slice(0,2).map(o=>o.outcome),["pending","pending"]);
});

test("normal stop receives the native final release before finishing; cancellation and late events detach",async()=>{
 const saved=globalThis.window;
 const nativeWindow=new EventTarget();
 let stopping:{requestId:string}|undefined;
 Object.assign(nativeWindow,{webkit:{messageHandlers:{noteLiteCloud:{postMessage(message:{requestId:string;action:string}){
   if(message.action==="notewise/stop")stopping=message;
   else queueMicrotask(()=>window.NoteLiteCloudNative!.resolve(message.requestId,{ok:true,result:{connected:true}}));
 }}}}});
 globalThis.window=nativeWindow as Window&typeof globalThis;
 try{
   for(const discard of [false,true]){
     const matcher=new NoteWiseMatcher(expectedPerformance(xml(noteXML()),settings),{...settings,mode:"strict"},identity);
     const input=new NoteWiseInput(identity.takeId,e=>matcher.accept(e),()=>{});
     await input.start(settings,"piano");
     const emit=(sequence:number,e:ActualEvent)=>window.NoteLiteCloudNative!.event({type:"notewiseInput",takeId:identity.takeId,sequence,event:e});
     emit(1,event(60,100,"held"));
     const stopped=input.stop(discard);
     emit(2,event(60,1100,"held",{type:"off",releaseReliable:true}));
     window.NoteLiteCloudNative!.resolve(stopping!.requestId,{ok:true,result:{available:false}});
     await stopped;
     emit(3,event(62,1200,"late"));
     const report=matcher.finish(1200);
     assert.equal(report.actualEvents.length,discard?1:2);
     assert.equal(report.opportunities[0].dimensions.duration.eligible,!discard);
     if(!discard)assert.equal(report.opportunities[0].dimensions.duration.outcome,"correct");
   }
 }finally{globalThis.window=saved;}
});
