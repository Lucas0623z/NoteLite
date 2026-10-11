import test from "node:test";
import assert from "node:assert/strict";
import type { CloudJob, NoteListing } from "../src/app/cloud.ts";
import { startJobPolling } from "../src/app/job-polling.ts";
import { RemoteScoreLoader, type RemoteSnapshot, type SavedScore } from "../src/app/remote-score.ts";
import { ScoreStatus, type ScoreStatusVersion } from "../src/app/score-status.ts";

const id = "11111111-1111-4111-8111-111111111111";
const secondId = "22222222-2222-4222-8222-222222222222";
function job(revision: number, state: CloudJob["state"] = "succeeded", jobId = id): CloudJob { return { id: jobId, filename: "练习.png", state, revision, scores: [], artifacts: {} }; }
function notes(revision: number): NoteListing { return { jobId: id, revision, score: 0, parts: [], notes: [] }; }
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function clock() {
  const scheduled: { callback: () => Promise<void>; delay: number; cancelled: boolean }[] = [];
  const schedule = (callback: () => Promise<void>, delay: number) => {
    const timer = { callback, delay, cancelled: false }; scheduled.push(timer);
    return () => { timer.cancelled = true; };
  };
  return { schedule, scheduled };
}

test("a poll commits both jobs only after the entire round, even when A keeps running", async () => {
  const a = deferred<CloudJob>(); const b = deferred<CloudJob>(); const timers = clock();
  const commits: string[][] = [];
  const stop = startJobPolling({ ids: [id, secondId], schedule: timers.schedule,
    read: (key) => key === id ? a.promise : b.promise,
    commit: async (values) => { commits.push(values.map(({ value }) => `${value.id}:${value.state}`)); },
    failed: () => assert.fail("no failure expected"),
  });
  const round = timers.scheduled[0].callback();
  a.resolve(job(0, "running")); await Promise.resolve(); await Promise.resolve();
  assert.equal(commits.length, 0, "A must not cause cleanup before B's response");
  b.resolve(job(1, "succeeded", secondId)); await round;
  assert.deepEqual(commits, [[`${id}:running`, `${secondId}:succeeded`]]);
  assert.equal(timers.scheduled.length, 2); assert.equal(timers.scheduled[1].delay, 3000);
  stop();
});

test("unchanged waiting IDs schedule another complete round after state updates", async () => {
  const timers = clock(); let reads = 0; let commits = 0;
  const stop = startJobPolling({ ids: [id, secondId], schedule: timers.schedule,
    read: async (key) => { reads++; return job(0, "running", key); },
    commit: async (values) => { assert.equal(values.length, 2); commits++; }, failed: () => assert.fail(),
  });
  await timers.scheduled[0].callback(); await timers.scheduled[1].callback();
  assert.equal(reads, 4); assert.equal(commits, 2); assert.equal(timers.scheduled.length, 3);
  stop();
});

test("stopping a poll before responses arrive prevents storage/UI commits and rescheduling", async () => {
  const response = deferred<CloudJob>(); const timers = clock(); let commits = 0; let failures = 0;
  const stop = startJobPolling({ ids: [id], schedule: timers.schedule, read: () => response.promise,
    commit: async () => { commits++; }, failed: () => { failures++; },
  });
  const round = timers.scheduled[0].callback(); stop(); response.resolve(job(1)); await round;
  assert.equal(commits, 0); assert.equal(failures, 0); assert.equal(timers.scheduled.length, 1);
});

test("stopping during persistence aborts its signal and prevents a late next round", async () => {
  const persisted = deferred<void>(); const entered = deferred<AbortSignal>(); const timers = clock();
  const stop = startJobPolling({ ids: [id], schedule: timers.schedule, read: async () => job(1),
    commit: async (_values, signal) => { entered.resolve(signal); await persisted.promise; }, failed: () => assert.fail(),
  });
  const round = timers.scheduled[0].callback(); const signal = await entered.promise;
  stop(); assert.equal(signal.aborted, true); persisted.resolve(); await round;
  assert.equal(timers.scheduled.length, 1);
});

