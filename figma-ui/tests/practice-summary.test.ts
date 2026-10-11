import test from "node:test";
import assert from "node:assert/strict";
import { analysisRequestID, ownedPracticeRecords, practiceDay, practiceSummary, shouldAllowPracticeAnalysis, type PracticeHistoryState } from "../src/app/practice-summary.ts";
import type { PracticeRecord } from "../src/app/practice-records";

const when = (day: number, hour = 10) => new Date(2026, 9, day, hour).toISOString();
const record = (eventId: string, day: number, userId = "user-A", extra: Partial<PracticeRecord> = {}): PracticeRecord => ({
  eventId, userId, name: "实际练习", scoreIdentity: "score-1", musicxml: "", sourceKind: "personal", scoreId: "score-1",
  startedAt: when(day), endedAt: when(day, 11), durationSeconds: 3600, mode: "playback", sync: "synced", ...extra,
});
const state = (records: PracticeRecord[], extra: Partial<PracticeHistoryState> = {}): PracticeHistoryState => ({ status: "ready", owner: "user-A", records, error: "", ...extra });

test("analysis is disabled without saved records, including a legacy check-in count", () => {
  assert.equal(shouldAllowPracticeAnalysis(state([]), "user-A"), false);
  assert.equal(shouldAllowPracticeAnalysis({ ...state([]), count: 999 } as PracticeHistoryState, "user-A"), false);
});
test("only actual saved records from the currently loaded owner can enable analysis", () => {
  assert.equal(shouldAllowPracticeAnalysis(state([record("saved", 11)]), "user-A"), true);
  assert.equal(shouldAllowPracticeAnalysis(state([record("saved", 11, "user-B")]), "user-A"), false);
  assert.equal(shouldAllowPracticeAnalysis(state([record("saved", 11)]), "user-B"), false);
  assert.equal(shouldAllowPracticeAnalysis(state([record("saved", 11)]), null), false);
});
test("unknown/loading/failed history cannot expose old records or enable analysis", () => {
  for (const status of ["loading", "error"] as const) {
    const history = state([record("old", 11)], { status, error: "读取失败" });
    assert.equal(shouldAllowPracticeAnalysis(history, "user-A"), false);
    assert.deepEqual(ownedPracticeRecords(history, "user-A"), []);
    assert.equal(practiceSummary(history, "user-A", practiceDay(when(11))!).known, false);
  }
});
test("guest records remain local and cannot appear in an authenticated account", () => {
  const guest = state([record("guest", 11, "guest"), record("private", 10)], { owner: "guest" });
  assert.equal(shouldAllowPracticeAnalysis(guest, "guest"), true);
  assert.deepEqual(ownedPracticeRecords(guest, "guest").map((record) => record.eventId), ["guest"]);
  assert.equal(shouldAllowPracticeAnalysis(guest, "user-A"), false);
});
test("streak derives from distinct actual dates rather than subtracting a counter", () => {
  const today = practiceDay(when(11))!;
  const summary = practiceSummary(state([record("a", 11), record("b", 11), record("c", 10), record("d", 8), record("future", 12)]), "user-A", today);
  assert.equal(summary.streak, 2); assert.equal(summary.count, 3);
  assert.deepEqual([...summary.days].sort((a, b) => a - b), [today - 3, today - 1, today]);
});
test("yesterday keeps a real streak while a missing intervening date ends it", () => {
  const history = state([record("a", 10), record("b", 9)]);
  assert.equal(practiceSummary(history, "user-A", practiceDay(when(11))!).streak, 2);
  assert.equal(practiceSummary(history, "user-A", practiceDay(when(12))!).streak, 0);
});
test("invalid timestamps, reversed time, empty IDs and zero duration do not become saved practice", () => {
  const invalid = [record("", 11), record("zero", 11, "user-A", { durationSeconds: 0 }), record("nan", 11, "user-A", { durationSeconds: NaN }), record("bad", 11, "user-A", { startedAt: "invalid" }), record("reverse", 11, "user-A", { endedAt: when(10) })];
  assert.equal(shouldAllowPracticeAnalysis(state(invalid), "user-A"), false);
  assert.equal(practiceDay("invalid"), null);
});
test("retrying an unknown analysis response retains its request ID across record order and repeated tab entries", () => {
  const requests = new Map<string, string>(); let created = 0;
  const create = () => `request-${++created}`;
  assert.equal(analysisRequestID(requests, "user-A", ["b", "a"], create), "request-1");
  assert.equal(analysisRequestID(requests, "user-A", ["a", "b", "a"], create), "request-1");
  assert.equal(created, 1);
});
test("a different account or different selected event set starts a distinct analysis request", () => {
  const requests = new Map<string, string>(); let created = 0;
  const create = () => `request-${++created}`;
  assert.equal(analysisRequestID(requests, "user-A", ["a"], create), "request-1");
  assert.equal(analysisRequestID(requests, "user-B", ["a"], create), "request-2");
  assert.equal(analysisRequestID(requests, "user-A", ["a", "b"], create), "request-3");
  assert.equal(analysisRequestID(requests, "user-A", ["a"], create), "request-1");
});

test("only an explicit new analysis replaces the retained request identity", () => {
  const requests = new Map<string, string>(); let created = 0;
  const create = () => `request-${++created}`;
  assert.equal(analysisRequestID(requests, "user-A", ["a"], create), "request-1");
  assert.equal(analysisRequestID(requests, "user-A", ["a"], create, true), "request-2");
  assert.equal(analysisRequestID(requests, "user-A", ["a"], create), "request-2");
});
