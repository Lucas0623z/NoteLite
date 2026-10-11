/** Written note identity, never an ambiguous pitch-only lookup. Indices are zero based. */
export type NoteKey = { partId: string; measureIndex: number; noteIndex: number };
export const noteKey = (key: NoteKey) => `${encodeURIComponent(key.partId)}:${key.measureIndex}:${key.noteIndex}`;
export type PlaybackNote = { key: NoteKey; start: number; end: number; midi: number; tieStart: boolean; tieStop: boolean; voiceKey: string; staff?: string };
export type PlaybackPosition = { keys: NoteKey[]; start: number };
export type ScoreTimeline = { notes: PlaybackNote[]; positions: PlaybackPosition[]; duration: number; initialTempo: number; warnings: string[] };

const elements = (node: Node, name?: string) => Array.from(node.childNodes).filter((n): n is Element => n.nodeType === 1 && (!name || (n as Element).localName === name));
const child = (node: Node, name: string) => elements(node, name)[0];
const text = (node: Node, name: string, fallback = "") => child(node, name)?.textContent?.trim() || fallback;
const number = (node: Node, name: string, fallback = 0) => Number(text(node, name, String(fallback)));
const units: Record<string, number> = { maxima: 32, long: 16, breve: 8, whole: 4, half: 2, quarter: 1, eighth: .5, "16th": .25, "32nd": .125, "64th": .0625, "128th": .03125 };

/** Port of the repository's MIDI repeat order, shared written IDs on every pass. */
function repeatOrder(parts: Element[], count: number) {
  const forward = new Set<number>(), backward = new Map<number, number>(), endings = new Map<number, Set<number>>();
  for (const part of parts) {
    let activeEnding = new Set<number>();
    elements(part, "measure").forEach((measure, i) => {
      let stop = false;
      for (const bar of elements(measure, "barline")) {
        const repeat = child(bar, "repeat");
        if (repeat?.getAttribute("direction") === "forward") forward.add(i);
        if (repeat?.getAttribute("direction") === "backward") {
          const times = Number(repeat.getAttribute("times") || 2);
          if (!Number.isInteger(times) || times < 1 || times > 100) throw new Error("反复次数无效，无法可靠试听。");
          backward.set(i, times);
        }
        const ending = child(bar, "ending");
        if (ending?.getAttribute("type") === "start") {
          const tokens = (ending.getAttribute("number") || "").split(",").map(v => Number(v.trim()));
          if (!tokens.length || tokens.some(v => !Number.isInteger(v) || v < 1)) throw new Error("房子编号暂不能可靠展开，请先校对。");
          activeEnding = new Set(tokens);
        } else if (ending) stop = true;
      }
      if (activeEnding.size) endings.set(i, new Set(activeEnding));
      if (stop) activeEnding = new Set();
    });
  }
  type Region = { start: number; end: number; times: number };
  const starts: number[] = [], regions = new Map<number, Region[]>(); let implicit = 0;
  for (let i = 0; i < count; i++) {
    if (forward.has(i)) starts.push(i);
    if (backward.has(i)) {
      const start = starts.pop() ?? implicit;
      const region = { start, end: i, times: backward.get(i)! };
      regions.set(start, [...(regions.get(start) || []), region]); implicit = i + 1;
    }
  }
  for (const list of regions.values()) list.sort((a, b) => b.end - a.end);
  const active: { region: Region; pass: number }[] = [], order: number[] = [];
  let index = 0, lastPass = 1, steps = 0;
  while (index < count) {
    if (++steps > Math.max(100000, count * 100) || order.length > 100000) throw new Error("反复展开过长，无法试听。");
    for (const region of regions.get(index) || []) if (!active.some(v => v.region === region)) active.push({ region, pass: 1 });
    const allowed = endings.get(index), pass = active[active.length - 1]?.pass ?? lastPass;
    if (!allowed?.size || allowed.has(pass)) order.push(index);
    let jump = false;
    while (active[active.length - 1]?.region.end === index) {
      const current = active[active.length - 1]!;
      if (current.pass < current.region.times) { current.pass++; index = current.region.start; jump = true; break; }
      lastPass = active.pop()!.pass;
    }
    if (!jump) index++;
  }
  return order;
}