test("one rejected job preserves other results, reports its own ID, and continues polling", async () => {
  const timers = clock(); const failures: (string | undefined)[] = []; const committed: string[] = [];
  const stop = startJobPolling({ ids: [id, secondId], schedule: timers.schedule,
    read: async (key) => { if (key === id) throw new Error("offline"); return job(1, "succeeded", key); },
    commit: async (values) => { committed.push(...values.map(({ id }) => id)); }, failed: (key) => { failures.push(key); },
  });
  await timers.scheduled[0].callback();
  assert.deepEqual(committed, [secondId]); assert.deepEqual(failures, [id]); assert.equal(timers.scheduled.length, 2);
  stop();
});

test("21 waiting jobs all complete through a transport that rejects a seventeenth concurrent request", async () => {
  const ids = Array.from({ length: 21 }, (_, index) => `job-${index}`);
  const timers = clock(); let active = 0; let maximum = 0; let busyRejections = 0; let commits = 0;
  const installed: string[] = [];
  const stop = startJobPolling({ ids, schedule: timers.schedule,
    read: async (key) => {
      if (active >= 16) { busyRejections++; throw new Error("native bridge busy"); }
      active++; maximum = Math.max(maximum, active);
      // Keep requests in flight long enough to expose an unbounded map's bridge rejection.
      await Promise.resolve(); await Promise.resolve();
      active--; return job(1, "succeeded", key);
    },
    commit: async (values) => { commits++; installed.push(...values.map(({ value }) => value.id)); },
    failed: (_key, error) => assert.fail(String(error)),
  });
  await timers.scheduled[0].callback();
  assert.deepEqual(installed, ids, "all jobs, including those beyond the native limit, must reach the single batch");
  assert.equal(commits, 1); assert.equal(busyRejections, 0); assert.equal(active, 0);
  assert.ok(maximum <= 4, "polling must retain bridge capacity for user operations");
  stop();
});

test("cancelling a large poll leaves its queued requests unstarted", async () => {
  const ids = Array.from({ length: 21 }, (_, index) => `job-${index}`); const timers = clock();
  const pending: { key: string; response: ReturnType<typeof deferred<CloudJob>> }[] = []; let commits = 0;
  const stop = startJobPolling({ ids, schedule: timers.schedule,
    read: (key) => { const response = deferred<CloudJob>(); pending.push({ key, response }); return response.promise; },
    commit: async () => { commits++; }, failed: () => assert.fail(),
  });
  const round = timers.scheduled[0].callback(); assert.equal(pending.length, 4);
  stop(); pending.forEach(({ key, response }) => response.resolve(job(1, "succeeded", key))); await round;
  assert.equal(pending.length, 4, "the remaining 17 reads must not start after cancellation");
  assert.equal(commits, 0); assert.equal(timers.scheduled.length, 1);
});

function harness(transport: ConstructorParameters<typeof RemoteScoreLoader>[0]) {
  const loaded: { snapshot: RemoteSnapshot; saved?: SavedScore }[] = [];
  const failed: { error: unknown; saved?: SavedScore }[] = [];
  const state = { locked: false, recovery: "", loading: 0 };
  const loader = new RemoteScoreLoader(transport, {
    loading: () => { state.loading++; state.locked = true; },
    loaded: (snapshot, saved) => { loaded.push({ snapshot, saved }); state.locked = false; state.recovery = ""; },
    failed: (error, saved) => { failed.push({ error, saved }); state.locked = true; state.recovery = saved ? "saved-but-not-loaded" : "not-loaded"; },
  });
  return { loader, loaded, failed, state };
}

for (const kind of ["notes", "xml"] as const) test(`a committed ${kind} write with a failed read stays locked until an actual successful reload`, async () => {
  let offline = true; let writes = 0;
  const { loader, loaded, failed, state } = harness({ job: async () => job(2), notes: async () => { if (offline) throw new Error("GET interrupted"); return notes(2); }, score: async () => "<score-partwise />" });
  const saved = await loader.save(async () => { writes++; return job(2); }, 0, kind);
  assert.equal(saved.load.kind, "failed"); assert.equal(writes, 1); assert.equal(loaded.length, 0);
  assert.equal(failed[0].saved?.revision, 2); assert.equal(failed[0].saved?.kind, kind);
  assert.equal(state.locked, true); assert.equal(state.recovery, "saved-but-not-loaded");
  offline = false; const recovered = await loader.load(job(2), 0);
  assert.equal(recovered.kind, "loaded"); assert.equal(state.locked, false); assert.equal(state.recovery, "");
  assert.equal(loader.isInstalled(job(2), 0), true); assert.equal(loader.isInstalled(job(2), 1), false);
  assert.equal(loaded[0].saved?.revision, 2, "recovery keeps the authoritative successful write context");
  offline = true; await loader.load(job(2), 0);
  assert.equal(failed[1].saved, undefined, "a later unrelated read failure is not reported as an unconfirmed save");
});

