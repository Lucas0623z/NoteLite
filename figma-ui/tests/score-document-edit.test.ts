import test from "node:test";
import assert from "node:assert/strict";
import { editScoreDocument, readScoreDocument } from "../src/app/scoreDocumentEdit.ts";
import { checkScoreRules, compareScoreRules, directElements, firstElement, parseScoreXML, textOf } from "../src/app/scoreRules.ts";
import { attributesXML, noteXML, scoreXML } from "./xml-dom.ts";

const measure = (content: string, number = "1") => `<measure number="${number}">${content}</measure>`;
const base = () => scoreXML(measure(attributesXML() + noteXML().repeat(4)));
const serializeElements = (xml: string, name: string) => Array.from(parseScoreXML(xml).getElementsByTagName("*")).filter((element) => element.localName === name).map((element) => new XMLSerializer().serializeToString(element));

test("read exposes actual names, every staff, measure, clef, key, compound meter and tempo rather than inferred music", () => {
  const xml = scoreXML(measure(attributesXML(2, "3+2", 8) + `<attributes><staves>2</staves><key><fifths>2</fifths><mode>major</mode></key><clef number="2"><sign>F</sign><line>4</line></clef></attributes><direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>80</per-minute></metronome></direction-type><sound tempo="80"/></direction>` + noteXML(5)));
  const info = readScoreDocument(xml).parts[0];
  assert.deepEqual(info.staffNumbers, ["1", "2"]); assert.equal(info.name, "Piano"); assert.equal(info.instrumentName, "Piano");
  assert.equal(info.clefs[1].staff, "2"); assert.equal(info.clefs[1].attributesIndex, 1);
  assert.equal(info.keys[0].fifths, 2); assert.deepEqual(info.meters[0].groups, [{ beats: "3+2", beatType: 8 }]);
  assert.equal(info.tempos[0].perMinute, "80"); assert.equal(info.tempos[0].soundTempo, 80); assert.equal(info.tempos[0].editable, true);
});
test("part name and an explicitly chosen instrument name are separate; MIDI program and transposition are untouched", () => {
  const xml = base().replace("</score-part>", `<score-instrument id="P1-I2"><instrument-name>Flute</instrument-name></score-instrument><midi-instrument id="P1-I1"><midi-channel>1</midi-channel><midi-program>1</midi-program></midi-instrument></score-part>`).replace("</attributes>", `<transpose><diatonic>-1</diatonic><chromatic>-2</chromatic></transpose></attributes>`);
  const renamed = editScoreDocument(xml, { kind: "name", partId: "P1", partName: "钢琴 & 旋律", instrumentName: "长笛", instrumentId: "P1-I2" });
  const info = readScoreDocument(renamed).parts[0];
  assert.equal(info.name, "钢琴 & 旋律"); assert.deepEqual(info.instruments.map((instrument) => instrument.name), ["Piano", "长笛"]);
  for (const element of ["midi-instrument", "transpose", "note"]) assert.deepEqual(serializeElements(renamed, element), serializeElements(xml, element));
});
test("missing score-instrument can be added without inventing a MIDI program or colliding with existing IDs", () => {
  const xml = base().replace(/<score-instrument[\s\S]*?<\/score-instrument>/, "").replace("<note>", '<note id="P1-I1">');
  const edited = editScoreDocument(xml, { kind: "name", partId: "P1", instrumentName: "小提琴" });
  assert.equal(readScoreDocument(edited).parts[0].instruments[0].id, "P1-I2"); assert.equal(serializeElements(edited, "midi-program").length, 0);
});
test("part-name-display follows edited visible name while other part-list data is retained", () => {
  const xml = base().replace("</part-name>", "</part-name><part-name-display><display-text>Piano</display-text></part-name-display><part-abbreviation>Pno.</part-abbreviation>");
  const edited = editScoreDocument(xml, { kind: "name", partId: "P1", partName: "Violin" });
  assert.ok(edited.includes("<display-text>Violin</display-text>")); assert.ok(edited.includes("<part-abbreviation>Pno.</part-abbreviation>"));
});
test("staff-specific clef correction keeps the other staff, notes, tuplets and repeat markings", () => {
  const xml = base().replace("</attributes>", `<staves>2</staves><clef number="2"><sign>F</sign><line>4</line></clef></attributes>`).replace("</measure>", `<barline location="right"><repeat direction="backward"/></barline></measure>`).replace("</type>", "</type><time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes></time-modification>");
  const edited = editScoreDocument(xml, { kind: "clef", partId: "P1", measureIndex: 0, staff: "2", sign: "C", line: 3, octaveChange: -1 });
  const clefs = readScoreDocument(edited).parts[0].clefs;
  assert.equal(clefs[0].sign, "G"); assert.equal(clefs[1].sign, "C"); assert.equal(clefs[1].line, 3); assert.equal(clefs[1].octaveChange, -1);
  for (const name of ["note", "barline"]) assert.deepEqual(serializeElements(edited, name), serializeElements(xml, name));
});
test("precise attributesIndex edits a mid-measure change without overwriting the initial clef", () => {
  const xml = scoreXML(measure(attributesXML() + noteXML().repeat(2) + `<attributes><clef><sign>F</sign><line>4</line></clef></attributes>` + noteXML().repeat(2)));
  const edited = editScoreDocument(xml, { kind: "clef", partId: "P1", measureIndex: 0, attributesIndex: 1, staff: "1", sign: "C", line: 3 });
  assert.deepEqual(readScoreDocument(edited).parts[0].clefs.map((clef) => clef.sign), ["G", "C"]);
});
test("missing header attributes are created before music, with correct XML element order and namespace", () => {
  const xml = base().replace(/<attributes>[\s\S]*?<\/attributes>/, "").replace(/<(\/?)([\w-]+)([^>]*?)>/g, '<$1m:$2$3>').replace('<m:score-partwise ', '<m:score-partwise xmlns:m="urn:musicxml" ');
  let edited = editScoreDocument(xml, { kind: "clef", partId: "P1", measureIndex: 0, staff: "1", sign: "G", line: 2 });
  edited = editScoreDocument(edited, { kind: "meter", partId: "P1", measureIndex: 0, groups: [{ beats: "4", beatType: 4 }] });
  edited = editScoreDocument(edited, { kind: "key", partId: "P1", measureIndex: 0, fifths: 2, mode: "major" });
  const document = parseScoreXML(edited), part = firstElement(document.documentElement, "part")!, bar = firstElement(part, "measure")!;
  assert.equal(directElements(bar)[0].localName, "attributes"); assert.deepEqual(directElements(directElements(bar)[0]).map((element) => element.localName), ["key", "time", "clef"]);
  assert.ok(Array.from(document.getElementsByTagName("*")).every((element) => element.namespaceURI === "urn:musicxml"));
});
test("traditional key boundaries -7..7 are editable without transposing actual note pitches", () => {
  const xml = base();
  for (const fifths of [-7, 0, 7]) {
    const edited = editScoreDocument(xml, { kind: "key", partId: "P1", measureIndex: 0, fifths, mode: "minor" });
    assert.equal(readScoreDocument(edited).parts[0].keys[0].fifths, fifths); assert.deepEqual(serializeElements(edited, "note"), serializeElements(xml, "note"));
  }
  assert.throws(() => editScoreDocument(xml, { kind: "key", partId: "P1", measureIndex: 0, fifths: 8 }), /调号/);
});
test("changing 4/4 to additive 3+2/8 changes only meter and reports the newly overfull original notes", () => {
  const xml = base(); const edited = editScoreDocument(xml, { kind: "meter", partId: "P1", measureIndex: 0, groups: [{ beats: "3+2", beatType: 8 }] });
  assert.deepEqual(serializeElements(edited, "note"), serializeElements(xml, "note"));
  assert.equal(compareScoreRules(xml, edited).canSave, false);
  assert.equal(checkScoreRules(edited).measureSpans[0].expectedByStaff["1"], 2.5);
});
test("mixed-denominator meter and staff-local signatures preserve the other staff and intermediary metadata", () => {
  const xml = base().replace("<time>", '<time symbol="common" color="#123456">');
  const edited = editScoreDocument(xml, { kind: "meter", partId: "P1", measureIndex: 0, staff: "2", groups: [{ beats: "2", beatType: 4 }, { beats: "3", beatType: 8 }] });
  assert.deepEqual(readScoreDocument(edited).parts[0].meters.map((meter) => [meter.staff, meter.groups]), [[null, [{ beats: "4", beatType: 4 }]], ["2", [{ beats: "2", beatType: 4 }, { beats: "3", beatType: 8 }]]]);
  const common = editScoreDocument(xml, { kind: "meter", partId: "P1", measureIndex: 0, groups: [{ beats: "3", beatType: 4 }] });
  assert.ok(common.includes('color="#123456"')); assert.ok(!common.includes('symbol="common"'));
});

