export interface HistoryRecord {
  id: string; recordID: string; title: string; startedAt: string; durationSeconds: number;
  completed: boolean; firstTryCorrect?: number; total?: number; errors: unknown[];
  results?: { status: string }[]; input?: string; mode?: string; bpm?: number; scope?: unknown;
}
export function calendarDay(date: Date) { return Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / 86400000; }
export function summarizeHistory(history: HistoryRecord[], now = new Date()) {
  const today = calendarDay(now);
  const valid = history.filter(record => record.durationSeconds > 0 && Number.isFinite(new Date(record.startedAt).getTime()));
  const days = new Set(valid.map(record => calendarDay(new Date(record.startedAt))).filter(day => day <= today));
  let streak = 0;
  let cursor = days.has(today) ? today : today - 1;
  while (days.has(cursor)) { streak++; cursor--; }
  const results = valid.flatMap(record => record.results || []).filter(result => ["correct", "corrected", "missing"].includes(result.status));
  const total = results.length;
  const correct = results.filter(result => result.status === "correct").length;
  return { today, days, streak, practiceDays: days.size, sessions: valid.length,
    todayCompleted: valid.filter(record => record.completed && calendarDay(new Date(record.startedAt)) === today).length,
    completed: valid.filter(record => record.completed).length,
    minutes: Math.floor(valid.reduce((sum, record) => sum + record.durationSeconds, 0) / 60),
    accuracy: total ? Math.round(correct / total * 100) : null, total, correct };
}
