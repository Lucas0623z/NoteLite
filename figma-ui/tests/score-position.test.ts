import test from "node:test";
import assert from "node:assert/strict";
import { attributesXML, noteXML, scoreXML } from "./xml-dom.ts";
import { createScoreTimeline, createPerformancePositionReceiver, positionAt, noteKey } from "../src/app/score-position.ts";

const measure = (body: string, attrs = "") => `<measure number="1" ${attrs}>${body}</measure>`;
const tempo = (bpm: number) => `<direction><sound tempo="${bpm}"/></direction>`;
test("real XML chord/voices share onset; rest is a cursor slot, not a sound", () => {
  const timeline = createScoreTimeline(scoreXML(measure(attributesXML(1, "2") + tempo(60) + noteXML() + noteXML(1, "<chord/>", "E") + `<note><rest/><duration>1</duration><voice>1</voice><type>quarter</type></note><backup><duration>2</duration></backup>` + noteXML(2, "", "G", "half"))));
  assert.equal(timeline.duration, 2);
  assert.deepEqual(timeline.notes.map(n => [n.start, n.end, n.midi]), [[0, 1, 60], [0, 1, 64], [0, 2, 67]]);
  assert.deepEqual(positionAt(timeline, .2).map(n => n.noteIndex), [0, 1, 3]);
  assert.deepEqual(positionAt(timeline, 1.2).map(n => n.noteIndex), [2]);
  assert.deepEqual(positionAt(timeline, 2), []);
});
test("dotted metronome, mid-measure tempo, and sounding transposition share cursor clock", () => {
  const xml = scoreXML(measure(attributesXML(2, "2") + `<attributes><transpose><chromatic>-2</chromatic></transpose></attributes><direction><direction-type><metronome><beat-unit>eighth</beat-unit><beat-unit-dot/><per-minute>80</per-minute></metronome></direction-type></direction>` + noteXML(2) + tempo(120) + noteXML(2, "", "D")));
  const timeline = createScoreTimeline(xml);
  assert.equal(timeline.initialTempo, 60); assert.equal(timeline.duration, 1.5);
  assert.deepEqual(timeline.notes.map(n => [n.start, n.end, n.midi]), [[0, 1, 58], [1, 1.5, 60]]);
  assert.equal(positionAt(timeline, 1)[0].noteIndex, 1);
});
test("ties sustain one sound but cursor advances across both written notes", () => {
  const timeline = createScoreTimeline(scoreXML(measure(attributesXML(1, "1") + tempo(60) + noteXML(1, `<tie type="start"/>`)) + measure(noteXML(1, `<tie type="stop"/>`))));
  assert.equal(timeline.notes.length, 1); assert.equal(timeline.notes[0].end, 2);
  assert.equal(positionAt(timeline, 1.2)[0].measureIndex, 1);
});
test("a piano tie can move between staves in the same voice without reattacking", () => {
  const timeline = createScoreTimeline(scoreXML(measure(attributesXML(1, "1") + tempo(60) + noteXML(1, `<tie type="start"/>`).replace("</note>", "<staff>1</staff></note>")) + measure(noteXML(1, `<tie type="stop"/>`).replace("</note>", "<staff>2</staff></note>"))));
  assert.equal(timeline.notes.length, 1); assert.equal(timeline.notes[0].end, 2);
  assert.equal(positionAt(timeline, 1.2)[0].measureIndex, 1);
  const independent = createScoreTimeline(scoreXML(measure(attributesXML(1, "1") + tempo(60) + noteXML(1, `<tie type="start"/>`)) + measure(noteXML(1, `<tie type="stop"/>`).replace("<voice>1</voice>", "<voice>2</voice>"))));
  assert.equal(independent.notes.length, 2);
});
test("first/implicit pickup and free meter avoid fabricated silent beats", () => {
  const pickup = createScoreTimeline(scoreXML(measure(attributesXML() + tempo(60) + noteXML()) + measure(noteXML(4, "", "D", "whole"))));
  assert.equal(pickup.duration, 5);
  const free = createScoreTimeline(scoreXML(measure(`<attributes><divisions>1</divisions><time><senza-misura/></time></attributes>${tempo(60)}${noteXML(8, "", "C", "breve")}`)));
  assert.equal(free.duration, 8);
});
test("repeat passes restore written tempo and reuse exact written IDs", () => {
  const timeline = createScoreTimeline(scoreXML(measure(attributesXML(1, "1") + tempo(60) + `<barline location="left"><repeat direction="forward"/></barline>` + noteXML()) + measure(tempo(120) + noteXML(1, "", "D") + `<barline><repeat direction="backward"/></barline>`)));
  assert.equal(timeline.duration, 3);
  assert.deepEqual(timeline.notes.map(n => [n.key.measureIndex, n.start, n.end]), [[0, 0, 1], [1, 1, 1.5], [0, 1.5, 2.5], [1, 2.5, 3]]);
  assert.equal(positionAt(timeline, 1.6)[0].measureIndex, 0);
});
test("numbered first and second endings play correct written order", () => {
  const timeline = createScoreTimeline(scoreXML(measure(attributesXML(1, "1") + tempo(60) + `<barline location="left"><repeat direction="forward"/></barline>` + noteXML()) + measure(`<barline location="left"><ending number="1" type="start"/></barline>${noteXML(1, "", "D")}<barline><ending number="1" type="stop"/><repeat direction="backward"/></barline>`) + measure(`<barline location="left"><ending number="2" type="start"/></barline>${noteXML(1, "", "E")}<barline><ending number="2" type="stop"/></barline>`)));
  assert.deepEqual(timeline.notes.map(n => n.key.measureIndex), [0, 1, 0, 2]);
});
test("a skipped first ending cannot leak its tempo into the second ending", () => {
  const timeline = createScoreTimeline(scoreXML(measure(attributesXML(1, "1") + tempo(60) + `<barline location="left"><repeat direction="forward"/></barline>` + noteXML()) + measure(`<barline location="left"><ending number="1" type="start"/></barline>${tempo(120)}${noteXML(1, "", "D")}<barline><ending number="1" type="stop"/><repeat direction="backward"/></barline>`) + measure(`<barline location="left"><ending number="2" type="start"/></barline>${noteXML(1, "", "E")}<barline><ending number="2" type="stop"/></barline>`)));
  assert.deepEqual(timeline.notes.map(n => [n.key.measureIndex, n.start, n.end]), [[0, 0, 1], [1, 1, 1.5], [0, 1.5, 2.5], [2, 2.5, 3.5]]);
});
test("a later sound offset retains the earlier printed tempo", () => {
  const timeline = createScoreTimeline(scoreXML(measure(attributesXML() + `<direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>80</per-minute></metronome></direction-type><sound tempo="120"><offset>2</offset></sound></direction>` + noteXML(4, "", "C", "whole"))));
  assert.equal(timeline.initialTempo, 80); assert.equal(timeline.duration, 2.5);
});
test("global tempo written on second part persists; conflicting parts fail explicitly", () => {
  const partA = `<part id="P1">${measure(attributesXML(1, "1") + noteXML())}${measure(noteXML())}</part>`;
  const partB = `<part id="P2">${measure(attributesXML(1, "1") + tempo(60) + noteXML())}${measure(noteXML())}</part>`;
  const timeline = createScoreTimeline(`<score-partwise>${partA}${partB}</score-partwise>`);
  assert.equal(timeline.duration, 2); assert.equal(timeline.initialTempo, 60);
  assert.throws(() => createScoreTimeline(`<score-partwise>${partA.replace(attributesXML(1, "1"), attributesXML(1, "1") + tempo(80))}${partB}</score-partwise>`), /声部速度不一致/);
});
test("unsafe XML rhythm and unsupported route refuse misleading playback", () => {
  assert.throws(() => createScoreTimeline(scoreXML(measure(attributesXML(1, "1") + noteXML(2)))), /超拍/);
  assert.throws(() => createScoreTimeline(scoreXML(measure(attributesXML() + `<backup><duration>1</duration></backup>` + noteXML()))), /起点/);
  assert.throws(() => createScoreTimeline(scoreXML(measure(attributesXML() + `<direction><sound dacapo="yes"/></direction>` + noteXML()))), /跳转/);
  assert.throws(() => createScoreTimeline(scoreXML(measure(attributesXML() + noteXML(0)))), /时值无效/);
});
test("performance receiver rejects wrong score, old sequence, malformed identity, and disposal", () => {
  const received: unknown[] = [], receiver = createPerformancePositionReceiver("job:0:r6", keys => received.push(keys));
  const event = { type: "performancePosition", scoreIdentity: "job:0:r6", sequence: 1, notes: [{ partId: "P1", measureIndex: 2, noteIndex: 3 }] };
  assert.equal(receiver.accept({ ...event, scoreIdentity: "job:0:r5" }), false);
  assert.equal(receiver.accept({ ...event, notes: [{ ...event.notes[0], noteIndex: -1 }] }), false);
  assert.equal(receiver.accept(event), true); assert.equal(receiver.accept(event), false);
  assert.equal(receiver.accept({ ...event, sequence: 2, notes: [] }), true);
  receiver.dispose(); assert.equal(receiver.accept({ ...event, sequence: 3 }), false);
  assert.deepEqual(received, [event.notes, [], []]);
});
test("actual performance positions cannot refer to notes absent from this score", () => {
  const key = { partId: "P1", measureIndex: 0, noteIndex: 0 }, receiver = createPerformancePositionReceiver("current", () => {}, new Set([noteKey(key)]));
  const event = { type: "performancePosition", scoreIdentity: "current", sequence: 1, notes: [key] };
  assert.equal(receiver.accept({ ...event, notes: [{ ...key, partId: "P2" }] }), false);
  assert.equal(receiver.accept({ ...event, notes: [{ ...key, measureIndex: 1 }] }), false);
  assert.equal(receiver.accept(event), true);
});
test("visual direction offset defaults to no sound shift; explicit sound offset takes precedence", () => {
  const xml = (offset: string, sound: string) => scoreXML(measure(attributesXML(1, "2") + `<direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>60</per-minute></metronome></direction-type>${offset}<sound tempo="60">${sound}</sound></direction>` + noteXML(2, "", "C", "half")));
  assert.equal(createScoreTimeline(xml("<offset>1</offset>", "")).duration, 2);
  assert.equal(createScoreTimeline(xml('<offset sound="yes">1</offset>', "")).duration, 1.5);
  assert.equal(createScoreTimeline(xml('<offset sound="yes">1</offset>', "<offset>0</offset>")).duration, 2);
});
