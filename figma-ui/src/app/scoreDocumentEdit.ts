import { collectTempoReferences, directElements, dottedQuarterLength, firstElement, parseScoreXML, textOf } from "./scoreRules.ts";

export type MeterGroup = { beats: string; beatType: number };
export type ClefInfo = { measureIndex: number; attributesIndex: number; staff: string; sign: string; line: number | null; octaveChange: number };
export type KeyInfo = { measureIndex: number; attributesIndex: number; staff: string | null; fifths: number | null; mode: string };
export type MeterInfo = { measureIndex: number; attributesIndex: number; staff: string | null; beats: string; beatType: number | null; groups: MeterGroup[]; senzaMisura: boolean };
export type TempoInfo = { measureIndex: number; staff: string | null; directionIndex: number; metronomeIndex: number; beatUnit: string; dots: number; perMinute: string; soundTempo: number | null; editable: boolean };
export type ScoreDocumentPart = { id: string; name: string; instrumentName: string; instruments: { id: string; name: string }[]; staffNumbers: string[]; measures: { index: number; number: string }[]; clefs: ClefInfo[]; keys: KeyInfo[]; meters: MeterInfo[]; tempos: TempoInfo[] };
export type ScoreDocumentInfo = { parts: ScoreDocumentPart[] };
type AtMeasure = { partId: string; measureIndex: number; staff?: string | null; attributesIndex?: number };
export type ScoreDocumentPatch =
  | { kind: "name"; partId: string; partName?: string; instrumentName?: string; instrumentId?: string }
  | (AtMeasure & { kind: "clef"; staff: string; sign: string; line?: number | null; octaveChange?: number })
  | (AtMeasure & { kind: "key"; fifths: number; mode?: string })
  | (AtMeasure & { kind: "meter"; groups: MeterGroup[] })
  | (AtMeasure & { kind: "tempo"; directionIndex?: number; metronomeIndex?: number; createNew?: boolean; beatUnit: string; dots: number; perMinute: number });

const nullableNumber = (value: string): number | null => value.trim() && Number.isFinite(Number(value)) ? Number(value) : null;
const optionalStaff = (element: Element) => element.getAttribute("number") || null;
const metronomesIn = (direction: Element) => directElements(direction, "direction-type").flatMap((type) => directElements(type, "metronome"));

export function readScoreDocument(xml: string): ScoreDocumentInfo {
  const document = parseScoreXML(xml); const root = document.documentElement;
  const definitions = directElements(firstElement(root, "part-list") || root, "score-part");
  return { parts: directElements(root, "part").map((part) => {
    const id = part.getAttribute("id") || "";
    const definition = definitions.find((candidate) => candidate.getAttribute("id") === id);
    const instruments = definition ? directElements(definition, "score-instrument").map((instrument) => ({ id: instrument.getAttribute("id") || "", name: textOf(instrument, "instrument-name") })) : [];
    const result: ScoreDocumentPart = { id, name: definition ? textOf(definition, "part-name") : id, instrumentName: instruments[0]?.name || "", instruments, staffNumbers: [], measures: [], clefs: [], keys: [], meters: [], tempos: [] };
    const staves = new Set<string>(["1"]);
    directElements(part, "measure").forEach((measure, measureIndex) => {
      result.measures.push({ index: measureIndex, number: measure.getAttribute("number") || String(measureIndex + 1) });
      for (const note of directElements(measure, "note")) if (textOf(note, "staff")) staves.add(textOf(note, "staff"));
      directElements(measure, "attributes").forEach((attributes, attributesIndex) => {
        const count = Number(textOf(attributes, "staves"));
        if (Number.isInteger(count) && count > 0 && count <= 128) for (let index = 1; index <= count; index++) staves.add(String(index));
        for (const clef of directElements(attributes, "clef")) {
          const staff = clef.getAttribute("number") || "1"; staves.add(staff);
          result.clefs.push({ measureIndex, attributesIndex, staff, sign: textOf(clef, "sign"), line: nullableNumber(textOf(clef, "line")), octaveChange: Number(textOf(clef, "clef-octave-change") || 0) });
        }
        for (const key of directElements(attributes, "key")) {
          const staff = optionalStaff(key); if (staff) staves.add(staff);
          result.keys.push({ measureIndex, attributesIndex, staff, fifths: nullableNumber(textOf(key, "fifths")), mode: textOf(key, "mode") });
        }
        for (const time of directElements(attributes, "time")) {
          const staff = optionalStaff(time); if (staff) staves.add(staff);
          const children = directElements(time); const groups: MeterGroup[] = [];
          for (let index = 0; index < children.length - 1; index++) if (children[index].localName === "beats" && children[index + 1].localName === "beat-type") groups.push({ beats: children[index].textContent?.trim() || "", beatType: Number(children[index + 1].textContent) });
          result.meters.push({ measureIndex, attributesIndex, staff, beats: groups[0]?.beats || "", beatType: groups[0]?.beatType ?? null, groups, senzaMisura: !!firstElement(time, "senza-misura") });
        }
      });
      directElements(measure, "direction").forEach((direction, directionIndex) => {
        const staff = textOf(direction, "staff") || null; if (staff) staves.add(staff);
        const sound = directElements(direction, "sound").find((candidate) => candidate.hasAttribute("tempo"));
        metronomesIn(direction).forEach((metronome, metronomeIndex) => {
          const beatUnit = textOf(metronome, "beat-unit"), dots = directElements(metronome, "beat-unit-dot").length, perMinute = textOf(metronome, "per-minute");
          result.tempos.push({ measureIndex, staff, directionIndex, metronomeIndex, beatUnit, dots, perMinute, soundTempo: sound ? nullableNumber(sound.getAttribute("tempo") || "") : null,
            editable: directElements(metronome, "beat-unit").length === 1 && !!firstElement(metronome, "per-minute") && !firstElement(metronome, "beat-unit-tied") && !firstElement(metronome, "metronome-note") && dottedQuarterLength(beatUnit, dots) !== null });
        });
      });
    });
    result.staffNumbers = [...staves].sort((a, b) => Number(a) - Number(b));
    return result;
  }) };
}

