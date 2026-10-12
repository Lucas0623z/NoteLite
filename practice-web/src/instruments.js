const hz = midi => 440 * 2 ** ((midi - 69) / 12);
const variant = (id, name, transpose) => Object.freeze({id, name, transpose});
const concert = [variant('concert', '实音 / C 调', 0)];
const families = {
  piano:'keyboard', harpsichord:'keyboard', clavinet:'keyboard', organ:'keyboard', accordion:'keyboard',
  violin:'bowed', viola:'bowed', cello:'bowed', contrabass:'bowed', erhu:'bowed', strings:'bowed',
  harp:'plucked', guitar:'plucked', bass:'plucked', guzheng:'plucked', pipa:'plucked', guqin:'plucked',
  flute:'wind', clarinet:'wind', bassoon:'wind', oboe:'wind', horn:'wind', trumpet:'wind', trombone:'wind',
  tuba:'wind', euphonium:'wind', 'english-horn':'wind', harmonica:'wind', piccolo:'wind', recorder:'wind',
  sax:'wind', suona:'wind', winds:'wind', voice:'voice',
};

function profile(id, name, minMidi, maxMidi, windowSize = 4096, variants = concert, input = 'microphone') {
  return Object.freeze({
    id, name, minMidi, maxMidi, minHz: hz(minMidi), maxHz: hz(maxMidi), windowSize,
    family:families[id] || 'generic', input, recommendedInput: input,
    realtimeEngine:'mpm', recordingEngine:'notewise-fusion',
    defaultVariant: variants[0].id, variants: Object.freeze(variants),
  });
}

// These are broad sounding-pitch ranges, independent of the next expected note.
// Low instruments need a longer microphone window to include several periods.
export const INSTRUMENT_PROFILES = Object.freeze([
  profile('piano', '钢琴 / 键盘', 21, 108, 8192, concert, 'midi'),
  profile('violin', '小提琴', 55, 108),
  profile('viola', '中提琴', 48, 101),
  profile('cello', '大提琴', 36, 96, 8192),
  profile('contrabass', '低音提琴', 24, 84, 8192, [variant('octave', '低八度发声', -12), ...concert]),
  profile('harp', '竖琴', 24, 103, 8192),
  profile('flute', '长笛 / 笛类', 48, 108),
  profile('clarinet', '单簧管', 34, 103, 8192, [variant('bb', '降 B 调', -2), variant('a', 'A 调', -3), variant('eb', '降 E 调', 3), ...concert]),
  profile('bassoon', '巴松', 22, 89, 8192),
  profile('oboe', '双簧管', 53, 101),
  profile('horn', '圆号', 28, 96, 8192, [variant('f', 'F 调', -7), variant('bb', '降 B 调', -2), ...concert]),
  profile('trumpet', '小号', 42, 103, 4096, [variant('bb', '降 B 调', -2), ...concert]),
  profile('trombone', '长号', 28, 91, 8192),
  profile('tuba', '大号', 21, 84, 8192),
  profile('euphonium', '上低音号 / 次中音号', 28, 91, 8192, [variant('bass', '低音谱号 / 实音', 0), variant('bb-treble', '降 B 调高音谱号', -14)]),
  profile('voice', '人声', 36, 101, 8192),
]);

const byId = new Map(INSTRUMENT_PROFILES.map(p => [p.id, p]));
const generic = profile('other', '其他有固定音高乐器', 21, 108, 8192);
const additional = [
  [/harpsichord|羽管键琴|大键琴/i, 'harpsichord', '羽管键琴', 'midi'],
  [/clavinet|clavi\b|击弦古钢琴/i, 'clavinet', '击弦古钢琴', 'midi'],
  [/english horn|cor anglais|英国管/i, 'english-horn', '英国管'],
  [/\b(?:electric bass|acoustic bass|bass guitar)\b|^bass$|贝斯/i, 'bass', '贝斯'],
  [/organ|管风琴/i, 'organ', '管风琴', 'midi'],
  [/accordion|手风琴/i, 'accordion', '手风琴', 'midi'],
  [/harmonica|口琴/i, 'harmonica', '口琴'],
  [/piccolo|短笛/i, 'piccolo', '短笛'],
  [/recorder|竖笛/i, 'recorder', '竖笛'],
  [/guitar|吉他/i, 'guitar', '吉他'],
  [/sax|萨克斯/i, 'sax', '萨克斯'],
  [/二胡|erhu/i, 'erhu', '二胡'],
  [/古筝|guzheng/i, 'guzheng', '古筝'],
  [/琵琶|pipa/i, 'pipa', '琵琶'],
  [/古琴|guqin/i, 'guqin', '古琴'],
  [/唢呐|suona/i, 'suona', '唢呐'],
];
const extraById = new Map(additional.map(([, id, name, input]) => [id, Object.freeze({...generic, id, name, input: input || 'microphone', recommendedInput: input || 'microphone'})]));
// Additional variants are explicit choices. Existing concert defaults stay compatible.
const extraVariants = {
  'english-horn':[...concert, variant('f','F 调',-7)],
  piccolo:[...concert, variant('octave','高八度发声',12)],
  guitar:[...concert, variant('octave','低八度发声',-12)],
  bass:[...concert, variant('octave','低八度发声',-12)],
  sax:[...concert, variant('bb-soprano','降 B 调高音',-2), variant('eb-alto','降 E 调中音',-9),
    variant('bb-tenor','降 B 调次中音',-14), variant('eb-baritone','降 E 调上低音',-21)],
};
for (const [id,p] of extraById) extraById.set(id,Object.freeze({...p,family:families[id]||'generic',
  variants:Object.freeze(extraVariants[id]||p.variants)}));
