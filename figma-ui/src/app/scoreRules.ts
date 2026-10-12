/** MusicXML rhythm checks. Intended duration, not printed note type, moves time.
 * MusicXML 4.0: note/chord, backup/forward, divisions, time and implicit measure.
 * https://www.w3.org/2021/06/musicxml40/tutorial/midi-compatible-part/
 */
export type RuleSeverity = "error" | "warning";
export type ScoreRuleIssue = {
  code: string; severity: RuleSeverity; message: string;
  partId?: string; measureIndex?: number; measure?: string; noteIndex?: number;
  voice?: string; staff?: string; actual?: number; expected?: number;
  /** A positive defect size lets a correction improve an existing problem. */
  impact?: number; value?: string;
};
export type VoiceSpan = { voice: string; staff: string; start: number; end: number; covered: number };
export type MeasureSpan = { partId: string; measureIndex: number; measure: string; implicit: boolean; voices: VoiceSpan[]; expectedByStaff: Record<string, number | null>; actual: number };
export type ScoreRuleReport = { structuralValid: boolean; issues: ScoreRuleIssue[]; errors: ScoreRuleIssue[]; warnings: ScoreRuleIssue[]; measureSpans: MeasureSpan[] };
export type ScoreRuleComparison = { before: ScoreRuleReport; after: ScoreRuleReport; introduced: ScoreRuleIssue[]; preexisting: ScoreRuleIssue[]; resolved: ScoreRuleIssue[]; canSave: boolean; requiresReview: boolean };

export function directElements(parent: Node, name?: string): Element[] {
  return Array.from(parent.childNodes).filter((node): node is Element => node.nodeType === 1 && (!name || (node as Element).localName === name));
}
export function firstElement(parent: Node, name: string): Element | undefined { return directElements(parent, name)[0]; }
export function textOf(parent: Node, name: string): string { return firstElement(parent, name)?.textContent?.trim() || ""; }
export function parseScoreXML(xml: string): Document {
  if (!xml.trim()) throw new Error("曲谱内容为空。");
  // Keep ordinary MusicXML PUBLIC doctypes, but never expand custom entities.
  if (/<!ENTITY\s/i.test(xml)) throw new Error("曲谱不能包含自定义 XML 实体。");
  let document: Document;
  try { document = new DOMParser().parseFromString(xml, "application/xml"); }
  catch { throw new Error("曲谱不是有效的 XML，无法检查或保存。"); }
  if (!document.documentElement || Array.from(document.getElementsByTagName("*")).some((node) => node.localName === "parsererror")) throw new Error("曲谱不是有效的 XML，无法检查或保存。");
  if (document.documentElement.localName !== "score-partwise") throw new Error("请使用按声部排列的 MusicXML（score-partwise）。");
  return document;
}

export const QUARTER_LENGTH: Readonly<Record<string, number>> = {
  maxima: 32, long: 16, breve: 8, whole: 4, half: 2, quarter: 1,
  eighth: 0.5, "16th": 0.25, "32nd": 0.125, "64th": 0.0625,
  "128th": 0.03125, "256th": 0.015625, "512th": 0.0078125, "1024th": 0.00390625,
};
export function dottedQuarterLength(type: string, dots: number): number | null {
  const length = QUARTER_LENGTH[type];
  return length === undefined || !Number.isInteger(dots) || dots < 0 ? null : length * (2 - 2 ** -dots);
}
const EPSILON = 1e-7;
const positive = (value: string): number | null => { const number = Number(value); return value.trim() && Number.isFinite(number) && number > 0 ? number : null; };
const near = (a: number, b: number) => Math.abs(a - b) <= EPSILON * Math.max(1, Math.abs(a), Math.abs(b));
const show = (value: number) => Number(value.toFixed(6));

export function meterQuarterLength(time: Element): number | null {
  if (firstElement(time, "senza-misura")) return null;
  const children = directElements(time).filter((node) => node.localName === "beats" || node.localName === "beat-type");
  if (!children.length || children.length % 2) return NaN;
  let total = 0;
  for (let index = 0; index < children.length; index += 2) {
    if (children[index].localName !== "beats" || children[index + 1].localName !== "beat-type") return NaN;
    const beats = children[index].textContent?.trim() || "";
    const denominator = positive(children[index + 1].textContent || "");
    if (!/^\d+(?:\s*\+\s*\d+)*$/.test(beats) || !denominator || !Number.isInteger(denominator)) return NaN;
    const numerator = beats.split("+").map((value) => positive(value));
    if (numerator.some((value) => value === null)) return NaN;
    total += numerator.reduce<number>((sum, value) => sum + value!, 0) * 4 / denominator;
  }
  return total;
}

