import type { PracticeRecord } from "./practice-records";

export type PracticeHistoryState = { status: "loading" | "ready" | "error"; owner: string | null; records: PracticeRecord[]; error: string };
export function practiceDay(value: string | Date): number | null {
  const date = value instanceof Date ? value : new Date(value);
  return Number.isFinite(date.getTime()) ? Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / 86400000 : null;
}
export function ownedPracticeRecords(state: PracticeHistoryState, owner: string | null): PracticeRecord[] {
  if (!owner || state.status !== "ready" || state.owner !== owner) return [];
  return state.records.filter((record) => record.userId === owner && !!record.eventId && Number.isFinite(record.durationSeconds) && record.durationSeconds > 0 && practiceDay(record.startedAt) !== null && practiceDay(record.endedAt) !== null && new Date(record.endedAt).getTime() >= new Date(record.startedAt).getTime());
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
export function practiceSummary(state: PracticeHistoryState, owner: string | null, today: number) {
  const days = new Set(ownedPracticeRecords(state, owner).map((record) => practiceDay(record.startedAt)!).filter((day) => day <= today));
  let cursor = days.has(today) ? today : today - 1, streak = 0;
  while (days.has(cursor)) { streak++; cursor--; }
  return { days, streak, count: days.size, known: state.status === "ready" && !!owner && state.owner === owner };
}
