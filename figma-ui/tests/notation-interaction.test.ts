import test from "node:test";
import assert from "node:assert/strict";
import { createNotationInteraction, graphicalNoteBindings, inspectNoteDraft, noteKeyId, prepareNotation, previewNoteEdits, restoreNotationSources, summarizeRuleErrors, type NoteBinding, type NoteKey } from "../src/app/notationInteraction.ts";
import { compareScoreRules, parseScoreXML } from "../src/app/scoreRules.ts";
import { attributesXML, noteXML, scoreXML } from "./xml-dom.ts";

const key = (noteIndex: number, partId = "P1", measureIndex = 0): NoteKey => ({ partId, measureIndex, noteIndex });
const serialize = (document: Document) => new XMLSerializer().serializeToString(document);

const draftSource = { key: key(0), step: "C", octave: "4", alter: "0", duration: "1", type: "quarter", dot: 0, rest: false };
const draftValues = { step: "C", octave: "4", alter: "0", duration: "1", type: "quarter", dot: "0", rest: false };
const draftXML = () => scoreXML(`<measure number="1">${attributesXML()}${noteXML().repeat(4)}</measure>`);

test("draft checks prevent a newly overfull duration from being saved, then recover when corrected", () => {
  const xml = draftXML();
  const invalid = inspectNoteDraft(xml, draftSource, { ...draftValues, duration: "2" }, true);
  assert.equal(invalid.canSave, false); assert.equal(invalid.changed, true);
  assert.ok(invalid.comparison?.introduced.some((issue) => issue.code === "measure-overfull"));
  assert.match(invalid.message, /不能保存/);
  const corrected = inspectNoteDraft(xml, draftSource, { ...draftValues, step: "D", octave: "5" }, true);
  assert.equal(corrected.canSave, true);
  assert.deepEqual(corrected.edit?.pitch, { step: "D", octave: 5, alter: 0 });
  assert.equal(serialize(parseScoreXML(xml)), serialize(parseScoreXML(draftXML())));
});

test("type/dot warnings are checked immediately without blocking a valid duration or changing the saved edit", () => {
  const checked = inspectNoteDraft(draftXML(), draftSource, { ...draftValues, type: "half", dot: "1" }, true);
  assert.equal(checked.canSave, true);
  assert.ok(checked.comparison?.introduced.some((issue) => issue.code === "notated-duration-mismatch"));
  assert.equal(checked.edit?.type, "half"); assert.equal(checked.edit?.dot, 1);
  assert.ok(checked.candidate?.includes("<type>half</type><dot/>"));
});

test("existing recognition errors do not block pitch corrections and no instrument range is judged", () => {
  const xml = draftXML().replace("<duration>1</duration>", "<duration>5</duration>");
  const checked = inspectNoteDraft(xml, { ...draftSource, duration: "5" }, { ...draftValues, duration: "5", octave: "9" }, true);
  assert.equal(checked.canSave, true);
  assert.ok(checked.comparison!.before.errors.length > 0);
  assert.equal(checked.comparison!.introduced.filter((issue) => issue.severity === "error").length, 0);
  assert.equal(checked.edit?.pitch?.octave, 9);
});

test("unchanged rest/type fields and invalid numeric drafts cannot enable save or produce an edit", () => {
  const xml = draftXML().replace("<pitch><step>C</step><octave>4</octave></pitch>", "<rest/>").replace("<type>quarter</type>", "");
  const source = { ...draftSource, rest: true, type: "" };
  assert.equal(inspectNoteDraft(xml, source, { ...draftValues, rest: true, type: "" }, true).changed, false);
  for (const duration of ["", "0", "-1", "Infinity", "NaN"]) {
    const checked = inspectNoteDraft(draftXML(), draftSource, { ...draftValues, duration }, true);
    assert.equal(checked.canSave, false); assert.equal(checked.edit, null);
  }
  assert.equal(inspectNoteDraft(draftXML(), draftSource, { ...draftValues, dot: "Infinity" }, true).edit, null);
});

test("local pitch-only correction uses the addressed XML note and leaves rhythm untouched", () => {
  const checked = inspectNoteDraft(draftXML(), { ...draftSource, key: key(2) }, { ...draftValues, step: "E", duration: "99", type: "half", dot: "2" }, false);
  assert.equal(checked.canSave, true);
  assert.deepEqual(checked.edit, { ...key(2), pitch: { step: "E", octave: 4, alter: 0 } });
  assert.deepEqual(Array.from(parseScoreXML(checked.candidate!).getElementsByTagName("step")).map((step) => step.textContent), ["C", "C", "E", "C"]);
});

