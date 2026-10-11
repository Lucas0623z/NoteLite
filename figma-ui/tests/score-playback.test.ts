import test from "node:test";
import assert from "node:assert/strict";
import { createScorePlayback } from "../src/app/score-playback.ts";
import type { SoundEngine } from "../src/app/score-playback.ts";
import type { ScoreTimeline } from "../src/app/score-position.ts";

const keys = [0, 1].map(noteIndex => ({ partId: "P1", measureIndex: 0, noteIndex }));
const timeline: ScoreTimeline = { duration: 2, initialTempo: 60, warnings: [], positions: keys.map((key, i) => ({ keys: [key], start: i })), notes: keys.map((key, i) => ({ key, start: i, end: i + 1, midi: 60 + i, tieStart: false, tieStop: false, voiceKey: String(i) })) };
function setup() {
  let clock = 10, update = () => {}, cancelled = 0, closed = 0, stopped = 0;
  const positions: unknown[] = [], states: string[] = [], tones: unknown[][] = [];
  const engine: SoundEngine = { get currentTime() { return clock; }, resume: async () => {}, suspend: async () => {}, close: async () => { closed++; }, stopTones: () => { stopped++; }, tone: (...args) => tones.push(args) };
  const controller = createScorePlayback({ engine: () => engine, position: keys => positions.push(keys), state: state => states.push(state), timer: callback => { update = callback; return () => { cancelled++; }; } });
  return { controller, positions, states, tones, tick: (now: number) => { clock = now; update(); }, counts: () => ({ cancelled, closed, stopped }) };
}
test("wall-clock polling cannot move cursor; same audio clock schedules sound and position", async () => {
  const rig = setup(); await rig.controller.start(timeline);
  assert.equal(rig.tones.length, 1); assert.deepEqual(rig.tones[0].slice(1), [10.04, 1, 440]);
  rig.tick(10); rig.tick(10); assert.deepEqual(rig.positions, [[]]);
  rig.tick(10.05); assert.deepEqual(rig.positions[1], [keys[0]]);
  rig.tick(11.05); assert.deepEqual(rig.positions[2], [keys[1]]); assert.equal(rig.tones.length, 2);
  rig.tick(12.05); assert.deepEqual(rig.positions[3], []); assert.equal(rig.states.at(-1), "stopped");
  assert.deepEqual(rig.counts(), { cancelled: 1, closed: 1, stopped: 1 });
});
test("pause freezes cursor, resume uses suspended audio clock, stop clears scheduled voices", async () => {
  const rig = setup(); await rig.controller.start(timeline); rig.tick(10.5);
  await rig.controller.pause(); const count = rig.positions.length;
  rig.tick(11.5); assert.equal(rig.positions.length, count); assert.equal(rig.tones.length, 1);
  // A real suspended AudioContext freezes here; resumption continues its time.
  rig.tick(10.5); await rig.controller.resume(); rig.tick(11.1);
  assert.deepEqual(rig.positions.at(-1), [keys[1]]);
  rig.controller.stop(); rig.tick(15); assert.deepEqual(rig.positions.at(-1), []);
  assert.equal(rig.states.at(-1), "stopped");
});
test("BPM scaling affects both tone start/duration and cursor; tuning reaches synthesis", async () => {
  const rig = setup(); await rig.controller.start(timeline, { bpm: 120, tuning: 442 });
  assert.deepEqual(rig.tones[0].slice(1), [10.04, .5, 442]);
  rig.tick(10.55); assert.deepEqual(rig.positions.at(-1), [keys[1]]);
  rig.tick(11.05); assert.equal(rig.states.at(-1), "stopped");
});
test("stopping during audio unlock prevents late start or leaked timer", async () => {
  let unlock!: () => void, timers = 0, closed = 0;
  const controller = createScorePlayback({ engine: () => ({ currentTime: 0, resume: () => new Promise<void>(resolve => { unlock = resolve; }), suspend: async () => {}, close: async () => { closed++; }, tone: () => assert.fail("late sound"), stopTones: () => {} }), position: () => {}, state: () => {}, timer: () => { timers++; return () => {}; } });
  const pending = controller.start(timeline); controller.stop(); unlock(); await pending;
  assert.equal(timers, 0); assert.equal(closed, 1);
});
test("a throttled scheduler reports interruption instead of silently skipping unsounded notes", async () => {
  let clock = 0, tick = () => {}, error = "", stopped = false;
  const controller = createScorePlayback({ engine: () => ({ get currentTime() { return clock; }, resume: async () => {}, suspend: async () => {}, close: async () => {}, tone: () => {}, stopTones: () => { stopped = true; } }), position: () => {}, state: () => {}, error: value => { error = value.message; }, timer: callback => { tick = callback; return () => {}; } });
  await controller.start(timeline); clock = 1.8; tick();
  assert.match(error, /暂停了音频调度/); assert.equal(stopped, true);
});