// Keep old broad manual choices and existing named-instrument suggestions usable.
extraById.set('strings', Object.freeze({...generic, id: 'strings', name: '提琴', family:'bowed'}));
extraById.set('winds', Object.freeze({...generic, id: 'winds', name: '管乐', family:'wind'}));
extraById.set('other', generic);
export const ALL_INSTRUMENT_PROFILES = Object.freeze([...INSTRUMENT_PROFILES,...extraById.values()]);
export const knownInstrument = id => byId.has(id) || extraById.has(id);

const named = [
  [/piano|keyboard|钢琴|电子琴|键盘|^pno\.?$|^pf\.?$/i, 'piano'],
  [/contrabass|double bass|低音提琴|^cb\.?$/i, 'contrabass'],
  [/violin|小提琴|^vln?\.?$/i, 'violin'],
  [/viola|中提琴|^vla\.?$/i, 'viola'],
  [/cello|violoncello|大提琴|^vc\.?$/i, 'cello'],
  [/\bharp\b|竖琴|^hp\.?$/i, 'harp'],
  [/flute|长笛|笛子|^fl\.?$/i, 'flute'],
  [/clarinet|单簧管|^cl\.?$/i, 'clarinet'],
  [/bassoon|巴松|大管|^bsn\.?$|^fg\.?$/i, 'bassoon'],
  [/oboe|双簧管|^ob\.?$/i, 'oboe'],
  [/euphonium|次中音号|上低音号|^euph\.?$/i, 'euphonium'],
  [/trumpet|小号|^tpt\.?$|^trp\.?$/i, 'trumpet'],
  [/trombone|长号|^tbn\.?$/i, 'trombone'],
  [/tuba|大号|^tba\.?$/i, 'tuba'],
  [/\bhorn\b|圆号|法国号|^hn\.?$|^cor\.?$/i, 'horn'],
  [/voice|vocal|soprano|mezzo|contralto|baritone|tenor|choir|声乐|人声|合唱/i, 'voice'],
];

export function resolveProfile(id) {
  return typeof id === 'object' && id ? resolveProfile(id.id || id.profileId) : byId.get(id) || extraById.get(id) || generic;
}

function metadataNames(part = {}) {
  const scoreNames = part.instrumentNames || (part.instrumentName ? [part.instrumentName] : []);
  // Exporters often fill score-instrument with a default piano or choir sound.
  // A specific named part such as Violin remains stronger evidence than that
  // playback label; generic Piano/Voice headings keep score-instrument priority.
  const namedPart = typeof part.name === 'string' ? nameProfile(part.name) : null;
  const names = namedPart && !['piano','voice'].includes(namedPart.id) ? [part.name, ...scoreNames] : [...scoreNames, part.name];
  return [...names, ...(part.instrumentAbbreviations || []), part.abbreviation || part.partAbbreviation]
    .filter(n => typeof n === 'string' && n.trim()).map(n => n.trim());
}

function nameProfile(name) {
  // Qualified instruments must be checked before broad family words such as horn.
  for (const [pattern, id] of additional) if (pattern.test(name)) return resolveProfile(id);
  for (const [pattern, id] of named) if (pattern.test(name)) return resolveProfile(id);
}

const gmAdditional = {7:'harpsichord',8:'clavinet',22:'accordion',23:'harmonica',24:'accordion',
  70:'english-horn',73:'piccolo',75:'recorder'};
