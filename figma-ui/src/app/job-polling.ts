export type PollValue<T> = { id: string; value: T };
type Schedule = (callback: () => Promise<void>, delay: number) => () => void;
type PollOptions<T> = {
  ids: string[];
  read: (id: string) => Promise<T>;
  commit: (values: PollValue<T>[], signal: AbortSignal) => Promise<void>;
  failed: (id: string | undefined, error: unknown) => void;
  delay?: number;
  schedule?: Schedule;
};

/** Collect one full round before committing; keep polling until its owner stops it. */
export function startJobPolling<T>({ ids, read, commit, failed, delay = 3000, schedule = (callback, delay) => {
  const timer = setTimeout(() => { void callback(); }, delay);
  return () => clearTimeout(timer);
} }: PollOptions<T>): () => void {
  const controller = new AbortController();
  let cancelTimer: (() => void) | undefined;
  async function poll() {
    const results: PromiseSettledResult<T>[] = new Array(ids.length);
    let next = 0;
    // The native bridge allows 16 concurrent requests. Keep polling at four so
    // file/edit/navigation requests retain capacity, even with a large library.
    await Promise.allSettled(Array.from({ length: Math.min(4, ids.length) }, async () => {
      while (!controller.signal.aborted && next < ids.length) {
        const index = next++;
        try { results[index] = { status: "fulfilled", value: await read(ids[index]) }; }
        catch (reason) { results[index] = { status: "rejected", reason }; }
      }
    }));
    if (controller.signal.aborted) return;
    const values = results.flatMap((result, index) => result.status === "fulfilled" ? [{ id: ids[index], value: result.value }] : []);
    try { if (values.length) await commit(values, controller.signal); }
    catch (error) { if (!controller.signal.aborted) failed(undefined, error); }
    if (controller.signal.aborted) return;
    results.forEach((result, index) => { if (result.status === "rejected") failed(ids[index], result.reason); });
    cancelTimer = schedule(poll, delay);
  }
  if (ids.length) cancelTimer = schedule(poll, delay);
  return () => { controller.abort(); cancelTimer?.(); };
}
