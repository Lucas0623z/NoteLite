import { useEffect, useRef, useState } from "react";
import { createPerformancePositionReceiver, createScoreTimeline, noteKey } from "./score-position";
import type { NoteKey } from "./score-position";
import { createScorePlayback, createWebAudioEngine } from "./score-playback";
import type { PlaybackState } from "./score-playback";
import { account } from "./account";
import { practiceRecords, PRACTICE_RECORD_EVENT, newPracticeEventId, type PracticeRecord } from "./practice-records";
import { isNativeCloud, nativeRequest } from "./cloud";
import { expectedPerformance, NoteWiseInput, NoteWiseMatcher, refineRecording, scoreDigest, type InputKind, type NoteWiseFeedback, type NoteWiseSettings } from "./notewise";
import { INSTRUMENT_PROFILES, resolveProfile } from "./instrument-profiles";

type Settings = { instrument: string; instrumentVariant: string; part: string; mode: string; input:InputKind; bpm: number; tuning: number; first: number; last: number; checked: boolean };

export type PracticeSource = { kind: "official" | "personal"; scoreId: string; revision: number };
export default function PracticeSession({ name, measures, parts, musicxml, scoreIdentity, recordIdentity = scoreIdentity, source, onPosition, onFeedback }: { name: string; measures: number; parts: string[]; musicxml: string; scoreIdentity: string; recordIdentity?: string; source?: PracticeSource; onPosition: (keys: NoteKey[]) => void; onFeedback?: (values:NoteWiseFeedback["noteStates"])=>void }) {
  const [settings, setSettings] = useState<Settings>({ instrument: "piano", instrumentVariant:"concert", part: "全部声部", mode: "自由练习", input:"timer", bpm: 100, tuning: 440, first: 1, last: measures, checked: false });
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
  const [startingInput,setStartingInput]=useState(false);
  const [feedback,setFeedback]=useState<NoteWiseFeedback|null>(null);
  const matcher=useRef<NoteWiseMatcher|null>(null);
  const listening=useRef<NoteWiseInput|null>(null);
  const playback = useRef<ReturnType<typeof createScorePlayback> | null>(null);
  const positionCallback = useRef(onPosition);
  const feedbackCallback = useRef(onFeedback);feedbackCallback.current=onFeedback;
  positionCallback.current = onPosition;
  const settingsDialog = useRef<HTMLDialogElement>(null);
  const started = useRef(0);
  const accumulated = useRef(0);
  const activeRecord = useRef<{ eventId: string; owner: string; startedAt: string; name: string; musicxml: string; scoreIdentity: string; source?: PracticeSource; mode:PracticeRecord["mode"]; elapsed: number; anchor: number | null } | null>(null);
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
    savingRecord.current = true;
    try {
    const current = activeRecord.current;
    if (current) {
      activeRecord.current = null;
      const elapsed = Math.max(0, Math.floor((current.elapsed + (current.anchor === null ? 0 : performance.now() - current.anchor)) / 1000));
      let analysis=matcher.current?.finish(elapsed*1000,interrupted);
      matcher.current=null;
      const input=listening.current;listening.current=null;
      if(input) { try { const recording=await input.stop();if(analysis)analysis.recording=recording; } catch { if(analysis)analysis.status="uncertain"; } }
      pendingSave.current = { owner: current.owner, input: { eventId: current.eventId, name: current.name, musicxml: current.musicxml, scoreIdentity: current.scoreIdentity, sourceKind: current.source?.kind || "local", scoreId: current.source?.scoreId, scoreRevision: current.source?.revision, mode:current.mode, durationSeconds: elapsed, startedAt: current.startedAt, endedAt: new Date().toISOString(), interrupted,...(analysis?{analysis}:{}) } };
    }
    const pending = pendingSave.current;
    if (!pending) return;
      const record = await practiceRecords.save(pending.input, pending.owner);
      pendingSave.current = null;
      if (!interrupted) setSaveFailed(false);
      if (!interrupted) setNotice(record.userId === "guest" ? `练习记录已保存在本机 · ${record.analysis?"演奏机会与反馈已保存":"自由计时，未分析演奏"}。` : `练习记录已保存在本机，正在同步 · ${record.analysis?"含演奏机会与反馈":"未分析演奏"}。`);
      const result = await practiceRecords.sync(record);
      if (!interrupted && result.userId !== "guest") setNotice(result.sync === "synced" ? `练习记录已同步到当前账户 · ${result.analysis?.source==="client-reported"?"含演奏反馈，尚未独立复核":"自由计时，未分析演奏"}。` : "练习记录已保存在本机，网络恢复后重试同步。可在练习历史查看状态。");
      if(record.analysis?.schemaVersion===2 && record.analysis.recording?.available) {
        if(!interrupted)setNotice("练习已保存，正在本机复核录音中的和弦与复音；不会上传录音或调用 AI。");
        try {
          const reviewed=await refineRecording(record.analysis as import("./notewise").NoteWiseAnalysis);
          const revised=await practiceRecords.reviseAnalysis(result,reviewed);
          if(!interrupted)setNotice(revised.pendingAnalysis?"录后复核已在本机保存，云端分析版本待确认。":"录后复核已保存；实时记录与复核版本分别保留，疑似结果可在记录中查看。");
        }catch(error){if(!interrupted)setNotice(`实时练习记录已保存。录后复核未完成：${error instanceof Error?error.message:"请稍后重试"}`);}
      }
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
        const instrument=resolveProfile(settings.instrument),variant=instrument.variants.find(v=>v.id===settings.instrumentVariant);
        timeline.notes=timeline.notes.map(note=>({...note,midi:note.transposeExplicit?note.midi:(note.writtenMidi??note.midi)+(variant?.transpose||0)}));
        feedbackCallback.current?.([]);
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
    const timer = window.setInterval(() => { const elapsed=accumulated.current*1000+Math.max(0,performance.now()-started.current);setSeconds(Math.floor(elapsed/1000));matcher.current?.tick(elapsed); }, 100);
    return () => window.clearInterval(timer);
  }, [running]);

  async function start() {
    if(startingInput)return;
    if(savingRecord.current){setNotice("上一段练习正在保存和复核，完成后即可开始下一段。");return;}
    if (pendingSave.current) { setNotice("上一次练习记录尚未保存，请先重试保存。"); return; }
    if (!settings.checked) { setDraft(settings); setSettingsOpen(true); setNotice("请先核对曲谱，并勾选开始前确认。"); return; }
    if (finished) { accumulated.current = 0; setSeconds(0);setFeedback(null); }
    playback.current?.stop();setStartingInput(true);
    const eventId=activeRecord.current?.eventId||newPracticeEventId();
    try {
      if(settings.input!=="timer") {
        const options:NoteWiseSettings={...settings,inputKind:settings.input,mode:settings.mode==="跟随节奏"?"strict":settings.mode==="等我弹对"?"wait":"follow",scoreRevision:source?.revision};
        if(!matcher.current)matcher.current=new NoteWiseMatcher(expectedPerformance(musicxml,options),options,{takeId:eventId,sourceScoreSha256:await scoreDigest(musicxml)},value=>{setFeedback(value);positionCallback.current(value.position);feedbackCallback.current?.(value.noteStates);setPerformanceConnected(true);});
        if(!listening.current)listening.current=new NoteWiseInput(eventId,e=>matcher.current?.accept(e),message=>{pause();setNotice(`${message}。练习已暂停，不会将中断判为漏音。`);});
        await listening.current.start(options,settings.instrument);matcher.current.resume();setPerformanceConnected(true);
      }
      started.current = performance.now();setFinished(false);setRunning(true);
      if(!activeRecord.current)activeRecord.current={eventId,owner:account.current?.userId||"guest",startedAt:new Date().toISOString(),name,musicxml,scoreIdentity:recordIdentity,source,mode:settings.input==="timer"?"free":settings.mode==="跟随节奏"?"strict":"follow",elapsed:0,anchor:started.current};else activeRecord.current.anchor=started.current;
      setNotice(settings.input==="timer"?"正在自由练习计时；未采集演奏。":settings.input==="midi"?"已连接 MIDI · 指针跟随弹奏；错音会立即提示。":"麦克风已开始本地录音与单音听音 · 不清晰或和弦保留待复核；录音仅在你提交作业时上传。");
    } catch(error){setNotice(error instanceof Error?error.message:"输入未能连接。请检查后重试。");if(!activeRecord.current){matcher.current=null;listening.current=null;setPerformanceConnected(false);}}
    finally{setStartingInput(false);}
  }
  function pause() {
    if(!activeRecord.current || activeRecord.current.anchor===null)return;
    accumulated.current += Math.max(0, Math.floor((performance.now() - started.current) / 1000));
    if (activeRecord.current?.anchor !== null && activeRecord.current) { activeRecord.current.elapsed += performance.now() - activeRecord.current.anchor!; activeRecord.current.anchor = null; }
    setSeconds(accumulated.current); setRunning(false);
    matcher.current?.pause();void listening.current?.pause().catch(()=>setNotice("输入暂停状态待确认，请结束保存本次练习。"));
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
      <p className="score-description">{settings.input==="timer"?"自由练习计时 · 不含演奏评分":`${settings.mode} · ${settings.input==="midi"?"MIDI演奏":"本地麦克风听音"}`}</p>
      <div className="practice-stat-grid"><div><span>首次弹对</span><strong>{feedback?.correct??"—"}</strong></div><div><span>错音</span><strong>{feedback?.wrong??"—"}</strong></div></div>
      <section className="score-edit"><h3>需要再练的地方</h3><p className="score-description">{feedback?`${feedback.message}${feedback.pending?` · ${feedback.pending} 处待复核`:""}`:"在练习设置中选择 MIDI 或麦克风，开始后指针与反馈会跟随实际演奏。"}</p></section>
      <button type="button" className="score-tool" onClick={() => setShowRecords(!showRecords)}>{showRecords ? "收起练习记录" : "练习记录"}</button>
      {saveFailed && <button type="button" className="score-tool" onClick={() => void recordWriter.current()}>重试保存练习记录</button>}
      {showRecords && <div className="practice-records">{sessions.length ? sessions.map((session) => <div key={session.eventId}><p>{new Date(session.endedAt).toLocaleString("zh-CN")}<strong>{time(session.durationSeconds)} · {session.sync === "synced" ? "已同步" : session.sync === "pending" ? "待同步" : "本机"} · {session.analysis?.source==="client-reported"?`演奏反馈 ${session.analysis.errors?.length??0} 项`:"未分析"}</strong></p>{session.analysis&&"recording" in session.analysis&&session.analysis.recording?.available&&<button type="button" className="score-tool" onClick={()=>void nativeRequest("notewise/recording/play",{takeId:session.eventId}).catch(error=>setNotice(error instanceof Error?error.message:"录音未能播放"))}>播放本次录音</button>}</div>) : <p className="score-description">结束一次练习后，可在这里查看保存的计时记录。</p>}</div>}
      <p className="score-description">{`演奏指针 · ${performanceConnected ? "已收到演奏跟谱位置" : "等待连接 MIDI 或麦克风跟谱"}`}</p>
      <p className="score-description">{`试听指针 · ${playbackState === "playing" ? "随声音移动" : playbackState === "paused" ? "已暂停" : "点击试听后显示"}`}</p>
    </aside>
    <footer className="practice-controls">
      <button type="button" disabled={running||!!activeRecord.current||startingInput} className="score-tool" onClick={() => { setDraft(settings); setSettingsOpen(true); setNotice(""); }}>练习设置</button>
      <div className="practice-control-actions">
        <button type="button" disabled={startingInput} className="score-tool score-tool-primary" onClick={running ? pause : ()=>void start()}>{startingInput?"正在连接输入…":running ? "暂停练习" : seconds && !finished ? "继续练习" : "开始练习"}</button>
        <button type="button" disabled={finished || (!running && seconds === 0)} className="score-tool" onClick={finish}>结束</button>
        <button type="button" disabled={running} className="score-tool" onClick={() => void audition()}>{playbackState === "playing" ? "暂停试听" : playbackState === "paused" ? "继续试听" : "试听"}</button>
        {playbackState !== "stopped" && <button type="button" className="score-tool" onClick={() => { playback.current?.stop(); setNotice("试听已停止。"); }}>停止试听</button>}
      </div>
      <span className="practice-tempo">{settings.bpm} BPM · 第 {settings.first}–{settings.last} 小节</span>
      {notice && <p role="status" className="practice-notice">{notice}</p>}
    </footer>
    <dialog ref={settingsDialog} aria-labelledby="practice-settings-title" className="practice-settings-dialog" onCancel={(event) => { event.stopPropagation(); setSettingsOpen(false); }} onClose={(event) => { event.stopPropagation(); setSettingsOpen(false); }} onClick={(event) => { event.stopPropagation(); if (event.target === event.currentTarget) setSettingsOpen(false); }}>
      <form onSubmit={(event) => { event.preventDefault(); if (valid) { playback.current?.stop(); setSettings(draft); setSettingsOpen(false); setNotice("设置已更新。演奏按所选小节与声部跟谱；试听使用速度与调音。"); } }}>
        <header className="practice-settings-header"><h2 id="practice-settings-title">练习设置</h2><button type="submit" className="score-tool" disabled={!valid}>完成</button></header>
        <section className="score-tool-section"><h3>乐器与输入</h3>
          <label className="score-field">乐器<select value={draft.instrument} onChange={(event) => {const id=event.currentTarget.value;setDraft({ ...draft, instrument:id,instrumentVariant:resolveProfile(id).defaultVariant });}}>{[...INSTRUMENT_PROFILES,resolveProfile("other")].map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></label>
          {resolveProfile(draft.instrument).variants.length>1&&<label className="score-field">乐器调性<select value={draft.instrumentVariant} onChange={event=>setDraft({...draft,instrumentVariant:event.currentTarget.value})}>{resolveProfile(draft.instrument).variants.map(variant=><option key={variant.id} value={variant.id}>{variant.name}</option>)}</select></label>}
          <p>谱面已写明移调时按谱面实音；未写明时采用所选乐器调性。听音覆盖所选乐器的完整音域。</p>
          <label className="score-field">练习声部<select value={draft.part} onChange={(event) => setDraft({ ...draft, part: event.currentTarget.value })}><option>全部声部</option>{parts.map((part) => <option key={part}>{part}</option>)}</select></label>
          <label className="score-field">演奏输入<select disabled={!!activeRecord.current} value={draft.input} onChange={event=>setDraft({...draft,input:event.currentTarget.value as InputKind})}><option value="timer">自由练习 · 仅计时</option><option value="midi" disabled={!isNativeCloud()}>MIDI 乐器</option><option value="microphone" disabled={!isNativeCloud()}>麦克风 · 本地听音与录音</option></select></label>
          <p>{draft.input==="timer"?"仅计时，不采集你的演奏。":"点击开始练习后才连接演奏输入。麦克风录音保留在本机；未主动提交的练习不会分享给老师。"}</p>
        </section>
        <section className="score-tool-section"><h3>练习方式</h3>
          <label className="score-field">模式<select disabled={!!activeRecord.current} value={draft.mode} onChange={(event) => setDraft({ ...draft, mode: event.currentTarget.value })}><option>自由练习</option><option disabled={draft.input==="timer"}>等我弹对</option><option disabled={draft.input==="timer"}>跟随节奏</option></select></label>
          <div className="practice-settings-grid">
            <label className="score-field">速度 BPM<input type="number" min={30} max={240} required value={draft.bpm} onChange={(event) => setDraft({ ...draft, bpm: event.currentTarget.valueAsNumber })} /></label>
            <label className="score-field">调音 A4 · Hz<input type="number" min={400} max={480} required value={draft.tuning} onChange={(event) => setDraft({ ...draft, tuning: event.currentTarget.valueAsNumber })} /></label>
            <label className="score-field">起始小节<input type="number" min={1} max={measures} required value={draft.first} onChange={(event) => setDraft({ ...draft, first: event.currentTarget.valueAsNumber })} /></label>
            <label className="score-field">结束小节<input type="number" min={draft.first} max={measures} required value={draft.last} onChange={(event) => setDraft({ ...draft, last: event.currentTarget.valueAsNumber })} /></label>
          </div>
          {!valid && <p role="status">请检查速度、调音和小节范围。</p>}
        </section>
        <section className="score-tool-section"><h3>开始前确认</h3><p className="score-filename">{name}</p><label className="practice-confirm"><input type="checkbox" checked={draft.checked} onChange={(event) => setDraft({ ...draft, checked: event.currentTarget.checked })} />我已对照原稿核对乐谱</label><p>{draft.input==="timer"?"当前设置仅用于自由计时。":"自由模式评估音高与跟谱；严格模式评估相对起音与有可靠释放的时值。MIDI不用于音准评分，声音不清晰时保留待复核。"}</p></section>
      </form>
    </dialog>
  </>;
}
