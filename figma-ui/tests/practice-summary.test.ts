import test from "node:test";
import assert from "node:assert/strict";
import { analysisRequestID, nextLocalPracticeDay, ownedPracticeRecords, practiceCalendarLabel, practiceDay, practiceMonthSummary, practiceSummary, shouldAllowPracticeAnalysis, type PracticeHistoryState } from "../src/app/practice-summary.ts";
import type { PracticeRecord } from "../src/app/practice-records";

const when = (day: number, hour = 10) => new Date(2026, 9, day, hour).toISOString();
const record = (eventId: string, day: number, userId = "user-A", extra: Partial<PracticeRecord> = {}): PracticeRecord => ({
  eventId, userId, name: "实际练习", scoreIdentity: "score-1", musicxml: "", sourceKind: "personal", scoreId: "score-1",
  startedAt: when(day), endedAt: when(day, 11), durationSeconds: 3600, mode: "free", sync: "synced", ...extra,
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

const summaryAt = (records: PracticeRecord[], date = new Date(2026, 9, 12, 12), extra: Partial<PracticeHistoryState> = {}) => practiceSummary(state(records, extra), "user-A", practiceDay(date)!, date.getTime());

test("a new user has zero check-ins and zero missed days, including earlier and future months", () => {
  const today = practiceDay(when(12))!, summary = summaryAt([]);
  assert.equal(summary.known, true); assert.equal(summary.streak, 0); assert.equal(summary.firstPracticeDay, null);
  for (const month of [0, 8, 9, 10]) {
    const calendar = practiceMonthSummary(summary, 2026, month, today);
    assert.equal(calendar.practiced, 0); assert.equal(calendar.missed, 0); assert.equal(calendar.observedDays, 0);
  }
  assert.equal(practiceCalendarLabel(summary, today - 1, today), "尚未开始记录");
  assert.equal(practiceCalendarLabel(summary, today, today), "今天尚无练习记录");
  assert.equal(practiceCalendarLabel(summary, today + 1, today), "未来日期");
});

test("missed days start at the first actual check-in and exclude the unfinished today", () => {
  const today = practiceDay(when(12))!, summary = summaryAt([record("first", 10)]);
  const calendar = practiceMonthSummary(summary, 2026, 9, today);
  assert.equal(calendar.practiced, 1); assert.equal(calendar.observedDays, 2); assert.equal(calendar.missed, 1);
  assert.equal(calendar.observedFrom, practiceDay(when(10)));
  assert.equal(calendar.observedThrough, practiceDay(when(11)));
  assert.equal(practiceCalendarLabel(summary, today - 3, today), "尚未开始记录");
  assert.equal(practiceCalendarLabel(summary, today - 1, today), "无练习记录");
});

test("a first practice today never creates past missed days; several sessions credit one day", () => {
  const today = practiceDay(when(12))!, summary = summaryAt([record("first", 12), record("again", 12)]);
  assert.equal(summary.streak, 1); assert.equal(summary.count, 1);
  assert.deepEqual(practiceMonthSummary(summary, 2026, 9, today), { practiced: 1, missed: 0, observedFrom: today, observedThrough: today - 1, observedDays: 0 });
  assert.equal(practiceCalendarLabel(summary, today, today), "已练琴");
});

test("month navigation uses real year/month boundaries without counting before the first record", () => {
  const now = new Date(2027, 0, 3, 12), today = practiceDay(now)!;
  const make = (id: string, start: Date) => record(id, 1, "user-A", { startedAt: start.toISOString(), endedAt: new Date(start.getTime() + 60000).toISOString(), durationSeconds: 60 });
  const summary = summaryAt([make("dec31", new Date(2026, 11, 31, 10)), make("jan2", new Date(2027, 0, 2, 10))], now);
  assert.equal(practiceMonthSummary(summary, 2026, 10, today).missed, 0);
  assert.equal(practiceMonthSummary(summary, 2026, 11, today).missed, 0);
  const january = practiceMonthSummary(summary, 2027, 0, today);
  assert.equal(january.practiced, 1); assert.equal(january.missed, 1); assert.equal(summary.streak, 1);
  assert.equal(practiceMonthSummary(summary, 2027, 1, today).missed, 0);
});

test("playback records remain available to history/analysis but cannot create practice check-ins or missed days", () => {
  const listening = state([record("listen", 11, "user-A", { mode: "playback" })]);
  assert.equal(ownedPracticeRecords(listening, "user-A").length, 1);
  assert.equal(shouldAllowPracticeAnalysis(listening, "user-A"), true);
  const summary = practiceSummary(listening, "user-A", practiceDay(when(12))!, new Date(2026, 9, 12, 12).getTime());
  assert.equal(summary.count, 0); assert.equal(summary.streak, 0); assert.equal(summary.firstPracticeDay, null);
  assert.equal(practiceMonthSummary(summary, 2026, 9, practiceDay(when(12))!).missed, 0);
  const actual = summaryAt([record("free", 10), record("follow", 11, "user-A", { mode: "follow" }), record("strict", 12, "user-A", { mode: "strict" }), record("listen", 9, "user-A", { mode: "playback" })]);
  assert.equal(actual.streak, 3); assert.equal(actual.count, 3);
});

test("a saved session spanning local midnight credits only its start date", () => {
  const start = new Date(2026, 9, 11, 23, 59), end = new Date(2026, 9, 12, 0, 3), now = new Date(2026, 9, 12, 1);
  const summary = summaryAt([record("midnight", 11, "user-A", { startedAt: start.toISOString(), endedAt: end.toISOString(), durationSeconds: 240 })], now);
  const today = practiceDay(now)!;
  assert.deepEqual([...summary.days], [today - 1]); assert.equal(summary.streak, 1); assert.equal(summary.count, 1);
  assert.equal(practiceMonthSummary(summary, 2026, 9, today).missed, 0);
  assert.equal(summaryAt([record("midnight", 11, "user-A", { startedAt: start.toISOString(), endedAt: end.toISOString(), durationSeconds: 240 })], new Date(2026, 9, 13, 0, 1)).streak, 0);
});

test("records ending later than the injected current instant do not become actual saved practice", () => {
  const now = new Date(2026, 9, 12, 10, 30), futureWithinToday = record("not-finished", 12);
  const futureTomorrow = record("ends-tomorrow", 12, "user-A", { endedAt: when(13) });
  const summary = summaryAt([futureWithinToday, futureTomorrow], now);
  assert.equal(ownedPracticeRecords(state([futureWithinToday, futureTomorrow]), "user-A", now.getTime()).length, 0);
  assert.equal(summary.count, 0); assert.equal(summary.firstPracticeDay, null);
});

test("impossible local timing cannot create check-ins that the history service would reject", () => {
  const records = [record("duration-exceeds-clock", 10, "user-A", { endedAt: when(10), durationSeconds: 120 }), record("clock-gap-exceeds-day", 10, "user-A", { endedAt: when(12), durationSeconds: 60 })];
  const summary = summaryAt(records);
  assert.equal(summary.count, 0); assert.equal(summary.firstPracticeDay, null);
  const rounded = record("valid-clock-rounding", 10, "user-A", { startedAt: when(10), endedAt: new Date(new Date(when(10)).getTime() + 1000).toISOString(), durationSeconds: 3 });
  assert.equal(summaryAt([rounded]).count, 1, "the existing two-second service tolerance remains accepted");
});

test("failed or changed-account history remains unknown rather than creating zero or missed-day claims", () => {
  const today = practiceDay(when(12))!;
  for (const extra of [{ status: "loading" as const }, { status: "error" as const }, { owner: "user-B" }]) {
    const summary = summaryAt([record("old-A", 10)], undefined, extra);
    assert.equal(summary.known, false); assert.equal(summary.count, 0);
    assert.equal(practiceCalendarLabel(summary, today - 1, today), "练习记录尚未读取");
  }
});

test("statistics retain dates beyond the 200-row visible history list", () => {
  const records = Array.from({ length: 300 }, (_, index) => {
    const start = new Date(2026, 0, index + 1, 10);
    return record(`actual-${index}`, 1, "user-A", { startedAt: start.toISOString(), endedAt: new Date(start.getTime() + 60000).toISOString(), durationSeconds: 60 });
  });
  const last = new Date(records.at(-1)!.endedAt), summary = summaryAt(records, last);
  assert.equal(summary.count, 300); assert.equal(summary.streak, 300);
  assert.equal(summary.firstPracticeDay, practiceDay(new Date(2026, 0, 1)));
});

test("local day ordinals and the next-midnight deadline survive DST, leap dates and year changes", () => {
  for (const now of [new Date(2026, 2, 8, 1, 30), new Date(2026, 10, 1, 1, 30), new Date(2028, 1, 29, 23, 59), new Date(2026, 11, 31, 23, 59)]) {
    const next = new Date(nextLocalPracticeDay(now.getTime()));
    assert.equal(next.getHours(), 0); assert.equal(next.getMinutes(), 0);
    assert.equal(practiceDay(next), practiceDay(now)! + 1);
    assert.ok(next.getTime() > now.getTime());
  }
});
