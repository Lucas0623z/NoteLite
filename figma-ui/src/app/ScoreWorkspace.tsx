import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import PracticeSession, { type PracticeSource } from "./PracticeSession";
import { createScoreRenderHost, resolveOSMDConstructor } from "./osmd";
import { cancelNativeFileRequests, cloud, CloudError, createUUID, downloadBlob, errorMessage, isNativeCloud, type CloudJob, type CloudNote, type NoteEdit } from "./cloud";
import { RemoteScoreLoader } from "./remote-score";
import { createNotationInteraction, graphicalNoteBindings, inspectNoteDraft, noteKeyId, notationSources, prepareNotation, previewNoteEdits, restoreNotationSources, summarizeRuleErrors, type NoteKey, type NotationFeedback } from "./notationInteraction";
import { checkScoreRules, compareScoreRules, parseScoreXML, type ScoreRuleComparison, type ScoreRuleReport } from "./scoreRules";
import { editScoreDocument, readScoreDocument, type ScoreDocumentPatch } from "./scoreDocumentEdit";
import { ScoreStatus, type ScoreStatusVersion } from "./score-status";

type NoteInfo = { index: number; key: NoteKey; measure: string; part: string; step: string; octave: string; alter: string; duration: string; rest: boolean; source?: CloudNote };
type Props = { name: string; format: string; file?: Blob; practice?: boolean; job?: CloudJob; recordIdentity?: string; practiceSource?: PracticeSource; orientationNotice?: string; onJob?: (job: CloudJob) => Promise<void>; onClose: () => void; onSave: (file: Blob) => Promise<void> };

