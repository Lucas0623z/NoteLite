import { useEffect, useRef, useState } from "react";
import normal from "../imports/my-scores-upload-normal.png";
import pressed from "../imports/my-scores-upload-pressed.png";
import ScoreWorkspace from "./ScoreWorkspace";
import { cloud, CloudError, createUUID, errorMessage, isNativeCloud, nativeRequest, type CloudJob } from "./cloud";

type Score = { id: string; name: string; format: string; file?: Blob; sample?: boolean; job?: CloudJob; removed?: boolean };
type Panel = "import" | "rename" | "delete" | "view" | "practice" | "settings" | null;
const sampleScore = `<score-partwise version="4.0"><work><work-title>示例练习</work-title></work><part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list><part id="P1"><measure number="1"><attributes><divisions>1</divisions><key><fifths>0</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes>${["C", "D", "E", "F"].map((step) => `<note><pitch><step>${step}</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>`).join("")}</measure></part></score-partwise>`;

async function scoreStore<T>(mode: IDBTransactionMode, action: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open("heibaikey-scores", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("scores", { keyPath: "id" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  return new Promise((resolve, reject) => {
    const transaction = db.transaction("scores", mode);
    const request = action(transaction.objectStore("scores"));
    transaction.oncomplete = () => { db.close(); resolve(request.result); };
    transaction.onerror = transaction.onabort = () => { db.close(); reject(transaction.error); };
  });
}

export default function MyScoresPage({ isDark }: { isDark: boolean }) {
  const [scores, setScores] = useState<Score[]>([]);
  const [loading, setLoading] = useState(true);
  const [importPage, setImportPage] = useState(false);
  const [panel, setPanel] = useState<Panel>(null);
  const [selected, setSelected] = useState<Score | null>(null);
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [baseURL, setBaseURL] = useState("https://124.221.211.156");
  const [pairCode, setPairCode] = useState("");
  const [connected, setConnected] = useState(false);
  const [orientationNotice, setOrientationNotice] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const files = useRef<HTMLInputElement>(null);
  const photos = useRef<HTMLInputElement>(null);
  const camera = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const scrollPosition = useRef(0);
  const landscapeWanted = useRef(false);
  const fullscreenOwned = useRef(false);
  const orientationOwned = useRef(false);
  const nativeOrientationOwned = useRef(false);
  const pendingFile = useRef<File | null>(null);
  const workspaceOpen = panel === "view" || panel === "practice";
  const importing = importPage || scores.length === 0;

  async function enterLandscape() {
    setOrientationNotice("");
    if (isNativeCloud()) {
      landscapeWanted.current = true;
      try { await nativeRequest("orientation/set", { mode: "landscape" }); nativeOrientationOwned.current = true; if (!landscapeWanted.current) restoreOrientation(); }
      catch { setOrientationNotice("自动横屏未完成，请将设备横放后继续。"); }
      return;
    }
    // Fullscreen must be requested directly from the tap, not a React effect.
    if (!window.matchMedia("(pointer: coarse)").matches) return;
    landscapeWanted.current = true;
    const orientation = screen.orientation as ScreenOrientation & { lock?: (direction: string) => Promise<void> };
    try {
      if (!document.fullscreenElement && document.documentElement.requestFullscreen) {
        await document.documentElement.requestFullscreen();
        fullscreenOwned.current = true;
      }
      if (!landscapeWanted.current) { restoreOrientation(); return; }
      if (orientation?.lock) {
        await orientation.lock("landscape");
        orientationOwned.current = true;
        if (!landscapeWanted.current) restoreOrientation();
      }
    } catch {
      // iOS Safari and embedded previews may reject locking; show a portrait hint.
    }
  }

  function restoreOrientation() {
    landscapeWanted.current = false;
    if (nativeOrientationOwned.current) { nativeOrientationOwned.current = false; void nativeRequest("orientation/set", { mode: "restore" }).catch(() => {}); }
    if (orientationOwned.current) {
      screen.orientation?.unlock();
      orientationOwned.current = false;
    }
    if (fullscreenOwned.current) {
      fullscreenOwned.current = false;
      if (document.fullscreenElement) void document.exitFullscreen().catch(() => {});
    }
  }

  useEffect(() => {
    if (workspaceOpen) return () => restoreOrientation();
  }, [workspaceOpen]);

  useEffect(() => {
    const onNativeEvent = (event: Event) => {
      const detail = (event as CustomEvent<{ type?: string; message?: string }>).detail;
      if (detail?.type === "orientationError") setOrientationNotice(detail.message || "自动横屏未完成，请将设备横放后继续。");
    };
    window.addEventListener("notelite-cloud-event", onNativeEvent);
    return () => window.removeEventListener("notelite-cloud-event", onNativeEvent);
  }, []);

  useEffect(() => {
    let live = true;
    scoreStore("readonly", (store) => store.getAll()).then((saved) => {
      if (live) setScores((saved as Score[]).filter((score) => !score.removed));
      if (live) void refreshCloud(saved as Score[]);
    }).catch(() => { if (live) setMessage("无法读取本地曲谱，请检查浏览器存储权限。"); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, []);

  useEffect(() => {
    const waiting = scores.filter((score) => score.job?.state === "queued" || score.job?.state === "running");
    if (!waiting.length) return;
    let live = true;
    const timer = window.setTimeout(async () => {
      for (const score of waiting) {
        try { const job = await cloud.job(score.id); if (live) await acceptJob(job, score); }
        catch (error) { if (live) setMessage(errorMessage(error)); }
      }
      // Saving a fresh score object schedules the next bounded poll.
      if (live) setScores((previous) => [...previous]);
    }, 3000);
    return () => { live = false; window.clearTimeout(timer); };
  }, [scores]);

  useEffect(() => {
    if (panel && !dialog.current?.open) dialog.current?.showModal();
    if (!panel && dialog.current?.open) dialog.current.close();
  }, [panel]);

  useEffect(() => {
    if (!importing && list.current) list.current.scrollTop = scrollPosition.current;
  }, [importing]);

  async function save(score: Score) {
    await scoreStore("readwrite", (store) => store.put(score));
    setScores((previous) => {
      const index = previous.findIndex((item) => item.id === score.id);
      return index < 0 ? [...previous, score] : previous.map((item) => item.id === score.id ? score : item);
    });
  }

  async function acceptJob(job: CloudJob, existing?: Score) {
    const previous = existing || scores.find((item) => item.id === job.id);
    if (previous?.removed) return;
    const imported: Score = { ...previous, id: job.id, name: previous?.name || job.filename, format: previous?.format || job.filename.split(".").pop()?.toUpperCase() || "", job };
    await save(imported);
    setSelected((current) => current?.id === imported.id ? imported : current);
    return imported;
  }

  async function refreshCloud(saved?: Score[]) {
    try {
      const configuration = await cloud.configuration();
      setBaseURL(configuration.baseURL);
      if (!configuration.hasCredentials) { setConnected(false); return; }
      const local = saved || await scoreStore("readonly", (store) => store.getAll()) as Score[];
      const jobs = await cloud.jobs();
      setConnected(true);
      for (const job of jobs) await acceptJob(job, local.find((score) => score.id === job.id));
    } catch (error) {
      if (error instanceof CloudError && error.status === 401) setConnected(false);
      // A first visit remains the original empty library. Imported scores remain usable offline.
      if (saved?.some((score) => score.job && !score.removed)) setMessage(errorMessage(error));
    }
  }

  async function connectDevice() {
    setBusy(true);
    try {
      await cloud.configure(baseURL);
      if (pairCode.trim()) await cloud.pair(pairCode, isNativeCloud() ? "NoteLite Apple" : "NoteLite 浏览器");
      const configuration = await cloud.configuration();
      if (!configuration.hasCredentials) throw new CloudError("请输入服务器提供的设备连接码。", 401);
      await cloud.health();
      await cloud.jobs();
      setConnected(true); setPairCode(""); setMessage("设备已连接，可以上传曲谱并保存校对。");
      await refreshCloud(); setPanel(null);
      const file = pendingFile.current; pendingFile.current = null;
      if (file) await importFile(file);
    } catch (error) { setMessage(errorMessage(error)); }
    finally { setBusy(false); }
  }

  async function importFile(file?: File) {
    if (!file) return;
    setBusy(true);
    try {
      const extension = file.name.split(".").pop()?.toLowerCase() || "";
      if (!["png", "jpg", "jpeg", "pdf", "musicxml", "mxl", "xml"].includes(extension)) {
        throw new Error("请选择 PNG、JPEG、PDF 或 MusicXML 曲谱文件。");
      }
      setMessage("正在上传曲谱…");
      const job = await cloud.upload(file, file.name);
      const imported = await acceptJob(job, { id: job.id, name: file.name, format: extension.toUpperCase(), file });
      if (!imported) return;
      setSelected(imported);
      setPanel(null);
      setImportPage(false);
      setMessage(job.recognitionMode === "import" ? "曲谱正在导入，完成后可查看、校对和导出。" : "曲谱正在识别，完成后可查看、校对和导出。");
    } catch (error) {
      if (error instanceof CloudError && error.status === 401) { pendingFile.current = file; setPanel("settings"); }
      setMessage(errorMessage(error));
    } finally { setBusy(false); }
  }

  async function chooseFile() {
    if (!isNativeCloud()) { files.current?.click(); return; }
    if (!connected) { setPanel("settings"); setMessage("先连接设备，再选择要识别的曲谱。"); return; }
    setBusy(true);
    try {
      const job = await cloud.importNative(); await acceptJob(job);
      setPanel(null); setImportPage(false); setMessage("曲谱已上传，正在处理…");
    } catch (error) { if (!(error instanceof CloudError && error.code === "cancelled")) setMessage(errorMessage(error)); }
    finally { setBusy(false); }
  }

  async function loadSample() {
    setBusy(true);
    try {
      await save({ id: createUUID(), name: "示例练习.musicxml", format: "MUSICXML", sample: true, file: new Blob([sampleScore], { type: "application/vnd.recordare.musicxml+xml" }) });
      setPanel(null); setImportPage(false); setMessage("已载入示例曲谱。");
    } catch { setMessage("示例保存失败，请检查浏览器存储权限。"); }
    finally { setBusy(false); }
  }

  async function confirmEdit() {
    if (!selected) return;
    setBusy(true);
    try {
      if (panel === "rename") await save({ ...selected, name: name.trim() });
      else {
        if (selected.job) await scoreStore("readwrite", (store) => store.put({ ...selected, removed: true }));
        else await scoreStore("readwrite", (store) => store.delete(selected.id));
        setScores((previous) => previous.filter((score) => score.id !== selected.id));
      }
      setPanel(null);
    } catch { setMessage("操作失败，请稍后重试。"); }
    finally { setBusy(false); }
  }

  function openPanel(next: Panel, score?: Score) {
    if (next === "view" || next === "practice") void enterLandscape();
    setSelected(score || null); setName(score?.name || ""); setMessage(""); setPanel(next);
    if (next === "settings") void cloud.configuration().then(async (configuration) => {
      setBaseURL(configuration.baseURL);
      if (!configuration.hasCredentials) { setConnected(false); return; }
      await cloud.jobs(); setConnected(true);
    }).catch((error) => { if (error instanceof CloudError && error.status === 401) setConnected(false); setMessage(errorMessage(error)); });
  }
  const outline = isDark ? "border-white/15" : "border-[#e5e5e5]";
  const button = `scores-action cursor-pointer rounded-[12px] border-2 border-b-[5px] px-3 py-2 text-sm font-bold text-[#67db23] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-current disabled:opacity-50 ${outline} ${isDark ? "bg-[#252525]" : "bg-white"}`;
  const title = panel === "import" ? "导入曲谱" : panel === "rename" ? "重命名" : panel === "delete" ? "删除曲谱" : panel === "view" ? selected?.name : panel === "practice" ? "开始练习" : "云端识谱设置";

  return <section className={`scores-library flex h-full min-h-0 flex-col ${isDark ? "text-white" : "text-[#333]"}`}>
    {loading ? <p role="status" className="m-auto text-sm text-[#999]">正在读取曲谱…</p> : <>
      {importing ? <div className="flex min-h-0 flex-1 flex-col">
        {scores.length > 0 && <button type="button" onClick={() => setImportPage(false)} className="self-start px-4 py-3 text-sm text-[#999] focus-visible:outline-2">‹ 返回我的曲谱</button>}
        <div className="scores-page flex min-h-0 flex-1 flex-col items-center justify-center px-4 py-8">
          <button type="button" aria-label="导入曲谱" onClick={() => openPanel("import")} className="group relative block w-full max-w-[400px] cursor-pointer touch-manipulation rounded-[18px] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#67db23]">
            <img src={normal} alt="上传文件、图片或拍照识谱，开启你的专属陪练吧！" draggable={false} className="block h-auto w-full select-none group-active:opacity-0" />
            <img src={pressed} alt="" aria-hidden="true" draggable={false} className="pointer-events-none absolute inset-0 h-full w-full select-none object-contain opacity-0 group-active:opacity-100" />
          </button>
        </div>
      </div> : <div ref={list} onScroll={(event) => { scrollPosition.current = event.currentTarget.scrollTop; }} className="min-h-0 flex-1 overflow-y-auto px-4 py-5">
        <header className="mb-5 flex items-center justify-between gap-4"><h1 className="text-xl font-bold">我的曲谱</h1><button type="button" className={button} onClick={() => setImportPage(true)}>导入乐谱</button></header>
        <div className="scores-cards grid gap-4">
          {scores.map((score) => <article key={score.id} className={`rounded-[18px] border-2 border-b-[5px] p-4 ${outline}`}>
            <h2 className="break-all text-lg font-bold">{score.name}</h2>
            <p className="mt-2 text-xs text-[#999]">{score.sample ? "1 个练习乐谱" : score.job ? ({ queued: "等待识谱", running: "正在识谱", succeeded: `${score.job.scores.length} 个乐章 · 校对版本 ${score.job.revision}`, failed: "识谱未完成" })[score.job.state] : "本地曲谱文件"} · {score.format}</p>
            {score.job?.state === "failed" && <p role="status" className="mt-2 text-xs text-[#999]">{score.job.error || "请检查原稿清晰度后重新导入。"}</p>}
            <div className="mt-4 flex flex-wrap gap-2">
              <button type="button" disabled={!!score.job && score.job.state !== "succeeded"} className={`${button} !border-[#49a619] !bg-[#67db23] !text-white`} onClick={() => openPanel("practice", score)}>开始练习</button>
              <button type="button" className={button} onClick={() => openPanel("view", score)}>查看曲谱</button>
              <button type="button" className={button} onClick={() => openPanel("rename", score)}>重命名</button>
              <button type="button" className={`${button} !text-[#e16c6c]`} onClick={() => openPanel("delete", score)}>删除</button>
            </div>
          </article>)}
        </div>
        <div className="mt-4 grid gap-3"><button type="button" className={button} onClick={() => openPanel("settings")}>云端识谱设置</button><button type="button" disabled={busy} className={button} onClick={loadSample}>载入示例曲谱</button></div>
      </div>}
      {message && <p role="status" className="px-4 pb-4 text-center text-sm leading-6 text-[#999]">{message}</p>}
    </>}
    <input ref={files} type="file" accept="image/png,image/jpeg,.pdf,.musicxml,.mxl,.xml" className="hidden" aria-label="选择曲谱文件" onChange={(event) => { void importFile(event.currentTarget.files?.[0]); event.currentTarget.value = ""; }} />
    <input ref={photos} type="file" accept="image/*" className="hidden" aria-label="从相册选择曲谱" onChange={(event) => { void importFile(event.currentTarget.files?.[0]); event.currentTarget.value = ""; }} />
    <input ref={camera} type="file" accept="image/*" capture="environment" className="hidden" aria-label="拍照识谱" onChange={(event) => { void importFile(event.currentTarget.files?.[0]); event.currentTarget.value = ""; }} />
    <dialog ref={dialog} data-workspace={panel === "view" || panel === "practice"} aria-labelledby="score-panel-title" onCancel={() => setPanel(null)} onClose={() => setPanel(null)} onClick={(event) => { if (event.target === event.currentTarget && !busy) setPanel(null); }} className={`scores-dialog fixed rounded-[20px] border-0 p-5 font-sans backdrop:bg-black/70 ${isDark ? "bg-[#191919] text-white" : "bg-white text-[#333]"}`}>
      {(panel === "view" || panel === "practice") && selected ? <ScoreWorkspace practice={panel === "practice"} name={selected.name} format={selected.format} file={selected.file} job={selected.job} orientationNotice={orientationNotice} onJob={async (job) => { await acceptJob(job, selected); }} onClose={() => setPanel(null)} onSave={async (file) => { const updated = { ...selected, file }; await save(updated); setSelected(updated); }} /> : <>
      <h2 id="score-panel-title" className="mb-3 break-all text-lg font-bold">{title}</h2>
      {panel === "import" ? <>
        <p className="mb-4 text-xs leading-6 text-[#999]">支持 PNG、JPEG、PDF 和 MusicXML。选择的曲谱上传到识谱服务；完成后可校对并导出 MusicXML、MIDI。</p>
        <div className="grid gap-3">
          <button type="button" disabled={busy} className={button} onClick={() => void chooseFile()}>选择文件</button>
          <button type="button" disabled={busy} className={button} onClick={() => photos.current?.click()}>从相册选择</button>
          <button type="button" disabled={busy} className={button} onClick={() => camera.current?.click()}>拍照识谱</button>
          <button type="button" disabled={busy} className={button} onClick={loadSample}>载入示例曲谱</button>
          <button type="button" disabled={busy} className={button} onClick={() => openPanel("settings")}>云端识谱设置</button>
        </div>
      </> : panel === "rename" ? <form onSubmit={(event) => { event.preventDefault(); if (name.trim()) void confirmEdit(); }}>
        <input aria-label="曲谱名称" autoFocus value={name} maxLength={160} onChange={(event) => setName(event.currentTarget.value)} className={`mb-4 w-full rounded-xl border-2 bg-transparent p-3 ${outline}`} />
        <button type="submit" disabled={busy || !name.trim()} className={`${button} w-full`}>保存</button>
      </form> : panel === "delete" ? <><p className="mb-4 text-sm leading-6">{selected?.job ? `从本机曲谱列表移除「${selected.name}」？云端原稿和校对版本会保留。` : `确定删除「${selected?.name}」？删除后无法恢复。`}</p><button type="button" disabled={busy} className={`${button} w-full !text-[#e16c6c]`} onClick={confirmEdit}>确认删除</button></> : <form onSubmit={(event) => { event.preventDefault(); void connectDevice(); }}>
        <p className="text-sm leading-7 text-[#999]">{connected ? "设备已连接。曲谱上传后可识谱、校对及导出。" : "填写服务地址和设备连接码，连接后再上传曲谱。"}</p>
        <label className="score-field">识谱服务地址<input aria-label="识谱服务地址" type="url" value={baseURL} disabled={!isNativeCloud()} onChange={(event) => setBaseURL(event.currentTarget.value)} /></label>
        <label className="score-field">设备连接码<input aria-label="设备连接码" value={pairCode} autoComplete="off" maxLength={80} onChange={(event) => setPairCode(event.currentTarget.value)} placeholder={connected ? "已连接；更换设备时填写" : "输入服务器提供的连接码"} /></label>
        <button type="submit" disabled={busy} className={`${button} w-full`}>{busy ? "正在连接…" : connected && !pairCode ? "检查连接" : "连接设备"}</button>
      </form>}
      {message && <p role="status" className="mt-3 text-sm leading-6 text-[#999]">{message}</p>}
      <button type="button" disabled={busy} className={`${button} mt-3 w-full !text-[#999]`} onClick={() => setPanel(null)}>{panel === "import" || panel === "delete" || panel === "rename" ? "取消" : "关闭"}</button>
      </>}
    </dialog>
  </section>;
}