export type TempoReference = { partId: string; measureIndex: number; position: number; quarterTempo: number | null; kind: "metronome" | "sound"; element: Element; unit: number | null };
/** Written positions shared by all parts. Keep later/offset changes separate. */
export function collectTempoReferences(document: Document): TempoReference[] {
  const result: TempoReference[] = [];
  for (const part of directElements(document.documentElement, "part")) {
    const partId = part.getAttribute("id") || ""; let divisions: number | null = null;
    directElements(part, "measure").forEach((measure, measureIndex) => {
      let cursor = 0;
      for (const element of directElements(measure)) {
        if (element.localName === "attributes" && firstElement(element, "divisions")) divisions = positive(textOf(element, "divisions"));
        else if (element.localName === "note" && !firstElement(element, "grace") && !firstElement(element, "chord") && divisions) cursor += (positive(textOf(element, "duration")) || 0) / divisions;
        else if (["backup", "forward"].includes(element.localName) && divisions) cursor += (element.localName === "backup" ? -1 : 1) * (positive(textOf(element, "duration")) || 0) / divisions;
        else if (element.localName === "direction" || element.localName === "sound") {
          const directionOffset = element.localName === "direction" ? firstElement(element, "offset") : undefined;
          const visualOffset = Number(directionOffset?.textContent || 0) / (divisions || 1);
          if (element.localName === "direction") for (const type of directElements(element, "direction-type")) for (const metronome of directElements(type, "metronome")) {
            const unit = dottedQuarterLength(textOf(metronome, "beat-unit"), directElements(metronome, "beat-unit-dot").length);
            const perMinute = positive(textOf(metronome, "per-minute"));
            const simple = directElements(metronome, "beat-unit").length === 1 && !firstElement(metronome, "beat-unit-tied") && !firstElement(metronome, "metronome-note");
            result.push({ partId, measureIndex, position: cursor + visualOffset, quarterTempo: simple && unit && perMinute ? unit * perMinute : null, kind: "metronome", element: metronome, unit });
          }
          for (const sound of element.localName === "sound" ? [element] : directElements(element, "sound")) if (sound.hasAttribute("tempo")) {
            const explicitOffset = firstElement(sound, "offset");
            const offset = explicitOffset ? Number(explicitOffset.textContent || 0) / (divisions || 1) : directionOffset?.getAttribute("sound") === "yes" ? visualOffset : 0;
            result.push({ partId, measureIndex, position: cursor + offset, quarterTempo: positive(sound.getAttribute("tempo") || ""), kind: "sound", element: sound, unit: null });
          }
        }
      }
    });
  }
  return result;
}

type Interval = { start: number; end: number };
type MeterState = Map<string, number | null>;
function mergeLength(intervals: Interval[]): number {
  const sorted = [...intervals].sort((a, b) => a.start - b.start);
  let covered = 0; let start = 0; let end = 0; let has = false;
  for (const interval of sorted) {
    if (!has) { start = interval.start; end = interval.end; has = true; }
    else if (interval.start <= end + EPSILON) end = Math.max(end, interval.end);
    else { covered += end - start; start = interval.start; end = interval.end; }
  }
  return covered + (has ? end - start : 0);
}
function sameLocation(a: ScoreRuleIssue, b: ScoreRuleIssue): boolean {
  return a.code === b.code && a.severity === b.severity && a.partId === b.partId && a.measureIndex === b.measureIndex && a.noteIndex === b.noteIndex && a.voice === b.voice && a.staff === b.staff && (!["tempo-conflict", "tempo-mismatch"].includes(a.code) || a.value === b.value);
}
function noWorse(a: ScoreRuleIssue, previous: ScoreRuleIssue): boolean {
  if (a.impact !== undefined && previous.impact !== undefined) return a.impact <= previous.impact + EPSILON;
  return a.value === previous.value && a.actual === previous.actual && a.expected === previous.expected;
}

