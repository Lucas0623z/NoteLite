import test from "node:test";
import assert from "node:assert/strict";
import { checkScoreRules, compareScoreRules } from "../src/app/scoreRules.ts";
import { attributesXML, noteXML, scoreXML } from "./xml-dom.ts";

const measure = (content: string, number = "1", extra = "") => `<measure number="${number}" ${extra}>${content}</measure>`;
const codes = (xml: string) => checkScoreRules(xml).issues.map((issue) => issue.code);

test("four quarter notes exactly fill 4/4; inherited divisions and meter continue to later measures", () => {
  const xml = scoreXML(measure(attributesXML() + noteXML().repeat(4)) + measure(noteXML().repeat(4), "2"));
  const result = checkScoreRules(xml);
  assert.equal(result.structuralValid, true); assert.deepEqual(result.issues, []);
  assert.deepEqual(result.measureSpans.map((span) => span.actual), [4, 4]);
});
test("chords and parallel piano voices use the XML cursor, never the sum of durations", () => {
  const xml = scoreXML(measure(attributesXML() + `<attributes><staves>2</staves></attributes>` + noteXML(4, "", "C", "whole") + noteXML(4, "<chord/>", "E", "whole") + `<backup><duration>4</duration></backup>` + noteXML(4, "", "G", "whole").replace("<voice>1</voice>", "<voice>2</voice><staff>2</staff>")));
  const result = checkScoreRules(xml);
  assert.deepEqual(result.issues, []); assert.equal(result.measureSpans[0].actual, 4);
  assert.deepEqual(result.measureSpans[0].voices.map((span) => [span.voice, span.staff, span.covered]), [["1", "1", 4], ["2", "2", 4]]);
});
test("cross-staff chords share their base note onset and can have shorter stops", () => {
  const base = noteXML(4, "", "C", "whole");
  const tone = noteXML(2, "<chord/>", "E", "half").replace("</type>", "</type><staff>2</staff>");
  const result = checkScoreRules(scoreXML(measure(attributesXML() + base + tone)));
  assert.equal(result.errors.length, 0);
  assert.equal(result.measureSpans[0].voices.find((voice) => voice.staff === "2")?.start, 0);
});
test("a partial second voice with forward positioning is valid, without requiring every voice to fill the bar", () => {
  const second = `<forward><duration>2</duration></forward>` + noteXML(1, "", "G").replace("<voice>1</voice>", "<voice>2</voice>") + `<forward><duration>1</duration></forward>`;
  const xml = scoreXML(measure(attributesXML() + noteXML(4, "", "C", "whole") + `<backup><duration>4</duration></backup>` + second));
  const result = checkScoreRules(xml);
  assert.deepEqual(result.issues, []);
  assert.deepEqual(result.measureSpans[0].voices.find((voice) => voice.voice === "2"), { voice: "2", staff: "1", start: 2, end: 3, covered: 1 });
});
test("tuplets use actual duration/divisions and check printed values with time-modification once", () => {
  const triplet = noteXML(1, "", "C", "eighth").replace("</type>", "</type><time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes></time-modification>");
  const xml = scoreXML(measure(attributesXML(3, "1") + triplet.repeat(3)));
  assert.deepEqual(checkScoreRules(xml).issues, []);
  assert.equal(checkScoreRules(xml).measureSpans[0].actual, 1);
});
test("grace notes consume no beats, while illegal grace durations are detected", () => {
  const grace = `<note><grace/><pitch><step>D</step><octave>4</octave></pitch><type>eighth</type></note>`;
  const xml = scoreXML(measure(attributesXML() + grace + noteXML(4, "", "C", "whole")));
  assert.deepEqual(checkScoreRules(xml).issues, []);
  assert.ok(codes(xml.replace("<type>eighth</type>", "<duration>1</duration><type>eighth</type>")).includes("grace-duration"));
});
test("implicit pickup and repeat fragments may be short; ordinary underfull measures require review only", () => {
  const pickup = scoreXML(measure(attributesXML() + noteXML(), "0", 'implicit="yes"'));
  assert.deepEqual(checkScoreRules(pickup).issues, []);
  const ordinary = pickup.replace('implicit="yes"', "");
  const result = compareScoreRules(pickup, ordinary);
  assert.equal(result.canSave, true); assert.equal(result.requiresReview, true);
  assert.equal(result.introduced[0].code, "measure-underfull");
});
test("full-measure rest in 3/4 is three intended beats rather than a literal whole note", () => {
  const rest = `<note><rest measure="yes"/><duration>3</duration><type>whole</type></note>`;
  assert.deepEqual(checkScoreRules(scoreXML(measure(attributesXML(1, "3") + rest))).issues, []);
});
test("additive and mixed-denominator compound meters are summed correctly", () => {
  const additive = scoreXML(measure(attributesXML(2, "3+2", 8) + noteXML(5, "", "C", "quarter")));
  assert.equal(checkScoreRules(additive).measureSpans[0].expectedByStaff["1"], 2.5);
  assert.equal(checkScoreRules(additive).errors.length, 0);
  const mixed = additive.replace("<beats>3+2</beats><beat-type>8</beat-type>", "<beats>2</beats><beat-type>4</beat-type><beats>3</beats><beat-type>8</beat-type>").replace("<duration>5</duration>", "<duration>7</duration>");
  assert.equal(checkScoreRules(mixed).measureSpans[0].expectedByStaff["1"], 3.5);
  assert.equal(checkScoreRules(mixed).errors.length, 0);
});
test("parts inherit divisions independently and staff-specific meters override common meters", () => {
  const xml = `<score-partwise><part-list><score-part id="P1"><part-name>A</part-name></score-part><score-part id="P2"><part-name>B</part-name></score-part></part-list><part id="P1">${measure(attributesXML(2) + noteXML(8, "", "C", "whole"))}</part><part id="P2">${measure(attributesXML(3) + `<attributes><time number="2"><beats>3</beats><beat-type>4</beat-type></time></attributes>` + noteXML(12, "", "C", "whole") + `<backup><duration>12</duration></backup>` + noteXML(9, "", "E", "half").replace("</type>", "</type><staff>2</staff>"))}</part></score-partwise>`;
  const result = checkScoreRules(xml);
  assert.equal(result.errors.length, 0);
  assert.deepEqual(result.measureSpans.map((span) => span.actual), [4, 4]);
  assert.equal(result.measureSpans[1].expectedByStaff["2"], 3);
});
test("divisions changes at measure boundaries and within forward score order remain exact", () => {
  const xml = scoreXML(measure(attributesXML() + noteXML().repeat(2) + `<attributes><divisions>2</divisions></attributes>` + noteXML(2).repeat(2)) + measure(noteXML(2).repeat(4), "2"));
  assert.deepEqual(checkScoreRules(xml).issues, []);
  const crossed = xml.replace(`<note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type></note></measure>`, `<note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type></note><backup><duration>6</duration></backup></measure>`);
  assert.ok(codes(crossed).includes("movement-across-divisions"));
});
test("new overfull measures, overlapping same voice, orphan chords and backward boundary crossing block saves", () => {
  const valid = scoreXML(measure(attributesXML() + noteXML().repeat(4)));
  for (const changed of [valid.replace("<duration>1</duration>", "<duration>2</duration>"), valid.replace("</measure>", "<backup><duration>5</duration></backup></measure>"), valid.replace("<pitch>", "<chord/><pitch>"), valid.replace("</measure>", "<backup><duration>4</duration></backup>" + noteXML() + "</measure>")]) {
    assert.equal(compareScoreRules(valid, changed).canSave, false);
  }
});
test("zero/negative/nonfinite duration, divisions and malformed tuplet/meter are explicit errors", () => {
  const valid = scoreXML(measure(attributesXML() + noteXML().repeat(4)));
  for (const duration of ["0", "-1", "NaN", "Infinity", ""]) assert.equal(compareScoreRules(valid, valid.replace("<duration>1</duration>", `<duration>${duration}</duration>`)).canSave, false);
  assert.ok(codes(valid.replace("<divisions>1</divisions>", "<divisions>0</divisions>")).includes("invalid-divisions"));
  assert.ok(codes(valid.replace("<beats>4</beats>", "<beats>3++2</beats>")).includes("invalid-meter"));
  assert.ok(codes(valid.replace("</type>", "</type><time-modification><actual-notes>0</actual-notes><normal-notes>2</normal-notes></time-modification>")).includes("invalid-tuplet"));
});
test("old OMR defects are visible separately, improvements save, worsening the same defect is new", () => {
  const before = scoreXML(measure(attributesXML() + noteXML(5, "", "C", "whole")));
  const pitchOnly = before.replace("<step>C</step>", "<step>D</step>");
  const same = compareScoreRules(before, pitchOnly);
  assert.equal(same.canSave, true); assert.equal(same.introduced.length, 0); assert.ok(same.preexisting.some((issue) => issue.code === "measure-overfull"));
  const improved = compareScoreRules(before, before.replace("<duration>5</duration>", "<duration>4.5</duration>"));
  assert.equal(improved.canSave, true);
  const worse = compareScoreRules(before, before.replace("<duration>5</duration>", "<duration>6</duration>"));
  assert.equal(worse.canSave, false); assert.ok(worse.introduced.some((issue) => issue.code === "measure-overfull"));
  const fixed = compareScoreRules(before, before.replace("<duration>5</duration>", "<duration>4</duration>"));
  assert.ok(fixed.resolved.some((issue) => issue.code === "measure-overfull"));
});
test("empty measures, missing meter and senza-misura do not invent a four-quarter bar or fill rests", () => {
  const empty = scoreXML(measure("")); assert.deepEqual(codes(empty), ["empty-measure"]);
  const unmetered = scoreXML(measure(`<attributes><divisions>1</divisions></attributes>` + noteXML()));
  assert.ok(codes(unmetered).includes("missing-meter")); assert.equal(checkScoreRules(unmetered).errors.length, 0);
  const senza = unmetered.replace("</divisions>", "</divisions><time><senza-misura/></time>");
  assert.deepEqual(checkScoreRules(senza).issues, []);
});
test("namespace-prefixed MusicXML and public doctype work; malformed XML/entities/timewise cannot save", () => {
  const xml = scoreXML(measure(attributesXML() + noteXML().repeat(4)));
  const prefixed = xml.replace(/<(\/?)([\w-]+)([^>]*?)>/g, '<$1m:$2$3>').replace('<m:score-partwise ', '<m:score-partwise xmlns:m="urn:musicxml" ');
  assert.deepEqual(checkScoreRules(prefixed).issues, []);
  assert.deepEqual(checkScoreRules('<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">' + xml).issues, []);
  for (const bad of ["<score-partwise>", xml + "<extra/>", xml.replace("<score-partwise", "<score-timewise").replace("</score-partwise>", "</score-timewise>"), '<!DOCTYPE score-partwise [<!ENTITY evil "bad">]>' + xml]) assert.equal(compareScoreRules(xml, bad).canSave, false);
});
test("dotted metronome converts to quarter tempo; contradictory visible and MIDI tempo is an error", () => {
  const direction = `<direction><direction-type><metronome><beat-unit>quarter</beat-unit><beat-unit-dot/><per-minute>80</per-minute></metronome></direction-type><sound tempo="120"/></direction>`;
  const xml = scoreXML(measure(attributesXML() + direction + noteXML().repeat(4)));
  assert.deepEqual(checkScoreRules(xml).issues, []);
  assert.equal(compareScoreRules(xml, xml.replace('tempo="120"', 'tempo="80"')).canSave, false);
});
test("deleting an earlier note does not invent the later note's preexisting OMR duration error", () => {
  const badNote = noteXML().replace("<duration>1</duration>", "<duration>0</duration>");
  const before = scoreXML(measure(attributesXML() + noteXML() + badNote + noteXML().repeat(2)));
  const after = before.replace(noteXML(), "");
  const result = compareScoreRules(before, after);
  assert.equal(result.canSave, true);
  assert.ok(result.preexisting.some((issue) => issue.code === "invalid-duration" && issue.noteIndex === 0));
  assert.ok(!result.introduced.some((issue) => issue.code === "invalid-duration"));
});
test("offset playback changes are not mistaken for the visual mark, and tempo zero requires review", () => {
  const direction = `<direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>80</per-minute></metronome></direction-type><sound tempo="120"><offset>2</offset></sound></direction>`;
  const xml = scoreXML(measure(attributesXML() + direction + noteXML().repeat(4)));
  assert.deepEqual(checkScoreRules(xml).issues, []);
  const zero = xml.replace('tempo="120"', 'tempo="0"');
  assert.equal(checkScoreRules(zero).errors.length, 0); assert.ok(codes(zero).includes("unspecified-tempo"));
});
test("a same-position tempo disagreement between parts is a new global rule error", () => {
  const mark = (bpm: number) => `<direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>${bpm}</per-minute></metronome></direction-type><sound tempo="${bpm}"/></direction>`;
  const xml = `<score-partwise><part id="P1">${measure(attributesXML() + mark(80) + noteXML().repeat(4))}</part><part id="P2">${measure(attributesXML() + mark(80) + noteXML().repeat(4))}</part></score-partwise>`;
  assert.equal(checkScoreRules(xml).errors.length, 0);
  const conflicting = xml.replace('<part id="P2">', '<part id="P2">').replace(mark(80) + noteXML().repeat(4) + "</measure></part></score-partwise>", mark(100) + noteXML().repeat(4) + "</measure></part></score-partwise>");
  const comparison = compareScoreRules(xml, conflicting);
  assert.equal(comparison.canSave, false); assert.ok(comparison.introduced.some((issue) => issue.code === "tempo-conflict"));
});