/** Sounding notes and cursor slots use exactly the same tempo/time map. */
export function createScoreTimeline(xml: string, Parser: typeof DOMParser = DOMParser): ScoreTimeline {
  const document = new Parser().parseFromString(xml, "application/xml");
  const root = document.documentElement;
  if (root.localName !== "score-partwise" || document.getElementsByTagName("parsererror").length) throw new Error("请先载入有效 MusicXML。");
  if (["segno", "coda"].some(n => document.getElementsByTagName(n).length) || Array.from(document.getElementsByTagName("sound")).some(e => ["dacapo", "dalsegno", "tocoda"].some(a => e.hasAttribute(a)))) throw new Error("此谱含跳转记号，试听暂不能可靠跟随该路线。");
  type MeasureData = { length: number; notes: PlaybackNote[]; positions: PlaybackPosition[]; tempos: { at: number; bpm: number }[] };
  const parts = elements(root, "part"), warnings = new Set<string>(), data: MeasureData[][] = [];
  for (const part of parts) {
    let divisions = 1, nominal: number | undefined = 4, transpose = 0;
    const staffTranspose = new Map<string, number>(), measures: MeasureData[] = [];
    for (const [mi, measure] of elements(part, "measure").entries()) {
      let cursor = 0, previousOnset = 0, maxEnd = 0, ni = 0;
      const notes: PlaybackNote[] = [], positions: PlaybackPosition[] = [], tempos: { at: number; bpm: number }[] = [];
      const addTempo = (bpm: number, at: number) => { if (!(bpm > 0) || !Number.isFinite(bpm) || !Number.isFinite(at) || at < 0) throw new Error("谱面速度或速度位置无效。"); tempos.push({ at, bpm }); };
      for (const item of elements(measure)) {
        if (item.localName === "attributes") {
          divisions = number(item, "divisions", divisions);
          if (!(divisions > 0) || !Number.isFinite(divisions)) throw new Error("谱面 divisions 无效。");
          const time = child(item, "time");
          if (time && child(time, "senza-misura")) nominal = undefined;
          else if (time) {
            const beats = elements(time, "beats"), denominators = elements(time, "beat-type");
            nominal = beats.reduce((sum, b, i) => sum + (b.textContent || "").split("+").reduce((v, s) => v + Number(s), 0) * 4 / Number(denominators[i]?.textContent), 0);
            if (!(nominal > 0) || !Number.isFinite(nominal)) throw new Error("谱面拍号无效。");
          }
          for (const trans of elements(item, "transpose")) {
            const value = number(trans, "chromatic") + 12 * number(trans, "octave-change"), staff = trans.getAttribute("number");
            if (staff) staffTranspose.set(staff, value); else { transpose = value; staffTranspose.clear(); }
          }
        } else if (item.localName === "backup" || item.localName === "forward") {
          const duration = number(item, "duration") / divisions;
          if (!(duration > 0)) throw new Error("谱面声部时值无效。");
          cursor += (item.localName === "backup" ? -1 : 1) * duration;
          if (cursor < -1e-7) throw new Error("声部游标越过小节起点，请先校对。");
          maxEnd = Math.max(maxEnd, cursor);
        } else if (item.localName === "direction" || item.localName === "sound") {
          const directionOffset = child(item, "offset");
          const at = cursor + number(item, "offset") / divisions;
          const sound = item.localName === "sound" ? item : child(item, "sound");
          const soundTempo = Number(sound?.getAttribute("tempo"));
          const soundAt = cursor + (sound && child(sound, "offset") ? number(sound, "offset") / divisions : directionOffset?.getAttribute("sound") === "yes" ? number(item, "offset") / divisions : 0);
          if (soundTempo > 0) addTempo(soundTempo, soundAt);
          // A future sound/offset must not suppress an earlier printed tempo.
          // At the same position, explicit sound is the playback authority.
          if (!(soundTempo > 0 && Math.abs(soundAt - at) < 1e-7)) for (const type of elements(item, "direction-type")) {
            const metronome = child(type, "metronome");
            if (metronome && child(metronome, "per-minute")) addTempo(number(metronome, "per-minute") * (units[text(metronome, "beat-unit")] || 0) * (2 - 2 ** -elements(metronome, "beat-unit-dot").length), at);
          }
        } else if (item.localName === "note") {
          const key = { partId: part.getAttribute("id") || "", measureIndex: mi, noteIndex: ni++ };
          if (child(item, "grace")) { warnings.add("装饰音暂不发声，指针跟随主音。"); continue; }
          const duration = number(item, "duration") / divisions;
          if (!(duration > 0) || !Number.isFinite(duration)) throw new Error(`第 ${measure.getAttribute("number") || mi + 1} 小节音符时值无效。`);
          const chord = !!child(item, "chord"), onset = chord ? previousOnset : cursor;
          if (!chord) { previousOnset = onset; cursor += duration; }
          maxEnd = Math.max(maxEnd, onset + duration, cursor);
          positions.push({ keys: [key], start: onset });
          const pitch = child(item, "pitch"), staff = text(item, "staff", "1"), voice = text(item, "voice", "1");
          if (pitch) {
            const semitone = ({ C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 } as Record<string, number>)[text(pitch, "step")];
            const midi = 12 * (number(pitch, "octave") + 1) + semitone + number(pitch, "alter") + (staffTranspose.get(staff) ?? transpose);
            if (!Number.isInteger(midi) || midi < 0 || midi > 127) throw new Error("试听暂不支持此谱的微分音或 MIDI 音高。");
            const ties = elements(item, "tie").map(t => t.getAttribute("type"));
            notes.push({ key, start: onset, end: onset + duration, midi, tieStart: ties.includes("start"), tieStop: ties.includes("stop"), voiceKey: JSON.stringify([key.partId, voice, midi]), staff });
          } else if (child(item, "unpitched")) warnings.add("无固定音高音符仅显示指针，试听不发声。");
        }
      }
      const pickup = nominal !== undefined && (mi === 0 || measure.getAttribute("implicit") === "yes") && maxEnd > 0 && maxEnd < nominal;
      if (nominal !== undefined && !pickup && maxEnd > nominal + 1e-7) throw new Error(`第 ${measure.getAttribute("number") || mi + 1} 小节超拍，请先校对后试听。`);
      const length = pickup || nominal === undefined ? maxEnd : nominal;
      if (tempos.some(t => t.at > length + 1e-7)) throw new Error("速度位置超出小节，无法可靠试听。");
      measures.push({ length, notes, positions, tempos });
    }
    data.push(measures);
  }
  const count = Math.max(0, ...data.map(p => p.length)), order = repeatOrder(parts, count);
  // Tempo is global even when written only on a non-leading part. Repeats
  // restore the tempo at the written entry, not the tempo left by the last pass.
  const writtenTempos: { at: number; bpm: number }[][] = [], entryTempos: number[] = [];
  let inheritedTempo = 120;
  for (let mi = 0; mi < count; mi++) {
    entryTempos.push(inheritedTempo);
    const merged = new Map<number, number>();
    for (const part of data) for (const event of part[mi]?.tempos || []) {
      const previous = merged.get(event.at);
      if (previous !== undefined && Math.abs(previous - event.bpm) > 1e-7) throw new Error(`第 ${mi + 1} 小节声部速度不一致，请先校对。`);
      merged.set(event.at, event.bpm);
    }
    const events = [...merged].sort((a, b) => a[0] - b[0]).map(([at, bpm]) => ({ at, bpm }));
    writtenTempos.push(events);
    if (events.length) inheritedTempo = events[events.length - 1].bpm;
  }
  const quarterNotes: PlaybackNote[] = [], quarterPositions: PlaybackPosition[] = [], tempoEvents: { at: number; bpm: number }[] = [];
  let offset = 0, playedTempo = 120, previousMeasure = -1;
  const visitedEntryTempo = new Map<number, number>();
  for (const mi of order) {
    const length = Math.max(0, ...data.map(p => p[mi]?.length || 0));
    // Backward repeats restore their actual first-entry tempo. Forward skips
    // keep the tempo already heard, so a skipped first ending cannot leak it.
    if (mi <= previousMeasure) playedTempo = visitedEntryTempo.get(mi) ?? entryTempos[mi];
    if (!visitedEntryTempo.has(mi)) visitedEntryTempo.set(mi, playedTempo);
    tempoEvents.push({ at: offset, bpm: playedTempo });
    tempoEvents.push(...writtenTempos[mi].map(t => ({ at: offset + t.at, bpm: t.bpm })));
    if (writtenTempos[mi].length) playedTempo = writtenTempos[mi][writtenTempos[mi].length - 1].bpm;
    quarterPositions.push({ keys: [], start: offset });
    for (const part of data) {
      const measure = part[mi]; if (!measure) continue;
      quarterNotes.push(...measure.notes.map(n => ({ ...n, start: offset + n.start, end: offset + n.end })));
      quarterPositions.push(...measure.positions.map(p => ({ ...p, start: offset + p.start })));
    }
    offset += length;
    previousMeasure = mi;
  }
  tempoEvents.sort((a, b) => a.at - b.at);
  const tempos = new Map<number, number>([[0, 120]]);
  for (const event of tempoEvents) tempos.set(event.at, event.bpm);
  const orderedTempos = [...tempos].sort((a, b) => a[0] - b[0]);
  const seconds = (quarter: number) => { let result = 0, start = 0, bpm = 120; for (const [at, next] of orderedTempos) { if (at > quarter) break; result += Math.max(0, at - start) * 60 / bpm; start = at; bpm = next; } return result + Math.max(0, quarter - start) * 60 / bpm; };
  const notes: PlaybackNote[] = [], ties = new Map<string, PlaybackNote[]>();
  for (const note of quarterNotes.sort((a, b) => a.start - b.start)) {
    const open = (ties.get(note.voiceKey) || []).filter(n => n.end >= note.start - 1e-7);
    const candidates = open.filter(n => Math.abs(n.end - note.start) < 1e-7);
    const sameStaff = candidates.filter(n => n.staff === note.staff);
    const matching = sameStaff.length ? sameStaff : candidates;
    if (note.tieStop && matching.length > 1) throw new Error("同声部的同音延音线有歧义，请先校对后试听。");
    const previous = note.tieStop ? matching[0] : undefined;
    if (previous) { previous.end = note.end; if (!note.tieStart) open.splice(open.indexOf(previous), 1); }
    else { const clone = { ...note }; notes.push(clone); if (note.tieStart) open.push(clone); }
    ties.set(note.voiceKey, open);
  }
  const positions: PlaybackPosition[] = [];
  for (const position of quarterPositions.sort((a, b) => a.start - b.start)) {
    const previous = positions[positions.length - 1], start = seconds(position.start);
    if (previous && Math.abs(previous.start - start) < 1e-7) previous.keys.push(...position.keys); else positions.push({ keys: [...position.keys], start });
  }
  return { notes: notes.map(n => ({ ...n, start: seconds(n.start), end: seconds(n.end) })), positions, duration: seconds(offset), initialTempo: tempos.get(0) || 120, warnings: [...warnings] };
}

