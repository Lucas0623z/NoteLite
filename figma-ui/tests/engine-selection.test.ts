import test from "node:test";
import assert from "node:assert/strict";
import { attributesXML, noteXML, scoreXML } from "./xml-dom.ts";
import { preparePerformance, NoteWiseMatcher, type NoteWiseSettings } from "../src/app/notewise.ts";
import { selectPerformanceSources } from "../src/app/engine-selection.ts";

const settings: NoteWiseSettings = {inputKind:"microphone",mode:"follow",bpm:60,tuning:440,first:1,last:1,part:"全部声部",instrument:"auto"};
const measure = (notes = noteXML(), attrs = "") => `<measure number="1">${attributesXML(1,"4")}${attrs}${notes}</measure>`;
const named = (name:string, notes = noteXML(), attrs = "") => scoreXML(measure(notes,attrs)).replaceAll("Piano",name);
const longXML = () => scoreXML(Array.from({length:1000},(_,i)=>`<measure number="${i+1}">${i===0?attributesXML(1,"4"):""}${noteXML().repeat(4)}</measure>`).join("")).replaceAll("Piano","Violin");

test("automatic instrument metadata selects family without changing the written or sounding notes", () => {
  const violin = preparePerformance(named("Violin"), settings);
  assert.deepEqual(violin.plan.instrumentIds,["violin"]);
  assert.equal(violin.plan.primary,"native-mpm-yin");
  assert.equal(violin.plan.texture,"mono");
  assert.equal(violin.expected[0].midi,60);
  const piano=preparePerformance(named("Piano"),settings);
  assert.equal(piano.plan.texture,"poly");assert.equal(piano.plan.needsRecordedReview,true);
  const midi=preparePerformance(named("Violin"),{...settings,inputKind:"midi"});
  assert.equal(midi.plan.primary,"midi-stream");assert.equal(midi.plan.realtimePolyphonySupported,true);
});

test("unmarked transposing instrument requires confirmation and explicit MusicXML wins over a manual variant", () => {
  const concert=named("Clarinet").replace("<part-list>","<defaults><concert-score/></defaults><part-list>");
  assert.equal(preparePerformance(concert,{...settings,instrument:"clarinet",instrumentVariant:"bb"}).expected[0].midi,60);
  assert.equal(preparePerformance(concert,settings).expected[0].midi,60);
  assert.throws(()=>preparePerformance(named("Clarinet"),settings),/缺少移调信息/);
  const marked=named("Clarinet",noteXML(),"<attributes><transpose><chromatic>-2</chromatic></transpose></attributes>");
  const automatic=preparePerformance(marked,settings);
  assert.equal(automatic.expected[0].midi,58);assert.equal(automatic.expected[0].writtenMidi,60);
  const manual=preparePerformance(marked,{...settings,instrument:"clarinet",instrumentVariant:"a"});
  assert.equal(manual.expected[0].midi,58);
  assert.equal(preparePerformance(named("Clarinet"),{...settings,instrument:"clarinet",instrumentVariant:"bb"}).expected[0].midi,58);
  assert.throws(()=>preparePerformance(named("Clarinet"),{...settings,instrument:"clarinet",instrumentVariant:"gone"}),/谱制无效/);
});

test("unresolved or ambiguous note instrument references require an actual choice", () => {
  const multi=named("Part 1").replace("</score-part>",'<score-instrument id="P1-I2"><instrument-name>Flute</instrument-name></score-instrument></score-part>');
  assert.throws(()=>preparePerformance(multi,settings),/乐器信息不足/);
  const unknown=multi.replace("<note>",'<note><instrument id="gone"/>');
  assert.throws(()=>preparePerformance(unknown,settings),/乐器信息不足/);
  const resolved=multi.replace("<note>",'<note><instrument id="P1-I2"/>');
  assert.deepEqual(preparePerformance(resolved,settings).plan.instrumentIds,["flute"]);
  assert.deepEqual(preparePerformance(unknown,{...settings,instrument:"violin"}).plan.instrumentIds,["violin"]);
});

test("part selection by the displayed name isolates routing and actual simultaneous notes choose recorded polyphony", () => {
  const first=named("Violin");
  const meta='<score-part id="P2"><part-name>Piano</part-name><score-instrument id="P2-I1"><instrument-name>Piano</instrument-name></score-instrument></score-part>';
  const second=`<part id="P2">${measure(noteXML()+noteXML(1,"<chord/>","E"))}</part>`;
  const mixed=first.replace("</part-list>",meta+"</part-list>").replace("</score-partwise>",second+"</score-partwise>");
  assert.throws(()=>preparePerformance(mixed,settings),/多种乐器/);
  assert.deepEqual(preparePerformance(mixed,{...settings,part:"Violin"}).plan.instrumentIds,["violin"]);
  const chord=preparePerformance(named("Violin",noteXML()+noteXML(1,"<chord/>","E")),settings);
  assert.equal(chord.plan.texture,"poly");assert.equal(chord.plan.scorePitchUsedForDetection,false);
});

test("long score routes by unique instruments and keeps unconfirmed notation in the selected span", () => {
  const value=selectPerformanceSources(longXML(),{...settings,last:1000});
  assert.equal(value.notes.length,4000);assert.deepEqual(value.plan.instrumentIds,["violin"]);
  const partial=named("Clarinet",noteXML()).replace("</part>",`<measure number="2"><attributes><transpose><chromatic>-2</chromatic></transpose></attributes>${noteXML()}</measure></part>`);
  assert.throws(()=>preparePerformance(partial,{...settings,last:2}),/缺少移调信息/);
  assert.equal(preparePerformance(partial,{...settings,first:2,last:2}).expected[0].midi,58);
});

test("batch matching preserves caller order, releases and analysed status for 4000 actual events", () => {
  const expected=preparePerformance(longXML(),{...settings,last:1000,inputKind:"midi"}).expected;
  const reversed=[...expected].reverse(),original=structuredClone(reversed);
  const matcher=new NoteWiseMatcher(reversed,{...settings,inputKind:"midi",mode:"strict"},{takeId:"11111111-1111-4111-8111-111111111111",sourceScoreSha256:"a".repeat(64)});
  for(let i=0;i<expected.length;i++){
    matcher.accept({eventId:`n${i}`,type:"on",timeMs:100+i*1000,midi:60,confidence:1,timingConfidence:1});
    matcher.accept({eventId:`n${i}`,type:"off",timeMs:1100+i*1000,midi:60,confidence:1,timingConfidence:1,releaseReliable:true});
  }
  const result=matcher.finish(4000100);
  assert.deepEqual(reversed,original);assert.equal(result.status,"analysed");assert.equal(result.completed,true);
  assert.equal(result.coverageByDimension.pitch.evaluated,4000);assert.equal(result.coverageByDimension.duration.evaluated,4000);
  assert.equal(result.errors.length,0);
});
