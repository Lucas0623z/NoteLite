import test from "node:test";
import assert from "node:assert/strict";
import { PracticeRecords, type PracticeRecord } from "../src/app/practice-records.ts";
import type { PracticeEvent } from "../src/app/account.ts";
import { CloudError } from "../src/app/cloud.ts";
import {NoteWiseMatcher,expectedPerformance} from "../src/app/notewise.ts";
import {scoreXML,noteXML,attributesXML} from "./xml-dom.ts";
const alice = "11111111-1111-4111-8111-111111111111", bob = "22222222-2222-4222-8222-222222222222";
const input = { eventId: "33333333-3333-4333-8333-333333333333", name: "自编练习", musicxml: "<score-partwise/>", scoreIdentity: "local:sample", sourceKind: "local" as const, mode: "free" as const, durationSeconds: 12, startedAt: "2026-10-11T10:00:00Z", endedAt: "2026-10-11T10:00:12Z" };
function fixture(owner: string | null = alice) {
  const records = new Map<string, PracticeRecord>(), historyCalls: unknown[] = [], scoreCalls: unknown[] = [];
  const store = { put: async (record: PracticeRecord) => { records.set(record.eventId, structuredClone(record)); }, getAll: async () => Array.from(records.values()).map((record) => structuredClone(record)) };
  const client = { current: owner ? { userId: owner } as { userId: string; sessionId?: string } : null, createScore: async (...args: unknown[]) => { scoreCalls.push(args); return { id: alice, revision: 1 }; }, addHistory: async (event: unknown) => { historyCalls.push(event); return { event: { ...event as object, analysis: { status: "unanalysed", source: "none", errors: null, verifiedByServer: false } } }; }, history: async (_cursor?: string) => ({ events: [] as PracticeEvent[], nextCursor: null as string | null }) };
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

function cloudEvent(index: number): PracticeEvent {
  return { eventId: `44444444-4444-4444-8444-${index.toString(16).padStart(12, "0")}`, sourceKind: "official", scoreId: "notelite-four-notes-v1", mode: "free", durationSeconds: 12, startedAt: "2026-10-01T10:00:00Z", endedAt: "2026-10-01T10:00:12Z", receivedAt: "2026-10-12T10:00:00Z" };
}
const rejectedIncomplete = (error: unknown) => error instanceof CloudError && error.code === "history_incomplete";
const rejectedIdentity = (error: unknown) => error instanceof CloudError && error.code === "identity_changed";

test("a new device reads every cloud history page and keeps performed dates rather than receipt dates", async () => {
  const f = fixture(), events = Array.from({ length: 450 }, (_, index) => cloudEvent(index));
  const cursors: (string | undefined)[] = [];
  f.client.history = async (cursor) => {
    cursors.push(cursor);
    const offset = cursor ? Number(cursor) : 0;
    return { events: events.slice(offset, offset + 200), nextCursor: offset + 200 < events.length ? String(offset + 200) : null };
  };
  const records = await f.repository.list();
  assert.deepEqual(cursors, [undefined, "200", "400"]); assert.equal(records.length, 450);
  assert.equal(records[449].startedAt, events[449].startedAt); assert.equal(records[449].endedAt, events[449].endedAt);
  assert.ok(records.every((record) => record.userId === alice && record.sync === "synced"));
  assert.equal(f.records.size, 0, "reading account statistics must not inject or fabricate local practice");
});

test("history merges the same event once across local and remote pages without losing its local snapshot", async () => {
  const f = fixture(); await f.repository.save(input);
  let reads = 0;
  f.client.history = async () => ++reads === 1
    ? { events: [{ ...cloudEvent(0), eventId: input.eventId }], nextCursor: "next" }
    : { events: [{ ...cloudEvent(0), eventId: input.eventId }, cloudEvent(1)], nextCursor: null };
  const records = await f.repository.list();
  assert.equal(records.length, 2); const merged = records.find((record) => record.eventId === input.eventId)!;
  assert.equal(merged.musicxml, input.musicxml); assert.equal(merged.name, input.name); assert.equal(merged.sync, "synced");
  assert.equal(f.historyCalls.length, 0, "listing must not create a new event for a duplicate");
});

test("failure on a later history page rejects the whole load instead of reporting partial statistics", async () => {
  const f = fixture(); let reads = 0;
  f.client.history = async () => { if (++reads === 2) throw new Error("history offline"); return { events: [cloudEvent(0)], nextCursor: "next" }; };
  await assert.rejects(f.repository.list(), /history offline/);
  assert.equal(reads, 2); assert.equal(f.records.size, 0);
});

test("repeated and cycling history cursors fail within bounded requests", async () => {
  for (const sequence of [["same", "same"], ["one", "two", "one"]]) {
    const f = fixture(); let reads = 0;
    f.client.history = async () => ({ events: [cloudEvent(reads)], nextCursor: sequence[reads++] });
    await assert.rejects(f.repository.list(), rejectedIncomplete); assert.equal(reads, sequence.length);
  }
});

for (const change of ["another owner", "renewed session", "logout"] as const) test(`a ${change} during pagination cannot install the previous account's history`, async () => {
  const f = fixture(); f.client.current = { userId: alice, sessionId: "original-session" }; let reads = 0;
  f.client.history = async () => {
    if (++reads === 1) return { events: [cloudEvent(0)], nextCursor: "next" };
    f.client.current = change === "logout" ? null : { userId: change === "another owner" ? bob : alice, sessionId: "different-session" };
    return { events: [cloudEvent(1)], nextCursor: null };
  };
  await assert.rejects(f.repository.list(), rejectedIdentity); assert.equal(reads, 2); assert.equal(f.records.size, 0);
});

test("guest history stays local and a login during its local read cannot return guest history for the new account", async () => {
  const f = fixture(null); await f.repository.save(input); let reads = 0;
  f.client.history = async () => { reads++; return { events: [], nextCursor: null }; };
  assert.equal((await f.repository.list()).length, 1); assert.equal(reads, 0);
  const originalRead = f.store.getAll;
  f.store.getAll = async () => { const values = await originalRead(); f.client.current = { userId: alice }; return values; };
  await assert.rejects(f.repository.list(), rejectedIdentity); assert.equal(reads, 0);
});

test("invalid or empty continuation pages cannot look like a complete empty account", async () => {
  for (const result of [{ events: [], nextCursor: "next" }, { events: [cloudEvent(0)] }, { events: [cloudEvent(0)], nextCursor: "" }, { events: [], nextCursor: 5 }]) {
    const f = fixture(); f.client.history = async () => result as never;
    await assert.rejects(f.repository.list(), rejectedIncomplete);
  }
});

test("the service's full 20,000 record quota includes its final empty page and further records fail explicitly", async () => {
  for (const overflow of [false, true]) {
    const f = fixture(); let reads = 0;
    f.client.history = async () => {
      const page = reads++;
      return page < 100 ? { events: Array.from({ length: 200 }, (_, index) => cloudEvent(page * 200 + index)), nextCursor: String(page + 1) }
        : { events: overflow ? [cloudEvent(20000)] : [], nextCursor: null };
    };
    if (overflow) await assert.rejects(f.repository.list(), rejectedIncomplete);
    else assert.equal((await f.repository.list()).length, 20000);
    assert.equal(reads, 101);
  }
});

test("a new device downloads the immutable performed score and verifies its digest without another practice event", async () => {
  const f = fixture();
  const xml = "<score-partwise><work><work-title>Original</work-title></work></score-partwise>";
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(xml))), (value) => value.toString(16).padStart(2, "0")).join("");
  const record = { ...input, userId: alice, sync: "synced" as const, musicxml: "", scoreSha256: hash };
  let requested = "";
  Object.assign(f.client, { historyXML: async (eventId: string) => { requested = eventId; return xml; } });
  assert.equal(await f.repository.snapshot(record), xml); assert.equal(requested, input.eventId);
  assert.equal(f.historyCalls.length, 0); assert.equal(f.scoreCalls.length, 0); assert.equal(f.records.size, 0);
  Object.assign(f.client, { historyXML: async () => "<score-partwise>Edited after practice</score-partwise>" });
  await assert.rejects(f.repository.snapshot(record), /完整性/);
});

test("a late performed snapshot cannot cross an owner, session or logout boundary", async () => {
  for (const change of ["owner", "session", "logout"] as const) {
    const f = fixture(); f.client.current = { userId: alice, sessionId: "start" };
    const record = { ...input, userId: alice, sync: "synced" as const, musicxml: "" };
    Object.assign(f.client, { historyXML: async () => { f.client.current = change === "logout" ? null : { userId: change === "owner" ? bob : alice, sessionId: "renewed" }; return input.musicxml; } });
    await assert.rejects(f.repository.snapshot(record), rejectedIdentity); assert.equal(f.records.size, 0);
  }
});

test("guest and unsynced owned practice use their original local XML without fetching cloud data", async () => {
  const f = fixture(null); let reads = 0;
  Object.assign(f.client, { historyXML: async () => { reads++; return "wrong"; } });
  const record = await f.repository.save(input); assert.equal(await f.repository.snapshot(record), input.musicxml);
  f.client.current = { userId: alice }; await assert.rejects(f.repository.snapshot(record), rejectedIdentity);
  const pending = await f.repository.save({ ...input, eventId: bob }); assert.equal(await f.repository.snapshot(pending), input.musicxml);
  assert.equal(reads, 0);
});
