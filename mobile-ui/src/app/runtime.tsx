import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { summarizeHistory, type HistoryRecord } from "./history";
import { boundedDownload, checkedJob, CloudError, delay, request, validArtifact, validateScore, type CloudJob } from "./cloud";
import Modal from "./Modal";
import { watchPracticePhase } from "./practice-phase";

export interface ScoreRecord {
  id: string; title: string; kind: string; phase: string; progress?: number;
  error?: string; paused: boolean; canPractice: boolean; partCount: number;
  jobId?: string; filename?: string; parts?: { id: string; title: string }[];
}
export interface YinbanState {
  records: ScoreRecord[]; history: HistoryRecord[]; serverConfigured: boolean;
  activeIDs: string[]; canImport: boolean; error?: string;
}
declare global {
  interface Window { webkit?: { messageHandlers?: { yinban?: { postMessage: (message: Record<string, unknown>) => void } } }; }
}
const empty: YinbanState = { records: [], history: [], serverConfigured: false, activeIDs: [], canImport: true };
function savedPreview(): YinbanState {
  try { const saved = JSON.parse(localStorage.getItem("yinban-preview") || "null");
    if (saved && Array.isArray(saved.records) && Array.isArray(saved.history)) return { ...empty, ...saved, records: saved.records.map((record: ScoreRecord) => ["uploading", "queued", "running", "downloading"].includes(record.phase) ? { ...record, paused: true } : record), serverConfigured: false, activeIDs: [] };
  } catch {}
  return empty;
}
const Context = createContext<{ state: YinbanState; native: boolean; send: (action: string, data?: Record<string, unknown>) => void; importPreview: (files: FileList | File[]) => Promise<number>; }>({ state: empty, native: false, send() {}, async importPreview() { return 0; } });
export function instrumentForCourse(course: string | null) {
  if (!course) return undefined;
  const name = course.split("-").pop() || "";
  return name === "钢琴" ? "piano" : ["小提琴", "中提琴", "大提琴", "低音提琴", "竖琴"].includes(name) ? "strings" : "winds";
}
export function useYinban() { return useContext(Context); }
function database(): Promise<IDBDatabase> { return new Promise((resolve, reject) => {
  const request = indexedDB.open("yinban-preview-files", 1);
  request.onupgradeneeded = () => request.result.createObjectStore("files");
  request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
}); }
async function fileStore(id: string, bytes?: ArrayBuffer | null): Promise<ArrayBuffer | undefined> {
  const db = await database();
  try { return await new Promise((resolve, reject) => {
    const transaction = db.transaction("files", bytes === undefined ? "readonly" : "readwrite");
    const store = transaction.objectStore("files");
    const request = bytes === undefined ? store.get(id) : bytes === null ? store.delete(id) : store.put(bytes, id);
    request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
  }); } finally { db.close(); }
}
function base64(bytes: ArrayBuffer) { let result = ""; const array = new Uint8Array(bytes);
  for (let offset = 0; offset < array.length; offset += 8192) result += String.fromCharCode(...array.subarray(offset, offset + 8192));
  return btoa(result);
}
export function YinbanProvider({ children }: { children: ReactNode }) {
  const native = typeof window.webkit?.messageHandlers?.yinban?.postMessage === "function";
  useLayoutEffect(() => { document.documentElement.dataset.native = String(native); }, [native]);
  const [state, setState] = useState<YinbanState>(native ? empty : savedPreview);
  const [practice, setPractice] = useState<ScoreRecord | null>(null);
  const [preview, setPreview] = useState<{ record: ScoreRecord; url: string } | null>(null);
  const [notice, setNotice] = useState("");
  const frame = useRef<HTMLIFrameElement>(null);
  const savedReports = useRef(new Set<string>());
  const savePracticeReport = useRef<() => void>(() => {});
  const cleanupPractice = useRef<() => void>(() => {});
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; cleanupPractice.current(); };
  }, []);
  const workers = useRef(new Map<string, AbortController>());
  const stateRef = useRef(state);
  stateRef.current = state;
  const [practicePart, setPracticePart] = useState<string | null>(null);
  useLayoutEffect(() => () => cleanupPractice.current(), [practice?.id, practicePart]);
  useEffect(() => {
    if (native) return;
    let cancelled = false;
    fetch("/omr/v1/health", { cache: "no-store", redirect: "error" }).then(response => response.json()).then(body => {
      if (!cancelled) setState(previous => ({ ...previous, serverConfigured: body.status === "ok" }));
    }).catch(() => { if (!cancelled) setState(previous => ({ ...previous, serverConfigured: false })); });
    return () => { cancelled = true; for (const controller of workers.current.values()) controller.abort(); };
  }, [native]);
  function updateRecord(id: string, values: Partial<ScoreRecord>) { setState(previous => ({ ...previous, records: previous.records.map(record => record.id === id ? { ...record, ...values } : record) })); }
  async function recognize(record: ScoreRecord) {
    if (workers.current.has(record.id)) return;
    const controller = new AbortController(); workers.current.set(record.id, controller);
    const { signal } = controller;
    const staged: string[] = []; let uploadStarted = false, jobKnown = Boolean(record.jobId);
    setState(previous => ({ ...previous, activeIDs: [...previous.activeIDs, record.id] }));
    updateRecord(record.id, { error: undefined, paused: false });
    try {
      let job: CloudJob;
      if (record.jobId) job = checkedJob(await (await request(`jobs/${record.jobId}`, { signal })).json());
      else {
        const bytes = await fileStore(record.id); if (!bytes) throw new Error("原始曲谱文件已丢失，请重新导入。");
        updateRecord(record.id, { phase: "uploading" }); uploadStarted = true;
        job = checkedJob(await (await request(`jobs?filename=${encodeURIComponent(record.filename || record.title)}`, { method: "POST", body: bytes, headers: { "Content-Type": "application/octet-stream" }, signal })).json());
        updateRecord(record.id, { jobId: job.id }); jobKnown = true;
      }
      while (["queued", "running"].includes(job.state)) {
        updateRecord(record.id, { phase: job.state }); await delay(signal);
        job = checkedJob(await (await request(`jobs/${job.id}`, { signal })).json());
      }
      if (job.state !== "succeeded") { updateRecord(record.id, { jobId: undefined }); void request(`jobs/${job.id}`, { method: "DELETE" }).catch(() => {}); throw new Error(job.error || "云端识谱未完成，请重试。"); }
      const artifacts = job.artifacts?.filter(artifact => validArtifact(artifact.name)) || [];
      if (!artifacts.length || artifacts.length > 128) throw new Error("服务器没有提供可练习的 MusicXML 乐谱。");
      updateRecord(record.id, { phase: "downloading" });
      const parts: { id: string; title: string }[] = []; let totalBytes = 0;
      for (const artifact of artifacts) {
        const response = await request(`jobs/${job.id}/artifacts/${encodeURIComponent(artifact.name)}`, { signal });
        const bytes = await boundedDownload(response); totalBytes += bytes.byteLength;
        if (totalBytes > 32 * 1024 * 1024) throw new Error("识谱结果合计超过 32 MB。");
        await validateScore(bytes);
        const id = `${record.id}:${artifact.name}`; await fileStore(id, bytes); staged.push(id); parts.push({ id, title: artifact.name });
      }
      if (signal.aborted) throw new DOMException("已暂停", "AbortError");
      updateRecord(record.id, { phase: "succeeded", canPractice: true, partCount: parts.length, parts, error: undefined, jobId: undefined });
      await request(`jobs/${job.id}`, { method: "DELETE" }).catch(() => { setNotice("识谱结果已保存在本机；云端临时任务清理失败，请检查服务保存期限。"); });
    } catch (error) {
      for (const id of staged) void fileStore(id, null);
      if (error instanceof CloudError && error.status === 404) updateRecord(record.id, { jobId: undefined });
      updateRecord(record.id, { phase: signal.aborted ? "imported" : "failed", paused: signal.aborted, error: signal.aborted ? uploadStarted && !jobKnown ? "上传已中断；服务器可能已收到原文件。重试前请检查服务任务。" : undefined : error instanceof Error ? error.message : "识谱失败。" });
    } finally {
      workers.current.delete(record.id); setState(previous => ({ ...previous, activeIDs: previous.activeIDs.filter(id => id !== record.id) }));
    }
  }
  useEffect(() => {
    const listener = (event: Event) => {
      const detail = (event as CustomEvent<YinbanState>).detail;
      if (detail && Array.isArray(detail.records) && Array.isArray(detail.history)) setState(detail);
    };
    window.addEventListener("yinban-state", listener);
    if (native) window.webkit!.messageHandlers!.yinban!.postMessage({ action: "ready" });
    return () => window.removeEventListener("yinban-state", listener);
  }, [native]);
  useEffect(() => { if (!native) try { localStorage.setItem("yinban-preview", JSON.stringify(state)); } catch { setNotice("本机存储空间不足，最新修改未能保存。"); } }, [state, native]);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview.url); }, [preview]);
  async function importPreview(files: FileList | File[]) {
    let imported = 0;
    for (const file of Array.from(files)) {
      const suffix = file.name.split(".").pop()?.toLowerCase() || "";
      const music = ["musicxml", "xml", "mxl"].includes(suffix);
      const limit = (music ? 15 : 25) * 1024 * 1024;
      if (file.size > limit || file.size === 0) { setNotice(`请选择大于 0、最多 ${music ? 15 : 25} MB 的曲谱文件。`); continue; }
      if (!["musicxml", "xml", "mxl", "pdf", "png", "jpg", "jpeg", "webp", "heic"].includes(suffix)) { setNotice("不支持此格式，请选择 MusicXML、PDF 或乐谱图片。"); continue; }
      const id = crypto.randomUUID();
      try {
        await fileStore(id, await file.arrayBuffer());
        if (music) await validateScore(await fileStore(id) as ArrayBuffer);
        setState(previous => ({ ...previous, records: [{ id, title: file.name, filename: file.name, kind: suffix, phase: music ? "ready" : "imported", paused: false, canPractice: music, partCount: music ? 1 : 0 }, ...previous.records] }));
        imported++;
      } catch (error) { void fileStore(id, null); setNotice(error instanceof Error ? error.message : "导入失败，浏览器无法保存曲谱。请检查存储权限。"); }
    }
    return imported;
  }
  async function demo() {
    try { const response = await fetch(new URL("practice/demo.musicxml", document.baseURI));
      if (!response.ok) throw new Error("missing");
      await importPreview([new File([await response.arrayBuffer()], "示例练习.musicxml", { type: "application/xml" })]);
    } catch { setNotice("示例曲谱资源无法读取。"); }
  }
  function send(action: string, data: Record<string, unknown> = {}) {
    if (native) { window.webkit!.messageHandlers!.yinban!.postMessage({ action, ...data }); return; }
    if (["preferences", "theme", "ready"].includes(action)) return;
    const record = stateRef.current.records.find(item => item.id === data.id);
    if (action === "demo") { void demo(); return; }
    if (action === "practice" && record?.canPractice) { setPracticePart(record.parts?.length === 1 ? record.parts[0].id : record.parts?.length ? null : record.id); setPractice(record); return; }
    if (action === "pause" && record) { workers.current.get(record.id)?.abort(); return; }
    if (action === "delete") { workers.current.get(String(data.id))?.abort(); setState(previous => ({ ...previous, records: previous.records.filter(item => item.id !== data.id) })); void fileStore(String(data.id), null); record?.parts?.forEach(part => void fileStore(part.id, null)); if (record?.jobId) void request(`jobs/${record.jobId}`, { method: "DELETE" }).catch(() => {}); return; }
    if (action === "rename") { setState(previous => ({ ...previous, records: previous.records.map(item => item.id === data.id ? { ...item, title: String(data.title).trim() || item.title } : item) })); return; }
    if (action === "deleteHistory") { setState(previous => ({ ...previous, history: previous.history.filter(item => item.id !== data.id) })); return; }
    if (action === "clearHistory") { setState(previous => ({ ...previous, history: [] })); return; }
    if (action === "preview" && record) {
      void fileStore(record.id).then(bytes => {
        if (!bytes) { setNotice("原始曲谱文件已丢失，请重新导入。"); return; }
        if (["musicxml", "xml", "mxl"].includes(record.kind)) { setPracticePart(record.id); setPractice(record); return; }
        setPreview({ record, url: URL.createObjectURL(new Blob([bytes], { type: record.kind === "pdf" ? "application/pdf" : `image/${record.kind === "jpg" ? "jpeg" : record.kind}` })) });
      }); return;
    }
    if (action === "exportData") {
      const url = URL.createObjectURL(new Blob([JSON.stringify({ ...state, profile: JSON.parse(localStorage.getItem("music-local-profile") || "{}") }, null, 2)], { type: "application/json" }));
      const link = document.createElement("a"); link.href = url; link.download = "音伴-本机练习数据.json"; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 2000); return;
    }
    if (action === "feedback") { location.href = "mailto:Lucas.z0623@outlook.com?subject=" + encodeURIComponent("音伴使用反馈"); return; }
    if (action === "recognize" && record && stateRef.current.serverConfigured) { void recognize(record); return; }
    if (action === "recognize" || action === "serverSettings") { setNotice(stateRef.current.serverConfigured ? "本机联调 OMR 服务已连接。当前曲谱只发送到这台电脑的识谱服务；正式 App 可配置 HTTPS 云端地址。" : "尚未启动本机 OMR 联调服务。请使用项目中的移动界面联调启动器；MusicXML 可直接本地练习。正式 App 在服务器设置中填写 HTTPS 地址。"); return; }
    setNotice("此功能需在 iPhone/iPad App 中使用。");
  }
  async function loadedPractice() {
    cleanupPractice.current();
    const iframeWindow = frame.current?.contentWindow as (Window & { NoteLiteNative?: { loadScore: (bytes: string, title: string, id: string) => Promise<void>; finish: () => Record<string, unknown> | null; getReport: () => Record<string, unknown> | null; suspend?: () => void; applyPreferences?: (preferences: Record<string, unknown>) => void } }) | null;
    if (!iframeWindow || !practice || !practicePart) return;
    const api = iframeWindow.NoteLiteNative;
    if (!api) { setNotice("练习组件加载失败，请重试。"); return; }
    try {
      const bytes = await fileStore(practicePart);
      if (!bytes) throw new Error("未找到本机曲谱文件。");
      const partTitle = practice.parts?.find(part => part.id === practicePart)?.title;
      await api.loadScore(base64(bytes), partTitle ? `${practice.title} · ${partTitle}` : practice.title, practicePart);
      if (!mounted.current || frame.current?.contentWindow !== iframeWindow) return;
      try { const options = JSON.parse(localStorage.getItem("music-settings") || "{}"); api.applyPreferences?.({ instrument: instrumentForCourse(localStorage.getItem("music-selected-course")), soundEnabled: options["音效"] ?? true, encouragementEnabled: options["鼓励信息"] ?? true }); } catch {}
      let attached = true;
      const saveReport = (report: Record<string, unknown> | null) => {
        if (!attached || !mounted.current || !report) return;
        const key = `${practice.id}-${report.createdAt}`;
        if (savedReports.current.has(key)) return;
        const history: HistoryRecord = { id: crypto.randomUUID(), recordID: practice.id, title: partTitle ? `${practice.title} · ${partTitle}` : practice.title,
          startedAt: String(report.createdAt || new Date().toISOString()), durationSeconds: Number(report.durationSeconds) || 0,
          completed: Boolean(report.completed), firstTryCorrect: Number(report.firstTryCorrect) || 0,
          total: Number(report.total) || 0, errors: Array.isArray(report.errors) ? report.errors : [],
          results: Array.isArray(report.results) ? report.results : undefined,
          input: typeof report.input === "string" ? report.input : undefined, mode: typeof report.mode === "string" ? report.mode : undefined,
          bpm: typeof report.bpm === "number" ? report.bpm : undefined, scope: report.scope };
        if (history.durationSeconds > 0) { savedReports.current.add(key); setState(previous => ({ ...previous, history: [history, ...previous.history].slice(0, 500) })); }
      };
      const finishAndSave = () => { if (attached && mounted.current) saveReport(api.finish()); };
      savePracticeReport.current = finishAndSave;
      const stopObserving = watchPracticePhase(() => iframeWindow.document.body.dataset.phase, callback => {
        const observer = new MutationObserver(callback);
        observer.observe(iframeWindow.document.body, { attributes: true, attributeFilter: ["data-phase"] });
        return () => observer.disconnect();
      }, () => saveReport(api.getReport()));
      const back = iframeWindow.document.getElementById("back");
      const leave = () => { finishAndSave(); cleanup(); if (mounted.current) setPractice(null); };
      const cleanup = () => {
        attached = false; stopObserving(); back?.removeEventListener("click", leave); api.suspend?.();
        if (savePracticeReport.current === finishAndSave) savePracticeReport.current = () => {};
        if (cleanupPractice.current === cleanup) cleanupPractice.current = () => {};
      };
      cleanupPractice.current = cleanup;
      back?.addEventListener("click", leave);
    } catch (error) { if (mounted.current && frame.current?.contentWindow === iframeWindow) setNotice(error instanceof Error ? error.message : "曲谱读取失败。"); }
  }
  function closePractice() {
    savePracticeReport.current(); cleanupPractice.current(); if (mounted.current) setPractice(null);
  }
  return <Context.Provider value={{ state, native, send, importPreview }}>
    {children}
    {practice && <Modal label="乐谱练习" onDismiss={closePractice} className="fixed inset-0 z-[100] flex flex-col bg-white pt-[env(safe-area-inset-top)]">
      <div className="flex justify-end px-3 py-2"><button onClick={closePractice} className="min-h-11 rounded-xl border-2 border-[#e5e5e5] px-4 text-[#4b4b4b]">返回我的曲谱</button></div>
      {practicePart ? <iframe key={practicePart} ref={frame} title="音伴本地练习" src="./practice/index.html" allow="microphone; midi" onLoad={() => void loadedPractice()} className="min-h-0 w-full flex-1 border-0" /> : <div className="mx-auto w-full max-w-lg px-5 text-[#4b4b4b]"><h2 className="mb-5 text-xl font-bold">选择练习乐谱</h2>{practice.parts?.map(part => <button key={part.id} onClick={() => setPracticePart(part.id)} className="mb-3 min-h-12 w-full rounded-xl border-2 p-3 text-left">{part.title}</button>)}</div>}
    </Modal>}
    {preview && <Modal label="原始曲谱预览" onDismiss={() => setPreview(null)} className="fixed inset-0 z-[100] flex flex-col bg-white p-3 pt-[max(12px,env(safe-area-inset-top))]">
      <button onClick={() => setPreview(null)} className="min-h-11 self-end rounded-xl border-2 px-4 text-[#4b4b4b]">关闭预览</button>
      {preview.record.kind === "pdf" ? <iframe title={preview.record.title} src={preview.url} className="min-h-0 flex-1" /> : <img src={preview.url} alt={preview.record.title} className="min-h-0 flex-1 object-contain" />}
    </Modal>}
    {notice && <Modal alert label="提示" onDismiss={() => setNotice("")} className="fixed inset-0 z-[120] flex items-center justify-center bg-black/50 p-6"><div className="max-w-sm rounded-[20px] bg-white p-5 text-[#4b4b4b]"><p className="leading-7">{notice}</p><button className="mt-4 min-h-11 w-full rounded-xl bg-[#67db23] font-bold" onClick={() => setNotice("")}>知道了</button></div></Modal>}
  </Context.Provider>;
}

export { summarizeHistory };
