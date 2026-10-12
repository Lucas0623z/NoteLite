import type { OpenSheetMusicDisplay } from "opensheetmusicdisplay";
import type { Note } from "opensheetmusicdisplay/build/dist/src/MusicalScore/VoiceData/Note";
import type { VexFlowGraphicalNote } from "opensheetmusicdisplay/build/dist/src/MusicalScore/Graphical/VexFlow/VexFlowGraphicalNote";
import type { NoteEdit } from "./cloud";
import type { NoteKey } from "./score-position";
import { compareScoreRules, parseScoreXML, type ScoreRuleComparison, type ScoreRuleIssue } from "./scoreRules.ts";

export type { NoteKey } from "./score-position";
export const noteKeyId = (key: NoteKey) => JSON.stringify([key.partId, key.measureIndex, key.noteIndex]);
export type NoteDraftSource = { key: NoteKey; step: string; octave: string; alter: string; duration: string; type: string; dot: number; rest: boolean };
export type NoteDraftValues = { step: string; octave: string; alter: string; duration: string; type: string; dot: string; rest: boolean };
export type NoteDraftCheck = { changed: boolean; canSave: boolean; edit: NoteEdit | null; candidate: string | null; comparison: ScoreRuleComparison | null; message: string };

/** Only a private candidate is checked; the exact same edit/candidate is saved. */
export function inspectNoteDraft(xml: string, source: NoteDraftSource, draft: NoteDraftValues, rhythm: boolean): NoteDraftCheck {
  const edit: NoteEdit = { ...source.key };
  const rejected = (message: string): NoteDraftCheck => ({ changed: true, canSave: false, edit: null, candidate: null, comparison: null, message });
  if (rhythm && source.rest !== draft.rest) edit.rest = draft.rest;
  if (!draft.rest && (source.rest || source.step !== draft.step || source.octave !== draft.octave || source.alter !== draft.alter)) {
    if (!["C", "D", "E", "F", "G", "A", "B"].includes(draft.step) || !draft.octave.trim() || !Number.isInteger(Number(draft.octave)) || !draft.alter.trim() || !Number.isFinite(Number(draft.alter))) return rejected("请填写有效的音名、八度和升降值。");
    edit.pitch = { step: draft.step, octave: Number(draft.octave), alter: Number(draft.alter) };
  }
  if (rhythm) {
    if (Number(draft.duration) !== Number(source.duration) || !draft.duration.trim()) {
      if (!draft.duration.trim() || !Number.isFinite(Number(draft.duration)) || Number(draft.duration) <= 0) return rejected("时值必须大于零，单位为当前小节的 divisions。");
      edit.duration = Number(draft.duration);
    }
    if (draft.type !== source.type) edit.type = draft.type;
    if (Number(draft.dot) !== source.dot) {
      if (!draft.dot.trim() || !Number.isInteger(Number(draft.dot)) || Number(draft.dot) < 0 || Number(draft.dot) > 4) return rejected("附点数量须为 0 至 4 的整数。");
      edit.dot = Number(draft.dot);
    }
  }
  const changed = Object.keys(edit).length > 3;
  if (!changed) return { changed: false, canSave: false, edit: null, candidate: null, comparison: null, message: "当前草稿未修改。" };
  try {
    const candidate = new XMLSerializer().serializeToString(previewNoteEdits(parseScoreXML(xml), [edit]));
    const comparison = compareScoreRules(xml, candidate);
    const errors = comparison.introduced.filter((issue) => issue.severity === "error");
    const warnings = comparison.introduced.filter((issue) => issue.severity === "warning");
    return { changed, canSave: comparison.canSave, edit, candidate, comparison, message: errors.length ? `当前草稿有 ${errors.length} 项新增拍数或时值错误，不能保存。` : warnings.length ? `当前草稿可保存；有 ${warnings.length} 项新提示，请复核。` : "当前草稿符合小节拍数与时值规则，可保存；已有谱面问题见检查说明。" };
  } catch (error) { return rejected(error instanceof Error ? error.message : String(error)); }
}

