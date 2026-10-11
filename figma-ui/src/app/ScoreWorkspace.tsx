import { useEffect, useLayoutEffect, useRef, useState } from "react";
import PracticeSession from "./PracticeSession";
import { createScoreRenderHost, resolveOSMDConstructor } from "./osmd";
import { cancelNativeFileRequests, cloud, CloudError, downloadBlob, errorMessage, isNativeCloud, type CloudJob, type CloudNote, type NoteEdit } from "./cloud";
import { RemoteScoreLoader } from "./remote-score";

type NoteInfo = { index: number; measure: string; part: string; step: string; octave: string; alter: string; duration: string; rest: boolean; source?: CloudNote };
type Props = { name: string; format: string; file?: Blob; practice?: boolean; job?: CloudJob; orientationNotice?: string; onJob?: (job: CloudJob) => Promise<void>; onClose: () => void; onSave: (file: Blob) => Promise<void> };

export default function ScoreWorkspace({ name, format, file, practice = false, job, orientationNotice, onJob, onClose, onSave }: Props) {
  const [practicing, setPracticing] = useState(practice);
  const [xml, setXml] = useState("");
  const [notes, setNotes] = useState<NoteInfo[]>([]);
  const [selected, setSelected] = useState(0);
  const [step, setStep] = useState("C");
  const [octave, setOctave] = useState("4");
  const [alter, setAlter] = useState("0");
  const [measure, setMeasure] = useState("");
  const [zoom, setZoom] = useState(1);
  const [status, setStatus] = useState("正在载入曲谱…");
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
  const replacement = useRef<HTMLInputElement>(null);
  const sheet = useRef<HTMLDivElement>(null);
  const remoteReady = job?.state === "succeeded";
  const xmlFile = (!!job && !!remoteReady && !originalView) || (!job && ["XML", "MUSICXML"].includes(format));
  const notation = !originalView && (xmlFile || (!job && format === "MXL"));
  const current = notes[selected];
  const draftReady = !!current && draftOwner === current;
  const filtered = notes.filter((note) => !measure || note.measure === measure);
  const [remoteLoader] = useState(() => new RemoteScoreLoader(cloud, {
    loading: () => { setRemoteLoading(true); setConflict(true); setStatus("正在载入最新曲谱…"); },
    loaded: ({ job: latest, listing, musicxml }, saved) => {
      const mapped = listing.notes.map((note, index) => ({ index, measure: note.measure, part: note.partId, step: note.pitch?.step || "C", octave: String(note.pitch?.octave ?? 4), alter: String(note.pitch?.alter ?? 0), duration: String(note.duration), rest: note.rest, source: note }));
      setXml(musicxml); setXmlDraft(musicxml); setRevision(listing.revision); setNotes(mapped);
      setSelected((previous) => Math.max(0, Math.min(previous, mapped.length - 1)));
      setRemoteLoading(false); setConflict(false); setReloadNotice("");
      setStatus(saved ? `${saved.kind === "xml" ? "完整曲谱" : "校对"}已保存 · 当前版本 ${listing.revision} · MusicXML 与 MIDI 已更新` : `曲谱已载入 · 校对版本 ${listing.revision}${latest.warnings?.length ? " · 请对照原稿核对识谱提示" : ""}`);
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
    else if (!job) setStatus(notation ? "正在排版曲谱…" : "原稿已载入 · 连接识谱服务并重新导入后可校对音符");
    return () => { live = false; URL.revokeObjectURL(objectUrl); };
  }, [originalFile, xmlFile, notation]);

  async function showOriginal() {
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
    setNotes(Array.from(document.querySelectorAll("part > measure > note")).map((note, index) => ({
      index, measure: note.parentElement?.getAttribute("number") || "",
      part: note.parentElement?.parentElement?.getAttribute("id") || "",
      step: note.querySelector("pitch > step")?.textContent || "C",
      octave: note.querySelector("pitch > octave")?.textContent || "4",
      alter: note.querySelector("pitch > alter")?.textContent || "0",
      duration: note.querySelector("duration")?.textContent || "0",
      rest: !!note.querySelector("rest"),
    })));
  }, [xml, job?.id]);

  useLayoutEffect(() => {
    // Match the fields to the selected note before painting. Ownership also
    // prevents a prior selection/revision's fields being saved to a new note.
    setDraftOwner(current || null);
    if (current) { setStep(current.step); setOctave(current.octave); setAlter(current.alter); setDuration(current.duration); setNoteType(current.source?.type || "quarter"); setDot(String(current.source?.dot || 0)); setRest(current.rest); }
  }, [current]);

  useEffect(() => {
    const container = sheet.current;
    setSheetReady(false);
    if (!container || !notation || (!xml && xmlFile) || (!xml && !file)) return;
    const host = createScoreRenderHost(container);
    let observer: ResizeObserver | undefined;
    setStatus("正在排版曲谱…");
    import("opensheetmusicdisplay").then(async (module) => {
      if (!host.isActive()) return;
      const OpenSheetMusicDisplay = resolveOSMDConstructor(module);
      const display = new OpenSheetMusicDisplay(host.element, { autoResize: false, backend: "svg", drawTitle: true });
      host.attach(display);
      const source = xmlFile ? new DOMParser().parseFromString(xml, "application/xml") : file!;
      if (source instanceof Document && (source.querySelector("parsererror") || source.documentElement.localName !== "score-partwise")) throw new Error("曲谱不是有效的 MusicXML。");
      await display.load(source);
      if (!host.isActive()) { host.dispose(); return; }
      display.Zoom = zoom;
      display.render();
      setSheetReady(true);
      setStatus(job ? `曲谱已载入 · 校对版本 ${revision}${job.warnings?.length ? " · 请对照原稿核对识谱提示" : ""}` : xmlFile ? "MusicXML 已载入 · 可从右侧选择音符校对" : "压缩曲谱已载入 · 上传至识谱服务后可校对并导出 MIDI");
      const paper = container.parentElement!;
      let width = paper.clientWidth;
      observer = new ResizeObserver(() => {
        if (!host.isActive()) return;
        const nextWidth = paper.clientWidth;
        if (nextWidth !== width && display.IsReadyToRender()) {
          width = nextWidth;
          display.render();
        }
      });
      observer.observe(paper);
    }).catch((error) => {
      const active = host.isActive();
      observer?.disconnect();
      host.dispose();
      console.error("MusicXML layout failed", error);
      if (active) { setSheetReady(false); setStatus(`曲谱排版失败：${error instanceof Error ? error.message : String(error)}`); }
    });
    return () => { host.dispose(); observer?.disconnect(); };
  }, [xml, notation, file, xmlFile, zoom, revision]);

  async function publishEdit(edits: NoteEdit[]) {
    if (!job) return;
    setBusy(true);
    try {
      const { job: updated } = await remoteLoader.save(() => cloud.patch(job.id, scoreIndex, revision, edits), scoreIndex, "notes");
      try { await onJob?.(updated); } catch { setStatus("校对已保存到云端，本机曲谱列表更新未完成。重新打开曲谱后可同步。"); }
    }
    catch (error) { setStatus(errorMessage(error)); if (error instanceof CloudError && (error.status === 409 || error.code === "write_status_unknown")) { setConflict(true); setReloadNotice(errorMessage(error)); } }
    finally { setBusy(false); }
  }

  async function saveXML(text = xmlDraft) {
    if (!job) return;
    const document = new DOMParser().parseFromString(text, "application/xml");
    if (document.querySelector("parsererror") || document.documentElement.localName !== "score-partwise") { setStatus("请选择有效的 MusicXML，当前版本不会被覆盖。"); return; }
    setBusy(true);
    try {
      const { job: updated } = await remoteLoader.save(() => cloud.put(job.id, scoreIndex, revision, text), scoreIndex, "xml");
      try { await onJob?.(updated); } catch { setStatus("完整曲谱已保存到云端，本机曲谱列表更新未完成。重新打开曲谱后可同步。"); }
    }
    catch (error) { setStatus(errorMessage(error)); if (error instanceof CloudError && (error.status === 409 || error.code === "write_status_unknown")) { setConflict(true); setReloadNotice(errorMessage(error)); } }
    finally { setBusy(false); }
  }

  async function exportFile(kind: "musicxml" | "midi" | "original" | "omr") {
    setBusy(true);
    try {
      if (job) { const stem = job.scores[scoreIndex]?.name || name.replace(/\.[^.]+$/, ""); await cloud.export(job.id, scoreIndex, kind, kind === "original" ? job.filename : `${stem}.${{ musicxml: "musicxml", midi: "mid", omr: "omr", original: "" }[kind]}`); }
      else if (file) await downloadBlob(file, name);
      setStatus("文件已导出。");
    } catch (error) { setStatus(errorMessage(error)); }
    finally { setBusy(false); }
  }

  async function savePitch() {
    if (!current || !draftReady || busy || conflict) return;
    if (job && current.source) {
      const edit: NoteEdit = { partId: current.source.partId, measureIndex: current.source.measureIndex, noteIndex: current.source.noteIndex };
      if (rest !== current.rest) edit.rest = rest;
      if (!rest && (current.rest || step !== current.step || octave !== current.octave || alter !== current.alter)) edit.pitch = { step, alter: Number(alter), octave: Number(octave) };
      if (duration !== current.duration) { if (!Number.isFinite(Number(duration)) || Number(duration) <= 0) { setStatus("时值必须大于零，单位为当前小节的 divisions。"); return; } edit.duration = Number(duration); }
      if (noteType !== current.source.type) edit.type = noteType;
      if (Number(dot) !== current.source.dot) edit.dot = Number(dot);
      await publishEdit([edit]); return;
    }
    if (current.rest) return;
    const document = new DOMParser().parseFromString(xml, "application/xml");
    const note = document.querySelectorAll("part > measure > note")[selected];
    const pitch = note?.querySelector("pitch");
    if (!pitch) return;
    pitch.querySelector("step")!.textContent = step;
    pitch.querySelector("octave")!.textContent = octave;
    let accidental = pitch.querySelector("alter");
    if (!accidental) { accidental = document.createElement("alter"); pitch.insertBefore(accidental, pitch.querySelector("octave")); }
    accidental.textContent = alter;
    // Existing explicit accidentals must not contradict the edited pitch.
    note.querySelector("accidental")?.remove();
    const updated = new XMLSerializer().serializeToString(document);
    setBusy(true);
    try {
      await onSave(new Blob([updated], { type: "application/vnd.recordare.musicxml+xml" }));
      setXml(updated); setStatus("校对已保存到本机。");
    } catch { setStatus("保存失败，请检查本地存储权限。"); }
    finally { setBusy(false); }
  }

  return <div className="score-workspace" data-practice={practicing}>
    <header className="score-workspace-header">
      <button type="button" className="score-tool" onClick={onClose}>‹ 我的曲谱</button>
      <div><h1 id="score-panel-title">{practicing ? "练琴时刻" : "曲谱预览与校对"}</h1><p>{practicing ? "黑白键 · 专注每一次练习" : "黑白键 · 让每一个音符更准确"}</p></div>
      <span className="score-local-badge">{job ? `云端版本 ${revision || job.revision}` : "本机保存"}</span>
    </header>
    <p className="score-landscape-hint" role="status">{orientationNotice || "横屏查看乐谱更清晰。若未自动旋转，请关闭系统方向锁定，并将设备横放。"}</p>
    <div className="score-workspace-layout">
      <aside className="score-tools">
        <p className="score-eyebrow">{practicing ? "正在练习" : "我的曲谱"}</p>
        <h2 className="score-filename">{name}</h2>
        <span className="score-format">{format}</span>
        <section className="score-tool-section"><h3>曲谱文件</h3><p>{job ? "识谱与校对保存在云端。原稿保留；保存时同时更新 MusicXML 与 MIDI。" : "示例曲谱保存在本机。"}</p>
          <button type="button" disabled={!!job && !remoteReady} className="score-tool score-tool-primary" onClick={() => setPracticing(!practicing)}>{practicing ? "返回曲谱校对" : "开始练习"}</button>
          <button type="button" className="score-tool" disabled={busy || (job ? !remoteReady : !file)} onClick={() => void exportFile("musicxml")}>下载当前曲谱</button>
          {job && <button type="button" className="score-tool" disabled={busy || !remoteReady} onClick={() => void exportFile("midi")}>下载 MIDI</button>}
          {job && <button type="button" className="score-tool" disabled={busy} onClick={() => void exportFile("original")}>下载原稿</button>}
          {job?.artifacts.omr && <button type="button" className="score-tool" disabled={busy} onClick={() => void exportFile("omr")}>下载 Audiveris 工程</button>}
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
        {reloadNotice && job && <button type="button" className="score-tool" disabled={busy || remoteLoading} onClick={() => void loadRemote(job, scoreIndex)}>重新载入最新版本</button>}
        <div className="score-paper">
          {notation ? <div ref={sheet} role={sheetReady ? "img" : undefined} aria-label={sheetReady ? "MusicXML 谱面" : undefined} /> : format === "PDF" && url ? <iframe src={url} title={`${name}乐谱原稿`} /> : originalFile?.type.startsWith("image/") && url ? <img src={url} alt={`${name}乐谱原稿`} /> : <p>{job && !remoteReady ? "正在等待识谱结果。" : "此文件暂不支持预览。"}</p>}
        </div>
      </main>
      {practicing ? <PracticeSession name={name} measures={Math.max(1, new Set(notes.map((note) => note.measure)).size)} parts={[...new Set(notes.map((note) => note.part))]} /> : <aside className="score-inspector">
        <p className="score-eyebrow">音符校对</p><h2>把每个音符校准</h2>
        <p className="score-description">{job ? "选择音符并对照原谱校对，保存后更新云端 MusicXML 与 MIDI。" : "从列表选择音符，对照原谱校对音高，保存后更新本地 MusicXML。"}</p>
        {notes.length ? <>
          <label className="score-field">小节筛选<input inputMode="numeric" value={measure} onChange={(event) => setMeasure(event.currentTarget.value)} placeholder="全部小节" /></label>
          <div className="score-note-list" aria-label="音符列表">{filtered.map((note) => <button key={note.index} type="button" disabled={busy} aria-label={`第 ${note.measure} 小节 · ${note.rest ? "休止符" : `${note.step}${note.alter === "1" ? "♯" : note.alter === "-1" ? "♭" : ""}${note.octave}`} #${note.index + 1}`} aria-pressed={selected === note.index} onClick={() => setSelected(note.index)}><span>第 {note.measure} 小节 · {note.rest ? "休止符" : `${note.step}${note.alter === "1" ? "♯" : note.alter === "-1" ? "♭" : ""}${note.octave}`}</span><span>#{note.index + 1}</span></button>)}</div>
          {!filtered.length && <p className="score-description">没有这个小节的音符。</p>}
          {current && <section className="score-edit"><h3>{current.part} · 第 {current.measure} 小节</h3><p className="score-description">音符 {selected + 1} · 原始时值 {current.duration}{current.source ? ` · 每拍 ${current.source.divisions} 单位` : ""}</p>
            {job && <label className="score-field">音符种类<select aria-label="音符或休止符" disabled={busy || conflict} value={rest ? "rest" : "note"} onChange={(event) => setRest(event.currentTarget.value === "rest")}><option value="note">音符</option><option value="rest">休止符</option></select></label>}
            {rest ? <p className="score-description">{job ? "休止符可修改时值，或切换为音符。" : "休止符暂不支持修改音高。"}</p> : <div className="score-pitch-fields">
              <label className="score-field">音名<select disabled={busy || conflict} value={step} onChange={(event) => setStep(event.currentTarget.value)}>{["C", "D", "E", "F", "G", "A", "B"].map((value) => <option key={value}>{value}</option>)}</select></label>
              <label className="score-field">升降<select disabled={busy || conflict} value={alter} onChange={(event) => setAlter(event.currentTarget.value)}><option value="0">还原</option><option value="1">升半音</option><option value="-1">降半音</option><option value="2">重升</option><option value="-2">重降</option></select></label>
              <label className="score-field">八度<select disabled={busy || conflict} value={octave} onChange={(event) => setOctave(event.currentTarget.value)}>{Array.from({ length: 10 }, (_, value) => <option key={value}>{value}</option>)}</select></label>
            </div>}
            {job && <div className="score-pitch-fields"><label className="score-field">时值<input aria-label="音符时值" type="number" min="0" step="any" disabled={busy || conflict} value={duration} onChange={(event) => setDuration(event.currentTarget.value)} /></label><label className="score-field">记谱时值<select aria-label="记谱时值" disabled={busy || conflict} value={noteType} onChange={(event) => setNoteType(event.currentTarget.value)}>{["", "maxima", "long", "breve", "whole", "half", "quarter", "eighth", "16th", "32nd", "64th", "128th", "256th", "512th", "1024th"].map((type) => <option key={type} value={type}>{type || "未指定"}</option>)}</select></label><label className="score-field">附点<select aria-label="附点数量" disabled={busy || conflict} value={dot} onChange={(event) => setDot(event.currentTarget.value)}>{[0, 1, 2, 3, 4].map((value) => <option key={value}>{value}</option>)}</select></label></div>}
            {(!rest || job) && <button type="button" className="score-tool score-tool-primary" disabled={busy || conflict || !draftReady || (step === current.step && octave === current.octave && alter === current.alter && (!job || duration === current.duration && noteType === current.source?.type && Number(dot) === current.source?.dot && rest === current.rest))} onClick={() => void savePitch()}>{busy ? "正在保存…" : "保存校对"}</button>}
            {job && current.source && <button type="button" className="score-tool" disabled={busy || conflict} onClick={() => { if (window.confirm(`删除第 ${current.measure} 小节的音符 ${selected + 1}？`)) void publishEdit([{ partId: current.source!.partId, measureIndex: current.source!.measureIndex, noteIndex: current.source!.noteIndex, delete: true }]); }}>删除当前音符</button>}
          </section>}
        </> : <div className="score-empty-inspector"><h3>{job ? "等待可校对乐谱" : "原稿已准备好"}</h3><p>{job ? "识谱完成后会显示音符列表。" : "导入 MusicXML 可校对音高。图片、PDF 和压缩曲谱重新导入云端服务后，可提取音符。"}</p></div>}
        {job && remoteReady && <section className="score-edit"><h3>完整 MusicXML 校对</h3><p className="score-description">可修改其他记谱内容。保存后，同时更新 MusicXML 和 MIDI。</p><button type="button" className="score-tool" disabled={busy || conflict} onClick={() => replacement.current?.click()}>导入校对后的 MusicXML</button><details><summary className="score-description">编辑 MusicXML 内容</summary><label className="score-field">MusicXML<textarea aria-label="完整 MusicXML" rows={10} value={xmlDraft} disabled={busy || conflict} onChange={(event) => setXmlDraft(event.currentTarget.value)} /></label><button type="button" className="score-tool score-tool-primary" disabled={busy || conflict || xmlDraft === xml} onClick={() => void saveXML()}>保存完整曲谱</button></details><input ref={replacement} className="hidden" type="file" accept=".musicxml,.xml" aria-label="导入校对后的 MusicXML 文件" onChange={(event) => { const file = event.currentTarget.files?.[0]; if (file) void file.text().then((text) => saveXML(text)).catch((error) => setStatus(errorMessage(error))); event.currentTarget.value = ""; }} /></section>}
      </aside>}
    </div>
  </div>;
}
