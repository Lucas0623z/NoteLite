import { useEffect, useRef, useState } from "react";
import { createPerformancePositionReceiver, createScoreTimeline, noteKey } from "./score-position";
import type { NoteKey } from "./score-position";
import { createScorePlayback, createWebAudioEngine } from "./score-playback";
import type { PlaybackState } from "./score-playback";
import { account } from "./account";
import { practiceRecords, PRACTICE_RECORD_EVENT, newPracticeEventId, type PracticeRecord } from "./practice-records";

type Settings = { instrument: string; part: string; mode: string; bpm: number; tuning: number; first: number; last: number; checked: boolean };

export type PracticeSource = { kind: "official" | "personal"; scoreId: string; revision: number };
export default function PracticeSession({ name, measures, parts, musicxml, scoreIdentity, recordIdentity = scoreIdentity, source, onPosition }: { name: string; measures: number; parts: string[]; musicxml: string; scoreIdentity: string; recordIdentity?: string; source?: PracticeSource; onPosition: (keys: NoteKey[]) => void }) {
  const [settings, setSettings] = useState<Settings>({ instrument: "钢琴 / 键盘", part: "全部声部", mode: "自由练习", bpm: 100, tuning: 440, first: 1, last: measures, checked: false });
  const [draft, setDraft] = useState(settings);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [running, setRunning] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [finished, setFinished] = useState(false);
  const [notice, setNotice] = useState("");
  const [sessions, setSessions] = useState<PracticeRecord[]>([]);
  const [showRecords, setShowRecords] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  const [playbackState, setPlaybackState] = useState<PlaybackState>("stopped");
  const [performanceConnected, setPerformanceConnected] = useState(false);
  const playback = useRef<ReturnType<typeof createScorePlayback> | null>(null);
  const positionCallback = useRef(onPosition);
  positionCallback.current = onPosition;
  const settingsDialog = useRef<HTMLDialogElement>(null);
  const started = useRef(0);
  const accumulated = useRef(0);
  const activeRecord = useRef<{ eventId: string; owner: string; startedAt: string; name: string; musicxml: string; scoreIdentity: string; source?: PracticeSource; elapsed: number; anchor: number | null } | null>(null);
  const recordWriter = useRef<(interrupted?: boolean) => Promise<void>>(async () => {});
  const pendingSave = useRef<{ input: Omit<PracticeRecord, "userId" | "sync">; owner: string } | null>(null);
  const savingRecord = useRef(false);
  const valid = draft.bpm >= 30 && draft.bpm <= 240 && draft.tuning >= 400 && draft.tuning <= 480 && Number.isInteger(draft.first) && Number.isInteger(draft.last) && draft.first >= 1 && draft.last >= draft.first && draft.last <= measures;
  const time = (duration: number) => `${Math.floor(duration / 60).toString().padStart(2, "0")}:${(duration % 60).toString().padStart(2, "0")}`;

  useEffect(() => {
    let live = true;
    const reload = () => { void practiceRecords.local().then((records) => { if (live) setSessions(records.filter((record) => record.scoreIdentity === recordIdentity)); }).catch(() => { if (live) setNotice("无法读取本机练习记录，请检查存储权限。"); }); };
    reload(); window.addEventListener(PRACTICE_RECORD_EVENT, reload);
    return () => { live = false; window.removeEventListener(PRACTICE_RECORD_EVENT, reload); };
  }, [recordIdentity]);
  recordWriter.current = async (interrupted = false) => {
    if (savingRecord.current) return;
    const current = activeRecord.current;
    if (current) {
      activeRecord.current = null;
      const elapsed = Math.max(0, Math.floor((current.elapsed + (current.anchor === null ? 0 : performance.now() - current.anchor)) / 1000));
      pendingSave.current = { owner: current.owner, input: { eventId: current.eventId, name: current.name, musicxml: current.musicxml, scoreIdentity: current.scoreIdentity, sourceKind: current.source?.kind || "local", scoreId: current.source?.scoreId, scoreRevision: current.source?.revision, mode: "free", durationSeconds: elapsed, startedAt: current.startedAt, endedAt: new Date().toISOString(), interrupted } };
    }
    const pending = pendingSave.current;
    if (!pending) return;
    savingRecord.current = true;
    try {
      const record = await practiceRecords.save(pending.input, pending.owner);
      pendingSave.current = null;
      if (!interrupted) setSaveFailed(false);
      if (!interrupted) setNotice(record.userId === "guest" ? "练习记录已保存在本机 · 自由计时，未分析演奏。" : "练习记录已保存在本机，正在同步 · 未分析演奏。");
      const result = await practiceRecords.sync(record);
      if (!interrupted && result.userId !== "guest") setNotice(result.sync === "synced" ? "练习记录已同步到当前账户 · 自由计时，未分析演奏。" : "练习记录已保存在本机，网络恢复后重试同步。可在练习历史查看状态。");
    } catch { if (!interrupted) { setSaveFailed(pendingSave.current !== null); setNotice(pendingSave.current ? "本机存储未能保存练习记录，请检查存储空间后点击重试保存。关闭此页面前请完成保存。" : "练习记录已保存在本机，同步状态待确认。请在练习历史重新读取。"); } }
    finally { savingRecord.current = false; }
  };
  useEffect(() => () => { void recordWriter.current(true); }, [scoreIdentity]);

  useEffect(() => {
    const controller = createScorePlayback({ engine: createWebAudioEngine, position: (keys) => positionCallback.current(keys), state: setPlaybackState, ended: () => setNotice("试听已结束。可再次试听，或开始自由练习。"), error: (error) => setNotice(error.message) });
    playback.current = controller;
    setPerformanceConnected(false);
    const document = new DOMParser().parseFromString(musicxml, "application/xml"), knownNotes = new Set<string>();
    const direct = (parent: Node, name: string) => Array.from(parent.childNodes).filter((node): node is Element => node.nodeType === 1 && (node as Element).localName === name);
    for (const part of direct(document.documentElement, "part")) direct(part, "measure").forEach((measure, measureIndex) => direct(measure, "note").forEach((_note, noteIndex) => knownNotes.add(noteKey({ partId: part.getAttribute("id") || "", measureIndex, noteIndex }))));
    const receiver = createPerformancePositionReceiver(scoreIdentity, (keys) => {
      if (playback.current === controller) positionCallback.current(keys);
    }, knownNotes);
    const event = (message: Event) => {
      if (receiver.accept((message as CustomEvent).detail)) { controller.stop(); setPerformanceConnected(true); positionCallback.current((message as CustomEvent).detail.notes); }
    };
    window.addEventListener("notelite-cloud-event", event);
    // Initialize audition from the score's tempo; free practice time stays separate.
    try { const bpm = createScoreTimeline(musicxml).initialTempo; setSettings((previous) => ({ ...previous, bpm, last: measures })); } catch { /* Show the precise notation error when audition is requested. */ }
    return () => { window.removeEventListener("notelite-cloud-event", event); receiver.dispose(); controller.stop(); if (playback.current === controller) playback.current = null; };
  }, [musicxml, scoreIdentity, measures]);

  async function audition() {
    try {
      if (playbackState === "playing") { await playback.current?.pause(); setNotice("试听已暂停，谱面指针停在当前音符。"); }
      else if (playbackState === "paused") { await playback.current?.resume(); setNotice("正在试听 · 合成音色 · 指针跟随声音。"); }
      else {
        const timeline = createScoreTimeline(musicxml);
        setPerformanceConnected(false);
        await playback.current?.start(timeline, { bpm: settings.bpm, tuning: settings.tuning });
        setNotice(`正在试听整份曲谱 · 合成音色 · 指针跟随声音。${timeline.warnings.join(" ")}`);
      }
    } catch (error) { setNotice(error instanceof Error ? error.message : "试听未能启动，请重试。"); }
  }

  useEffect(() => {
    if (settingsOpen) settingsDialog.current?.showModal();
    else settingsDialog.current?.close();
  }, [settingsOpen]);

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setSeconds(accumulated.current + Math.max(0, Math.floor((performance.now() - started.current) / 1000))), 250);
    return () => window.clearInterval(timer);
  }, [running]);

  function start() {
    if (pendingSave.current) { setNotice("上一次练习记录尚未保存，请先重试保存。"); return; }
    if (!settings.checked) { setDraft(settings); setSettingsOpen(true); setNotice("请先核对曲谱，并勾选开始前确认。"); return; }
    if (finished) { accumulated.current = 0; setSeconds(0); }
    playback.current?.stop(); started.current = performance.now(); setFinished(false); setRunning(true);
    if (!activeRecord.current) activeRecord.current = { eventId: newPracticeEventId(), owner: account.current?.userId || "guest", startedAt: new Date().toISOString(), name, musicxml, scoreIdentity: recordIdentity, source, elapsed: 0, anchor: started.current };
    else activeRecord.current.anchor = started.current;
    setNotice("正在自由练习计时；尚未连接演奏输入，不生成音准或节奏评分。");
  }
  function pause() {
    accumulated.current += Math.max(0, Math.floor((performance.now() - started.current) / 1000));
    if (activeRecord.current?.anchor !== null && activeRecord.current) { activeRecord.current.elapsed += performance.now() - activeRecord.current.anchor!; activeRecord.current.anchor = null; }
    setSeconds(accumulated.current); setRunning(false);
  }
  function finish() {
    if (!activeRecord.current) return;
    const elapsed = running ? accumulated.current + Math.max(0, Math.floor((performance.now() - started.current) / 1000)) : seconds;
    setRunning(false); setSeconds(elapsed); accumulated.current = elapsed; setFinished(true);
    void recordWriter.current();
  }

  return <>
    <aside className="score-inspector practice-summary">
      <p className="score-eyebrow">本次练习</p><h2>{running ? "专注练琴中" : finished ? "练习已结束" : seconds ? "练习已暂停" : "准备好了吗？"}</h2>
      <div className="practice-clock" aria-label={`练习时长 ${time(seconds)}`}>{time(seconds)}</div>
      <p className="score-description">自由练习计时 · 不含演奏评分</p>
      <div className="practice-stat-grid"><div><span>首次弹对</span><strong>—</strong></div><div><span>错音</span><strong>—</strong></div></div>
      <section className="score-edit"><h3>需要再练的地方</h3><p className="score-description">连接演奏识别后，这里会显示需要复习的小节和音符。目前尚未接入 MIDI 或麦克风识别。</p></section>
      <button type="button" className="score-tool" onClick={() => setShowRecords(!showRecords)}>{showRecords ? "收起练习记录" : "练习记录"}</button>
      {saveFailed && <button type="button" className="score-tool" onClick={() => void recordWriter.current()}>重试保存练习记录</button>}
      {showRecords && <div className="practice-records">{sessions.length ? sessions.map((session) => <p key={session.eventId}>{new Date(session.endedAt).toLocaleString("zh-CN")}<strong>{time(session.durationSeconds)} · {session.sync === "synced" ? "已同步" : session.sync === "pending" ? "待同步" : "本机"} · 未分析</strong></p>) : <p className="score-description">结束一次练习后，可在这里查看保存的计时记录。</p>}</div>}
      <p className="score-description">演奏指针 · {performanceConnected ? "已收到演奏跟谱位置" : "等待连接 MIDI 或麦克风跟谱"}</p>
      <p className="score-description">试听指针 · {playbackState === "playing" ? "随声音移动" : playbackState === "paused" ? "已暂停" : "点击试听后显示"}</p>
    </aside>
    <footer className="practice-controls">
      <button type="button" disabled={running} className="score-tool" onClick={() => { setDraft(settings); setSettingsOpen(true); setNotice(""); }}>练习设置</button>
      <div className="practice-control-actions">
        <button type="button" className="score-tool score-tool-primary" onClick={running ? pause : start}>{running ? "暂停练习" : seconds && !finished ? "继续练习" : "开始练习"}</button>
        <button type="button" disabled={finished || (!running && seconds === 0)} className="score-tool" onClick={finish}>结束</button>
        <button type="button" disabled={running} className="score-tool" onClick={() => void audition()}>{playbackState === "playing" ? "暂停试听" : playbackState === "paused" ? "继续试听" : "试听"}</button>
        {playbackState !== "stopped" && <button type="button" className="score-tool" onClick={() => { playback.current?.stop(); setNotice("试听已停止。"); }}>停止试听</button>}
      </div>
      <span className="practice-tempo">{settings.bpm} BPM · 第 {settings.first}–{settings.last} 小节</span>
      {notice && <p role="status" className="practice-notice">{notice}</p>}
    </footer>
    <dialog ref={settingsDialog} aria-labelledby="practice-settings-title" className="practice-settings-dialog" onCancel={(event) => { event.stopPropagation(); setSettingsOpen(false); }} onClose={(event) => { event.stopPropagation(); setSettingsOpen(false); }} onClick={(event) => { event.stopPropagation(); if (event.target === event.currentTarget) setSettingsOpen(false); }}>
      <form onSubmit={(event) => { event.preventDefault(); if (valid) { playback.current?.stop(); setSettings(draft); setSettingsOpen(false); setNotice("设置已更新。试听使用速度与调音，播放整份曲谱；小节范围与声部暂仅保存为练习偏好。"); } }}>
        <header className="practice-settings-header"><h2 id="practice-settings-title">练习设置</h2><button type="submit" className="score-tool" disabled={!valid}>完成</button></header>
        <section className="score-tool-section"><h3>乐器与输入</h3>
          <label className="score-field">乐器<select value={draft.instrument} onChange={(event) => setDraft({ ...draft, instrument: event.currentTarget.value })}>{["钢琴 / 键盘", "长笛", "小提琴", "大提琴", "其他乐器"].map((value) => <option key={value}>{value}</option>)}</select></label>
          <label className="score-field">练习声部<select value={draft.part} onChange={(event) => setDraft({ ...draft, part: event.currentTarget.value })}><option>全部声部</option>{parts.map((part) => <option key={part}>{part}</option>)}</select></label>
          <label className="score-field">演奏输入<select disabled><option>自由练习 · 仅计时</option></select></label>
          <p>MIDI 与麦克风识别尚未接入，当前不采集你的演奏。</p>
        </section>
        <section className="score-tool-section"><h3>练习方式</h3>
          <label className="score-field">模式<select value={draft.mode} onChange={(event) => setDraft({ ...draft, mode: event.currentTarget.value })}><option>自由练习</option><option disabled>等我弹对（尚未接入）</option><option disabled>跟随节奏（尚未接入）</option></select></label>
          <div className="practice-settings-grid">
            <label className="score-field">速度 BPM<input type="number" min={30} max={240} required value={draft.bpm} onChange={(event) => setDraft({ ...draft, bpm: event.currentTarget.valueAsNumber })} /></label>
            <label className="score-field">调音 A4 · Hz<input type="number" min={400} max={480} required value={draft.tuning} onChange={(event) => setDraft({ ...draft, tuning: event.currentTarget.valueAsNumber })} /></label>
            <label className="score-field">起始小节<input type="number" min={1} max={measures} required value={draft.first} onChange={(event) => setDraft({ ...draft, first: event.currentTarget.valueAsNumber })} /></label>
            <label className="score-field">结束小节<input type="number" min={draft.first} max={measures} required value={draft.last} onChange={(event) => setDraft({ ...draft, last: event.currentTarget.valueAsNumber })} /></label>
          </div>
          {!valid && <p role="status">请检查速度、调音和小节范围。</p>}
        </section>
        <section className="score-tool-section"><h3>开始前确认</h3><p className="score-filename">{name}</p><label className="practice-confirm"><input type="checkbox" checked={draft.checked} onChange={(event) => setDraft({ ...draft, checked: event.currentTarget.checked })} />我已对照原稿核对乐谱</label><p>当前设置仅用于自由练习，不会生成演奏分析结果。</p></section>
      </form>
    </dialog>
  </>;
}
