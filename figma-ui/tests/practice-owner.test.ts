import test from "node:test";
import assert from "node:assert/strict";
import { capturePracticeOwner, requirePracticeOwner, startOwnedPracticeInput } from "../src/app/practice-owner.ts";
import { PracticeRecords, type PracticeRecord } from "../src/app/practice-records.ts";
import { NoteWiseInput, type NoteWiseSettings } from "../src/app/notewise.ts";

const A = "11111111-1111-4111-8111-111111111111", B = "22222222-2222-4222-8222-222222222222";
type Identity = { userId: string; sessionId: string } | null;
const identity = (userId = A, sessionId = "original-session"): Identity => ({ userId, sessionId });
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

for (const change of ["another owner", "new session", "logout", "guest login"] as const) {
  test(`permission/start reply after ${change} is stopped once and cannot commit a practice`, async () => {
    let current = change === "guest login" ? null : identity();
    const captured = capturePracticeOwner(current), native = deferred<{ connected: boolean }>();
    let stopped = 0, committed = 0;
    const starting = startOwnedPracticeInput(captured, () => current, () => native.promise, async () => { stopped++; });
    current = change === "logout" ? null : identity(change === "another owner" ? B : A, "new-session");
    native.resolve({ connected: true });
    await assert.rejects(starting.then(() => { committed++; }), /账户或登录会话已更改/);
    assert.equal(stopped, 1); assert.equal(committed, 0);
  });
}

test("a paused take's old session fails before native resume and owner capture copies mutable identity", async () => {
  const mutable = { userId: A, sessionId: "old-session" }, captured = capturePracticeOwner(mutable);
  mutable.sessionId = "new-session";
  assert.equal(captured.sessionId, "old-session");
  let nativeStarts = 0, nativeStops = 0;
  await assert.rejects(startOwnedPracticeInput(captured, () => mutable,
    async () => { nativeStarts++; }, async () => { nativeStops++; }), /登录会话已更改/);
  assert.equal(nativeStarts, 0); assert.equal(nativeStops, 0);
  assert.throws(() => requirePracticeOwner(captured, mutable));
});

test("unchanged account and genuine guest starts complete without cancellation", async () => {
  for (const current of [identity(), null]) {
    const captured = capturePracticeOwner(current);
    let stopped = 0;
    const result = await startOwnedPracticeInput(captured, () => current, async () => ({ connected: true }), async () => { stopped++; });
    assert.equal(result.connected, true); assert.equal(stopped, 0);
    assert.equal(captured.owner, current?.userId || "guest");
  }
});

test("failed native start clears its input without masking the original error when cleanup also fails", async () => {
  const original = new Error("permission denied"), current = identity();
  let stopped = 0;
  await assert.rejects(startOwnedPracticeInput(capturePracticeOwner(current), () => current,
    async () => { throw original; }, async () => { stopped++; throw new Error("old native session was detached"); }), error => error === original);
  assert.equal(stopped, 1);
});

test("slow native stop saves raw recording evidence only to the captured owner after another login", async () => {
  const records = new Map<string, PracticeRecord>(), stopped = deferred<{ available: boolean; sampleRate: number }>();
  let current = identity(), uploads = 0;
  const client = {
    get current() { return current; },
    createScore: async () => { uploads++; throw new Error("Must not upload A's record using B"); },
    addHistory: async () => { uploads++; throw new Error("Must not upload A's record using B"); },
  };
  const repository = new PracticeRecords({ put: async value => { records.set(value.eventId, structuredClone(value)); }, getAll: async () => [...records.values()] }, client as never, () => {});
  const captured = capturePracticeOwner(current);
  const saving = (async () => {
    const recording = await stopped.promise;
    const record = await repository.save({ eventId: "33333333-3333-4333-8333-333333333333", name: "合成练习", musicxml: "<score-partwise/>", scoreIdentity: "owner-snapshot", sourceKind: "local", mode: "free", durationSeconds: 5,
      startedAt: "2026-10-12T10:00:00Z", endedAt: "2026-10-12T10:00:05Z", analysis: { status: "uncertain", source: "client-reported", errors: [], verifiedByServer: false, recording } }, captured.owner);
    return repository.sync(record);
  })();
  current = identity(B, "B-session"); stopped.resolve({ available: true, sampleRate: 44100 });
  const record = await saving;
  assert.equal(record.userId, A); assert.equal(record.sync, "pending");
  assert.equal(record.analysis?.recording?.sampleRate, 44100);
  assert.equal(records.get(record.eventId)?.userId, A);
  assert.equal(uploads, 0); assert.deepEqual(await repository.local(), []);
});

test("the real native input transport carries its copied owner/session through start, pause and stop and detaches late events", async () => {
  const saved = globalThis.window, messages: { action: string; payload: Record<string, unknown> }[] = [];
  const nativeWindow = new EventTarget();
  Object.assign(nativeWindow, { webkit: { messageHandlers: { noteLiteCloud: { postMessage(message: { requestId: string; action: string; payload: Record<string, unknown> }) {
    messages.push(message);
    queueMicrotask(() => window.NoteLiteCloudNative!.resolve(message.requestId, { ok: true, result: message.action === "notewise/stop" ? { available: false } : { connected: true } }));
  } } } } });
  globalThis.window = nativeWindow as Window & typeof globalThis;
  try {
    const settings: NoteWiseSettings = { inputKind: "midi", mode: "follow", bpm: 60, tuning: 440, first: 1, last: 1, part: "全部声部" };
    for (const captured of [{ owner: A, sessionId: "33333333-3333-4333-8333-333333333333" }, { owner: "guest", sessionId: null }]) {
      const expected = { ...captured }; let accepted = 0;
      const input = new NoteWiseInput("44444444-4444-4444-8444-444444444444", () => { accepted++; }, () => {}, captured);
      captured.owner = B;
      await input.start(settings, "piano");
      window.NoteLiteCloudNative!.event({ type: "notewiseInput", takeId: "44444444-4444-4444-8444-444444444444", sequence: 1, event: { type: "on", eventId: "synthetic-note", midi: 60, timeMs: 0, confidence: 1, timingConfidence: 1, centsEvidence: "none" } });
      assert.equal(accepted, 1);
      await input.pause(); await input.stop();
      for (const message of messages.splice(0)) {
        assert.equal(message.payload.expectedUserId, expected.owner);
        assert.equal(message.payload.expectedSessionId, expected.sessionId);
      }
      window.NoteLiteCloudNative!.event({ type: "notewiseInput", takeId: "44444444-4444-4444-8444-444444444444", sequence: 2, event: { type: "on", eventId: "late-note", midi: 62, timeMs: 10, confidence: 1, timingConfidence: 1, centsEvidence: "none" } });
      assert.equal(accepted, 1, "stopped input must not consume an old account's later audio event");
    }
  } finally { globalThis.window = saved; }
});