export function positionAt(timeline: ScoreTimeline, seconds: number): NoteKey[] {
  if (seconds < 0 || seconds >= timeline.duration) return [];
  let low = 0, high = timeline.positions.length;
  while (low < high) { const mid = (low + high) >>> 1; if (timeline.positions[mid].start <= seconds) low = mid + 1; else high = mid; }
  return low ? timeline.positions[low - 1].keys : [];
}

/** Receives actual recognizer positions later; a wall clock never feeds this path. */
export function createPerformancePositionReceiver(scoreIdentity: string, apply: (keys: NoteKey[]) => void, knownNotes?: ReadonlySet<string>) {
  let sequence = -1, active = true;
  return {
    accept(event: unknown) {
      if (!active || !event || typeof event !== "object") return false;
      const value = event as Record<string, unknown>;
      if (value.type !== "performancePosition" || value.scoreIdentity !== scoreIdentity || !Number.isInteger(value.sequence) || (value.sequence as number) <= sequence || !Array.isArray(value.notes) || value.notes.length > 256) return false;
      if (!value.notes.every(n => n && typeof n === "object" && typeof n.partId === "string" && Number.isInteger(n.measureIndex) && n.measureIndex >= 0 && Number.isInteger(n.noteIndex) && n.noteIndex >= 0)) return false;
      if (knownNotes && !(value.notes as NoteKey[]).every(n => knownNotes.has(noteKey(n)))) return false;
      sequence = value.sequence as number; apply(value.notes as NoteKey[]); return true;
    },
    dispose() { active = false; apply([]); },
  };
}
