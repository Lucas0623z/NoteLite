import { useEffect, useRef, useState } from "react";

type Settings = { instrument: string; part: string; mode: string; bpm: number; tuning: number; first: number; last: number; checked: boolean };

export default function PracticeSession({ name, measures, parts }: { name: string; measures: number; parts: string[] }) {
  const [settings, setSettings] = useState<Settings>({ instrument: "钢琴 / 键盘", part: "全部声部", mode: "自由练习", bpm: 100, tuning: 440, first: 1, last: measures, checked: false });
  const [draft, setDraft] = useState(settings);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [running, setRunning] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [finished, setFinished] = useState(false);
  const [notice, setNotice] = useState("");
  const [sessions, setSessions] = useState<{ seconds: number; time: string }[]>([]);
  const [showRecords, setShowRecords] = useState(false);
  const settingsDialog = useRef<HTMLDialogElement>(null);
  const started = useRef(0);
  const accumulated = useRef(0);
  const valid = draft.bpm >= 30 && draft.bpm <= 240 && draft.tuning >= 400 && draft.tuning <= 480 && Number.isInteger(draft.first) && Number.isInteger(draft.last) && draft.first >= 1 && draft.last >= draft.first && draft.last <= measures;
  const time = (duration: number) => `${Math.floor(duration / 60).toString().padStart(2, "0")}:${(duration % 60).toString().padStart(2, "0")}`;

  useEffect(() => {
    if (settingsOpen) settingsDialog.current?.showModal();
    else settingsDialog.current?.close();
  }, [settingsOpen]);

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setSeconds(accumulated.current + Math.floor((Date.now() - started.current) / 1000)), 250);
    return () => window.clearInterval(timer);
  }, [running]);

  function start() {
    if (!settings.checked) { setDraft(settings); setSettingsOpen(true); setNotice("请先核对曲谱，并勾选开始前确认。"); return; }
    if (finished) { accumulated.current = 0; setSeconds(0); }
    started.current = Date.now(); setFinished(false); setRunning(true);
    setNotice("正在自由练习计时；尚未连接演奏输入，不生成音准或节奏评分。");
  }
  function pause() {
    accumulated.current += Math.floor((Date.now() - started.current) / 1000);
    setSeconds(accumulated.current); setRunning(false);
  }
  function finish() {
    const elapsed = running ? accumulated.current + Math.floor((Date.now() - started.current) / 1000) : seconds;
    setRunning(false); setSeconds(elapsed); accumulated.current = elapsed; setFinished(true);
    setSessions((previous) => [{ seconds: elapsed, time: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }) }, ...previous]);
    setNotice("本次计时已结束。记录仅保留在当前页面，不计入打卡或连胜。");
  }

  return <>
    <aside className="score-inspector practice-summary">
      <p className="score-eyebrow">本次练习</p><h2>{running ? "专注练琴中" : finished ? "练习已结束" : seconds ? "练习已暂停" : "准备好了吗？"}</h2>
      <div className="practice-clock" aria-label={`练习时长 ${time(seconds)}`}>{time(seconds)}</div>
      <p className="score-description">自由练习计时 · 不含演奏评分</p>
      <div className="practice-stat-grid"><div><span>首次弹对</span><strong>—</strong></div><div><span>错音</span><strong>—</strong></div></div>
      <section className="score-edit"><h3>需要再练的地方</h3><p className="score-description">连接演奏识别后，这里会显示需要复习的小节和音符。目前尚未接入 MIDI 或麦克风识别。</p></section>
      <button type="button" className="score-tool" onClick={() => setShowRecords(!showRecords)}>{showRecords ? "收起本次记录" : "本次记录"}</button>
      {showRecords && <div className="practice-records">{sessions.length ? sessions.map((session, index) => <p key={index}>{session.time}<strong>{time(session.seconds)}</strong></p>) : <p className="score-description">结束一次练习后，可在这里查看计时记录。</p>}</div>}
      <p className="score-description">演奏设备 · 尚未连接</p>
    </aside>
    <footer className="practice-controls">
      <button type="button" disabled={running} className="score-tool" onClick={() => { setDraft(settings); setSettingsOpen(true); setNotice(""); }}>练习设置</button>
      <div className="practice-control-actions">
        <button type="button" className="score-tool score-tool-primary" onClick={running ? pause : start}>{running ? "暂停练习" : seconds && !finished ? "继续练习" : "开始练习"}</button>
        <button type="button" disabled={finished || (!running && seconds === 0)} className="score-tool" onClick={finish}>结束</button>
        <button type="button" disabled={running} className="score-tool" onClick={() => setNotice("曲目试听尚未接入，当前可查看乐谱并自由练习计时。")}>试听</button>
      </div>
      <span className="practice-tempo">{settings.bpm} BPM · 第 {settings.first}–{settings.last} 小节</span>
      {notice && <p role="status" className="practice-notice">{notice}</p>}
    </footer>
    <dialog ref={settingsDialog} aria-labelledby="practice-settings-title" className="practice-settings-dialog" onCancel={(event) => { event.stopPropagation(); setSettingsOpen(false); }} onClose={(event) => { event.stopPropagation(); setSettingsOpen(false); }} onClick={(event) => { event.stopPropagation(); if (event.target === event.currentTarget) setSettingsOpen(false); }}>
      <form onSubmit={(event) => { event.preventDefault(); if (valid) { setSettings(draft); setSettingsOpen(false); setNotice("设置已更新。速度、调音及范围为本页偏好，暂不驱动演奏识别或乐谱裁切。"); } }}>
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