test("large rule failures produce two short error messages and a remaining count while preserving full details", () => {
  const issues = Array.from({ length: 50 }, (_, index) => ({ code: "measure-overfull", severity: "error" as const, message: `第 ${index + 1} 小节超拍。` }));
  const status = summarizeRuleErrors(issues);
  assert.ok(status.includes("第 1 小节")); assert.ok(status.includes("第 2 小节"));
  assert.ok(!status.includes("第 3 小节")); assert.match(status, /48 项错误/);
  assert.equal(issues.length, 50);
});

test("render-only identities distinguish chord/repeated/grace/rest XML locations and restore original colors", () => {
  const xml = scoreXML(`<measure number="1">${attributesXML()}${noteXML(1).replace("<type>", '<notehead color="#aabbcc">normal</notehead><type>')}${noteXML(1, "<chord/>")}${noteXML(1, "<grace/>")}${noteXML(1).replace("<pitch><step>C</step><octave>4</octave></pitch>", "<rest/>")}</measure><measure number="1">${noteXML(1)}</measure>`);
  const original = parseScoreXML(xml); const before = serialize(original); const prepared = prepareNotation(original);
  assert.equal(serialize(original), before);
  assert.equal(prepared.identities.size, 5);
  const markers = [...prepared.identities.keys()];
  const sources = markers.map((marker) => ({ NoteheadColorXml: marker, NoteheadColor: marker })).reverse();
  const mapped = restoreNotationSources(sources, prepared);
  assert.deepEqual([...mapped.values()].map((value) => value.key), [key(0, "P1", 1), key(3), key(2), key(1), key(0)]);
  assert.equal(sources[4].NoteheadColor, "#aabbcc");
  assert.equal(sources[0].NoteheadColor, "#000000");
  assert.equal(sources.every((source) => !markers.includes(source.NoteheadColorXml)), true);
  assert.equal(serialize(original), before); // Neither save nor export uses the marked clone.
});

class Element {
  nodeType = 1;
  localName: string;
  childNodes: Element[] = [];
  parentNode: Element | null = null;
  attributes = new Map<string, string>();
  listeners = new Map<string, Set<(event: any) => void>>();
  bounds = { left: 0, top: 0, width: 10, height: 10 };
  ownerDocument = { createElementNS: (_namespace: string, name: string) => new Element(name) };
  constructor(name = "g") { this.localName = name; }
  appendChild(child: Element) { child.remove(); child.parentNode = this; this.childNodes.push(child); return child; }
  remove() { if (this.parentNode) this.parentNode.childNodes = this.parentNode.childNodes.filter((value) => value !== this); this.parentNode = null; }
  contains(child: Element) { return child === this || this.childNodes.some((value) => value.contains(child)); }
  setAttribute(name: string, value: string) { this.attributes.set(name, value); }
  getAttribute(name: string) { return this.attributes.get(name) ?? null; }
  removeAttribute(name: string) { this.attributes.delete(name); }
  addEventListener(name: string, callback: (event: any) => void) { if (!this.listeners.has(name)) this.listeners.set(name, new Set()); this.listeners.get(name)!.add(callback); }
  removeEventListener(name: string, callback: (event: any) => void) { this.listeners.get(name)?.delete(callback); }
  event(name: string, values: object) { const event = { target: this, button: 0, preventDefault() {}, ...values }; for (const callback of this.listeners.get(name) || []) callback(event); }
  get ownerSVGElement(): Element | null { let node = this.parentNode; while (node) { if (node.localName === "svg") return node; node = node.parentNode; } return null; }
  getBoundingClientRect() { return this.bounds; }
  getScreenCTM() { return { inverse: () => ({}) }; }
  createSVGPoint() { return { x: 0, y: 0, matrixTransform() { return { x: this.x, y: this.y }; } }; }
  heads() { return this.childNodes.flatMap((child): Element[] => child.getAttribute("data-notelite-note") ? [child] : child.heads()); }
  overlays() { return this.childNodes.flatMap((child): Element[] => child.getAttribute("data-notelite-playhead") ? [child] : child.overlays()); }
}
const asElement = (element: Element) => element as unknown as globalThis.Element;
const head = (parent: Element, fill = "#000000", left = 10, top = 50) => {
  const element = parent.appendChild(new Element()); element.bounds = { left, top, width: 10, height: 10 };
  const path = element.appendChild(new Element("path")); path.setAttribute("fill", fill); path.setAttribute("stroke", "none");
  return { element, path };
};
const binding = (noteIndex: number, element: Element): NoteBinding => ({ key: key(noteIndex), head: asElement(element), label: `同音 C4 · 原始音符 ${noteIndex}` });