function programProfile(program) {
  if (gmAdditional[program]) return resolveProfile(gmAdditional[program]);
  const ids = {41:'violin',42:'viola',43:'cello',44:'contrabass',47:'harp',57:'trumpet',58:'trombone',59:'tuba',61:'horn',69:'oboe',71:'bassoon',72:'clarinet',74:'flute'};
  if (ids[program]) return resolveProfile(ids[program]);
  if (program >= 1 && program <= 6) return resolveProfile('piano');
  if (program >= 17 && program <= 21) return resolveProfile('organ');
  if (program >= 25 && program <= 32) return resolveProfile('guitar');
  if (program >= 33 && program <= 40) return resolveProfile('bass');
  if (program >= 53 && program <= 55) return resolveProfile('voice');
  if (program >= 57 && program <= 64) return Object.freeze({...generic, id:'brass',name:'铜管'});
  if (program >= 65 && program <= 68) return resolveProfile('sax');
  if (program >= 73 && program <= 80) return resolveProfile('flute');
}

function inferred(part, allowDefaultPiano = false) {
  if (part?.instrumentConfirmed === false) return {profile:generic, source:'谱面没有确认的乐器信息，请手动选择', reliable:false};
  const names = metadataNames(part);
  for (const name of names) {
    const match = nameProfile(name);
    if (match) return {profile:match, source:'谱面乐器名称', reliable:true, metadataName:name};
  }
  const program = Number(part?.program);
  const explicitProgram = part?.programExplicit ?? (Number.isInteger(program) && program > 0);
  const hasUnknownName = names.some(n => !/^(?:part|staff|instrument|unknown|unnamed|声部|乐器|未命名|未标明)(?:\s*\d+)?$/i.test(n));
  const match = explicitProgram && Number.isInteger(program) && program > 0 && program <= 128 && programProfile(program);
  // GM 1 is frequently an exporter's placeholder; an unrecognized instrument
  // name should remain available for manual confirmation instead of becoming piano.
  if (match && (allowDefaultPiano || program !== 1 || !hasUnknownName)) return {profile:match, source:'谱面 MIDI 音色', reliable:true};
  return {profile:generic, source:'请手动确认；谱号和音域不足以确定乐器', reliable:false};
}

/** Resolve a selected instrument without inferring transposition from an auto label. */
export function resolveInstrument(part, selected = 'auto', options = {}) {
  if (selected && typeof selected === 'object') {options = {...selected, ...options}; selected = options.instrument || options.profileId || options.id || 'auto';}
  const manual = selected !== 'auto';
  const result = manual ? {profile:resolveProfile(selected), source:knownInstrument(selected)?'已手动选择乐器':'未识别的乐器，请重新选择',
    reliable:knownInstrument(selected)} : inferred(part);
  const p = result.profile;
  if (manual && options.variant !== undefined && options.variant !== null &&
      options.variant !== '' && !p.variants.some(v => v.id === options.variant))
    throw new Error('所选乐器谱制无效，请重新选择。');
  const selectedVariant = p.variants.find(v => v.id === options.variant) || p.variants.find(v => v.id === p.defaultVariant);
  const override = options.transpose !== undefined && options.transpose !== null && options.transpose !== '';
  const transpose = override ? Number(options.transpose) : manual ? selectedVariant.transpose : 0;
  if (!Number.isInteger(transpose) || Math.abs(transpose) > 48) throw new Error('乐器移调须为 -48 至 48 之间的整数半音。');
  const explicit = part?.concertScore === true || part?.transposeExplicit === true ||
    (Array.isArray(part?.notes) && part.notes.length>0 && part.notes.every(n=>n.transposeExplicit));
  const transpositionConfirmed = manual && result.reliable || override || explicit || !p.variants.some(v=>v.transpose!==0);
  return {...p, profile:p, profileId:result.reliable ? p.id : null, name:result.reliable ? p.name : '乐器未标明',
    source:result.source, reliable:result.reliable, metadataName:result.metadataName,
    manual, variant:selectedVariant.id, transpose, transposeOverride:override, transpositionConfirmed};
}

