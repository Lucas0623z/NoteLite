import { positionAt } from "./score-position.ts";
import type { NoteKey, PlaybackNote, ScoreTimeline } from "./score-position.ts";

export type PlaybackState = "stopped" | "playing" | "paused";
export type SoundEngine = {
  readonly currentTime: number;
  resume(): Promise<void>;
  suspend(): Promise<void>;
  close(): Promise<void>;
  tone(note: PlaybackNote, start: number, duration: number, tuning: number): void;
  stopTones(): void;
};

/** Audio clock owns both sound and cursor; the UI timer only requests updates. */
export function createScorePlayback(options: {
  engine: () => SoundEngine;
  position: (keys: NoteKey[]) => void;
  state: (state: PlaybackState) => void;
  ended?: () => void;
  error?: (error: Error) => void;
  timer?: (callback: () => void) => () => void;
}) {
  let engine: SoundEngine | undefined, timeline: ScoreTimeline | undefined;
  let state: PlaybackState = "stopped", origin = 0, ratio = 1, tuning = 440, index = 0, generation = 0;
  let cancelTimer: (() => void) | undefined, lastPosition = "";
  const publish = (next: PlaybackState) => { state = next; options.state(next); };
  const position = (keys: NoteKey[]) => {
    const signature = JSON.stringify(keys);
    if (signature !== lastPosition) { lastPosition = signature; options.position(keys); }
  };
  function stop() {
    generation++;
    cancelTimer?.(); cancelTimer = undefined;
    const current = engine; engine = undefined; timeline = undefined;
    current?.stopTones(); void current?.close().catch(() => {});
    position([]); publish("stopped");
  }
  function tick() {
    if (state !== "playing" || !engine || !timeline) return;
    const now = engine.currentTime;
    const elapsed = Math.max(0, now - origin) * ratio;
    if (elapsed >= timeline.duration) { stop(); options.ended?.(); return; }
    // Short horizon bounds the number of future voices, including long scores.
    while (index < timeline.notes.length && origin + timeline.notes[index].start / ratio <= now + .12) {
      const note = timeline.notes[index++], end = origin + note.end / ratio;
      if (origin + note.start / ratio < now - .15) throw new Error("设备暂停了音频调度，试听已停止。请重新开始试听。");
      if (end > now) engine.tone(note, Math.max(now, origin + note.start / ratio), end - Math.max(now, origin + note.start / ratio), tuning);
    }
    if (now >= origin) position(positionAt(timeline, elapsed));
  }
  return {
    async start(score: ScoreTimeline, preferences: { bpm?: number; tuning?: number } = {}) {
      stop();
      if (!(score.duration > 0) || !score.positions.length) throw new Error("这份谱面没有可试听的音符。");
      const nextRatio = (preferences.bpm ?? score.initialTempo) / score.initialTempo;
      const nextTuning = preferences.tuning ?? 440;
      if (!(nextRatio > 0) || !Number.isFinite(nextRatio) || !(nextTuning > 0) || !Number.isFinite(nextTuning)) throw new Error("试听速度或调音无效。");
      const request = generation, created = options.engine(); engine = created;
      try {
        await created.resume();
        if (request !== generation) return;
        timeline = score; ratio = nextRatio; tuning = nextTuning; index = 0; origin = created.currentTime + .04;
        publish("playing"); tick();
        cancelTimer = (options.timer ?? ((callback) => { const id = window.setInterval(callback, 25); return () => window.clearInterval(id); }))(() => {
          try { tick(); } catch (error) { stop(); options.error?.(error instanceof Error ? error : new Error(String(error))); }
        });
      } catch (error) { if (request === generation) stop(); throw error; }
    },
    async pause() {
      if (state !== "playing" || !engine) return;
      const current = engine, request = generation;
      await current.suspend();
      if (current === engine && request === generation) { tick(); if (engine) publish("paused"); }
    },
    async resume() {
      if (state !== "paused" || !engine) return;
      const current = engine, request = generation;
      await current.resume();
      if (current === engine && request === generation) { publish("playing"); tick(); }
    },
    stop,
  };
}

/** Synthesized audition, not a microphone or instrument recognition engine. */
export function createWebAudioEngine(): SoundEngine {
  const Constructor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Constructor) throw new Error("当前设备不支持乐谱试听。");
  const context = new Constructor(), voices = new Set<OscillatorNode>();
  const master = context.createGain(); master.gain.value = .12; master.connect(context.destination);
  return {
    get currentTime() { return context.currentTime; },
    resume: () => context.resume(), suspend: () => context.suspend(), close: () => context.close(),
    tone(note, start, duration, tuning) {
      if (voices.size >= 128) throw new Error("同时发声音符过多，请先校对谱面。");
      const oscillator = context.createOscillator(), gain = context.createGain();
      oscillator.type = "triangle"; oscillator.frequency.value = tuning * 2 ** ((note.midi - 69) / 12);
      const end = start + duration, attack = Math.min(.012, duration / 4), release = Math.min(.035, duration / 3);
      gain.gain.setValueAtTime(0, start); gain.gain.linearRampToValueAtTime(1, start + attack);
      gain.gain.setValueAtTime(1, Math.max(start + attack, end - release)); gain.gain.linearRampToValueAtTime(0, end);
      oscillator.connect(gain); gain.connect(master); voices.add(oscillator);
      oscillator.onended = () => { voices.delete(oscillator); oscillator.disconnect(); gain.disconnect(); };
      oscillator.start(start); oscillator.stop(end);
    },
    stopTones() { for (const voice of voices) { try { voice.stop(); } catch { /* Already ended. */ } } voices.clear(); },
  };
}
