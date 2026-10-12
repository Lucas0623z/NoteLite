import type { ResolvedInstrument } from './instruments.js';
export const NOTEWISE_POLICY_VERSION: string;
export const NOTEWISE_FUSION_POLICY: Readonly<{version:string;mono:Readonly<Record<string,string|number>>;poly:Readonly<Record<string,string>>;confidence:Readonly<Record<string,number|boolean>>}>;
export type NoteWiseEnginePlan = {
  schemaVersion:1;policyVersion:string;platform:'apple'|'windows';phase:'realtime'|'recorded';
  inputKind:'midi'|'microphone'|'recording';mode:'mono'|'poly'|'midi';texture:'mono'|'poly';primary:string;
  validators:readonly string[];instrumentIds:readonly string[];family:string;minMidi:number;maxMidi:number;
  minHz:number;maxHz:number;requiresConfirmation:readonly string[];realtimePolyphonySupported:boolean;
  needsRecordedReview:boolean;confidenceThreshold:number;scorePitchUsedForDetection:false;
};
export function planNoteWise(instruments:(ResolvedInstrument|string)[],options?:{
  phase?:'realtime'|'recorded';inputKind?:'midi'|'microphone'|'recording';polyphonic?:boolean;platform?:'apple'|'windows';
}):NoteWiseEnginePlan;