test("all-staff key edits replace same-position overrides, preserving their styling and later changes", () => {
  const overrides = '<key><fifths>0</fifths></key><key number="2" color="#123456"><fifths>-1</fifths><mode>minor</mode></key><staves>2</staves>';
  const later = '<attributes><key number="2"><fifths>-3</fifths></key></attributes>';
  const xml = base().replace("</divisions>", "</divisions>" + overrides).replace("</measure>", later + "</measure>");
  const edited = editScoreDocument(xml, { kind: "key", partId: "P1", measureIndex: 0, staff: null, fifths: 2, mode: "major" });
  assert.deepEqual(readScoreDocument(edited).parts[0].keys.map((entry) => [entry.attributesIndex, entry.staff, entry.fifths, entry.mode]), [[0, null, 2, "major"], [0, "2", 2, "major"], [1, "2", -3, ""]]);
  assert.ok(edited.includes('color="#123456"'));
  assert.deepEqual(serializeElements(edited, "note"), serializeElements(xml, "note"));
});

test("all-staff meter edits enforce the chosen meter on both actual staffs, while preserving later overrides", () => {
  const extra = '<time number="2" color="#654321"><beats>3</beats><beat-type>4</beat-type></time><staves>2</staves>';
  const staff2 = noteXML(3).replace("<voice>1</voice>", "<voice>2</voice>").replace("</note>", "<staff>2</staff></note>");
  const first = measure(attributesXML().replace("</time>", "</time>" + extra) + noteXML(4, "", "C", "whole") + "<backup><duration>4</duration></backup>" + staff2);
  const second = measure('<attributes><time number="2"><beats>3</beats><beat-type>4</beat-type></time></attributes>' + noteXML(4, "", "C", "whole") + "<backup><duration>4</duration></backup>" + staff2, "2");
  const xml = scoreXML(first + second);
  const edited = editScoreDocument(xml, { kind: "meter", partId: "P1", measureIndex: 0, staff: null, groups: [{ beats: "5", beatType: 4 }] });
  const spans = checkScoreRules(edited).measureSpans;
  assert.deepEqual(spans.map((span) => span.expectedByStaff), [{ "1": 5, "2": 5 }, { "1": 5, "2": 3 }]);
  assert.ok(edited.includes('color="#654321"'));
  assert.equal(compareScoreRules(xml, edited).canSave, true);
  assert.deepEqual(serializeElements(edited, "note"), serializeElements(xml, "note"));
});