export function summarizeRuleErrors(issues: ScoreRuleIssue[]): string {
  const errors = issues.filter((issue) => issue.severity === "error");
  return errors.slice(0, 2).map((issue) => issue.message).join("；") + (errors.length > 2 ? `；另有 ${errors.length - 2} 项错误，请展开“本次修改检查”。` : "");
}
const direct = (node: Node, name: string): Element[] => Array.from(node.childNodes).filter((child): child is Element => child.nodeType === 1 && (child as Element).localName === name);
const NOTE_ORDER = ["grace", "cue", "chord", "pitch", "unpitched", "rest", "duration", "tie", "instrument", "footnote", "level", "voice", "type", "dot", "accidental", "time-modification", "stem", "notehead", "notehead-text", "staff", "beam", "notations", "lyric", "play", "listen"];
function insertOrdered(parent: Element, element: Element, order = NOTE_ORDER) {
  const position = order.indexOf(element.localName);
  const next = Array.from(parent.childNodes).find((child) => child.nodeType === 1 && order.indexOf((child as Element).localName) > position);
  parent.insertBefore(element, next || null);
}
type NoteIdentity = { key: NoteKey; color: string | null; label: string };
export type PreparedNotation = { document: Document; identities: Map<string, NoteIdentity> };

/** Mark only a private render document. OSMD's reader carries this through to NoteheadColorXml. */
export function prepareNotation(source: Document): PreparedNotation {
  const document = source.cloneNode(true) as Document;
  const identities = new Map<string, NoteIdentity>();
  for (const part of direct(document.documentElement, "part")) {
    direct(part, "measure").forEach((measure, measureIndex) => {
      direct(measure, "note").forEach((note, noteIndex) => {
        if (identities.size >= 0xffffff) throw new Error("曲谱音符数量超过可交互排版上限。");
        const marker = `#${(identities.size + 1).toString(16).padStart(6, "0")}`;
        let head = direct(note, "notehead")[0];
        const color = head?.getAttribute("color") || note.getAttribute("color") || null;
        if (!head) {
          head = document.createElementNS(note.namespaceURI, "notehead");
          head.textContent = "normal";
          insertOrdered(note, head);
        }
        head.setAttribute("color", marker);
        const pitch = direct(note, "pitch")[0];
        const step = pitch && direct(pitch, "step")[0]?.textContent;
        const octave = pitch && direct(pitch, "octave")[0]?.textContent;
        const label = direct(note, "rest").length ? "休止符" : `${step || "音符"}${octave || ""}`;
        identities.set(marker, { key: { partId: part.getAttribute("id") || "", measureIndex, noteIndex }, color, label: `第 ${measure.getAttribute("number") || measureIndex + 1} 小节 · ${label} · 音符 ${noteIndex + 1}` });
      });
    });
  }
  return { document, identities };
}

/** Identity is the XML location, never pitch, timestamp sorting, or SVG draw order. */
export function restoreNotationSources<T extends { NoteheadColorXml: string; NoteheadColor: string }>(sources: Iterable<T>, prepared: PreparedNotation, defaultColor = "#000000") {
  const mapped = new Map<T, NoteIdentity>();
  for (const source of sources) {
    const identity = prepared.identities.get(source.NoteheadColorXml?.toLowerCase());
    if (!identity) continue;
    mapped.set(source, identity);
    source.NoteheadColorXml = identity.color || "";
    source.NoteheadColor = identity.color || defaultColor;
  }
  return mapped;
}

export function notationSources(display: OpenSheetMusicDisplay): Note[] {
  const sources = new Set<Note>();
  for (const measure of display.Sheet.SourceMeasures) for (const vertical of measure.VerticalSourceStaffEntryContainers) for (const staff of vertical.StaffEntries) {
    if (staff) for (const voice of staff.VoiceEntries) for (const note of voice.Notes) sources.add(note);
  }
  return [...sources];
}

export type NoteBinding = { key: NoteKey; label: string; head: Element; graphical?: VexFlowGraphicalNote };
export function graphicalNoteBindings(display: OpenSheetMusicDisplay, mapped: Map<Note, NoteIdentity>): NoteBinding[] {
  const bindings: NoteBinding[] = [];
  for (const [source, identity] of mapped) {
    const graphical = display.EngravingRules.GNote(source) as VexFlowGraphicalNote | undefined;
    const heads = graphical?.getNoteheadSVGs();
    // OSMD returns every chord head; vfnoteIndex is this source note's exact head.
    const head = heads?.[graphical?.vfnoteIndex ?? 0];
    if (head) bindings.push({ ...identity, head, graphical });
  }
  return bindings;
}

type AttributeBackup = { element: Element; name: string; value: string | null };
const descendants = (element: Element): Element[] => [element, ...Array.from(element.childNodes).flatMap((child) => child.nodeType === 1 ? descendants(child as Element) : [])];
const restore = (attributes: AttributeBackup[]) => { for (const { element, name, value } of attributes) value === null ? element.removeAttribute(name) : element.setAttribute(name, value); };

