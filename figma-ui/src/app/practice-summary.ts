import type { PracticeRecord } from "./practice-records";

export type PracticeHistoryState = { status: "loading" | "ready" | "error"; owner: string | null; records: PracticeRecord[]; error: string };
export function practiceDay(value: string | Date): number | null {
  const date = value instanceof Date ? value : new Date(value);
  return Number.isFinite(date.getTime()) ? Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / 86400000 : null;
}
export function ownedPracticeRecords(state: PracticeHistoryState, owner: string | null, now = Date.now()): PracticeRecord[] {
  if (!owner || state.status !== "ready" || state.owner !== owner) return [];
  return state.records.filter((record) => {
    const start = new Date(record.startedAt).getTime(), end = new Date(record.endedAt).getTime();
    const spanSeconds = (end - start) / 1000;
    return record.userId === owner && !!record.eventId && Number.isFinite(record.durationSeconds) && record.durationSeconds > 0 && record.durationSeconds <= 86400 && Number.isFinite(start) && Number.isFinite(end) && spanSeconds >= 0 && spanSeconds <= 86400 && record.durationSeconds <= spanSeconds + 2 && end <= now;
  });
}
export function shouldAllowPracticeAnalysis(state: PracticeHistoryState, owner: string | null): boolean {
  return ownedPracticeRecords(state, owner).length > 0;
}
export function analysisRequestID(requests: Map<string, string>, owner: string, eventIds: string[], create: () => string, startNew = false): string {
  const key = JSON.stringify([owner, [...new Set(eventIds)].sort()]);
  let requestId = requests.get(key);
  if (!requestId || startNew) { requestId = create(); requests.set(key, requestId); }
  return requestId;
}
export function practiceSummary(state: PracticeHistoryState, owner: string | null, today: number, now = Date.now()) {
  // A saved session credits its local start date once, including sessions paused across midnight.
  const days = new Set(ownedPracticeRecords(state, owner, now).filter((record) => ["free", "follow", "strict"].includes(record.mode)).map((record) => practiceDay(record.startedAt)!).filter((day) => day <= today));
  let cursor = days.has(today) ? today : today - 1, streak = 0;
  while (days.has(cursor)) { streak++; cursor--; }
  let firstPracticeDay: number | null = null;
  for (const day of days) if (firstPracticeDay === null || day < firstPracticeDay) firstPracticeDay = day;
  return { days, streak, count: days.size, firstPracticeDay, known: state.status === "ready" && !!owner && state.owner === owner };
}

export function practiceMonthSummary(summary: ReturnType<typeof practiceSummary>, year: number, month: number, today: number) {
  const firstDay = Date.UTC(year, month, 1) / 86400000, nextMonth = Date.UTC(year, month + 1, 1) / 86400000;
  const observedFrom = summary.firstPracticeDay === null ? null : Math.max(firstDay, summary.firstPracticeDay);
  const observedThrough = Math.min(nextMonth - 1, today - 1);
  let practiced = 0, completedDayCheckins = 0;
  for (const day of summary.days) {
    if (day >= firstDay && day < nextMonth) practiced++;
    if (observedFrom !== null && day >= observedFrom && day <= observedThrough) completedDayCheckins++;
  }
  const observedDays = observedFrom === null ? 0 : Math.max(0, observedThrough - observedFrom + 1);
  return { practiced, missed: Math.max(0, observedDays - completedDayCheckins), observedFrom, observedThrough, observedDays };
}

export function practiceCalendarLabel(summary: ReturnType<typeof practiceSummary>, day: number, today: number): string {
  if (!summary.known) return "练习记录尚未读取";
  if (day > today) return "未来日期";
  if (summary.days.has(day)) return "已练琴";
  if (day === today) return "今天尚无练习记录";
  if (summary.firstPracticeDay === null || day < summary.firstPracticeDay) return "尚未开始记录";
  return "无练习记录";
}

export function nextLocalPracticeDay(now: number): number {
  const date = new Date(now);
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + 1).getTime();
}