/** Note indexes shift after deletion. Align their rhythmic identities so an old
 * OMR warning on the next note is not misreported as a newly introduced defect. */
function shiftedNoteLocations(beforeXML: string, afterXML: string): Map<string, Map<number, number>> {
  const result = new Map<string, Map<number, number>>();
  let before: Document, after: Document;
  try { before = parseScoreXML(beforeXML); after = parseScoreXML(afterXML); } catch { return result; }
  const fingerprint = (note: Element) => JSON.stringify({
    kinds: directElements(note).filter((child) => ["pitch", "rest", "unpitched"].includes(child.localName)).map((child) => [child.localName, child.getAttribute("measure")]),
    duration: directElements(note, "duration").map((child) => child.textContent?.trim()), type: textOf(note, "type"), dots: directElements(note, "dot").length,
    voice: textOf(note, "voice") || "1", staff: textOf(note, "staff") || "1", chord: !!firstElement(note, "chord"), grace: !!firstElement(note, "grace"),
    tuplet: firstElement(note, "time-modification")?.textContent?.replace(/\s/g, "") || "",
  });
  const oldParts = directElements(before.documentElement, "part");
  for (const newPart of directElements(after.documentElement, "part")) {
    const partId = newPart.getAttribute("id") || "";
    const oldPart = oldParts.find((part) => part.getAttribute("id") === partId);
    if (!oldPart) continue;
    const oldMeasures = directElements(oldPart, "measure");
    directElements(newPart, "measure").forEach((measure, measureIndex) => {
      if (!oldMeasures[measureIndex]) return;
      const oldNotes = directElements(oldMeasures[measureIndex], "note").map(fingerprint);
      const newNotes = directElements(measure, "note").map(fingerprint);
      if (oldNotes.length === newNotes.length) return;
      const mapping = new Map<number, number>();
      result.set(`${partId}\u0000${measureIndex}`, mapping);
      if (oldNotes.length * newNotes.length > 300000) {
        // Bound comparison memory for unusually dense imported measures.
        let previous = 0;
        newNotes.forEach((note, index) => { const match = oldNotes.indexOf(note, previous); if (match >= 0) { mapping.set(index, match); previous = match + 1; } });
        return;
      }
      const rows = Array.from({ length: oldNotes.length + 1 }, () => new Uint32Array(newNotes.length + 1));
      for (let oldIndex = oldNotes.length - 1; oldIndex >= 0; oldIndex--) for (let newIndex = newNotes.length - 1; newIndex >= 0; newIndex--) rows[oldIndex][newIndex] = oldNotes[oldIndex] === newNotes[newIndex] ? rows[oldIndex + 1][newIndex + 1] + 1 : Math.max(rows[oldIndex + 1][newIndex], rows[oldIndex][newIndex + 1]);
      let oldIndex = 0, newIndex = 0;
      while (oldIndex < oldNotes.length && newIndex < newNotes.length) {
        if (oldNotes[oldIndex] === newNotes[newIndex]) { mapping.set(newIndex++, oldIndex++); }
        else if (rows[oldIndex + 1][newIndex] >= rows[oldIndex][newIndex + 1]) oldIndex++;
        else newIndex++;
      }
    });
  }
  return result;
}