export default function ScoreWorkspace({ name, format, file, practice = false, job, recordIdentity, practiceSource, orientationNotice, onJob, onClose, onSave }: Props) {
  const [practicing, setPracticing] = useState(practice);
  const [xml, setXml] = useState("");
  const [notes, setNotes] = useState<NoteInfo[]>([]);
  const [selected, setSelected] = useState(0);
  const [step, setStep] = useState("C");
  const [octave, setOctave] = useState("4");
  const [alter, setAlter] = useState("0");
  const [measure, setMeasure] = useState("");
  const [zoom, setZoom] = useState(1);
  const [status, setStatusText] = useState("正在载入曲谱…");
  const [scoreStatus] = useState(() => new ScoreStatus(setStatusText));
  const [busy, setBusy] = useState(false);
  const [url, setUrl] = useState("");
  const [originalFile, setOriginalFile] = useState<Blob | undefined>(file);
  const [scoreIndex, setScoreIndex] = useState(0);
  const [revision, setRevision] = useState(0);
  const [duration, setDuration] = useState("1");
  const [noteType, setNoteType] = useState("quarter");
  const [dot, setDot] = useState("0");
  const [rest, setRest] = useState(false);
  const [draftOwner, setDraftOwner] = useState<NoteInfo | null>(null);
  const [conflict, setConflict] = useState(false);
  const [reloadNotice, setReloadNotice] = useState("");
  const [remoteLoading, setRemoteLoading] = useState(false);
  const [originalView, setOriginalView] = useState(false);
  const [xmlDraft, setXmlDraft] = useState("");
  const [sheetReady, setSheetReady] = useState(false);
  const [lastCheck, setLastCheck] = useState<ScoreRuleComparison | null>(null);
  const replacement = useRef<HTMLInputElement>(null);
  const sheet = useRef<HTMLDivElement>(null);
  const interaction = useRef<ReturnType<typeof createNotationInteraction> | null>(null);
  const selectedKey = useRef<NoteKey | null>(null);
  const latestNotes = useRef<NoteInfo[]>([]);
  const playhead = useRef<NoteKey[]>([]);
  const performanceColors = useRef<NotationFeedback[]>([]);
  useEffect(()=>{interaction.current?.setSelection(practicing?null:selectedKey.current);if(!practicing){performanceColors.current=[];interaction.current?.setFeedback([]);}},[practicing]);
  const statusVersion = useMemo<ScoreStatusVersion>(() => ({ jobId: job?.id, score: scoreIndex, revision, xml }), [job?.id, scoreIndex, revision, xml]);
  useLayoutEffect(() => scoreStatus.select(statusVersion), [scoreStatus, statusVersion]);
  function setStatus(message: string, version?: ScoreStatusVersion) { scoreStatus.report(message, version); }
  const remoteReady = job?.state === "succeeded";
  const xmlFile = (!!job && !!remoteReady && !originalView) || (!job && ["XML", "MUSICXML"].includes(format));
  const notation = !originalView && (xmlFile || (!job && format === "MXL"));
  const current = notes[selected];
  const draftReady = !!current && draftOwner === current;
  const filtered = notes.filter((note) => !measure || note.measure === measure);
  const ruleReport = useMemo<ScoreRuleReport | null>(() => xml ? checkScoreRules(xml) : null, [xml]);
  const noteDraft = useMemo(() => {
    if (!xml || !current || !draftReady) return null;
    return inspectNoteDraft(xml, { key: current.key, step: current.step, octave: current.octave, alter: current.alter, duration: current.duration, type: current.source?.type || "", dot: current.source?.dot || 0, rest: current.rest }, { step, octave, alter, duration, type: noteType, dot, rest }, !!job);
  }, [xml, current, draftReady, step, octave, alter, duration, noteType, dot, rest, job?.id]);
  const changeCheck = lastCheck || noteDraft?.comparison;
  const localScoreIdentity = useMemo(() => createUUID(), [xml]);
  useEffect(() => setLastCheck(null), [xml]);
  useEffect(() => setLastCheck(null), [current, step, octave, alter, duration, noteType, dot, rest]);
  const [remoteLoader] = useState(() => new RemoteScoreLoader(cloud, {
    loading: () => { scoreStatus.beginOperation(); setRemoteLoading(true); setConflict(true); setStatus("正在载入最新曲谱…"); },
    loaded: ({ job: latest, score, listing, musicxml }, saved) => {
      const mapped = listing.notes.map((note, index) => ({ index, key: { partId: note.partId, measureIndex: note.measureIndex, noteIndex: note.noteIndex }, measure: note.measure, part: note.partId, step: note.pitch?.step || "C", octave: String(note.pitch?.octave ?? 4), alter: String(note.pitch?.alter ?? 0), duration: String(note.duration), rest: note.rest, source: note }));
      setXml(musicxml); setXmlDraft(musicxml); setRevision(listing.revision); setNotes(mapped);
      setSelected((previous) => { const matching = selectedKey.current && mapped.findIndex((note) => noteKeyId(note.key) === noteKeyId(selectedKey.current!)); return matching !== null && matching >= 0 ? matching : Math.max(0, Math.min(previous, mapped.length - 1)); });
      setRemoteLoading(false); setConflict(false); setReloadNotice("");
      setStatus(saved ? `${saved.kind === "xml" ? "完整曲谱" : "校对"}已保存 · 当前版本 ${listing.revision} · MusicXML 与 MIDI 已更新` : `曲谱已载入 · 校对版本 ${listing.revision}${latest.warnings?.length ? " · 请对照原稿核对识谱提示" : ""}`, { jobId: latest.id, score, revision: listing.revision, xml: musicxml });
    },
    failed: (error, saved) => {
      setRemoteLoading(false); setConflict(true);
      setReloadNotice(`${saved ? "已保存到云端，最新谱面未载入，请重新载入。" : "最新曲谱未载入，请重新载入。"}${errorMessage(error)}`);
    },
  }));
  useEffect(() => {
    remoteLoader.activate();
    return () => { remoteLoader.deactivate(); cancelNativeFileRequests(); };
  }, [remoteLoader]);
  async function loadRemote(target: CloudJob, index: number) { return remoteLoader.load(target, index); }

  useEffect(() => {
    if (!job) return;
    if (!remoteReady) { setStatus(job.state === "failed" ? job.error || "识谱未完成，请检查原稿后重新上传。" : job.state === "queued" ? "曲谱已上传，正在等待识谱…" : "正在识谱，完成后自动载入可校对的乐谱…"); return; }
    if (remoteLoader.isInstalled(job, scoreIndex)) return;
    void loadRemote(job, scoreIndex);
    return () => remoteLoader.invalidate();
  }, [job?.id, job?.state, job?.revision, scoreIndex, remoteLoader]);

  useEffect(() => {
    if (!originalFile) { if (!job) setStatus("没有可预览的曲谱文件。"); return; }
    const objectUrl = URL.createObjectURL(originalFile);
    setUrl(objectUrl);
    let live = true;
    if (!job && xmlFile) originalFile.text().then((text) => { if (live) { setXml(text); setXmlDraft(text); } });
    else if (!job && !notation) setStatus("原稿已载入 · 连接识谱服务并重新导入后可校对音符");
    return () => { live = false; URL.revokeObjectURL(objectUrl); };
  }, [originalFile, xmlFile, notation]);

  async function showOriginal() {
    scoreStatus.beginOperation();
    if (originalView) { setOriginalView(false); return; }
    setBusy(true);
    try {
      if (job && (!originalFile || isNativeCloud())) {
        const blob = await cloud.original(job.id, scoreIndex, job.filename);
        if (!blob) { setStatus("原稿已打开，可对照校对乐谱。"); return; }
        setOriginalFile(blob);
      }
      setOriginalView(true);
    } catch (error) { setStatus(errorMessage(error)); }
    finally { setBusy(false); }
  }

  useEffect(() => {
    if (!xml || job) return;
    const document = new DOMParser().parseFromString(xml, "application/xml");
    if (document.querySelector("parsererror")) { setStatus("文件不是有效的 MusicXML，无法进行校对。"); setNotes([]); return; }
    let index = 0;
    setNotes(Array.from(document.querySelectorAll("score-partwise > part")).flatMap((part) => Array.from(part.querySelectorAll(":scope > measure")).flatMap((measure, measureIndex) => Array.from(measure.querySelectorAll(":scope > note")).map((note, noteIndex) => ({
      index: index++, key: { partId: part.getAttribute("id") || "", measureIndex, noteIndex }, measure: measure.getAttribute("number") || "",
      part: part.getAttribute("id") || "",
      step: note.querySelector("pitch > step")?.textContent || "C",
      octave: note.querySelector("pitch > octave")?.textContent || "4",
      alter: note.querySelector("pitch > alter")?.textContent || "0",
      duration: note.querySelector("duration")?.textContent || "0",
      rest: !!note.querySelector("rest"),
    })))));
  }, [xml, job?.id]);

  useLayoutEffect(() => {
    // Match the fields to the selected note before painting. Ownership also
    // prevents a prior selection/revision's fields being saved to a new note.
    setDraftOwner(current || null);
    latestNotes.current = notes;
    selectedKey.current = current?.key || null;
    interaction.current?.setSelection(practicing?null:selectedKey.current);
    if (current) { setStep(current.step); setOctave(current.octave); setAlter(current.alter); setDuration(current.duration); setNoteType(current.source?.type || ""); setDot(String(current.source?.dot || 0)); setRest(current.rest); }
  }, [current, notes, practicing]);

  useEffect(() => {
    const container = sheet.current;
    setSheetReady(false);
    if (!container || !notation || (!xml && xmlFile) || (!xml && !file)) return;
    const host = createScoreRenderHost(container);
    let observer: ResizeObserver | undefined;
    let localInteraction: ReturnType<typeof createNotationInteraction> | null = null;
    const layoutStatus = scoreStatus.beginLayout(statusVersion);
    import("opensheetmusicdisplay").then(async (module) => {
      if (!host.isActive()) return;
      const OpenSheetMusicDisplay = resolveOSMDConstructor(module);
      const display = new OpenSheetMusicDisplay(host.element, { autoResize: false, backend: "svg", drawTitle: true });
      host.attach(display);
      const source = xmlFile ? new DOMParser().parseFromString(xml, "application/xml") : file!;
      if (source instanceof Document && (source.querySelector("parsererror") || source.documentElement.localName !== "score-partwise")) throw new Error("曲谱不是有效的 MusicXML。");
      const prepared = source instanceof Document ? prepareNotation(source) : null;
      await display.load(prepared?.document || source);
      if (!host.isActive()) { host.dispose(); return; }
      const identities = prepared ? restoreNotationSources(notationSources(display), prepared, display.EngravingRules.DefaultColorNotehead) : null;
      display.Zoom = zoom;
      display.render();
      if (identities) {
        localInteraction = createNotationInteraction(host.element, () => graphicalNoteBindings(display, identities), (key) => {
          const index = latestNotes.current.findIndex((note) => noteKeyId(note.key) === noteKeyId(key));
          if (index >= 0) { setSelected(index); setMeasure(""); }
        });
        interaction.current = localInteraction;
        localInteraction.refresh(); localInteraction.setSelection(practicing?null:selectedKey.current); localInteraction.setPlayhead(playhead.current);localInteraction.setFeedback(performanceColors.current);
      }
      setSheetReady(true);
      layoutStatus.ready(job ? `曲谱已载入 · 校对版本 ${revision}${job.warnings?.length ? " · 请对照原稿核对识谱提示" : ""}` : xmlFile ? "MusicXML 已载入 · 可从右侧选择音符校对" : "压缩曲谱已载入 · 上传至识谱服务后可校对并导出 MIDI");
      const paper = container.parentElement!;
      let width = paper.clientWidth;
      observer = new ResizeObserver(() => {
        if (!host.isActive()) return;
        const nextWidth = paper.clientWidth;
        if (nextWidth !== width && display.IsReadyToRender()) {
          width = nextWidth;
          display.render();
          localInteraction?.refresh();
        }
      });
      observer.observe(paper);
    }).catch((error) => {
      const active = host.isActive();
      localInteraction?.dispose();
      if (interaction.current === localInteraction) interaction.current = null;
      observer?.disconnect();
      host.dispose();
      console.error("MusicXML layout failed", error);
      if (active) { setSheetReady(false); layoutStatus.failed(`曲谱排版失败：${error instanceof Error ? error.message : String(error)}`); }
    });
    return () => { localInteraction?.dispose(); if (interaction.current === localInteraction) interaction.current = null; host.dispose(); observer?.disconnect(); };
  }, [xml, notation, file, xmlFile, zoom, revision, scoreStatus, statusVersion]);

  async function publishEdit(edits: NoteEdit[]) {
    if (!job) return;
    scoreStatus.beginOperation();
    try { const candidate = new XMLSerializer().serializeToString(previewNoteEdits(parseScoreXML(xml), edits)); if (!canSave(candidate)) return; }
    catch (error) { setStatus(errorMessage(error)); return; }
    setBusy(true);
    try {
      const { job: updated } = await remoteLoader.save(() => cloud.patch(job.id, scoreIndex, revision, edits), scoreIndex, "notes");
      try { await onJob?.(updated); } catch { setStatus("校对已保存到云端，本机曲谱列表更新未完成。重新打开曲谱后可同步。"); }
    }
    catch (error) { setStatus(errorMessage(error)); if (error instanceof CloudError && (error.status === 409 || error.code === "write_status_unknown")) { setConflict(true); setReloadNotice(errorMessage(error)); } }
    finally { setBusy(false); }
  }

  async function saveXML(text = xmlDraft) {
    scoreStatus.beginOperation();
    const document = new DOMParser().parseFromString(text, "application/xml");
    if (document.querySelector("parsererror") || document.documentElement.localName !== "score-partwise") { setStatus("请选择有效的 MusicXML，当前版本不会被覆盖。"); return; }
    if (!canSave(text)) return;
    setBusy(true);
    try {
      if (job) {
        const { job: updated } = await remoteLoader.save(() => cloud.put(job.id, scoreIndex, revision, text), scoreIndex, "xml");
        try { await onJob?.(updated); } catch { setStatus("完整曲谱已保存到云端，本机曲谱列表更新未完成。重新打开曲谱后可同步。"); }
      } else {
        await onSave(new Blob([text], { type: "application/vnd.recordare.musicxml+xml" }));
        setXml(text); setXmlDraft(text); setStatus("曲谱信息已保存到本机。", { ...statusVersion, xml: text });
      }
    }
    catch (error) { setStatus(errorMessage(error)); if (error instanceof CloudError && (error.status === 409 || error.code === "write_status_unknown")) { setConflict(true); setReloadNotice(errorMessage(error)); } }
    finally { setBusy(false); }
  }

  function canSave(candidate: string): boolean {
    const comparison = compareScoreRules(xml, candidate);
    setLastCheck(comparison);
    if (!comparison.canSave) { setStatus(`修改未保存：${summarizeRuleErrors(comparison.introduced) || "曲谱结构无效，请展开检查说明。"}`); return false; }
    return true;
  }

  async function exportFile(kind: "musicxml" | "midi" | "original" | "omr") {
    scoreStatus.beginOperation();
    setBusy(true);
    try {
      if (job) { const stem = job.scores[scoreIndex]?.name || name.replace(/\.[^.]+$/, ""); await cloud.export(job.id, scoreIndex, kind, kind === "original" ? job.filename : `${stem}.${{ musicxml: "musicxml", midi: "mid", omr: "omr", original: "" }[kind]}`); }
      else if (file) await downloadBlob(file, name);
      setStatus("文件已导出。");
    } catch (error) { setStatus(errorMessage(error)); }
    finally { setBusy(false); }
  }

  async function savePitch() {
    if (!current || !draftReady || busy || conflict || !noteDraft?.canSave || !noteDraft.edit || !noteDraft.candidate) return;
    if (job && current.source) {
      await publishEdit([noteDraft.edit]); return;
    }
    if (current.rest) return;
    scoreStatus.beginOperation();
    const updated = noteDraft.candidate;
    if (!canSave(updated)) return;
    setBusy(true);
    try {
      await onSave(new Blob([updated], { type: "application/vnd.recordare.musicxml+xml" }));
      setXml(updated); setStatus("校对已保存到本机。", { ...statusVersion, xml: updated });
    } catch { setStatus("保存失败，请检查本地存储权限。"); }
    finally { setBusy(false); }
  }

  return <div className="score-workspace" data-practice={practicing}>
    <header className="score-workspace-header">
      <button type="button" className="score-tool" onClick={onClose}>‹ 我的曲谱</button>
      <div><h1 id="score-panel-title">{practicing ? "练琴时刻" : "曲谱预览与校对"}</h1><p>{practicing ? "黑白键 · 专注每一次练习" : "黑白键 · 让每一个音符更准确"}</p></div>
      <span className="score-local-badge">{job ? `云端版本 ${revision || job.revision}` : practiceSource?.kind === "official" ? "官方曲谱" : practiceSource ? `个人谱版本 ${practiceSource.revision}` : "本机保存"}</span>
    </header>
    <p className="score-landscape-hint" role="status">{orientationNotice || "横屏查看乐谱更清晰。若未自动旋转，请关闭系统方向锁定，并将设备横放。"}</p>
    <div className="score-workspace-layout">
      <aside className="score-tools">
        <p className="score-eyebrow">{practicing ? "正在练习" : "我的曲谱"}</p>
        <h2 className="score-filename">{name}</h2>
        <span className="score-format">{format}</span>
        <section className="score-tool-section"><h3>曲谱文件</h3><p>{job ? "识谱与校对保存在云端。原稿保留；保存时同时更新 MusicXML 与 MIDI。" : practiceSource?.kind === "official" ? "官方练习谱已缓存到本机。修改后保存为个人校对版。" : practiceSource ? "个人曲谱随账户同步。保存时检查版本，避免覆盖另一设备的修改。" : "曲谱保存在本机。"}</p>
          <button type="button" disabled={!!job && !remoteReady} className="score-tool score-tool-primary" onClick={() => setPracticing(!practicing)}>{practicing ? "返回曲谱校对" : "开始练习"}</button>
          <button type="button" className="score-tool" disabled={busy || (job ? !remoteReady : !file)} onClick={() => void exportFile("musicxml")}>下载当前曲谱</button>
          {job && <button type="button" className="score-tool" disabled={busy || !remoteReady} onClick={() => void exportFile("midi")}>下载 MIDI</button>}
          {job && <button type="button" className="score-tool" disabled={busy} onClick={() => void exportFile("original")}>下载原稿</button>}
          {job?.artifacts.omr && <button type="button" className="score-tool" disabled={busy} onClick={() => void exportFile("omr")}>下载 NoteLite 工程</button>}
        </section>
        <section className="score-tool-section"><h3>预览设置</h3>
          <div className="score-zoom"><button type="button" className="score-tool" aria-label="缩小乐谱" disabled={!notation || zoom <= 0.6} onClick={() => setZoom((value) => Math.max(0.6, value - 0.1))}>−</button><span>{Math.round(zoom * 100)}%</span><button type="button" className="score-tool" aria-label="放大乐谱" disabled={!notation || zoom >= 1.8} onClick={() => setZoom((value) => Math.min(1.8, value + 0.1))}>＋</button></div>
          {job && job.scores.length > 1 && <label className="score-field">乐章<select aria-label="选择乐章" disabled={busy} value={scoreIndex} onChange={(event) => { setScoreIndex(Number(event.currentTarget.value)); setSelected(0); setMeasure(""); setXml(""); setNotes([]); }}>{job.scores.map((score) => <option key={score.index} value={score.index}>{score.name}</option>)}</select></label>}
          {(originalFile || job) && !["XML", "MUSICXML", "MXL"].includes(format) && <button type="button" disabled={busy} className="score-tool" onClick={() => void showOriginal()}>{originalView ? "查看识谱结果" : "对照原稿"}</button>}
          <p>{job ? "选择乐章并对照原稿校对，识谱结果可能需要人工修正。" : "图片与 PDF 重新导入云端服务后可识谱。"}</p>
        </section>
        <div className="score-help">{practicing ? "跟着乐谱慢慢练习，先准确，再加快。" : "校对后记得保存，再开始下一次练习。"}</div>
      </aside>
      <main className="score-preview">
        <div className="score-preview-heading"><div><p className="score-eyebrow">乐谱预览</p><h2>{(job?.scores[scoreIndex]?.name || name).replace(/\.[^.]+$/, "")}</h2></div><span className="score-format">{notes.length ? `${notes.length} 个音符 / 休止符` : "原稿"}</span></div>
        <p role="status" className="score-status">{reloadNotice || status}</p>
        {ruleReport && ruleReport.issues.length > 0 && <details className="score-description"><summary>已保存谱面检查：{ruleReport.errors.length} 项待校对，{ruleReport.warnings.length} 项提示</summary><ul>{ruleReport.issues.map((issue, index) => <li key={index}>{issue.message}</li>)}</ul></details>}
        {changeCheck && changeCheck.introduced.length > 0 && <details className="score-description"><summary>本次修改检查：{changeCheck.introduced.filter((issue) => issue.severity === "error").length} 项新增错误，{changeCheck.introduced.filter((issue) => issue.severity === "warning").length} 项提示</summary><ul>{changeCheck.introduced.map((issue, index) => <li key={index}>{issue.message}</li>)}</ul></details>}
        {reloadNotice && job && <button type="button" className="score-tool" disabled={busy || remoteLoading} onClick={() => void loadRemote(job, scoreIndex)}>重新载入最新版本</button>}
        <div className="score-paper">
          {notation ? <div ref={sheet} role={sheetReady ? "img" : undefined} aria-label={sheetReady ? "MusicXML 谱面" : undefined} /> : format === "PDF" && url ? <iframe src={url} title={`${name}乐谱原稿`} /> : originalFile?.type.startsWith("image/") && url ? <img src={url} alt={`${name}乐谱原稿`} /> : <p>{job && !remoteReady ? "正在等待识谱结果。" : "此文件暂不支持预览。"}</p>}
        </div>
      </main>
      {practicing ? <PracticeSession name={name} measures={Math.max(1, new Set(notes.map((note) => note.measure)).size)} parts={[...new Set(notes.map((note) => note.part))]} musicxml={xml} recordIdentity={recordIdentity ? `${recordIdentity}${job ? `:${scoreIndex}` : ""}` : undefined} source={practiceSource} scoreIdentity={job ? `${job.id}:${scoreIndex}:${revision}` : `local:${localScoreIdentity}`} onPosition={(keys: NoteKey[]) => { playhead.current = keys; interaction.current?.setPlayhead(keys); }} onFeedback={values=>{performanceColors.current=values;interaction.current?.setFeedback(values);}} /> : <aside className="score-inspector">
        <p className="score-eyebrow">音符校对</p><h2>把每个音符校准</h2>
        <p className="score-description">{job ? "点击谱面音符或从列表选择，选中音符显示蓝色。校对保存后更新云端 MusicXML 与 MIDI。" : "点击谱面音符或从列表选择，选中音符显示蓝色。校对保存后更新本地 MusicXML。"}</p>
        {xml && <ScoreMetadataEditor xml={xml} disabled={busy || conflict} onSave={saveXML} onError={(error) => setStatus(errorMessage(error))} />}
        {notes.length ? <>
          <label className="score-field">小节筛选<input inputMode="numeric" value={measure} onChange={(event) => setMeasure(event.currentTarget.value)} placeholder="全部小节" /></label>
          <div className="score-note-list" aria-label="音符列表">{filtered.map((note) => <button key={note.index} type="button" disabled={busy} aria-label={`第 ${note.measure} 小节 · ${note.rest ? "休止符" : `${note.step}${note.alter === "1" ? "♯" : note.alter === "-1" ? "♭" : ""}${note.octave}`} #${note.index + 1}`} aria-pressed={selected === note.index} onClick={() => setSelected(note.index)}><span>第 {note.measure} 小节 · {note.rest ? "休止符" : `${note.step}${note.alter === "1" ? "♯" : note.alter === "-1" ? "♭" : ""}${note.octave}`}</span><span>#{note.index + 1}</span></button>)}</div>
          {!filtered.length && <p className="score-description">没有这个小节的音符。</p>}
          {current && <section className="score-edit"><h3>{current.part} · 第 {current.measure} 小节</h3><p className="score-description">音符 {selected + 1} · 原始时值 {current.duration}{current.source ? ` · 每拍 ${current.source.divisions} 单位` : ""}</p>
            {job && <label className="score-field">音符种类<select aria-label="音符或休止符" disabled={busy || conflict} value={rest ? "rest" : "note"} onChange={(event) => setRest(event.currentTarget.value === "rest")}><option value="note">音符</option><option value="rest">休止符</option></select></label>}
            {rest ? <p className="score-description">{job ? "休止符可修改时值，或切换为音符。" : "休止符暂不支持修改音高。"}</p> : <div className="score-pitch-fields">
              <label className="score-field">音名<select disabled={busy || conflict} value={step} onChange={(event) => setStep(event.currentTarget.value)}>{["C", "D", "E", "F", "G", "A", "B"].map((value) => <option key={value}>{value}</option>)}</select></label>
              <label className="score-field">升降<select disabled={busy || conflict} value={alter} onChange={(event) => setAlter(event.currentTarget.value)}><option value="0">还原</option><option value="1">升半音</option><option value="-1">降半音</option><option value="2">重升</option><option value="-2">重降</option></select></label>
              <label className="score-field">八度<select aria-label="八度" disabled={busy || conflict} value={octave} onChange={(event) => setOctave(event.currentTarget.value)}>{Array.from({ length: 10 }, (_, value) => <option key={value}>{value}</option>)}</select></label>
            </div>}
            {job && <div className="score-pitch-fields"><label className="score-field">时值<input aria-label="音符时值" type="number" min="0" step="any" disabled={busy || conflict} value={duration} onChange={(event) => setDuration(event.currentTarget.value)} /></label><label className="score-field">记谱时值<select aria-label="记谱时值" disabled={busy || conflict} value={noteType} onChange={(event) => setNoteType(event.currentTarget.value)}>{["", "maxima", "long", "breve", "whole", "half", "quarter", "eighth", "16th", "32nd", "64th", "128th", "256th", "512th", "1024th"].map((type) => <option key={type} value={type}>{type || "未指定"}</option>)}</select></label><label className="score-field">附点<select aria-label="附点数量" disabled={busy || conflict} value={dot} onChange={(event) => setDot(event.currentTarget.value)}>{[0, 1, 2, 3, 4].map((value) => <option key={value}>{value}</option>)}</select></label></div>}
            {noteDraft && <p className="score-description" role="status" aria-label="音符草稿检查">{noteDraft.message}</p>}
            {(!rest || job) && <button type="button" className="score-tool score-tool-primary" disabled={busy || conflict || !draftReady || !noteDraft?.canSave} onClick={() => void savePitch()}>{busy ? "正在保存…" : "保存校对"}</button>}
            {job && current.source && <button type="button" className="score-tool" disabled={busy || conflict} onClick={() => { if (window.confirm(`删除第 ${current.measure} 小节的音符 ${selected + 1}？`)) void publishEdit([{ partId: current.source!.partId, measureIndex: current.source!.measureIndex, noteIndex: current.source!.noteIndex, delete: true }]); }}>删除当前音符</button>}
          </section>}
        </> : <div className="score-empty-inspector"><h3>{job ? "等待可校对乐谱" : "原稿已准备好"}</h3><p>{job ? "识谱完成后会显示音符列表。" : "导入 MusicXML 可校对音高。图片、PDF 和压缩曲谱重新导入云端服务后，可提取音符。"}</p></div>}
        {job && remoteReady && <section className="score-edit"><h3>完整 MusicXML 校对</h3><p className="score-description">可修改其他记谱内容。保存后，同时更新 MusicXML 和 MIDI。</p><button type="button" className="score-tool" disabled={busy || conflict} onClick={() => replacement.current?.click()}>导入校对后的 MusicXML</button><details><summary className="score-description">编辑 MusicXML 内容</summary><label className="score-field">MusicXML<textarea aria-label="完整 MusicXML" rows={10} value={xmlDraft} disabled={busy || conflict} onChange={(event) => setXmlDraft(event.currentTarget.value)} /></label><button type="button" className="score-tool score-tool-primary" disabled={busy || conflict || xmlDraft === xml} onClick={() => void saveXML()}>保存完整曲谱</button></details><input ref={replacement} className="hidden" type="file" accept=".musicxml,.xml" aria-label="导入校对后的 MusicXML 文件" onChange={(event) => { const file = event.currentTarget.files?.[0]; if (file) void file.text().then((text) => saveXML(text)).catch((error) => setStatus(errorMessage(error))); event.currentTarget.value = ""; }} /></section>}
      </aside>}
    </div>
  </div>;
}

type MetadataDraft = { partName: string; instrumentName: string; sign: string; line: string; clefOctave: string; fifths: string; mode: string; keyAll: boolean; meterAll: boolean; groups: { beats: string; beatType: string }[]; beatUnit: string; dots: string; perMinute: string };
function ScoreMetadataEditor({ xml, disabled, onSave, onError }: { xml: string; disabled: boolean; onSave: (xml: string) => Promise<void>; onError: (error: unknown) => void }) {
  const info = useMemo(() => { try { return readScoreDocument(xml); } catch { return null; } }, [xml]);
  const [context, setContext] = useState({ partId: "", measureIndex: 0, staff: "1", instrumentId: "", clef: "-1", key: "-1", meter: "-1", tempo: "-1" });
  const part = info?.parts.find((value) => value.id === context.partId) || info?.parts[0];
  const staff = part?.staffNumbers.includes(context.staff) ? context.staff : part?.staffNumbers[0] || "1";
  const measureIndex = part?.measures.some((value) => value.index === context.measureIndex) ? context.measureIndex : 0;
  const instrument = part?.instruments.find((value) => value.id === context.instrumentId) || part?.instruments[0];
  const choose = <T extends { measureIndex: number; staff: string | null; attributesIndex?: number; directionIndex?: number }>(entries: T[] | undefined, position: string): T | undefined => {
    if (position === "new") return undefined;
    if (position !== "-1") return entries?.[Number(position)];
    const matching = entries?.filter((entry) => entry.measureIndex <= measureIndex && (entry.staff === null || entry.staff === staff)).sort((left, right) => left.measureIndex - right.measureIndex || (left.attributesIndex ?? left.directionIndex ?? 0) - (right.attributesIndex ?? right.directionIndex ?? 0) || Number(left.staff !== null) - Number(right.staff !== null));
    return matching?.[matching.length - 1];
  };
  const clef = choose(part?.clefs, context.clef);
  const key = choose(part?.keys, context.key);
  const meter = choose(part?.meters, context.meter);
  const tempo = choose(part?.tempos, context.tempo);
  const [draft, setDraft] = useState<MetadataDraft>({ partName: "", instrumentName: "", sign: "", line: "", clefOctave: "0", fifths: "", mode: "", keyAll: true, meterAll: true, groups: [{ beats: "", beatType: "4" }], beatUnit: "quarter", dots: "0", perMinute: "" });
  useLayoutEffect(() => {
    const numericTempo = tempo?.perMinute && Number.isFinite(Number(tempo.perMinute)) && Number(tempo.perMinute) > 0 ? tempo.perMinute : "";
    setDraft({ partName: part?.name || "", instrumentName: instrument?.name || "", sign: clef?.sign || "", line: clef?.line === null || clef?.line === undefined ? "" : String(clef.line), clefOctave: String(clef?.octaveChange || 0), fifths: key?.fifths === null || key?.fifths === undefined ? "" : String(key.fifths), mode: key?.mode || "", keyAll: !key?.staff, meterAll: !meter?.staff, groups: meter?.groups.length ? meter.groups.map((group) => ({ beats: group.beats, beatType: String(group.beatType) })) : [{ beats: "", beatType: "4" }], beatUnit: tempo?.beatUnit || "quarter", dots: String(tempo?.dots || 0), perMinute: numericTempo });
  }, [part, instrument, clef, key, meter, tempo]);
  const change = <K extends keyof MetadataDraft>(name: K, value: MetadataDraft[K]) => setDraft((previous) => ({ ...previous, [name]: value }));
  const changeContext = (values: Partial<typeof context>) => setContext((previous) => ({ ...previous, clef: "-1", key: "-1", meter: "-1", tempo: "-1", ...values }));
  const patch = async (value: ScoreDocumentPatch) => {
    if (disabled) return;
    try { await onSave(editScoreDocument(xml, value)); } catch (error) { onError(error); }
  };
  const position = (kind: "clef" | "key" | "meter" | "tempo", entries: { measureIndex: number; staff: string | null; attributesIndex?: number; directionIndex?: number; metronomeIndex?: number }[] | undefined) => {
    const options = entries?.map((entry, index) => ({ entry, index })).filter(({ entry }) => entry.measureIndex === measureIndex && (entry.staff === null || entry.staff === staff)) || [];
    if (options.length < 2 && kind !== "tempo") return null;
    return <label className="score-field">{kind === "tempo" ? "速度标记位置" : "属性位置"}<select disabled={disabled} value={context[kind]} onChange={(event) => { const value = event.currentTarget.value; setContext((previous) => ({ ...previous, [kind]: value })); }}><option value="-1">当前有效信息</option><option value="new">在本小节开头新增</option>{options.map(({ entry, index }) => <option key={index} value={index}>{kind === "tempo" ? `速度标记 ${(entry.directionIndex || 0) + 1} · 节拍器 ${(entry.metronomeIndex || 0) + 1}` : `第 ${(entry.attributesIndex || 0) + 1} 组属性`}</option>)}</select></label>;
  };
  const attributesAt = (entry: { measureIndex: number; attributesIndex: number } | undefined) => entry?.measureIndex === measureIndex ? { attributesIndex: entry.attributesIndex } : {};
  const at = { partId: part?.id || "", measureIndex };
  const tempoLocked = tempo?.editable === false;
  if (!part || !part.measures.length) return null;
  return <details className="score-edit">
    <summary className="score-description">编辑谱面前置信息</summary>
    <p className="score-description">可修改乐器、每个谱表的谱号、调号、拍号和速度。保存只检查小节拍数与时值；已有识谱问题继续提示。</p>
    <label className="score-field">声部<select aria-label="前置信息声部" disabled={disabled} value={part.id} onChange={(event) => changeContext({ partId: event.currentTarget.value, measureIndex: 0, staff: "1", instrumentId: "" })}>{info!.parts.map((value) => <option key={value.id} value={value.id}>{value.name || value.id}</option>)}</select></label>
    <label className="score-field">所在小节<select aria-label="前置信息小节" disabled={disabled} value={measureIndex} onChange={(event) => changeContext({ measureIndex: Number(event.currentTarget.value) })}>{part.measures.map((value) => <option key={value.index} value={value.index}>第 {value.number} 小节</option>)}</select></label>
    <label className="score-field">谱表<select aria-label="前置信息谱表" disabled={disabled} value={staff} onChange={(event) => changeContext({ staff: event.currentTarget.value })}>{part.staffNumbers.map((value) => <option key={value} value={value}>谱表 {value}</option>)}</select></label>
    <section className="score-edit"><h3>乐器名称</h3>
      <label className="score-field">谱面声部名称<input aria-label="谱面声部名称" disabled={disabled} value={draft.partName} onChange={(event) => change("partName", event.currentTarget.value)} /></label>
      {part.instruments.length > 1 && <label className="score-field">乐器条目<select aria-label="乐器条目" disabled={disabled} value={instrument?.id || ""} onChange={(event) => changeContext({ instrumentId: event.currentTarget.value })}>{part.instruments.map((value) => <option key={value.id} value={value.id}>{value.name || value.id}</option>)}</select></label>}
      <label className="score-field">乐器名称<input aria-label="乐器名称" disabled={disabled} value={draft.instrumentName} onChange={(event) => change("instrumentName", event.currentTarget.value)} placeholder="原谱未提供时可填写" /></label>
      <button type="button" className="score-tool" disabled={disabled || draft.partName === part.name && draft.instrumentName === (instrument?.name || "")} onClick={() => void patch({ kind: "name", partId: part.id, ...(draft.partName !== part.name ? { partName: draft.partName } : {}), ...(draft.instrumentName !== (instrument?.name || "") ? { instrumentName: draft.instrumentName, instrumentId: instrument?.id } : {}) })}>保存乐器名称</button>
    </section>
    <section className="score-edit"><h3>谱表 {staff} · 谱号</h3>{position("clef", part.clefs)}
      <label className="score-field">谱号<select aria-label="谱号" disabled={disabled} value={draft.sign} onChange={(event) => { const sign = event.currentTarget.value; setDraft((previous) => ({ ...previous, sign, line: ({ G: "2", F: "4", C: "3" } as Record<string, string>)[sign] || "" })); }}><option value="">未提供</option><option value="G">高音谱号 G</option><option value="F">低音谱号 F</option><option value="C">C 谱号</option><option value="percussion">打击乐谱号</option><option value="TAB">六线谱 TAB</option><option value="none">无谱号</option>{draft.sign && !["G", "F", "C", "percussion", "TAB", "none"].includes(draft.sign) && <option value={draft.sign}>{draft.sign}</option>}</select></label>
      <label className="score-field">谱号所在线<input aria-label="谱号所在线" type="number" min="1" max="5" disabled={disabled || !["G", "F", "C"].includes(draft.sign)} value={draft.line} onChange={(event) => change("line", event.currentTarget.value)} /></label>
      <label className="score-field">八度偏移<select aria-label="谱号八度偏移" disabled={disabled} value={draft.clefOctave} onChange={(event) => change("clefOctave", event.currentTarget.value)}>{[-2, -1, 0, 1, 2].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
      <button type="button" className="score-tool" disabled={disabled || !draft.sign} onClick={() => void patch({ kind: "clef", ...at, ...attributesAt(clef), staff, sign: draft.sign, line: draft.line ? Number(draft.line) : null, octaveChange: Number(draft.clefOctave) })}>保存谱号</button>
    </section>
    <section className="score-edit"><h3>调号</h3>{position("key", part.keys)}
      <label className="score-field">升降号数<input aria-label="调号升降号数" type="number" min="-7" max="7" disabled={disabled} value={draft.fifths} onChange={(event) => change("fifths", event.currentTarget.value)} placeholder="负数为降号，正数为升号" /></label>
      <label className="score-field">调式<select aria-label="调式" disabled={disabled} value={draft.mode} onChange={(event) => change("mode", event.currentTarget.value)}><option value="">未注明</option>{["major", "minor", "dorian", "phrygian", "lydian", "mixolydian", "aeolian", "ionian", "locrian", "none"].map((value) => <option key={value} value={value}>{({ major: "大调", minor: "小调" } as Record<string, string>)[value] || value}</option>)}</select></label>
      {part.staffNumbers.length > 1 && <label className="score-description"><input type="checkbox" disabled={disabled} checked={draft.keyAll} onChange={(event) => change("keyAll", event.currentTarget.checked)} /> 应用到本声部全部谱表</label>}
      <button type="button" className="score-tool" disabled={disabled || !draft.fifths.trim()} onClick={() => void patch({ kind: "key", ...at, ...attributesAt(key), staff: draft.keyAll ? null : staff, fifths: Number(draft.fifths), mode: draft.mode })}>保存调号</button>
    </section>
    <section className="score-edit"><h3>拍号</h3>{position("meter", part.meters)}
      {meter?.senzaMisura && <p className="score-description">原谱为散板。填写拍号并保存会替换本位置的散板标记。</p>}
      {draft.groups.map((group, index) => <div key={index}><label className="score-field">每小节拍数{draft.groups.length > 1 ? ` · 组 ${index + 1}` : ""}<input aria-label={`拍号拍数 ${index + 1}`} disabled={disabled} value={group.beats} onChange={(event) => change("groups", draft.groups.map((value, number) => number === index ? { ...value, beats: event.currentTarget.value } : value))} placeholder="例如 4 或 3+2" /></label><label className="score-field">单位音符<input aria-label={`拍号单位 ${index + 1}`} type="number" min="1" disabled={disabled} value={group.beatType} onChange={(event) => change("groups", draft.groups.map((value, number) => number === index ? { ...value, beatType: event.currentTarget.value } : value))} /></label>{draft.groups.length > 1 && <button type="button" className="score-tool" disabled={disabled} onClick={() => change("groups", draft.groups.filter((_value, number) => number !== index))}>移除拍号组 {index + 1}</button>}</div>)}
      <button type="button" className="score-tool" disabled={disabled} onClick={() => change("groups", [...draft.groups, { beats: "", beatType: "4" }])}>增加复合拍号组</button>
      {part.staffNumbers.length > 1 && <label className="score-description"><input type="checkbox" disabled={disabled} checked={draft.meterAll} onChange={(event) => change("meterAll", event.currentTarget.checked)} /> 应用到本声部全部谱表</label>}
      <button type="button" className="score-tool" disabled={disabled || draft.groups.some((group) => !group.beats.trim() || !group.beatType.trim())} onClick={() => void patch({ kind: "meter", ...at, ...attributesAt(meter), staff: draft.meterAll ? null : staff, groups: draft.groups.map((group) => ({ beats: group.beats, beatType: Number(group.beatType) })) })}>保存拍号</button>
    </section>
    <section className="score-edit"><h3>速度</h3>{position("tempo", part.tempos)}
      <p className="score-description">同一位置的速度会同步到其他声部，保留各声部的拍单位。</p>
      {tempo?.perMinute && (!Number.isFinite(Number(tempo.perMinute)) || Number(tempo.perMinute) <= 0) && <p className="score-description">原谱速度文字：{tempo.perMinute}。{tempo.soundTempo !== null ? `当前播放速度为四分音符每分钟 ${tempo.soundTempo}。` : ""}填写明确数字后可校正原标记。</p>}
      {tempoLocked && <p className="score-description">此处是速度关系标记，保留原记谱。选择“在本小节开头新增”可添加数值速度。</p>}
      <label className="score-field">速度单位<select aria-label="速度单位" disabled={disabled || tempoLocked} value={draft.beatUnit} onChange={(event) => change("beatUnit", event.currentTarget.value)}>{["whole", "half", "quarter", "eighth", "16th", "32nd", "64th", "128th"].map((value) => <option key={value} value={value}>{({ whole: "全音符", half: "二分音符", quarter: "四分音符", eighth: "八分音符" } as Record<string, string>)[value] || value}</option>)}</select></label>
      <label className="score-field">附点<input aria-label="速度单位附点" type="number" min="0" max="3" disabled={disabled || tempoLocked} value={draft.dots} onChange={(event) => change("dots", event.currentTarget.value)} /></label>
      <label className="score-field">每分钟单位数<input aria-label="谱面速度" type="number" min="1" step="any" disabled={disabled || tempoLocked} value={draft.perMinute} onChange={(event) => change("perMinute", event.currentTarget.value)} placeholder="原谱未提供时可填写" /></label>
      <button type="button" className="score-tool" disabled={disabled || tempoLocked || !draft.perMinute.trim()} onClick={() => void patch({ kind: "tempo", ...at, staff: tempo?.staff || null, ...(context.tempo === "new" ? { createNew: true } : tempo?.measureIndex === measureIndex ? { directionIndex: tempo.directionIndex, metronomeIndex: tempo.metronomeIndex } : {}), beatUnit: draft.beatUnit, dots: Number(draft.dots), perMinute: Number(draft.perMinute) })}>保存速度</button>
    </section>
  </details>;
}