/** Resolve the actual score-instrument reference, never the first sound of a switching part. */
export function resolveInstrumentForNote(part, note, selected='auto', options={}) {
  if (selected!=='auto') return resolveInstrument({...part,transposeExplicit:!!note?.transposeExplicit},selected,options);
  const refs=Array.isArray(note?.instrumentIds)?note.instrumentIds:[];
  if (refs.length>1) return {...resolveInstrument({instrumentConfirmed:false}),source:'同一音符含多个乐器，需要确认演奏声部'};
  if (refs.length===1) {
    const entry=part?.instruments?.find(i=>i.id===refs[0]);
    if (!entry) return {...resolveInstrument({instrumentConfirmed:false}),source:'音符引用的乐器条目不存在'};
    return resolveInstrument({...part,name:entry.name||part.name,instrumentNames:[entry.name],
      instrumentAbbreviations:[entry.abbreviation],program:entry.program,programExplicit:entry.programExplicit,
      transposeExplicit:!!note.transposeExplicit,notes:[]},'auto',options);
  }
  if (part?.instruments?.length>1)
    return {...resolveInstrument({instrumentConfirmed:false}),source:'多乐器声部缺少逐音符乐器标记'};
  return resolveInstrument({...part,transposeExplicit:!!note?.transposeExplicit},'auto',options);
}

/** Metadata-only MusicXML reading shared by the shells; no register-based instrument guess. */
export function readScoreInstruments(xml, Parser=globalThis.DOMParser) {
  if (typeof xml!=='string' || !Parser) throw new Error('无法读取曲谱乐器信息。');
  const doc=new Parser().parseFromString(xml,'application/xml');
  const direct=(p,name)=>Array.from(p?.childNodes||[]).filter(n=>n.nodeType===1&&(!name||n.localName===name));
  const one=(p,name)=>direct(p,name)[0], txt=(p,name)=>one(p,name)?.textContent?.trim()||'';
  const root=doc.documentElement;
  if (root?.localName!=='score-partwise' || doc.getElementsByTagName('parsererror').length)
    throw new Error('MusicXML 乐器信息无效。');
  const metas=direct(one(root,'part-list'),'score-part');
  const concertScore=!!one(one(root,'defaults'),'concert-score');
  const parts=direct(root,'part').map((part,index)=>{
    const id=part.getAttribute('id')||'P'+(index+1),meta=metas.find(p=>p.getAttribute('id')===id);
    const midi=direct(meta,'midi-instrument');
    const instruments=direct(meta,'score-instrument').map(entry=>{
      const sound=midi.find(m=>m.getAttribute('id')===entry.getAttribute('id'));
      return {id:entry.getAttribute('id')||'',name:txt(entry,'instrument-name'),abbreviation:txt(entry,'instrument-abbreviation'),
        program:Number(txt(sound,'midi-program'))||0,programExplicit:!!one(sound,'midi-program')};
    });
    const notes=[],staffTransposes=new Set();let transposeExplicit=concertScore;
    for (const measure of direct(part,'measure')) for (const element of direct(measure)) {
      if(element.localName==='attributes') for (const transpose of direct(element,'transpose')) {
        const staff=transpose.getAttribute('number');
        if(staff)staffTransposes.add(staff);else {transposeExplicit=true;staffTransposes.clear();}
      }
      if(element.localName==='note' && one(element,'pitch')) notes.push({
        instrumentIds:direct(element,'instrument').map(i=>i.getAttribute('id')).filter(Boolean),
        transposeExplicit:transposeExplicit||staffTransposes.has(txt(element,'staff')||'1')});
    }
    const first=instruments[0],program=midi.find(m=>one(m,'midi-program'));
    return {id,name:txt(meta,'part-name')||id,abbreviation:txt(meta,'part-abbreviation'),
      instrumentNames:instruments.map(i=>i.name).filter(Boolean),instrumentAbbreviations:instruments.map(i=>i.abbreviation).filter(Boolean),
      instruments,notes,concertScore,program:first?.program||Number(txt(program,'midi-program'))||0,
      programExplicit:first?.programExplicit||!!one(program,'midi-program')};
  });
  return {parts,concertScore};
}

/** Retain previous suggestions for instruments outside the sixteen main profiles. */
export function inferInstrumentMetadata(part) {
  const result = inferred(part, true), p = result.profile;
  const legacyName = ['horn','trumpet','trombone','tuba'].includes(p.id) ? `铜管（${p.name}）` : p.name;
  return {name:result.reliable ? legacyName : '乐器未标明', source:result.source, input:p.input, profileId:result.reliable ? p.id : null, reliable:result.reliable};
}

/** MusicXML explicit transpose already made note.midi a sounding pitch. */
export function soundingMidi(note, instrument) {
  if (note.transposeExplicit) return note.midi;
  return (note.writtenMidi ?? note.midi) + (instrument?.transpose || 0);
}
