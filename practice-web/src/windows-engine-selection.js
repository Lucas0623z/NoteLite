import {resolveInstrumentForNote} from './instruments.js';

/** Windows routing uses the same actual selected note references as normalization.
 * Whole-score metadata cannot hide a switching part or invalidate a selected
 * excerpt whose notation was already explicitly confirmed.
 */
export function selectedWindowsInstruments(score,groups,settingsForPart=()=>({instrument:'auto'})){
  const notes=groups.flatMap(g=>g.notes),resolved=[];
  for(const part of score.parts){
    const selected=notes.filter(n=>n.part===part.id);
    if(!selected.length)continue;
    const scope={...part,notes:selected},options=settingsForPart(part)||{instrument:'auto'},seen=new Set();
    for(const note of selected){
      const value=resolveInstrumentForNote(scope,note,options.instrument||options.profileId||options.id||'auto',options);
      const key=JSON.stringify([value.profileId,value.reliable,value.transpositionConfirmed,value.transpose,value.source]);
      if(!seen.has(key)){seen.add(key);resolved.push({...value,sourcePartId:part.id});}
    }
  }
  return resolved;
}