function createElement(parent: Element, name: string): Element {
  const qualified = parent.prefix ? `${parent.prefix}:${name}` : name;
  return parent.ownerDocument!.createElementNS(parent.namespaceURI, qualified);
}
function removeElement(element: Element): void { element.parentNode?.removeChild(element); }
function insertOrdered(parent: Element, child: Element, order: readonly string[]): void {
  const position = order.indexOf(child.localName);
  const next = directElements(parent).find((element) => order.indexOf(element.localName) > position);
  parent.insertBefore(child, next || null);
}
function setText(parent: Element, name: string, value: string | number, order: readonly string[]): Element {
  let child = firstElement(parent, name);
  if (!child) { child = createElement(parent, name); insertOrdered(parent, child, order); }
  child.textContent = String(value); return child;
}
const ATTRIBUTE_ORDER = ["footnote", "level", "divisions", "key", "time", "staves", "part-symbol", "instruments", "clef", "staff-details", "transpose", "directive", "measure-style"];
const DIRECTION_ORDER = ["direction-type", "offset", "footnote", "level", "voice", "staff", "sound", "listening"];
const NAME_ORDER = ["part-name", "part-name-display", "part-abbreviation", "part-abbreviation-display", "group", "score-instrument", "midi-device", "midi-instrument"];
function atAttributes(measure: Element): Element {
  // Changing the header must not accidentally overwrite a later mid-measure clef.
  const leading = directElements(measure).find((element) => !["print", "bookmark", "link"].includes(element.localName));
  if (leading?.localName === "attributes") return leading;
  const attributes = createElement(measure, "attributes"); measure.insertBefore(attributes, leading || null); return attributes;
}
function scopedAttribute(attributes: Element, name: string, staff: string | null, clef = false): Element {
  let element = directElements(attributes, name).find((candidate) => (candidate.getAttribute("number") || (clef ? "1" : null)) === staff);
  if (!element) { element = createElement(attributes, name); if (staff && (!clef || staff !== "1")) element.setAttribute("number", staff); insertOrdered(attributes, element, ATTRIBUTE_ORDER); }
  return element;
}
function scopedAttributes(attributes: Element, name: string, staff: string | null): Element[] {
  const primary = scopedAttribute(attributes, name, staff);
  // A common signature applies to every staff at this position. Existing
  // numbered signatures in the same attributes block must not override it.
  // Update those in place so their visual attributes survive; later blocks
  // and measures remain separate, intentional changes.
  return staff ? [primary] : [primary, ...directElements(attributes, name).filter((element) => element !== primary)];
}
function requireStaff(staff: string | null | undefined): string | null {
  if (staff === undefined || staff === null || staff === "") return null;
  if (!/^\d+$/.test(staff) || Number(staff) < 1 || Number(staff) > 128) throw new Error("谱表编号必须为 1 至 128 的整数。");
  return String(Number(staff));
}
function checkName(value: string): string {
  const trimmed = value.trim();
  if (!trimmed || trimmed.length > 200 || /[\u0000-\u0008\u000B\u000C\u000E-\u001F]/.test(trimmed)) throw new Error("名称须为 1 至 200 个有效字符。");
  return trimmed;
}
function setTempo(measure: Element, patch: Extract<ScoreDocumentPatch, { kind: "tempo" }>, staff: string | null): Element {
  const unit = dottedQuarterLength(patch.beatUnit, patch.dots);
  if (unit === null || patch.dots > 4 || !Number.isFinite(patch.perMinute) || patch.perMinute <= 0 || patch.perMinute > 1000) throw new Error("速度须为正数，拍单位有效，附点为 0 至 4 个。");
  const directions = directElements(measure, "direction");
  let direction: Element | undefined;
  let metronome: Element | undefined;
  if (patch.directionIndex !== undefined && !patch.createNew) {
    if (!Number.isInteger(patch.directionIndex) || patch.directionIndex < 0 || !directions[patch.directionIndex]) throw new Error("该速度标记已不存在，请重新载入曲谱。");
    direction = directions[patch.directionIndex];
    metronome = metronomesIn(direction)[patch.metronomeIndex ?? 0];
    if (!metronome) throw new Error("该速度标记已不存在，请重新载入曲谱。");
  } else if (!patch.createNew) {
    // Header creation/replacement only considers directions before the first
    // rhythmic element and with zero offset, preserving later tempo changes.
    for (const child of directElements(measure)) {
      if (["note", "backup", "forward"].includes(child.localName)) break;
      if (child.localName !== "direction" || Number(textOf(child, "offset") || 0) !== 0 || (textOf(child, "staff") || null) !== staff) continue;
      const candidate = metronomesIn(child)[0];
      if (candidate) { direction = child; metronome = candidate; break; }
    }
  }
  if (metronome && (directElements(metronome, "beat-unit").length !== 1 || !firstElement(metronome, "per-minute") || firstElement(metronome, "beat-unit-tied") || firstElement(metronome, "metronome-note"))) throw new Error("此标记为速度关系或复杂节拍；请在完整 MusicXML 中修改，不能替换为普通速度。 ");
  if (!direction) {
    direction = createElement(measure, "direction"); direction.setAttribute("placement", "above");
    const before = directElements(measure).find((child) => !["print", "attributes", "bookmark", "link"].includes(child.localName));
    measure.insertBefore(direction, before || null);
    if (staff) setText(direction, "staff", staff, DIRECTION_ORDER);
  }
  if (!metronome) { const type = createElement(direction, "direction-type"); insertOrdered(direction, type, DIRECTION_ORDER); metronome = createElement(type, "metronome"); type.appendChild(metronome); }
  const ORDER = ["beat-unit", "beat-unit-dot", "beat-unit-tied", "per-minute", "metronome-arrows", "metronome-note", "metronome-relation"];
  setText(metronome, "beat-unit", patch.beatUnit, ORDER);
  directElements(metronome, "beat-unit-dot").forEach(removeElement);
  for (let index = 0; index < patch.dots; index++) insertOrdered(metronome, createElement(metronome, "beat-unit-dot"), ORDER);
  setText(metronome, "per-minute", patch.perMinute, ORDER);
  const quarterTempo = Number((patch.perMinute * unit).toFixed(9));
  const visualOffset = Number(textOf(direction, "offset") || 0);
  const defaultSoundOffset = firstElement(direction, "offset")?.getAttribute("sound") === "yes" ? visualOffset : 0;
  let sound = directElements(direction, "sound").find((element) => element.hasAttribute("tempo") && Number(firstElement(element, "offset")?.textContent ?? defaultSoundOffset) === visualOffset);
  if (!sound) { sound = createElement(direction, "sound"); insertOrdered(direction, sound, DIRECTION_ORDER); }
  sound.setAttribute("tempo", String(quarterTempo));
  if (defaultSoundOffset !== visualOffset && !firstElement(sound, "offset")) setText(sound, "offset", visualOffset, ["instrument-change", "midi-device", "midi-instrument", "play", "swing", "offset"]);
  // A separate leading <sound tempo> at this exact header position would
  // override the edited visible metronome in some MIDI readers. Keep it in sync
  // while preserving its other playback attributes and all later changes.
  const children = directElements(measure);
  const targetIsHeader = children.indexOf(direction) < children.findIndex((child) => ["note", "backup", "forward"].includes(child.localName)) || !children.some((child) => ["note", "backup", "forward"].includes(child.localName));
  if (targetIsHeader && Number(textOf(direction, "offset") || 0) === 0) for (const child of children) {
    if (["note", "backup", "forward"].includes(child.localName)) break;
    if (child.localName === "sound" && child.hasAttribute("tempo") && Number(textOf(child, "offset") || 0) === 0) child.setAttribute("tempo", String(quarterTempo));
  }
  return metronome;
}

