import { knownInstrument, resolveInstrument, resolveProfile } from './instruments.js';

export const NOTEWISE_POLICY_VERSION='notewise-fusion-1';
export const NOTEWISE_FUSION_POLICY=Object.freeze({
  version:NOTEWISE_POLICY_VERSION,
  mono:Object.freeze({windowsPrimary:'pyin',windowsReview:'crepe',applePrimary:'native-mpm-yin',
    appleReview:'basic-pitch',reviewMinimumHz:50,reviewMaximumHz:1975.6,
    onsetToleranceSeconds:.18,centsTolerance:60,appleOnsetToleranceSeconds:.15,appleCentsTolerance:50}),
  poly:Object.freeze({primary:'basic-pitch',review:'independent-acoustic-evidence'}),
  confidence:Object.freeze({native:.9,basicPitch:.5,comparisonIsCalibratedProbability:false}),
});

/** Instrument priors choose analysis, never the note we hope the player performed. */
export function planNoteWise(instruments, {
  phase='recorded',inputKind='microphone',polyphonic=false,platform='windows',
}={}) {
  if(!['realtime','recorded'].includes(phase)||!['midi','microphone','recording'].includes(inputKind)||
    !['apple','windows'].includes(platform)||typeof polyphonic!=='boolean')
    throw new Error('NoteWise 引擎计划参数无效。');
  if(!Array.isArray(instruments)||!instruments.length||instruments.length>128)
    throw new Error('请先确认要练习的声部和乐器。');
  const values=instruments.map(i=>typeof i==='string'?resolveInstrument({},i):i);
  const requiresConfirmation=[];
  for(const i of values) {
    if(!i || i.reliable!==true || !knownInstrument(i.profileId||i.profile?.id||i.id))
      requiresConfirmation.push('instrument');
    if(i?.transpositionConfirmed!==true)requiresConfirmation.push('transposition');
  }
  const profiles=values.map(i=>resolveProfile(i?.profileId||i?.profile?.id||i?.id||'other'));
  const instrumentIds=[...new Set(profiles.map(p=>p.id))];
  const families=[...new Set(profiles.map(p=>p.family))];
  const sequentialSwitch=platform==='windows' && families.length===1 && !polyphonic &&
    values.every(i=>typeof i?.sourcePartId==='string'&&i.sourcePartId.length>0) &&
    new Set(values.map(i=>i.sourcePartId)).size===1;
  if(inputKind!=='midi' && instrumentIds.length>1 && !sequentialSwitch)
    requiresConfirmation.push('instrument');
  const family=families.length===1?families[0]:'mixed';
  const texture=polyphonic||['keyboard','plucked'].includes(family)?'poly':'mono';
  const mode=inputKind==='midi'?'midi':phase==='realtime'?'mono':texture;
  const primary=mode==='midi'?'midi-stream':mode==='poly'?'basic-pitch':
    phase==='realtime'?'native-mpm-yin':platform==='apple'?'native-mpm-yin':'pyin';
  const validators=mode==='midi'?[]:mode==='poly'?['independent-acoustic-evidence']:
    phase==='realtime'?['mpm-yin-agreement']:platform==='apple'?['basic-pitch']:['crepe'];
  return Object.freeze({
    schemaVersion:1,policyVersion:NOTEWISE_POLICY_VERSION,platform,phase,inputKind,mode,texture,primary,
    validators:Object.freeze(validators),instrumentIds:Object.freeze(instrumentIds),family,
    minMidi:Math.min(...profiles.map(p=>p.minMidi)),maxMidi:Math.max(...profiles.map(p=>p.maxMidi)),
    minHz:Math.min(...profiles.map(p=>p.minHz)),maxHz:Math.max(...profiles.map(p=>p.maxHz)),
    requiresConfirmation:Object.freeze([...new Set(requiresConfirmation)]),
    realtimePolyphonySupported:inputKind==='midi',
    needsRecordedReview:inputKind!=='midi'&&(phase==='recorded'||texture==='poly'),
    confidenceThreshold:primary==='basic-pitch'?NOTEWISE_FUSION_POLICY.confidence.basicPitch:
      NOTEWISE_FUSION_POLICY.confidence.native,
    scorePitchUsedForDetection:false,
  });
}