for (const rejected of [false, true]) test(`a superseded read's late ${rejected ? "failure" : "success"} cannot overwrite the newer installed snapshot`, async () => {
  const old = deferred<CloudJob>(); let calls = 0; let noteReads = 0;
  const { loader, loaded, failed } = harness({ job: async () => ++calls === 1 ? old.promise : job(2), notes: async () => { noteReads++; return notes(2); }, score: async () => "revision-2" });
  const previous = loader.load(job(1), 0); const current = await loader.load(job(2), 0);
  assert.equal(current.kind, "loaded");
  if (rejected) old.reject(new Error("old GET failure")); else old.resolve(job(1));
  assert.equal((await previous).kind, "superseded"); assert.equal(loaded.length, 1); assert.equal(failed.length, 0);
  assert.equal(loaded[0].snapshot.musicxml, "revision-2"); assert.equal(noteReads, 1);
});

test("a props-driven read that supersedes save's explicit read retains the committed recovery context", async () => {
  const old = deferred<CloudJob>(); const entered = deferred<void>(); let calls = 0; let offline = true;
  const { loader, loaded, failed, state } = harness({
    job: async () => { if (++calls === 1) { entered.resolve(); return old.promise; } return job(2); },
    notes: async () => { if (offline) throw new Error("newest GET fails"); return notes(2); }, score: async () => "revision-2",
  });
  const save = loader.save(async () => job(2), 0, "notes"); await entered.promise;
  assert.equal((await loader.load(job(2), 0)).kind, "failed"); old.resolve(job(2));
  assert.equal((await save).load.kind, "superseded"); assert.equal(failed.length, 1); assert.equal(failed[0].saved?.revision, 2);
  assert.equal(state.locked, true); assert.equal(state.recovery, "saved-but-not-loaded");
  offline = false; assert.equal((await loader.load(job(2), 0)).kind, "loaded");
  assert.equal(loaded.length, 1); assert.equal(state.locked, false); assert.equal(state.recovery, "");
});

test("a consistent but older snapshot cannot unlock a newly committed revision", async () => {
  let revision = 1; let reads = 0;
  const { loader, loaded, failed, state } = harness({ job: async () => { reads++; return job(revision); }, notes: async () => notes(revision), score: async () => `revision-${revision}` });
  const result = await loader.save(async () => job(2), 0, "xml");
  assert.equal(result.load.kind, "failed"); assert.equal(reads, 6); assert.equal(loaded.length, 0);
  assert.equal(failed[0].saved?.revision, 2); assert.equal(state.locked, true);
  revision = 2; assert.equal((await loader.load(job(2), 0)).kind, "loaded"); assert.equal(state.locked, false);
});

test("unmounting during a write prevents late reload callbacks while preserving the write result", async () => {
  const response = deferred<CloudJob>(); let reads = 0;
  const { loader, loaded, failed, state } = harness({ job: async () => { reads++; return job(2); }, notes: async () => notes(2), score: async () => "revision-2" });
  const saving = loader.save(() => response.promise, 0, "notes"); loader.deactivate(); response.resolve(job(2));
  const result = await saving;
  assert.equal(result.job.revision, 2); assert.equal(result.load.kind, "superseded");
  assert.equal(reads, 0); assert.equal(state.loading, 0); assert.equal(loaded.length, 0); assert.equal(failed.length, 0);
});

