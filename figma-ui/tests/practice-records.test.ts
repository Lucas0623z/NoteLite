import test from "node:test";
import assert from "node:assert/strict";
import { PracticeRecords, type PracticeRecord } from "../src/app/practice-records.ts";
import {NoteWiseMatcher,expectedPerformance} from "../src/app/notewise.ts";
import {scoreXML,noteXML,attributesXML} from "./xml-dom.ts";
const alice = "11111111-1111-4111-8111-111111111111", bob = "22222222-2222-4222-8222-222222222222";
const input = { eventId: "33333333-3333-4333-8333-333333333333", name: "自编练习", musicxml: "<score-partwise/>", scoreIdentity: "local:sample", sourceKind: "local" as const, mode: "free" as const, durationSeconds: 12, startedAt: "2026-10-11T10:00:00Z", endedAt: "2026-10-11T10:00:12Z" };
function fixture(owner: string | null = alice) {
  const records = new Map<string, PracticeRecord>(), historyCalls: unknown[] = [], scoreCalls: unknown[] = [];
  const store = { put: async (record: PracticeRecord) => { records.set(record.eventId, structuredClone(record)); }, getAll: async () => Array.from(records.values()).map((record) => structuredClone(record)) };
  const client = { current: owner ? { userId: owner } : null, createScore: async (...args: unknown[]) => { scoreCalls.push(args); return { id: alice, revision: 1 }; }, addHistory: async (event: unknown) => { historyCalls.push(event); return { event: { ...event as object, analysis: { status: "unanalysed", source: "none", errors: null, verifiedByServer: false } } }; }, history: async () => ({ events: [], nextCursor: null }) };
  const repository = new PracticeRecords(store, client as never, () => {});
  return { records, historyCalls, scoreCalls, store, client, repository };
}
test("practice survives repository reload, stays unanalysed, and keeps the performed XML snapshot", async () => {
  const f = fixture(); const record = await f.repository.save(input);
  assert.equal(f.records.get(input.eventId)?.sync, "pending");
  await f.repository.sync(record);
  const reopened = new PracticeRecords(f.store, f.client as never, () => {}), [saved] = await reopened.local();
  assert.equal(saved.musicxml, input.musicxml); assert.equal(saved.durationSeconds, 12); assert.equal(saved.sync, "synced"); assert.equal(saved.analysis?.errors, null);
  assert.equal(f.historyCalls.length, 1);
});
test("guest and a different account's queued practice never auto-upload or appear in the next account", async () => {
  const f = fixture(null); const guest = await f.repository.save(input); await f.repository.sync(guest);
  f.client.current = { userId: alice }; assert.deepEqual(await f.repository.local(), []); assert.equal(f.historyCalls.length, 0);
  const owned = await f.repository.save({ ...input, eventId: bob }); f.client.current = { userId: bob };
  await f.repository.sync(owned); assert.equal(f.scoreCalls.length, 0); assert.deepEqual(await f.repository.local(), []);
});
test("a lost history response stays pending, retries the same event and does not recreate its score", async () => {
  const f = fixture(); let fail = true;
  f.client.addHistory = async (event: unknown) => { f.historyCalls.push(event); if (fail) throw new Error("response lost"); return { event: event as never }; };
  const pending = await f.repository.sync(await f.repository.save(input)); assert.equal(pending.sync, "pending"); assert.ok(pending.scoreId);
  fail = false; await f.repository.retry();
  assert.equal(f.scoreCalls.length, 1); assert.deepEqual(f.historyCalls[0], f.historyCalls[1]); assert.equal(f.records.get(input.eventId)?.sync, "synced");
});
test("switching account while its score upload completes cannot write practice into the next account", async () => {
  const f = fixture(); f.client.createScore = async () => { f.client.current = { userId: bob }; return { id: alice, revision: 1 }; };
  const result = await f.repository.sync(await f.repository.save(input));
  assert.equal(result.userId, alice); assert.equal(result.sync, "pending"); assert.equal(f.historyCalls.length, 0);
});
test("concurrent retries of one event share the request and an identical snapshot is reused", async () => {
  const f = fixture(); const first = await f.repository.save(input); await Promise.all([f.repository.sync(first), f.repository.sync(first)]);
  const second = await f.repository.save({ ...input, eventId: bob }); await f.repository.sync(second);
  assert.equal(f.scoreCalls.length, 1); assert.equal(f.historyCalls.length, 2);
});
test("structured live evidence is forwarded; later recording review appends a version without new practice time",async()=>{
 const f=fixture(),xml=scoreXML(`<measure number="1">${attributesXML(1,"1")+noteXML()}</measure>`),options={mode:"follow" as const,inputKind:"midi" as const,bpm:60,tuning:440,first:1,last:1,part:"全部声部"};
 const matcher=new NoteWiseMatcher(expectedPerformance(xml,options),options,{takeId:input.eventId,sourceScoreSha256:"a".repeat(64)});matcher.accept({eventId:"m1",type:"on",midi:60,timeMs:100,confidence:1,timingConfidence:1});const live=matcher.finish(1200);
 f.client.addHistory=async(event:unknown)=>{f.historyCalls.push(event);return{event:{...event as object,scoreSha256:"a".repeat(64),analysisVersion:1,latestAnalysisVersion:1}} as never;};
 const versions:unknown[]=[];Object.assign(f.client,{addHistoryAnalysis:async(_id:string,body:unknown)=>{versions.push(body);return{version:2,analysisHash:"b".repeat(64),analysis:(body as {analysis:unknown}).analysis};}});
 const stored=await f.repository.sync(await f.repository.save({...input,musicxml:xml,mode:"follow",analysis:live}));assert.deepEqual((f.historyCalls[0] as {analysis:unknown}).analysis,live);
 const review={...structuredClone(live),detectorVersion:"basic-pitch-coreml-0.4.0"};const revised=await f.repository.reviseAnalysis(stored,review);
 assert.equal(f.historyCalls.length,1);assert.equal(versions.length,1);assert.equal(revised.analysisVersion,2);assert.equal(revised.durationSeconds,12);assert.equal(revised.localAnalyses?.length,1);assert.equal(revised.pendingAnalysis,undefined);
});
test("unknown append response retries the same version identity and account switch prevents cross-owner upload",async()=>{
 const f=fixture();const revision={schemaVersion:2,sourceScoreSha256:"a".repeat(64),takeId:input.eventId,status:"analysed",source:"client-reported",errors:[],verifiedByServer:false} as never;
 let fail=true;const requests:unknown[]=[];Object.assign(f.client,{addHistoryAnalysis:async(_id:string,body:unknown)=>{requests.push(structuredClone(body));if(fail)throw new Error("response lost");return{version:2,analysis:revision,analysisHash:"b".repeat(64)};}});
 const stored={...await f.repository.save(input),sync:"synced" as const,scoreSha256:"a".repeat(64),analysisVersion:1};const pending=await f.repository.reviseAnalysis(stored,revision);assert.ok(pending.pendingAnalysis);
 f.client.current={userId:bob};await f.repository.sync(pending);assert.equal(requests.length,1);
 f.client.current={userId:alice};fail=false;await f.repository.retry();assert.deepEqual(requests[0],requests[1]);assert.equal(f.records.get(input.eventId)?.analysisVersion,2);assert.equal(f.historyCalls.length,0);
});