export function checkScoreRules(xml: string): ScoreRuleReport {
  const issues: ScoreRuleIssue[] = []; const measureSpans: MeasureSpan[] = [];
  let structuralValid = true;
  const finish = (): ScoreRuleReport => ({ structuralValid, issues, errors: issues.filter((issue) => issue.severity === "error"), warnings: issues.filter((issue) => issue.severity === "warning"), measureSpans });
  let document: Document;
  try { document = parseScoreXML(xml); }
  catch (error) { structuralValid = false; issues.push({ code: "xml-structure", severity: "error", message: error instanceof Error ? error.message : "曲谱结构无效。" }); return finish(); }
  const parts = directElements(document.documentElement, "part");
  if (!parts.length) { structuralValid = false; issues.push({ code: "missing-parts", severity: "error", message: "曲谱没有声部，无法保存。" }); }
  const ids = new Set<string>();
  for (const part of parts) {
    const partId = part.getAttribute("id") || "";
    if (!partId || ids.has(partId)) { structuralValid = false; issues.push({ code: "part-id", severity: "error", message: "声部标识缺失或重复。", partId }); }
    ids.add(partId);
    let inheritedDivisions: number | null = null;
    const meters: MeterState = new Map();
    const measures = directElements(part, "measure");
    if (!measures.length) issues.push({ code: "empty-part", severity: "warning", message: "声部没有小节。", partId });
    measures.forEach((measure, measureIndex) => {
      const number = measure.getAttribute("number") || String(measureIndex + 1);
      const location = { partId, measureIndex, measure: number };
      const add = (issue: Omit<ScoreRuleIssue, "partId" | "measureIndex" | "measure">) => issues.push({ ...location, ...issue });
      const label = `声部 ${partId} · 第 ${number} 小节`;
      let cursor = 0; let maxEnd = 0; let noteIndex = 0; let rhythmicInvalid = false; let changedMeterInside = false;
      let previousNote: { start: number; length: number; voice: string; grace: boolean } | null = null;
      const divisionEvents: { position: number; value: number | null }[] = [{ position: 0, value: inheritedDivisions }];
      const divisionsAt = (position: number) => {
        const candidates = [...divisionEvents].sort((a, b) => a.position - b.position).filter((event) => event.position <= position + EPSILON);
        return candidates[candidates.length - 1]?.value ?? null;
      };
      const intervals = new Map<string, { voice: string; staff: string; spans: Interval[] }>();
      const staffEnds = new Map<string, number>();
      const staffStarts = new Map<string, number>();
      const tempoEvents: { position: number; quarterTempo: number; shown: boolean; staff: string }[] = [];
      const record = (voice: string, staff: string, start: number, end: number, isChord = false, index?: number) => {
        maxEnd = Math.max(maxEnd, end); staffEnds.set(staff, Math.max(staffEnds.get(staff) || 0, end)); staffStarts.set(staff, Math.min(staffStarts.get(staff) ?? start, start));
        const key = `${voice}\u0000${staff}`;
        const state = intervals.get(key) || { voice, staff, spans: [] };
        if (!isChord && state.spans.some((span) => Math.min(span.end, end) > Math.max(span.start, start) + EPSILON)) add({ code: "voice-overlap", severity: "error", noteIndex: index, voice, staff, message: `${label} 的声部 ${voice} 有重叠时值；请检查 backup 或音符时值。`, impact: state.spans.reduce((sum, span) => sum + Math.max(0, Math.min(span.end, end) - Math.max(span.start, start)), 0) });
        state.spans.push({ start, end }); intervals.set(key, state);
      };
      const durationLength = (element: Element, context: string, index?: number): number | null => {
        const raw = textOf(element, "duration"); const duration = positive(raw); const divisions = divisionsAt(cursor);
        if (duration === null) { rhythmicInvalid = true; add({ code: "invalid-duration", severity: "error", noteIndex: index, value: `${context}:${raw}`, message: `${label}${index === undefined ? "" : ` 音符 ${index + 1}`} 的${context}必须为正数。` }); return null; }
        if (divisions === null) { rhythmicInvalid = true; add({ code: "missing-divisions", severity: "error", noteIndex: index, message: `${label} 未提供有效 divisions，不能计算音符时值。` }); return null; }
        return duration / divisions;
      };
      for (const element of directElements(measure)) {
        if (element.localName === "attributes") {
          const rawDivisions = textOf(element, "divisions");
          if (firstElement(element, "divisions")) {
            const value = positive(rawDivisions);
            if (value === null) { rhythmicInvalid = true; add({ code: "invalid-divisions", severity: "error", value: rawDivisions, message: `${label} 的 divisions 必须为正数。` }); }
            const existing = divisionEvents.find((event) => near(event.position, cursor));
            if (existing) existing.value = value; else divisionEvents.push({ position: cursor, value });
          }
          for (const time of directElements(element, "time")) {
            const length = meterQuarterLength(time); const staff = time.getAttribute("number") || "*";
            if (Number.isNaN(length)) { add({ code: "invalid-meter", severity: "error", staff, value: time.textContent || "", message: `${label} 的拍号无效，请使用正整数拍数与拍单位。` }); rhythmicInvalid = true; }
            else {
              if (cursor > EPSILON) { changedMeterInside = true; add({ code: "mid-measure-meter", severity: "warning", staff, message: `${label} 在小节中途改变拍号，整小节拍数需要人工复核。` }); }
              if (staff === "*") meters.clear();
              meters.set(staff, length);
            }
          }
          previousNote = null;
        } else if (element.localName === "backup" || element.localName === "forward") {
          const length = durationLength(element, element.localName === "backup" ? "回退时值" : "前进时值");
          if (length !== null) {
            const destination = element.localName === "backup" ? cursor - length : cursor + length;
            if (destination < -EPSILON) { rhythmicInvalid = true; add({ code: "backup-before-measure", severity: "error", actual: destination, expected: 0, impact: -destination, message: `${label} 的 backup 退到了小节起点之前。` }); }
            const low = Math.min(cursor, destination), high = Math.max(cursor, destination);
            if (divisionEvents.some((event) => event.position > low + EPSILON && event.position < high - EPSILON)) add({ code: "movement-across-divisions", severity: "error", impact: high - low, message: `${label} 的 ${element.localName} 跨越了 divisions 变化，请拆分时值移动。` });
            if (element.localName === "forward") {
              const voice = textOf(element, "voice"); const staff = textOf(element, "staff") || "1";
              // Unqualified forward coordinates the part; it is not a new voice.
              if (voice) record(voice, staff, cursor, destination);
              else { maxEnd = Math.max(maxEnd, destination); for (const existing of staffEnds.keys()) staffEnds.set(existing, Math.max(staffEnds.get(existing)!, destination)); }
            }
            cursor = Math.max(0, destination);
          }
          previousNote = null;
        } else if (element.localName === "note") {
          const index = noteIndex++; const voice = textOf(element, "voice") || "1"; const staff = textOf(element, "staff") || "1";
          const grace = !!firstElement(element, "grace"); const chord = !!firstElement(element, "chord");
          const pitchKinds = directElements(element).filter((child) => ["pitch", "rest", "unpitched"].includes(child.localName)).map((child) => child.localName);
          if (pitchKinds.length !== 1) add({ code: "note-kind", severity: "error", noteIndex: index, voice, staff, value: pitchKinds.join(","), message: `${label} 音符 ${index + 1} 必须且只能是音符、休止符或无定音高音符。` });
          if (grace && firstElement(element, "duration")) add({ code: "grace-duration", severity: "error", noteIndex: index, voice, staff, value: textOf(element, "duration"), message: `${label} 音符 ${index + 1} 为倚音，不应含 duration。` });
          if (!grace && directElements(element, "duration").length > 1) add({ code: "duplicate-duration", severity: "error", noteIndex: index, voice, staff, message: `${label} 音符 ${index + 1} 有多个 duration，无法确定时值。` });
          if (chord && firstElement(element, "rest")) add({ code: "chord-rest", severity: "error", noteIndex: index, voice, staff, message: `${label} 音符 ${index + 1} 的休止符不能作为和弦音。` });
          const length = grace ? 0 : durationLength(element, "音符时值", index);
          if (chord && (!previousNote || previousNote.voice !== voice || previousNote.grace !== grace)) add({ code: "orphan-chord", severity: "error", noteIndex: index, voice, staff, message: `${label} 音符 ${index + 1} 的和弦没有同声部的前置音符。` });
          if (length !== null && chord && previousNote && length > previousNote.length + EPSILON) add({ code: "chord-too-long", severity: "error", noteIndex: index, voice, staff, actual: length, expected: previousNote.length, impact: length - previousNote.length, message: `${label} 音符 ${index + 1} 的和弦音时值超过首音。` });
          const type = textOf(element, "type"); const dots = directElements(element, "dot").length;
          const printed = type ? dottedQuarterLength(type, dots) : null;
          if (type && printed === null) add({ code: "invalid-note-type", severity: "error", noteIndex: index, voice, staff, value: type, message: `${label} 音符 ${index + 1} 的记谱时值无效。` });
          let ratio = 1; const modification = firstElement(element, "time-modification");
          if (modification) {
            const actual = positive(textOf(modification, "actual-notes")); const normal = positive(textOf(modification, "normal-notes"));
            if (actual === null || normal === null || !Number.isInteger(actual) || !Number.isInteger(normal)) add({ code: "invalid-tuplet", severity: "error", noteIndex: index, voice, staff, value: modification.textContent || "", message: `${label} 音符 ${index + 1} 的连音比例必须为正整数。` });
            else ratio = normal / actual;
          }
          // Intended and notated durations may deliberately differ in MusicXML.
          // A full-measure rest is not a literal whole-note value in every meter.
          if (!grace && length !== null && printed !== null && firstElement(element, "rest")?.getAttribute("measure") !== "yes" && !near(length, printed * ratio)) add({ code: "notated-duration-mismatch", severity: "warning", noteIndex: index, voice, staff, actual: length, expected: printed * ratio, impact: Math.abs(length - printed * ratio), message: `${label} 音符 ${index + 1} 的实际时值 ${show(length)} 拍与记谱时值 ${show(printed * ratio)} 拍不同，请复核。` });
          const start: number = chord && previousNote ? previousNote.start : cursor;
          if (length !== null && !grace) { record(voice, staff, start, start + length, chord, index); if (!chord) cursor += length; }
          if (!chord) previousNote = { start, length: length ?? 0, voice, grace };
        } else if (element.localName === "direction" || element.localName === "sound") {
          const offset = element.localName === "direction" ? Number(textOf(element, "offset") || 0) / (divisionsAt(cursor) || 1) : 0;
          const position = cursor + offset; const staff = textOf(element, "staff") || "*";
          if (element.localName === "direction") for (const directionType of directElements(element, "direction-type")) for (const metronome of directElements(directionType, "metronome")) {
            const unit = textOf(metronome, "beat-unit"); const dots = directElements(metronome, "beat-unit-dot").length;
            const length = dottedQuarterLength(unit, dots); const perMinute = positive(textOf(metronome, "per-minute"));
            if (directElements(metronome, "beat-unit").length === 1 && perMinute && length && !firstElement(metronome, "beat-unit-tied")) tempoEvents.push({ position, quarterTempo: perMinute * length, shown: true, staff });
          }
          const sounds = element.localName === "sound" ? [element] : directElements(element, "sound");
          for (const sound of sounds) if (sound.hasAttribute("tempo")) {
            const rawTempo = sound.getAttribute("tempo") || "";
            const tempo = positive(rawTempo);
            if (rawTempo.trim() && Number(rawTempo) === 0) add({ code: "unspecified-tempo", severity: "warning", message: `${label} 的播放速度为 0，导出 MIDI 时需要确定速度。` });
            else if (tempo === null) add({ code: "invalid-tempo", severity: "error", value: rawTempo, message: `${label} 的播放速度不能为负数或无效数字。` });
            else {
              const soundOffset = firstElement(sound, "offset");
              const directionOffset = firstElement(element, "offset");
              const inheritedOffset = element.localName === "direction" && directionOffset?.getAttribute("sound") === "yes" ? offset : 0;
              const soundPosition = cursor + (soundOffset ? Number(soundOffset.textContent || 0) / (divisionsAt(cursor) || 1) : inheritedOffset);
              tempoEvents.push({ position: soundPosition, quarterTempo: tempo, shown: false, staff });
            }
          }
          previousNote = null;
        } else if (!["print", "barline", "bookmark", "link"].includes(element.localName)) previousNote = null;
      }
      inheritedDivisions = divisionsAt(maxEnd);
      const implicit = measure.getAttribute("implicit") === "yes";
      const expectedByStaff: Record<string, number | null> = {};
      for (const [staff, end] of staffEnds) {
        const expected = meters.get(staff) ?? (meters.has(staff) ? null : meters.get("*")) ?? null;
        expectedByStaff[staff] = expected;
        if (expected === null && !meters.has(staff) && !meters.has("*")) add({ code: "missing-meter", severity: "warning", staff, message: `${label} 未提供拍号，暂不能核对小节拍数。` });
        if (expected !== null && !changedMeterInside) {
          if (end > expected + EPSILON) add({ code: "measure-overfull", severity: "error", staff, actual: end, expected, impact: end - expected, message: `${label} 第 ${staff} 行有 ${show(end)} 拍，超过拍号要求的 ${show(expected)} 拍。` });
          else if (!rhythmicInvalid && !implicit && end < expected - EPSILON) add({ code: "measure-underfull", severity: "warning", staff, actual: end, expected, impact: expected - end, message: `${label} 第 ${staff} 行只覆盖 ${show(end)} 拍（应为 ${show(expected)} 拍）；可能为弱起、片段或缺少休止符，请复核。` });
        }
      }
      const voices: VoiceSpan[] = [...intervals.values()].map(({ voice, staff, spans }) => ({ voice, staff, start: Math.min(...spans.map((span) => span.start)), end: Math.max(...spans.map((span) => span.end)), covered: mergeLength(spans) }));
      for (const span of voices) {
        const expected = expectedByStaff[span.staff];
        if (expected !== null && expected !== undefined && span.end > expected + EPSILON && !changedMeterInside) add({ code: "voice-overfull", severity: "error", voice: span.voice, staff: span.staff, actual: span.end, expected, impact: span.end - expected, message: `${label} 声部 ${span.voice} 超过小节末尾 ${show(span.end - expected)} 拍。` });
      }
      if (!noteIndex && !maxEnd) add({ code: "empty-measure", severity: "warning", message: `${label} 为空；不会自动填入休止符。` });
      for (const shown of tempoEvents.filter((event) => event.shown)) for (const sound of tempoEvents.filter((event) => !event.shown && near(event.position, shown.position))) {
        if (!near(shown.quarterTempo, sound.quarterTempo)) add({ code: "tempo-mismatch", severity: "error", staff: shown.staff, value: String(show(shown.position)), actual: sound.quarterTempo, expected: shown.quarterTempo, impact: Math.abs(sound.quarterTempo - shown.quarterTempo), message: `${label} 的纸面速度与播放速度不同；纸面折算为四分音符 ${show(shown.quarterTempo)}，播放为 ${show(sound.quarterTempo)}。` });
      }
      measureSpans.push({ ...location, implicit, voices, expectedByStaff, actual: maxEnd });
    });
  }
  const tempoGroups = new Map<string, TempoReference[]>();
  for (const reference of collectTempoReferences(document)) if (reference.quarterTempo !== null) {
    const key = `${reference.measureIndex}:${reference.position.toFixed(7)}`;
    tempoGroups.set(key, [...(tempoGroups.get(key) || []), reference]);
  }
  for (const references of tempoGroups.values()) {
    if (new Set(references.map((reference) => reference.partId)).size < 2) continue;
    const minimum = Math.min(...references.map((reference) => reference.quarterTempo!));
    const maximum = Math.max(...references.map((reference) => reference.quarterTempo!));
    if (!near(minimum, maximum)) issues.push({ code: "tempo-conflict", severity: "error", measureIndex: references[0].measureIndex, value: String(show(references[0].position)), actual: minimum, expected: maximum, impact: maximum - minimum, message: `第 ${references[0].measureIndex + 1} 小节同一位置的声部速度不一致（四分音符 ${show(minimum)} 至 ${show(maximum)}）；请统一后保存。` });
  }
  return finish();
}

