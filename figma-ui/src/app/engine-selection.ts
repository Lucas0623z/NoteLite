import { createScoreTimeline, type PlaybackNote } from "./score-position.ts";
import { readScoreInstruments, resolveInstrumentForNote, type ResolvedInstrument } from "./instrument-profiles.ts";
import { planNoteWise } from "../../../practice-web/src/engine-policy.js";

type Selection = { instrument?:string;instrumentVariant?:string;part:string;first:number;last:number;inputKind:"midi"|"microphone" };

export function selectPerformanceSources(xml:string,settings:Selection) {
  const timeline=createScoreTimeline(xml);
  const parts=new Map(readScoreInstruments(xml).parts.map(p=>[p.id,p]));
  const notes=timeline.notes.filter(n=>n.key.measureIndex>=settings.first-1&&n.key.measureIndex<settings.last&&
    (settings.part==="全部声部"||n.key.partId===settings.part||parts.get(n.key.partId)?.name===settings.part));
  if(!notes.length)throw new Error("所选小节或声部没有可评估的有音高音符。");
  if(notes.length>10000)throw new Error("练习范围过长，请分段练习。");
  const instruments=new Map<PlaybackNote,ResolvedInstrument>();
  for(const note of notes) instruments.set(note,resolveInstrumentForNote(parts.get(note.key.partId)||{},
    note,settings.instrument||"piano",{variant:settings.instrumentVariant}));
  // A route describes instruments, not individual notes. Retain different
  // certainty/transpose states while bounding long scores by unique routes.
  const routes=new Map<string,ResolvedInstrument>();
  for(const value of instruments.values()) routes.set(JSON.stringify([
    value.profileId,value.reliable,value.transpositionConfirmed,value.variant,value.transpose,
  ]),value);
  const values=[...routes.values()];
  const plan=planNoteWise(values,{platform:"apple",phase:"realtime",inputKind:settings.inputKind,
    polyphonic:selectionIsPolyphonic(notes)});
  if(plan.instrumentIds.length>1 && values.every(value=>value.reliable))
    throw new Error("所选范围包含多种乐器，请选择单独声部，或在设置中确认你实际演奏的乐器。");
  if(plan.requiresConfirmation.includes("instrument"))
    throw new Error("谱面乐器信息不足或包含未解析的换乐器标记，请在设置中确认要演奏的乐器。");
  if(plan.requiresConfirmation.includes("transposition"))
    throw new Error("谱面缺少移调信息，请在设置中选择乐器及实音谱制，避免将正确演奏判成错音。");
  if(plan.instrumentIds.length>1)
    throw new Error("所选范围包含多种乐器，请选择单独声部，或在设置中确认你实际演奏的乐器。");
  return {timeline,notes,instruments,plan};
}

export function selectionIsPolyphonic(notes:readonly Pick<PlaybackNote,"start"|"end"|"midi">[]) {
  const ordered=[...notes].sort((a,b)=>a.start-b.start||a.end-b.end);
  let end=-Infinity;
  for(const n of ordered){if(n.start<end-.0001)return true;end=Math.max(end,n.end);}
  return false;
}