test("OSMD chord head indices bind to their own XML note even when pitches repeat", () => {
  const svg = new Element("svg"); const first = head(svg).element; const second = head(svg).element;
  const document = prepareNotation(parseScoreXML(scoreXML(`<measure number="1">${attributesXML()}${noteXML(1)}${noteXML(1, "<chord/>")}</measure>`)));
  const sources = [...document.identities.keys()].map((marker) => ({ NoteheadColorXml: marker, NoteheadColor: marker }));
  const mapped = restoreNotationSources(sources, document);
  const display = { EngravingRules: { GNote: (source: typeof sources[number]) => ({ vfnoteIndex: sources.indexOf(source), getNoteheadSVGs: () => [asElement(first), asElement(second)] }) } };
  const bindings = graphicalNoteBindings(display as any, mapped as any);
  assert.deepEqual(bindings.map((value) => noteKeyId(value.key)), [noteKeyId(key(0)), noteKeyId(key(1))]);
  assert.equal(bindings[0].head, asElement(first)); assert.equal(bindings[1].head, asElement(second));
});

test("left-click/touch-style click selects the exact repeated-note path and colors only that head", () => {
  const host = new Element("div"); const svg = host.appendChild(new Element("svg"));
  const chordFirst = head(svg, "#aabbcc"); const chordSecond = head(svg); const repeated = head(svg);
  const selected: NoteKey[] = [];
  const controller = createNotationInteraction(host as any, () => [binding(0, chordFirst.element), binding(1, chordSecond.element), binding(2, repeated.element)], (key) => selected.push(key));
  controller.refresh(); host.event("click", { target: repeated.path, button: 0 });
  assert.deepEqual(selected, [key(2)]); assert.equal(repeated.path.getAttribute("fill"), "#2563eb");
  assert.equal(chordFirst.path.getAttribute("fill"), "#aabbcc"); assert.equal(chordSecond.path.getAttribute("fill"), "#000000");
  host.event("click", { target: chordSecond.path, button: 2 }); assert.equal(selected.length, 1);
  host.event("click", { target: chordSecond.path, button: 0 });
  assert.deepEqual(selected, [key(2), key(1)]); assert.equal(chordSecond.path.getAttribute("fill"), "#2563eb");
  assert.equal(repeated.path.getAttribute("fill"), "#000000"); controller.dispose();
  assert.equal(chordFirst.path.getAttribute("fill"), "#aabbcc"); assert.equal(chordSecond.path.getAttribute("fill"), "#000000");
});

test("selection survives a genuine SVG replacement by key and disposed listeners cannot select stale notes", () => {
  const host = new Element("div"); const svg = host.appendChild(new Element("svg"));
  let current = head(svg); const selected: NoteKey[] = [];
  const controller = createNotationInteraction(host as any, () => [binding(1, current.element)], (key) => selected.push(key));
  controller.refresh(); controller.setSelection(key(1)); const old = current;
  old.element.remove(); current = head(svg, "#ff0000"); controller.refresh();
  assert.equal(current.path.getAttribute("fill"), "#2563eb"); assert.equal(old.path.getAttribute("fill"), "#000000");
  assert.deepEqual(controller.elements(key(1)), [asElement(current.element)]);
  let prevented = false; host.event("keydown", { target: current.element, key: "Enter", preventDefault: () => { prevented = true; } });
  assert.equal(prevented, true); assert.deepEqual(selected, [key(1)]);
  controller.dispose(); host.event("click", { target: current.path });
  assert.equal(selected.length, 1); assert.equal(current.path.getAttribute("fill"), "#ff0000"); assert.equal(current.element.getAttribute("role"), null);
});
test("actual practice feedback paints exact written heads and preserves blue edit selection and source colors",()=>{
 const host=new Element("div"),svg=host.appendChild(new Element("svg"));const correct=head(svg,"#aabbcc"),wrong=head(svg),pending=head(svg);
 const controller=createNotationInteraction(host as any,()=>[binding(0,correct.element),binding(1,wrong.element),binding(2,pending.element)],()=>{});controller.refresh();
 controller.setFeedback([{key:key(0),state:"correct"},{key:key(1),state:"wrong"},{key:key(2),state:"pending"}]);
 assert.equal(correct.path.getAttribute("fill"),"#22a447");assert.equal(wrong.path.getAttribute("fill"),"#dc2626");assert.equal(pending.path.getAttribute("fill"),"#d97706");
 controller.setSelection(key(1));assert.equal(wrong.path.getAttribute("fill"),"#2563eb");controller.setSelection(null);assert.equal(wrong.path.getAttribute("fill"),"#dc2626");
 controller.refresh();assert.equal(correct.path.getAttribute("fill"),"#22a447");controller.setFeedback([]);assert.equal(correct.path.getAttribute("fill"),"#aabbcc");assert.equal(wrong.path.getAttribute("fill"),"#000000");controller.dispose();
});