/** Existing OMR defects remain visible; an unrelated correction does not invent
 * them anew. Worsening an existing defect is a newly introduced problem. */
export function compareScoreRules(beforeXML: string, afterXML: string): ScoreRuleComparison {
  const before = checkScoreRules(beforeXML), after = checkScoreRules(afterXML);
  const shifts = shiftedNoteLocations(beforeXML, afterXML);
  const matches = (issue: ScoreRuleIssue, old: ScoreRuleIssue) => {
    if (issue.noteIndex === undefined) return sameLocation(issue, old);
    const mapping = shifts.get(`${issue.partId}\u0000${issue.measureIndex}`);
    if (!mapping) return sameLocation(issue, old);
    const index = mapping.get(issue.noteIndex);
    return index !== undefined && sameLocation({ ...issue, noteIndex: index }, old);
  };
  const preexisting = after.issues.filter((issue) => before.issues.some((old) => matches(issue, old) && noWorse(issue, old)));
  const introduced = after.issues.filter((issue) => !preexisting.includes(issue));
  const resolved = before.issues.filter((old) => !after.issues.some((issue) => matches(issue, old)));
  return { before, after, introduced, preexisting, resolved, canSave: after.structuralValid && !introduced.some((issue) => issue.severity === "error"), requiresReview: introduced.some((issue) => issue.severity === "warning") };
}