test("all-staff edits also work without an existing common signature and retain other attribute blocks", () => {
  const xml = base().replace("<time>", '<time number="2">').replace("</divisions>", '</divisions><key number="2"><fifths>-1</fifths></key><staves>2</staves>');
  const edited = editScoreDocument(editScoreDocument(xml, { kind: "key", partId: "P1", measureIndex: 0, fifths: 3 }), { kind: "meter", partId: "P1", measureIndex: 0, groups: [{ beats: "4", beatType: 4 }] });
  const info = readScoreDocument(edited).parts[0];
  assert.equal(info.keys.length, 2); assert.ok(info.keys.every((entry) => entry.fifths === 3));
  assert.equal(info.meters.length, 2); assert.ok(info.meters.every((entry) => entry.beats === "4"));
});

test("all-staff edits reject a nontraditional numbered key rather than partially changing the common key", () => {
  const xml = base().replace("</divisions>", '</divisions><key><fifths>0</fifths></key><key number="2"><key-step>C</key-step><key-alter>0.5</key-alter></key>');
  assert.throws(() => editScoreDocument(xml, { kind: "key", partId: "P1", measureIndex: 0, fifths: 2 }), /非传统/);
  assert.ok(xml.includes("<fifths>0</fifths>"));
});
test("tempo editing synchronizes dotted printed unit, quarter-note MIDI sound, and separate leading sound", () => {
  const xml = base().replace("</attributes>", `</attributes><direction placement="above"><direction-type><words>Allegretto</words></direction-type><direction-type><metronome parentheses="yes"><beat-unit>quarter</beat-unit><per-minute>80</per-minute></metronome></direction-type><sound tempo="80" dynamics="70"/></direction><sound tempo="80" pizzicato="yes"/>`);
  const edited = editScoreDocument(xml, { kind: "tempo", partId: "P1", measureIndex: 0, directionIndex: 0, metronomeIndex: 0, beatUnit: "quarter", dots: 1, perMinute: 80 });
  const info = readScoreDocument(edited).parts[0].tempos[0];
  assert.equal(info.dots, 1); assert.equal(info.perMinute, "80"); assert.equal(info.soundTempo, 120);
  assert.equal(serializeElements(edited, "sound").every((sound) => sound.includes('tempo="120"')), true);
  assert.ok(edited.includes("<words>Allegretto</words>")); assert.ok(edited.includes('dynamics="70"')); assert.ok(edited.includes('pizzicato="yes"')); assert.ok(edited.includes('parentheses="yes"'));
  assert.equal(checkScoreRules(edited).errors.length, 0); assert.deepEqual(serializeElements(edited, "note"), serializeElements(xml, "note"));
});
test("creating a missing initial tempo leaves later tempo changes and offsets untouched", () => {
  const later = `<direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>120</per-minute></metronome></direction-type><offset>0</offset><sound tempo="120"/></direction>`;
  const xml = scoreXML(measure(attributesXML() + noteXML().repeat(2) + later + noteXML().repeat(2)));
  const edited = editScoreDocument(xml, { kind: "tempo", partId: "P1", measureIndex: 0, beatUnit: "eighth", dots: 0, perMinute: 160 });
  const tempos = readScoreDocument(edited).parts[0].tempos;
  assert.deepEqual(tempos.map((tempo) => [tempo.perMinute, tempo.soundTempo]), [["160", 80], ["120", 120]]);
  assert.equal(serializeElements(edited, "direction")[1], later);
});
test("separate leading sound with a future offset is retained rather than overwritten by a header tempo", () => {
  const later = `<sound tempo="120"><offset>2</offset></sound>`;
  const xml = base().replace("</attributes>", "</attributes>" + later);
  const edited = editScoreDocument(xml, { kind: "tempo", partId: "P1", measureIndex: 0, beatUnit: "quarter", dots: 0, perMinute: 80 });
  assert.ok(serializeElements(edited, "sound").includes(later));
});
test("tempo relation/swing and nontraditional key are explicit unsupported edits, never silently erased", () => {
  const relationship = `<direction><direction-type><metronome><beat-unit>quarter</beat-unit><beat-unit>eighth</beat-unit></metronome></direction-type></direction>`;
  const xml = base().replace("</attributes>", "</attributes>" + relationship);
  assert.equal(readScoreDocument(xml).parts[0].tempos[0].editable, false);
  assert.throws(() => editScoreDocument(xml, { kind: "tempo", partId: "P1", measureIndex: 0, directionIndex: 0, beatUnit: "quarter", dots: 0, perMinute: 80 }), /复杂节拍/);
  const unusual = base().replace("</divisions>", "</divisions><key><key-step>C</key-step><key-alter>0.5</key-alter></key>");
  assert.throws(() => editScoreDocument(unusual, { kind: "key", partId: "P1", measureIndex: 0, fifths: 2 }), /非传统/);
});
test("creating a new numerical tempo preserves an existing complex metric relationship", () => {
  const relation = `<direction><direction-type><metronome><beat-unit>quarter</beat-unit><beat-unit>eighth</beat-unit></metronome></direction-type></direction>`;
  const xml = base().replace("</attributes>", "</attributes>" + relation);
  const edited = editScoreDocument(xml, { kind: "tempo", partId: "P1", measureIndex: 0, createNew: true, beatUnit: "quarter", dots: 0, perMinute: 80 });
  assert.ok(serializeElements(edited, "direction").includes(relation));
  assert.equal(readScoreDocument(edited).parts[0].tempos.length, 2);
  assert.equal(checkScoreRules(edited).errors.length, 0);
});
test("a global tempo edit synchronizes equal quarter BPM across parts while preserving each printed unit and later speeds", () => {
  const direction = (unit: string, perMinute: number, soundTempo: number, dots = "") => `<direction><direction-type><metronome><beat-unit>${unit}</beat-unit>${dots}<per-minute>${perMinute}</per-minute></metronome></direction-type><sound tempo="${soundTempo}"/></direction>`;
  const p1 = measure(attributesXML() + direction("quarter", 80, 80) + noteXML().repeat(4));
  const p2 = measure(attributesXML() + direction("half", 40, 80) + noteXML().repeat(2) + direction("quarter", 100, 100) + noteXML().repeat(2));
  const xml = `<score-partwise><part-list><score-part id="P1"><part-name>Piano</part-name></score-part><score-part id="P2"><part-name>Violin</part-name></score-part></part-list><part id="P1">${p1}</part><part id="P2">${p2}</part></score-partwise>`;
  const edited = editScoreDocument(xml, { kind: "tempo", partId: "P1", measureIndex: 0, directionIndex: 0, beatUnit: "quarter", dots: 1, perMinute: 80 });
  const parts = readScoreDocument(edited).parts;
  assert.deepEqual(parts[0].tempos.map((tempo) => [tempo.beatUnit, tempo.dots, tempo.perMinute, tempo.soundTempo]), [["quarter", 1, "80", 120]]);
  assert.deepEqual(parts[1].tempos.map((tempo) => [tempo.beatUnit, tempo.dots, tempo.perMinute, tempo.soundTempo]), [["half", 0, "60", 120], ["quarter", 0, "100", 100]]);
  assert.equal(checkScoreRules(edited).errors.length, 0);
  assert.deepEqual(serializeElements(edited, "note"), serializeElements(xml, "note"));
});
test("conflicting preexisting playback/visible/part tempos require explicit XML correction rather than silently choosing one", () => {
  const mark = `<direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>80</per-minute></metronome></direction-type><sound tempo="100"/></direction>`;
  const xml = base().replace("</attributes>", "</attributes>" + mark);
  assert.throws(() => editScoreDocument(xml, { kind: "tempo", partId: "P1", measureIndex: 0, directionIndex: 0, beatUnit: "quarter", dots: 0, perMinute: 120 }), /冲突/);
});
test("Audiveris text per-minute such as 80env. remains visible and can be explicitly corrected to a number", () => {
  const mark = `<direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>80env.</per-minute></metronome></direction-type><sound tempo="80"/></direction>`;
  const xml = base().replace("</attributes>", "</attributes>" + mark);
  const before = readScoreDocument(xml).parts[0].tempos[0];
  assert.equal(before.perMinute, "80env."); assert.equal(before.editable, true);
  const edited = editScoreDocument(xml, { kind: "tempo", partId: "P1", measureIndex: 0, directionIndex: 0, beatUnit: "quarter", dots: 0, perMinute: 90 });
  const after = readScoreDocument(edited).parts[0].tempos[0];
  assert.equal(after.perMinute, "90"); assert.equal(after.soundTempo, 90);
  assert.equal(checkScoreRules(edited).errors.length, 0);
});
test("a numerical mark with visual offset creates matching sound offset without deleting a separate earlier sound", () => {
  const mark = `<direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>80</per-minute></metronome></direction-type><offset>2</offset><sound tempo="100"/></direction>`;
  const xml = base().replace("</attributes>", "</attributes>" + mark);
  const edited = editScoreDocument(xml, { kind: "tempo", partId: "P1", measureIndex: 0, directionIndex: 0, beatUnit: "quarter", dots: 0, perMinute: 120 });
  const sounds = serializeElements(edited, "sound");
  assert.ok(sounds.includes('<sound tempo="100"/>'));
  assert.ok(sounds.includes('<sound tempo="120"><offset>2</offset></sound>'));
});
test("invalid values and stale part/measure/field addresses fail before returning modified XML", () => {
  const xml = base();
  assert.throws(() => editScoreDocument(xml, { kind: "name", partId: "P1", partName: "" }), /名称/);
  assert.throws(() => editScoreDocument(xml, { kind: "name", partId: "missing", partName: "A" }), /声部/);
  assert.throws(() => editScoreDocument(xml, { kind: "clef", partId: "P1", measureIndex: 2, staff: "1", sign: "G", line: 2 }), /小节/);
  assert.throws(() => editScoreDocument(xml, { kind: "clef", partId: "P1", measureIndex: 0, attributesIndex: 3, staff: "1", sign: "G", line: 2 }), /记谱信息/);
  assert.throws(() => editScoreDocument(xml, { kind: "clef", partId: "P1", measureIndex: 0, staff: "1", sign: "G", line: 8 }), /线位/);
  assert.throws(() => editScoreDocument(xml, { kind: "meter", partId: "P1", measureIndex: 0, groups: [{ beats: "0", beatType: 4 }] }), /拍号/);
  assert.throws(() => editScoreDocument(xml, { kind: "tempo", partId: "P1", measureIndex: 0, beatUnit: "quarter", dots: 0, perMinute: 0 }), /速度/);
  assert.equal(textOf(firstElement(firstElement(parseScoreXML(xml).documentElement, "part-list")!, "score-part")!, "part-name"), "Piano");
});