test("a physically shared glyph cannot silently choose one of two XML notes", () => {
  const host = new Element("div"); const shared = head(host); const selected: NoteKey[] = [];
  const controller = createNotationInteraction(host as any, () => [binding(0, shared.element), binding(1, shared.element)], (key) => selected.push(key));
  controller.refresh(); host.event("click", { target: shared.path });
  assert.deepEqual(selected, []); assert.equal(shared.element.getAttribute("data-notelite-note"), null); controller.dispose();
});

test("playhead spans both piano staves, moves across systems/pages, and clears separately from blue selection", () => {
  const host = new Element("div"); const firstPage = host.appendChild(new Element("svg")); const secondPage = host.appendChild(new Element("svg"));
  const first = head(firstPage, "#000000", 20, 50); const lower = head(firstPage, "#000000", 22, 150); const next = head(secondPage, "#000000", 100, 250);
  const system = (ranges: number[][]) => ({ StaffLines: ranges.map(([top, bottom]) => ({ Measures: [{ getVFStave: () => ({ getYForLine: (index: number) => index === 0 ? top : bottom, getNumLines: () => 5 }) }] })) });
  const piano = system([[40, 80], [140, 180]]); const later = system([[240, 280]]);
  const withSystem = (value: NoteBinding, system: object) => ({ ...value, graphical: { parentVoiceEntry: { parentStaffEntry: { parentMeasure: { ParentMusicSystem: system } } } } } as any);
  const controller = createNotationInteraction(host as any, () => [withSystem(binding(0, first.element), piano), withSystem(binding(1, lower.element), piano), withSystem(binding(2, next.element), later)], () => {});
  controller.refresh(); controller.setSelection(key(1)); controller.setPlayhead([key(0), key(1)]);
  assert.equal(firstPage.overlays().length, 1); const line = firstPage.overlays()[0].childNodes[0];
  assert.equal(line.getAttribute("y1"), "28"); assert.equal(line.getAttribute("y2"), "192"); assert.equal(line.getAttribute("stroke"), "#22a447");
  assert.equal(lower.path.getAttribute("fill"), "#2563eb"); controller.setPlayhead([key(2)]);
  assert.equal(firstPage.overlays().length, 0); assert.equal(secondPage.overlays().length, 1);
  controller.setPlayhead([]); assert.equal(host.overlays().length, 0); assert.equal(lower.path.getAttribute("fill"), "#2563eb"); controller.dispose();
});

test("prechecking a note duration rejects newly overflowing rhythm without mutating stored XML", () => {
  const xml = scoreXML(`<measure number="1">${attributesXML()}${noteXML().repeat(4)}</measure>`); const original = parseScoreXML(xml); const before = serialize(original);
  const edited = previewNoteEdits(original, [{ ...key(1), duration: 2 }]);
  const comparison = compareScoreRules(xml, serialize(edited));
  assert.equal(comparison.canSave, false); assert.equal(comparison.introduced.some((issue) => issue.code === "measure-overfull"), true);
  assert.equal(serialize(original), before);
  const pitchOnly = previewNoteEdits(original, [{ ...key(1), pitch: { step: "G", alter: 2, octave: 9 } }]);
  assert.equal(compareScoreRules(xml, serialize(pitchOnly)).canSave, true); // Deliberately no range/playability judgement.
});

test("new note type, dots, pitch alterations and render markers keep MusicXML child order", () => {
  const original = parseScoreXML(scoreXML(`<measure number="1">${attributesXML()}<note><grace/><chord/><rest/><voice>1</voice><stem>up</stem><staff>1</staff><beam number="1">begin</beam><notations/><lyric><text>la</text></lyric></note></measure>`));
  const edited = previewNoteEdits(original, [{ ...key(0), rest: false, pitch: { step: "C", alter: 1, octave: 4 }, type: "eighth", dot: 1 }]);
  const note = edited.getElementsByTagName("note")[0];
  const names = Array.from(note.childNodes).filter((child) => child.nodeType === 1).map((child) => (child as globalThis.Element).localName);
  assert.deepEqual(names, ["grace", "chord", "pitch", "voice", "type", "dot", "stem", "staff", "beam", "notations", "lyric"]);
  assert.deepEqual(Array.from(edited.getElementsByTagName("pitch")[0].childNodes).map((child) => (child as globalThis.Element).localName), ["step", "alter", "octave"]);
  const prepared = prepareNotation(edited);
  assert.deepEqual(Array.from(prepared.document.getElementsByTagName("note")[0].childNodes).filter((child) => child.nodeType === 1).map((child) => (child as globalThis.Element).localName), ["grace", "chord", "pitch", "voice", "type", "dot", "stem", "notehead", "staff", "beam", "notations", "lyric"]);
  assert.equal(original.getElementsByTagName("note")[0].getElementsByTagName("type").length, 0);
});