export type NotationFeedback = { key: NoteKey; state: "correct" | "wrong" | "pending" };
export function createNotationInteraction(host: HTMLElement, bindings: () => NoteBinding[], onSelect: (key: NoteKey) => void) {
  let active = true;
  let selected: NoteKey | null = null;
  let playhead: NoteKey[] = [];
  let feedback: NotationFeedback[] = [];
  let current: NoteBinding[] = [];
  let attributes: AttributeBackup[] = [];
  let colored: AttributeBackup[] = [];
  let overlays: Element[] = [];
  const elements = (key: NoteKey) => current.filter((binding) => noteKeyId(binding.key) === noteKeyId(key)).map((binding) => binding.head);
  const saveAttribute = (element: Element, name: string) => attributes.push({ element, name, value: element.getAttribute(name) });
  const colorSelection = () => {
    restore(colored); colored = [];
    for (const binding of current) {
      const chosen = selected !== null && noteKeyId(binding.key) === noteKeyId(selected);
      binding.head.setAttribute("aria-pressed", String(chosen));
      const state=feedback.find(value=>noteKeyId(value.key)===noteKeyId(binding.key))?.state;
      if (!chosen && !state) continue;
      const color=chosen?"#2563eb":state==="correct"?"#22a447":state==="wrong"?"#dc2626":"#d97706";
      for (const element of descendants(binding.head)) for (const name of ["fill", "stroke"]) {
        const value = element.getAttribute(name);
        if (value === "none" || name === "stroke" && value === null) continue;
        colored.push({ element, name, value }); element.setAttribute(name, color);
      }
    }
  };
  const clearPointer = () => { for (const overlay of overlays) overlay.remove(); overlays = []; };
  const drawPointer = () => {
    clearPointer();
    if (!active || !playhead.length) return;
    const groups = new Map<object, { svg: SVGSVGElement; x: number[]; top: number; bottom: number }>();
    for (const key of playhead) for (const binding of current.filter((value) => noteKeyId(value.key) === noteKeyId(key))) {
      const head = binding.head as SVGGraphicsElement;
      const svg = head.ownerSVGElement;
      const graphical = binding.graphical;
      const system = graphical?.parentVoiceEntry.parentStaffEntry.parentMeasure.ParentMusicSystem;
      const matrix = svg?.getScreenCTM();
      if (!svg || !system || !matrix) continue;
      const bounds = head.getBoundingClientRect();
      const point = svg.createSVGPoint(); point.x = bounds.left + bounds.width / 2; point.y = bounds.top + bounds.height / 2;
      const position = point.matrixTransform(matrix.inverse());
      const staffBounds = system.StaffLines.flatMap((line) => {
        const measure = line.Measures[0] as unknown as { getVFStave?(): { getYForLine(index: number): number; getNumLines(): number } };
        const stave = measure?.getVFStave?.();
        return stave ? [stave.getYForLine(0), stave.getYForLine(Math.max(0, stave.getNumLines() - 1))] : [];
      });
      const top = Math.min(position.y, ...staffBounds) - 12;
      const bottom = Math.max(position.y, ...staffBounds) + 12;
      const group = groups.get(system);
      if (group) { group.x.push(position.x); group.top = Math.min(group.top, top); group.bottom = Math.max(group.bottom, bottom); }
      else groups.set(system, { svg, x: [position.x], top, bottom });
    }
    for (const { svg, x, top, bottom } of groups.values()) {
      const pointer = svg.ownerDocument.createElementNS("http://www.w3.org/2000/svg", "g");
      pointer.setAttribute("data-notelite-playhead", "true"); pointer.setAttribute("aria-label", "当前谱面位置"); pointer.setAttribute("pointer-events", "none");
      const location = Math.min(...x);
      const line = svg.ownerDocument.createElementNS("http://www.w3.org/2000/svg", "line");
      for (const [name, value] of Object.entries({ x1: location, x2: location, y1: top, y2: bottom, stroke: "#22a447", "stroke-width": 2 })) line.setAttribute(name, String(value));
      const arrow = svg.ownerDocument.createElementNS("http://www.w3.org/2000/svg", "path");
      arrow.setAttribute("d", `M ${location - 6} ${top - 8} L ${location + 6} ${top - 8} L ${location} ${top} Z`); arrow.setAttribute("fill", "#f59e0b");
      pointer.appendChild(line); pointer.appendChild(arrow); svg.appendChild(pointer); overlays.push(pointer);
    }
  };
  const find = (target: EventTarget | null) => {
    let element = target as Node | null;
    while (element && element !== host) {
      const matches = current.filter((binding) => binding.head === element);
      const unique = new Map(matches.map((binding) => [noteKeyId(binding.key), binding]));
      if (unique.size === 1) return [...unique.values()][0];
      if (unique.size > 1) return undefined; // An actually shared glyph cannot identify one XML note.
      element = element.parentNode;
    }
  };
  const click = (event: MouseEvent) => {
    if (!active || event.button !== 0) return;
    const binding = find(event.target);
    if (binding) { selected = binding.key; colorSelection(); onSelect(binding.key); }
  };
  const keydown = (event: KeyboardEvent) => {
    if (!active || !["Enter", " "].includes(event.key)) return;
    const binding = find(event.target);
    if (binding) { event.preventDefault(); selected = binding.key; colorSelection(); onSelect(binding.key); }
  };
  host.addEventListener("click", click); host.addEventListener("keydown", keydown);
  return {
    elements,
    refresh() {
      if (!active) return;
      restore(attributes); attributes = []; restore(colored); colored = [];
      current = bindings().filter((binding) => host.contains(binding.head));
      const ownership = new Map<Element, Set<string>>();
      for (const binding of current) {
        if (!ownership.has(binding.head)) ownership.set(binding.head, new Set());
        ownership.get(binding.head)!.add(noteKeyId(binding.key));
      }
      for (const [head, keys] of ownership) {
        if (keys.size !== 1) continue;
        const binding = current.find((value) => value.head === head)!;
        for (const name of ["role", "tabindex", "aria-label", "aria-pressed", "data-notelite-note"]) saveAttribute(head, name);
        head.setAttribute("role", "button"); head.setAttribute("tabindex", "0"); head.setAttribute("aria-label", binding.label); head.setAttribute("data-notelite-note", noteKeyId(binding.key));
      }
      colorSelection(); drawPointer();
    },
    setSelection(key: NoteKey | null) { if (active) { selected = key; colorSelection(); } },
    setFeedback(values: NotationFeedback[]) { if (active) { feedback=values.map(value=>({key:{...value.key},state:value.state}));colorSelection(); } },
    setPlayhead(keys: NoteKey[]) { if (active) { playhead = [...keys]; drawPointer(); } },
    dispose() {
      active = false; host.removeEventListener("click", click); host.removeEventListener("keydown", keydown);
      restore(colored); restore(attributes); colored = []; attributes = []; current = []; clearPointer();
    },
  };
}

