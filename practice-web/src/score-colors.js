const options={applyToNoteheads:true,applyToStem:true,applyToBeams:false,applyToModifiers:false};

/** Keep source notes: OSMD replaces graphical notes and SVG elements on reflow. */
export function collectScoreNotes(osmd){
  const entries=[],seen=new Set();
  for(const instrument of osmd.Sheet.Instruments)for(const voice of instrument.Voices)for(const entry of voice.VoiceEntries)for(const note of entry.Notes){
    if(seen.has(note)||note.isRest()||note.IsGraceNote)continue;
    seen.add(note);
    entries.push({note,part:instrument.IdString,onset:note.getAbsoluteTimestamp().RealValue*4,
      originalHead:note.NoteheadColor,originalStem:note.ParentVoiceEntry.StemColor});
  }
  return entries;
}

function paint(osmd,entry,color,reset=false){
  const note=entry.note;
  // Model colors survive OSMD's next autoResize/render. Resolve the current
  // graphical note for immediate SVG feedback rather than caching a stale one.
  note.NoteheadColor=reset?entry.originalHead:color;
  note.ParentVoiceEntry.StemColor=reset?entry.originalStem:color;
  const graphic=osmd.EngravingRules.GNote(note);
  graphic?.setColor(reset?(entry.originalHead||'#202733'):color,options);
  if(reset&&entry.originalStem&&entry.originalStem!==entry.originalHead)graphic?.getStemSVG()?.setAttribute('stroke',entry.originalStem);
}

export function colorScoreGroup(osmd,entries,group,color){
  if(!group)return;
  const parts=new Set(group.notes.map(n=>n.part));
  for(const entry of entries)if(Math.abs(entry.onset-group.onset)<1e-5&&parts.has(entry.part))paint(osmd,entry,color);
}

export function resetScoreColors(osmd,entries){
  for(const entry of entries)paint(osmd,entry,'#202733',true);
}
