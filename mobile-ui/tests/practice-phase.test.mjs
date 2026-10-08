import test from "node:test";
import assert from "node:assert/strict";
import ts from "typescript";
import { readFileSync } from "node:fs";
const source = readFileSync(new URL("../src/app/practice-phase.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { watchPracticePhase } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

function observerHarness() {
  let phase = "idle", callback = null, disconnects = 0;
  const queue = [];
  return {
    read: () => phase,
    subscribe(listener) { callback = listener; return () => { callback = null; disconnects++; }; },
    mutate(next) { phase = next; if (callback) queue.push(callback); },
    drain() { let delivered = 0; while (queue.length) { assert.ok(++delivered < 20, "phase observer entered an infinite microtask loop"); queue.shift()(); } return delivered; },
    disconnects: () => disconnects,
  };
}
test("saving after finished cannot recurse when a legacy finish writes the same phase", () => {
  const harness = observerHarness(); let saved = 0;
  watchPracticePhase(harness.read, harness.subscribe, () => { saved++; harness.mutate("finished"); });
  harness.mutate("active"); harness.drain();
  harness.mutate("finished"); assert.equal(harness.drain(), 2);
  assert.equal(saved, 1);
  harness.mutate("finished"); harness.drain(); assert.equal(saved, 1);
});
test("retrying a new session produces one save per genuine finished transition", () => {
  const harness = observerHarness(); let saved = 0;
  watchPracticePhase(harness.read, harness.subscribe, () => { saved++; });
  for (const phase of ["active", "finished", "finished", "idle", "active", "paused", "active", "finished"]) { harness.mutate(phase); harness.drain(); }
  assert.equal(saved, 2);
});
test("disconnect suppresses already queued callbacks and is idempotent", () => {
  const harness = observerHarness(); let saved = 0;
  const stop = watchPracticePhase(harness.read, harness.subscribe, () => { saved++; });
  harness.mutate("finished"); stop(); stop(); harness.drain();
  assert.equal(saved, 0); assert.equal(harness.disconnects(), 1);
});