/** Build the same note changes locally for rule checking; the original XML is untouched. */
export function previewNoteEdits(source: Document, edits: NoteEdit[]): Document {
  const document = source.cloneNode(true) as Document;
  const setText = (parent: Element, name: string, value: string) => {
    let element = direct(parent, name)[0];
    if (!element) { element = document.createElementNS(parent.namespaceURI, name); insertOrdered(parent, element, parent.localName === "pitch" ? ["step", "alter", "octave"] : NOTE_ORDER); }
    element.textContent = value; return element;
  };
  for (const edit of edits) {
    const part = direct(document.documentElement, "part").find((item) => item.getAttribute("id") === edit.partId);
    const measure = part && direct(part, "measure")[edit.measureIndex];
    const note = measure && direct(measure, "note")[edit.noteIndex];
    if (!note) throw new Error("音符位置已改变，请重新载入曲谱。");
    if (edit.delete) { note.parentNode!.removeChild(note); continue; }
    if (edit.rest === true) {
      for (const name of ["pitch", "unpitched", "accidental"]) for (const element of direct(note, name)) note.removeChild(element);
      if (!direct(note, "rest").length) insertOrdered(note, document.createElementNS(note.namespaceURI, "rest"));
    } else if (edit.rest === false) for (const element of direct(note, "rest")) note.removeChild(element);
    if (edit.pitch && edit.rest !== true) {
      for (const name of ["rest", "unpitched", "accidental"]) for (const element of direct(note, name)) note.removeChild(element);
      let pitch = direct(note, "pitch")[0];
      if (!pitch) { pitch = document.createElementNS(note.namespaceURI, "pitch"); insertOrdered(note, pitch); }
      setText(pitch, "step", edit.pitch.step); setText(pitch, "alter", String(edit.pitch.alter)); setText(pitch, "octave", String(edit.pitch.octave));
    }
    if (edit.duration !== undefined) setText(note, "duration", String(edit.duration));
    if (edit.type !== undefined) { if (edit.type) setText(note, "type", edit.type); else for (const element of direct(note, "type")) note.removeChild(element); }
    if (edit.dot !== undefined) {
      for (const element of direct(note, "dot")) note.removeChild(element);
      for (let index = 0; index < edit.dot; index++) insertOrdered(note, document.createElementNS(note.namespaceURI, "dot"));
    }
  }
  return document;
}
