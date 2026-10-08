import test from "node:test";
import assert from "node:assert/strict";
import ts from "typescript";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/app/history.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { summarizeHistory, calendarDay } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
function record(date, extra = {}) { return { id: date, recordID: "score", title: "测试曲谱", startedAt: new Date(`${date}T12:00:00`).toISOString(), durationSeconds: 120, completed: true, errors: [], ...extra }; }

test("calendar uses actual practice days across month boundaries", () => {
  const summary = summarizeHistory([record("2026-09-30"), record("2026-10-02"), record("2026-10-03")], new Date("2026-10-03T19:00:00"));
  assert.equal(summary.practiceDays, 3); assert.equal(summary.streak, 2);
  assert.equal(summary.days.has(calendarDay(new Date("2026-10-01T12:00:00"))), false);
});
test("streak counts yesterday when today has no practice and expires after a gap", () => {
  const history = [record("2026-10-01"), record("2026-10-02")];
  assert.equal(summarizeHistory(history, new Date("2026-10-03T12:00:00")).streak, 2);
  assert.equal(summarizeHistory(history, new Date("2026-10-04T12:00:00")).streak, 0);
});
test("partial practice does not grade unperformed score positions", () => {
  const summary = summarizeHistory([record("2026-10-03", { completed: false, total: 100, firstTryCorrect: 2, results: [{ status: "correct" }, { status: "correct" }, { status: "corrected" }] })], new Date("2026-10-03T12:00:00"));
  assert.equal(summary.accuracy, 67); assert.equal(summary.total, 3); assert.equal(summary.completed, 0);
});
test("legacy records without scored results have no invented accuracy", () => {
  assert.equal(summarizeHistory([record("2026-10-03", { total: 99, firstTryCorrect: 88 })], new Date("2026-10-03T12:00:00")).accuracy, null);
});
test("duplicate same-day sessions do not inflate practice days; zero-length records do not count", () => {
  const summary = summarizeHistory([record("2026-10-03"), record("2026-10-03", { id: "second" }), record("2026-10-02", { durationSeconds: 0 })], new Date("2026-10-03T12:00:00"));
  assert.equal(summary.practiceDays, 1); assert.equal(summary.sessions, 2); assert.equal(summary.minutes, 4); assert.equal(summary.todayCompleted, 2);
});
test("future and malformed records do not create calendar marks", () => {
  const summary = summarizeHistory([record("2026-10-05"), { ...record("2026-10-03"), startedAt: "invalid" }], new Date("2026-10-03T12:00:00"));
  assert.equal(summary.days.size, 0); assert.equal(summary.streak, 0);
});