/** Edits only the requested header item. It never transposes pitches, changes
 * MIDI instrument programs, fills measures, or rewrites notation/voice data. */
export function editScoreDocument(xml: string, patch: ScoreDocumentPatch): string {
  const document = parseScoreXML(xml); const root = document.documentElement;
  const part = directElements(root, "part").find((candidate) => candidate.getAttribute("id") === patch.partId);
  if (!part) throw new Error("该声部已不存在，请重新载入曲谱。");
  if (patch.kind === "name") {
    const list = firstElement(root, "part-list"); const definition = list && directElements(list, "score-part").find((candidate) => candidate.getAttribute("id") === patch.partId);
    if (!definition) throw new Error("声部定义缺失，不能修改名称。");
    if (patch.partName !== undefined) {
      const value = checkName(patch.partName); setText(definition, "part-name", value, NAME_ORDER);
      const display = firstElement(definition, "part-name-display");
      if (display) { directElements(display).forEach(removeElement); setText(display, "display-text", value, ["display-text"]); }
    }
    if (patch.instrumentName !== undefined) {
      const value = checkName(patch.instrumentName); const instruments = directElements(definition, "score-instrument");
      let instrument = patch.instrumentId !== undefined ? instruments.find((candidate) => candidate.getAttribute("id") === patch.instrumentId) : instruments[0];
      if (patch.instrumentId !== undefined && !instrument) throw new Error("该乐器定义已不存在，请重新载入曲谱。");
      if (!instrument) {
        instrument = createElement(definition, "score-instrument");
        const used = new Set(Array.from(document.getElementsByTagName("*")).map((element) => element.getAttribute("id")).filter(Boolean));
        let suffix = 1; while (used.has(`${patch.partId}-I${suffix}`)) suffix++;
        instrument.setAttribute("id", `${patch.partId}-I${suffix}`); insertOrdered(definition, instrument, NAME_ORDER);
      }
      setText(instrument, "instrument-name", value, ["instrument-name", "instrument-abbreviation", "instrument-sound", "solo", "ensemble", "virtual-instrument"]);
    }
  } else {
    if (!Number.isInteger(patch.measureIndex) || patch.measureIndex < 0) throw new Error("小节位置无效。");
    const measure = directElements(part, "measure")[patch.measureIndex];
    if (!measure) throw new Error("该小节已不存在，请重新载入曲谱。");
    const staff = requireStaff(patch.staff);
    if (patch.kind === "tempo") {
      const before = collectTempoReferences(document);
      const metronome = setTempo(measure, patch, staff);
      const current = collectTempoReferences(document).find((reference) => reference.element === metronome)!;
      const samePosition = before.filter((reference) => reference.measureIndex === current.measureIndex && Math.abs(reference.position - current.position) < 1e-7 && reference.quarterTempo !== null);
      const oldValues = samePosition.map((reference) => reference.quarterTempo!);
      if (oldValues.length && Math.max(...oldValues) - Math.min(...oldValues) > 1e-7) throw new Error("此位置原有纸面、播放或声部速度互相冲突；请先在完整 MusicXML 中统一速度，不能自动任选一个覆盖。");
      // Speed is global: matching marks at this one written position across
      // staves/parts must agree. Retain their unit, dots, styling and later marks.
      for (const reference of samePosition) {
        if (reference.element === metronome) continue;
        if (reference.kind === "sound") reference.element.setAttribute("tempo", String(current.quarterTempo));
        else if (reference.unit) firstElement(reference.element, "per-minute")!.textContent = String(Number((current.quarterTempo! / reference.unit).toFixed(9)));
      }
    }
    else {
      const attributes = patch.attributesIndex === undefined ? atAttributes(measure) : directElements(measure, "attributes")[patch.attributesIndex];
      if (!attributes || patch.attributesIndex !== undefined && (!Number.isInteger(patch.attributesIndex) || patch.attributesIndex < 0)) throw new Error("该记谱信息已不存在，请重新载入曲谱。");
      if (patch.kind === "clef") {
        if (!staff || !["G", "F", "C", "percussion", "TAB", "jianpu", "none"].includes(patch.sign)) throw new Error("请选择有效谱号和谱表。");
        if (patch.line !== undefined && patch.line !== null && (!Number.isInteger(patch.line) || patch.line < 1 || patch.line > 5)) throw new Error("谱号线位须为 1 至 5。");
        if (patch.octaveChange !== undefined && (!Number.isInteger(patch.octaveChange) || Math.abs(patch.octaveChange) > 4)) throw new Error("谱号八度变化须为 -4 至 4 的整数。");
        const clef = scopedAttribute(attributes, "clef", staff, true); const ORDER = ["sign", "line", "clef-octave-change"];
        setText(clef, "sign", patch.sign, ORDER);
        if (patch.line === null || ["percussion", "TAB", "jianpu", "none"].includes(patch.sign)) directElements(clef, "line").forEach(removeElement);
        else if (patch.line !== undefined) setText(clef, "line", patch.line, ORDER);
        if (patch.octaveChange !== undefined) {
          if (!patch.octaveChange) directElements(clef, "clef-octave-change").forEach(removeElement);
          else setText(clef, "clef-octave-change", patch.octaveChange, ORDER);
        }
      } else if (patch.kind === "key") {
        if (!Number.isInteger(patch.fifths) || patch.fifths < -7 || patch.fifths > 7) throw new Error("调号须为 -7 至 7 个升降号。");
        if (patch.mode !== undefined && !["", "major", "minor", "dorian", "phrygian", "lydian", "mixolydian", "aeolian", "ionian", "locrian", "none"].includes(patch.mode)) throw new Error("调式无效。");
        const keys = scopedAttributes(attributes, "key", staff);
        if (keys.some((key) => directElements(key).some((element) => ["key-step", "key-alter", "key-accidental"].includes(element.localName)))) throw new Error("此调号为非传统调号，请在完整 MusicXML 中修改。");
        const ORDER = ["cancel", "fifths", "mode", "key-step", "key-alter", "key-accidental", "key-octave"];
        for (const key of keys) {
          setText(key, "fifths", patch.fifths, ORDER);
          if (patch.mode !== undefined) { if (patch.mode) setText(key, "mode", patch.mode, ORDER); else directElements(key, "mode").forEach(removeElement); }
        }
      } else if (patch.kind === "meter") {
        if (!patch.groups.length || patch.groups.length > 16 || patch.groups.some((group) => !/^\d+(?:\s*\+\s*\d+)*$/.test(group.beats) || group.beats.split("+").some((beats) => Number(beats) < 1 || Number(beats) > 128) || !Number.isInteger(group.beatType) || ![1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024].includes(group.beatType))) throw new Error("拍号须使用有效的拍数和拍单位，例如 3+2 / 8。");
        for (const time of scopedAttributes(attributes, "time", staff)) {
          directElements(time).filter((child) => ["beats", "beat-type", "senza-misura"].includes(child.localName)).forEach(removeElement);
          // Common/cut symbols no longer describe a newly edited arbitrary meter.
          time.removeAttribute("symbol");
          const before = directElements(time)[0] || null;
          for (const group of patch.groups) { const beats = createElement(time, "beats"), beatType = createElement(time, "beat-type"); beats.textContent = group.beats.replace(/\s/g, ""); beatType.textContent = String(group.beatType); time.insertBefore(beats, before); time.insertBefore(beatType, before); }
        }
      }
    }
  }
  return new XMLSerializer().serializeToString(document);
}