test("reactivating after an effect cleanup permits a fresh read and ignores the previous response", async () => {
  const old = deferred<CloudJob>(); let calls = 0;
  const { loader, loaded, failed } = harness({ job: async () => ++calls === 1 ? old.promise : job(2), notes: async () => notes(2), score: async () => "revision-2" });
  const previous = loader.load(job(1), 0); loader.deactivate(); loader.activate();
  assert.equal((await loader.load(job(2), 0)).kind, "loaded"); old.reject(new Error("unmounted request"));
  assert.equal((await previous).kind, "superseded"); assert.equal(loaded.length, 1); assert.equal(failed.length, 0);
});

test("async layout cannot erase persisted feedback, cloud revision or uncertainty, and render failures remain visible", async () => {
  let visible = "";
  const status = new ScoreStatus((message) => { visible = message; });
  const initial: ScoreStatusVersion = { score: 0, revision: 0, xml: "original" };
  const saved = { ...initial, xml: "tempo-96" };
  status.select(initial);
  status.beginLayout(initial).ready("MusicXML 已载入");
  const persisted = deferred<void>();
  status.beginOperation();
  const save = persisted.promise.then(() => status.report("曲谱信息已保存到本机。", saved));
  assert.equal(visible, "MusicXML 已载入", "a pending persistence must not announce a successful save");
  persisted.resolve(); await save;
  assert.equal(visible, "曲谱信息已保存到本机。");
  const layoutLoaded = deferred<void>();
  const layout = status.beginLayout(saved);
  const render = layoutLoaded.promise.then(() => layout.ready("MusicXML 已载入"));
  assert.equal(visible, "曲谱信息已保存到本机。", "starting the changed XML's render must retain the actual save result");
  layoutLoaded.resolve(); await render;
  assert.equal(visible, "曲谱信息已保存到本机。", "a later successful render must also retain it");

  const badRender = deferred<void>();
  const failedLayout = status.beginLayout(saved);
  const renderFailed = badRender.promise.catch(() => failedLayout.failed("曲谱排版失败：无法绘制"));
  badRender.reject(new Error("cannot render")); await renderFailed;
  status.report("文件已导出。");
  assert.equal(visible, "曲谱排版失败：无法绘制", "a successful independent operation cannot hide the current render failure");
  const retry = status.beginLayout(saved);
  assert.equal(visible, "曲谱排版失败：无法绘制", "a retry must actually succeed before clearing that failure");
  retry.ready("MusicXML 已载入");
  assert.equal(visible, "文件已导出。");

  const committed = { jobId: id, score: 0, revision: 2, xml: "revision-2" };
  const remoteRead = deferred<string>();
  const loader = new RemoteScoreLoader({ job: async () => job(2), notes: async () => notes(2), score: () => remoteRead.promise }, {
    loading: () => { status.beginOperation(); status.report("正在载入最新曲谱…"); },
    loaded: ({ musicxml, listing }, write) => status.report(`${write?.kind === "xml" ? "完整曲谱已保存" : "曲谱已载入"} · 当前版本 ${listing.revision}`, { ...committed, xml: musicxml }),
    failed: () => assert.fail("the committed write and snapshot should be confirmed"),
  });
  const cloudSave = loader.save(async () => job(2), 0, "xml");
  await Promise.resolve(); await Promise.resolve();
  remoteRead.resolve("revision-2"); await cloudSave;
  const cloudLayout = status.beginLayout(committed);
  cloudLayout.ready("曲谱已载入 · 校对版本 2");
  assert.equal(visible, "完整曲谱已保存 · 当前版本 2");
  for (const warning of ["保存结果未知，请重新载入。", "曲谱已在另一设备修改，请重新载入。"] as const) {
    status.beginOperation(); status.report(warning);
    const resized = status.beginLayout(committed);
    await Promise.resolve(); resized.ready("曲谱已载入 · 校对版本 2");
    assert.equal(visible, warning, "an asynchronous zoom/reflow must not replace a write warning");
  }
  const oldLayout = status.beginLayout(committed);
  const newer = { ...committed, revision: 3, xml: "revision-3" };
  status.select(newer);
  const newLayout = status.beginLayout(newer);
  newLayout.ready("曲谱已载入 · 校对版本 3");
  await Promise.resolve(); oldLayout.ready("曲谱已载入 · 校对版本 2");
  oldLayout.failed("旧版本排版失败");
  assert.equal(visible, "曲谱已载入 · 校对版本 3", "switching versions clears old feedback and rejects both late outcomes from the old render");
});
