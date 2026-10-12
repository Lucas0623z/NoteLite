import { useEffect, useRef, useState } from "react";
import normal from "../imports/my-scores-upload-normal.png";
import pressed from "../imports/my-scores-upload-pressed.png";
import ScoreWorkspace from "./ScoreWorkspace";
import { AccountFileSelection, cloud, CloudError, createUUID, errorMessage, isNativeCloud, nativeRequest, recheckImportAuthentication, scopedAccountWrite, type AccountOperationScope, type CloudJob, type ScoreFileSource } from "./cloud";
import { completedJobNotice, uploadedJobNotice, type ScoreNotice } from "./job-notice";
import { startJobPolling } from "./job-polling";
import { openOwnedDatabase, ownedStores, guardAccountWrite, isDeletedAccountOwner } from "./account-local-data";
import { account, ACCOUNT_EVENT, type PersonalScore } from "./account";

type Score = { id: string; name: string; format: string; file?: Blob; sample?: boolean; job?: CloudJob; removed?: boolean; owner?: string; personal?: PersonalScore; officialId?: string };
const scoreOwner = (score: Score) => score.owner || "guest";
type Panel = "import" | "rename" | "delete" | "view" | "practice" | null;
type DialogEvent = "mounted" | "unmounted" | "trigger-pointer-down" | "trigger-pointer-up" | "trigger-click" | "open-request" | "effect" | "show-modal-before" | "show-modal-after" | "close-before" | "close-after" | "cancel" | "close-event" | "backdrop-click" | "inside-click";
function traceDialog(event: DialogEvent, dialog: HTMLDialogElement | null, panel: Panel) {
  if (!import.meta.env.DEV) return;
  // The handler exists only in a DEBUG native shell launched for UI tests.
  // Keep diagnostics static: no account, filename, XML or credential values.
  const handlers = window.webkit?.messageHandlers;
  if (handlers && Reflect.has(handlers, "noteLiteDiagnostics")) console.info(`[NoteLite dialog] event=${event} open=${!!dialog?.open} panel=${panel || "none"}`);
}
const sampleScore = `<score-partwise version="4.0"><work><work-title>示例练习</work-title></work><part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list><part id="P1"><measure number="1"><attributes><divisions>1</divisions><key><fifths>0</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes>${["C", "D", "E", "F"].map((step) => `<note><pitch><step>${step}</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>`).join("")}</measure></part></score-partwise>`;

async function openScoreDB(): Promise<IDBDatabase> {
  return openOwnedDatabase("heibaikey-scores", "scores", "id");
}
async function scoreStore<T>(mode: IDBTransactionMode, action: (store: IDBObjectStore) => IDBRequest<T>, owner = account.current?.userId || "guest"): Promise<T> {
  const db = await openScoreDB();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(ownedStores("scores"), mode);
    let request: IDBRequest<T>;
    const write = () => { request = action(transaction.objectStore("scores")); };
    if (mode === "readwrite") guardAccountWrite(transaction, owner, write); else write();
    transaction.oncomplete = () => { db.close(); resolve(request.result); };
    transaction.onerror = transaction.onabort = () => { db.close(); reject(transaction.error); };
  });
}

function scoreFromJob(job: CloudJob, previous?: Score): Score {
  return { ...previous, id: job.id, name: previous?.name || job.filename, format: previous?.format || job.filename.split(".").pop()?.toUpperCase() || "", job };
}

async function persistPolledJobs(jobs: CloudJob[], signal: AbortSignal, owner: string): Promise<Score[]> {
  const db = await openScoreDB();
  if (signal.aborted || isDeletedAccountOwner(owner)) { db.close(); return []; }
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(ownedStores("scores"), "readwrite");
    const store = transaction.objectStore("scores");
    const request = store.getAll();
    const updated: Score[] = [];
    const abort = () => { try { transaction.abort(); } catch { /* Already completed. */ } };
    signal.addEventListener("abort", abort, { once: true });
    request.onsuccess = () => guardAccountWrite(transaction, owner, () => {
      const latest = new Map((request.result as Score[]).map((score) => [score.id, score]));
      for (const job of jobs) {
        const previous = latest.get(job.id);
        // Preserve current names/files and local removals, including changes made
        // while this round was waiting for its other network responses.
        if (!previous || scoreOwner(previous) !== owner || previous.removed || (previous.job?.revision ?? 0) > job.revision) continue;
        const score = scoreFromJob(job, previous); store.put(score); updated.push(score);
      }
    });
    const finish = () => { signal.removeEventListener("abort", abort); db.close(); };
    transaction.oncomplete = () => { finish(); resolve(updated); };
    transaction.onerror = transaction.onabort = () => { finish(); reject(transaction.error || new DOMException("Polling cancelled", "AbortError")); };
  });
}

export default function MyScoresPage({ isDark, onRequestSignIn }: { isDark: boolean; onRequestSignIn?: () => void }) {
  const [scores, setScores] = useState<Score[]>([]);
  const [loading, setLoading] = useState(true);
  const [importPage, setImportPage] = useState(false);
  const [panel, setPanel] = useState<Panel>(null);
  const [selected, setSelected] = useState<Score | null>(null);
  const [name, setName] = useState("");
  const [notice, setNotice] = useState<ScoreNotice>({ text: "" });
  const message = notice.text;
  function setMessage(text: string) { setNotice({ text }); }
  const [busy, setBusy] = useState(false);
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
  const owner = useRef(account.current?.userId || "guest");
  const libraryGeneration = useRef(0);
  const fileSelections = useRef(new AccountFileSelection());
  const pageMounted = useRef(true);
  const workspaceOpen = panel === "view" || panel === "practice";
  const importing = importPage || scores.length === 0;
  const waitingKey = JSON.stringify(scores.filter((score) => score.job?.state === "queued" || score.job?.state === "running").map((score) => score.id).sort());

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
    pageMounted.current = true;
    const reload = async () => {
      const generation = ++libraryGeneration.current;
      fileSelections.current.clear();
      owner.current = account.current?.userId || "guest";
      cloud.useAccount(account.current?.userId || null);
      setPanel(null); setSelected(null); setScores([]); setLoading(true); setBusy(false);
      try { await account.me(); } catch { /* Cached scores remain usable offline. */ }
      if (!live || generation !== libraryGeneration.current) return;
      const currentOwner = owner.current = account.current?.userId || "guest";
      cloud.useAccount(account.current?.userId || null);
      try {
        const saved = await scoreStore("readonly", (store) => store.getAll()) as Score[];
        if (!live || generation !== libraryGeneration.current) return;
        const local = saved.filter((score) => scoreOwner(score) === currentOwner);
        setScores(local.filter((score) => !score.removed));
        if (account.current?.userId === currentOwner) {
          try {
            const remote = await account.scores();
            if (!live || generation !== libraryGeneration.current || owner.current !== currentOwner) return;
            for (const personal of remote.scores) {
              const cached = local.find((score) => score.id === personal.id);
              if (cached?.removed) continue;
              await save({ id: personal.id, owner: currentOwner, name: personal.title, format: "MUSICXML", personal, file: cached?.personal?.revision === personal.revision ? cached.file : undefined });
            }
          } catch (error) { if (live && generation === libraryGeneration.current) setMessage(errorMessage(error)); }
        }
        if (live && generation === libraryGeneration.current) void refreshCloud(local);
      } catch { if (live) setMessage("无法读取本地曲谱，请检查浏览器存储权限。"); }
      finally { if (live && generation === libraryGeneration.current) setLoading(false); }
    };
    void reload(); window.addEventListener(ACCOUNT_EVENT, reload);
    return () => { live = false; pageMounted.current = false; ++libraryGeneration.current; fileSelections.current.clear(); window.removeEventListener(ACCOUNT_EVENT, reload); };
  }, []);

  useEffect(() => {
    const ids = JSON.parse(waitingKey) as string[];
    return startJobPolling({
      ids, read: (id) => cloud.job(id),
      commit: async (values, signal) => {
        const pollingOwner = owner.current;
        const saved = await persistPolledJobs(values.map(({ value }) => value), signal, pollingOwner);
        if (signal.aborted || pollingOwner !== owner.current) return;
        const updates = new Map(saved.map((score) => [score.id, score.job!]));
        const merge = (score: Score) => {
          const job = updates.get(score.id);
          return job && (score.job?.revision ?? 0) <= job.revision ? { ...score, job } : score;
        };
        setScores((previous) => previous.map(merge));
        setSelected((current) => current ? merge(current) : current);
        setNotice((current) => saved.reduce((notice, score) => completedJobNotice(notice, score.job!), current));
      },
      failed: (id, error) => setNotice((current) => current.jobId && (id ? current.jobId === id : ids.includes(current.jobId)) ? { ...current, text: errorMessage(error) } : current),
    });
  }, [waitingKey]);

  useEffect(() => {
    traceDialog("effect", dialog.current, panel);
    if (panel && !dialog.current?.open) {
      traceDialog("show-modal-before", dialog.current, panel);
      dialog.current?.showModal();
      traceDialog("show-modal-after", dialog.current, panel);
    }
    if (!panel && dialog.current?.open) {
      traceDialog("close-before", dialog.current, panel);
      dialog.current.close();
      traceDialog("close-after", dialog.current, panel);
    }
  }, [panel]);

  useEffect(() => {
    traceDialog("mounted", dialog.current, null);
    return () => traceDialog("unmounted", dialog.current, null);
  }, []);

  useEffect(() => {
    if (!importing && list.current) list.current.scrollTop = scrollPosition.current;
  }, [importing]);

  async function save(score: Score) {
    score = { ...score, owner: score.owner || owner.current };
    if (score.owner !== owner.current) throw new Error("账户已切换，请重新打开曲谱。");
    await scoreStore("readwrite", (store) => store.put(score), scoreOwner(score));
    if (score.owner !== owner.current) return;
    setScores((previous) => {
      const index = previous.findIndex((item) => item.id === score.id);
      return index < 0 ? [...previous, score] : previous.map((item) => item.id === score.id ? score : item);
    });
  }

  async function acceptJob(job: CloudJob, existing?: Score, requestOwner = owner.current) {
    if (requestOwner !== owner.current || requestOwner !== account.current?.userId) return;
    const generation = libraryGeneration.current;
    const previous = existing || scores.find((item) => item.id === job.id);
    if (previous?.removed) return;
    const imported = { ...scoreFromJob(job, previous), owner: requestOwner };
    await save(imported);
    if (generation !== libraryGeneration.current || requestOwner !== owner.current || requestOwner !== account.current?.userId) return;
    setNotice((current) => completedJobNotice(current, job));
    setSelected((current) => current?.id === imported.id ? imported : current);
    return imported;
  }

  async function refreshCloud(saved?: Score[]) {
    const requestOwner = owner.current;
    if (requestOwner !== account.current?.userId) return;
    cloud.useAccount(requestOwner);
    try {
      const local = (saved || await scoreStore("readonly", (store) => store.getAll()) as Score[]).filter((score) => scoreOwner(score) === requestOwner);
      if (requestOwner !== owner.current || requestOwner !== account.current?.userId) return;
      const jobs = await cloud.jobs();
      if (requestOwner !== owner.current || requestOwner !== account.current?.userId) return;
      for (const job of jobs) { if (requestOwner !== owner.current) return; await acceptJob(job, local.find((score) => score.id === job.id), requestOwner); }
    } catch (error) {
      if (requestOwner !== owner.current || requestOwner !== account.current?.userId) return;
      // A first visit remains the original empty library. Imported scores remain usable offline.
      if (saved?.some((score) => score.job && !score.removed)) setMessage(errorMessage(error));
    }
  }

  function requestSignIn(text = "请先登录账户，再选择要识别的曲谱。") {
    setPanel(null);
    setMessage(text);
    onRequestSignIn?.();
  }

  function requireImportAccount() {
    const userId = account.current?.userId;
    if (!userId) { requestSignIn(); return null; }
    cloud.useAccount(userId);
    return { owner: userId, sessionId: account.current!.sessionId, generation: libraryGeneration.current };
  }

  function operationStillCurrent(scope: AccountOperationScope) {
    return scope.generation === libraryGeneration.current && scope.owner === owner.current && scope.owner === (account.current?.userId || "guest") && scope.sessionId === (account.current?.sessionId || null);
  }

  function captureScoreScope(score: Score): AccountOperationScope {
    return { owner: scoreOwner(score), sessionId: account.current?.sessionId || null, generation: libraryGeneration.current };
  }

  function chooseImage(source: "photos" | "camera", input: HTMLInputElement | null) {
    const scope = requireImportAccount();
    if (scope && input && operationStillCurrent(scope)) { fileSelections.current.begin(source, scope); input.click(); }
  }

  function selectedFile(source: ScoreFileSource, input: HTMLInputElement) {
    const file = input.files?.[0], scope = fileSelections.current.take(source, operationStillCurrent);
    input.value = "";
    if (file && scope) void importFile(file, scope);
  }

  async function reportImportError(error: unknown, scope: AccountOperationScope) {
    if (!operationStillCurrent(scope)) return;
    if (error instanceof CloudError && error.status === 401) {
      const state = await recheckImportAuthentication({ userId: scope.owner, sessionId: scope.sessionId! }, account, () => operationStillCurrent(scope));
      if (!pageMounted.current) return;
      if (state === "expired") requestSignIn("登录已失效，请重新登录后选择曲谱。");
      else if (state === "active") setMessage("账户已登录，识谱服务暂时未接受当前会话。请稍后重试，或在个人档案中重新登录。");
      else if (state === "unavailable") setMessage("暂时无法确认登录状态，请检查网络后重试。");
      return;
    }
    if (!(error instanceof CloudError && error.code === "cancelled")) setMessage(errorMessage(error));
  }

  async function importFile(file: File, scope: AccountOperationScope) {
    if (!operationStillCurrent(scope)) return;
    setBusy(true);
    try {
      const extension = file.name.split(".").pop()?.toLowerCase() || "";
      if (!["png", "jpg", "jpeg", "pdf", "musicxml", "mxl", "xml"].includes(extension)) {
        throw new Error("请选择 PNG、JPEG、PDF 或 MusicXML 曲谱文件。");
      }
      setMessage("正在上传曲谱…");
      const job = await cloud.upload(file, file.name);
      if (!operationStillCurrent(scope)) return;
      const imported = await acceptJob(job, { id: job.id, name: file.name, format: extension.toUpperCase(), file }, scope.owner);
      if (!imported || !operationStillCurrent(scope)) return;
      setSelected(imported);
      setPanel(null);
      setImportPage(false);
      setNotice(uploadedJobNotice(job));
    } catch (error) {
      await reportImportError(error, scope);
    } finally { if (operationStillCurrent(scope)) setBusy(false); }
  }

  async function chooseFile() {
    const scope = requireImportAccount();
    if (!scope) return;
    if (!isNativeCloud()) { if (files.current && operationStillCurrent(scope)) { fileSelections.current.begin("files", scope); files.current.click(); } return; }
    setBusy(true);
    try {
      const job = await cloud.importNative();
      if (!operationStillCurrent(scope)) return;
      const imported = await acceptJob(job, undefined, scope.owner);
      if (!imported || !operationStillCurrent(scope)) return;
      setPanel(null); setImportPage(false); setNotice(uploadedJobNotice(job));
    } catch (error) {
      await reportImportError(error, scope);
    } finally { if (operationStillCurrent(scope)) setBusy(false); }
  }

  async function loadSample() {
    setBusy(true);
    try {
      await save({ id: createUUID(), name: "示例练习.musicxml", format: "MUSICXML", sample: true, file: new Blob([sampleScore], { type: "application/vnd.recordare.musicxml+xml" }) });
      setPanel(null); setImportPage(false); setMessage("已载入示例曲谱。");
    } catch { setMessage("示例保存失败，请检查浏览器存储权限。"); }
    finally { setBusy(false); }
  }

  async function loadOfficialSample() {
    setBusy(true);
    try {
      if (!account.current) throw new Error("请在个人档案中登录，读取官方曲谱和练习历史。");
      const requestOwner = owner.current, officialId = "notelite-four-notes-v1";
      const xml = await account.officialXML(officialId);
      if (requestOwner !== owner.current) return;
      await save({ id: `official:${requestOwner}:${officialId}`, owner: requestOwner, name: "四音基础练习", officialId, format: "MUSICXML", file: new Blob([xml], { type: "application/vnd.recordare.musicxml+xml" }) });
      setPanel(null); setImportPage(false); setMessage("官方练习谱已载入，练习历史将随账户同步。");
    } catch (error) { setMessage(errorMessage(error)); } finally { setBusy(false); }
  }

  async function confirmEdit() {
    if (!selected) return;
    const score = selected, scope = captureScoreScope(score);
    if (!operationStillCurrent(scope)) return;
    setBusy(true);
    try {
      if (panel === "rename") {
        const personal = score.personal ? await scopedAccountWrite(() => operationStillCurrent(scope), () => score.file ? score.file.text() : account.scoreXML(score.id), (xml) => account.updateScore(score.personal!, xml, name.trim())) : undefined;
        if (!operationStillCurrent(scope)) return;
        await save({ ...score, name: name.trim(), ...(personal ? { personal } : {}) });
      }
      else {
        if (score.job || score.personal) await scoreStore("readwrite", (store) => store.put({ ...score, removed: true }), scope.owner);
        else await scoreStore("readwrite", (store) => store.delete(score.id), scope.owner);
        if (!operationStillCurrent(scope)) return;
        setScores((previous) => previous.filter((item) => item.id !== score.id));
      }
      if (!operationStillCurrent(scope)) return;
      setPanel(null);
    } catch (error) { if (operationStillCurrent(scope)) setMessage(errorMessage(error)); }
    finally { if (operationStillCurrent(scope)) setBusy(false); }
  }

  async function openPanel(next: Panel, score?: Score) {
    traceDialog("open-request", dialog.current, next);
    if (next === "view" || next === "practice") {
      void enterLandscape();
      if (score?.personal && !score.file) {
        setBusy(true);
        try { const xml = await account.scoreXML(score.id); if (scoreOwner(score) !== owner.current) return; score = { ...score, file: new Blob([xml], { type: "application/vnd.recordare.musicxml+xml" }) }; await save(score); }
        catch (error) { setMessage(errorMessage(error)); restoreOrientation(); return; }
        finally { setBusy(false); }
      }
    }
    setSelected(score || null); setName(score?.name || ""); setMessage(""); setPanel(next);
  }
  const outline = isDark ? "border-white/15" : "border-[#e5e5e5]";
  const button = `scores-action cursor-pointer rounded-[12px] border-2 border-b-[5px] px-3 py-2 text-sm font-bold text-[#67db23] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-current disabled:opacity-50 ${outline} ${isDark ? "bg-[#252525]" : "bg-white"}`;
  const title = panel === "import" ? "导入曲谱" : panel === "rename" ? "重命名" : panel === "delete" ? "删除曲谱" : panel === "view" ? selected?.name : panel === "practice" ? "开始练习" : "曲谱";

  return <section className={`scores-library flex h-full min-h-0 flex-col ${isDark ? "text-white" : "text-[#333]"}`}>
    {loading ? <p role="status" className="m-auto text-sm text-[#999]">正在读取曲谱…</p> : <>
      {importing ? <div className="flex min-h-0 flex-1 flex-col">
        {scores.length > 0 && <button type="button" onClick={() => setImportPage(false)} className="self-start px-4 py-3 text-sm text-[#999] focus-visible:outline-2">‹ 返回我的曲谱</button>}
        <div className="scores-page flex min-h-0 flex-1 flex-col items-center justify-center px-4 py-8">
          <button type="button" aria-label="导入曲谱" onPointerDown={() => traceDialog("trigger-pointer-down", dialog.current, panel)} onPointerUp={() => traceDialog("trigger-pointer-up", dialog.current, panel)} onClick={() => { traceDialog("trigger-click", dialog.current, panel); openPanel("import"); }} className="group relative block w-full max-w-[400px] cursor-pointer touch-manipulation rounded-[18px] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#67db23]">
            <img src={normal} alt="上传文件、图片或拍照识谱，开启你的专属陪练吧！" draggable={false} style={{ pointerEvents: "none" }} className="block h-auto w-full select-none group-active:opacity-0" />
            <img src={pressed} alt="" aria-hidden="true" draggable={false} className="pointer-events-none absolute inset-0 h-full w-full select-none object-contain opacity-0 group-active:opacity-100" />
          </button>
        </div>
      </div> : <div ref={list} onScroll={(event) => { scrollPosition.current = event.currentTarget.scrollTop; }} className="min-h-0 flex-1 overflow-y-auto px-4 py-5">
        <header className="mb-5 flex items-center justify-between gap-4"><h1 className="text-xl font-bold">我的曲谱</h1><button type="button" className={button} onClick={() => setImportPage(true)}>导入乐谱</button></header>
        <div className="scores-cards grid gap-4">
          {scores.map((score) => <article key={score.id} className={`rounded-[18px] border-2 border-b-[5px] p-4 ${outline}`}>
            <h2 className="break-all text-lg font-bold">{score.name}</h2>
            <p className="mt-2 text-xs text-[#999]">{score.sample ? "1 个练习乐谱" : score.personal ? `账户同步曲谱 · 版本 ${score.personal.revision}` : score.officialId ? "官方基础练习" : score.job ? ({ queued: "等待识谱", running: "正在识谱", succeeded: `${score.job.scores.length} 个乐章 · 校对版本 ${score.job.revision}`, failed: "识谱未完成" })[score.job.state] : "本地曲谱文件"} · {score.format}</p>
            {score.job?.state === "failed" && <p role="status" className="mt-2 text-xs text-[#999]">{score.job.error || "请检查原稿清晰度后重新导入。"}</p>}
            <div className="mt-4 flex flex-wrap gap-2">
              <button type="button" disabled={!!score.job && score.job.state !== "succeeded"} className={`${button} !border-[#49a619] !bg-[#67db23] !text-white`} onClick={() => openPanel("practice", score)}>开始练习</button>
              <button type="button" className={button} onClick={() => openPanel("view", score)}>查看曲谱</button>
              <button type="button" className={button} onClick={() => openPanel("rename", score)}>重命名</button>
              <button type="button" className={`${button} !text-[#e16c6c]`} onClick={() => openPanel("delete", score)}>删除</button>
            </div>
          </article>)}
        </div>
        <div className="mt-4 grid gap-3"><button type="button" disabled={busy} className={button} onClick={loadSample}>载入示例曲谱</button>{account.current && <button type="button" disabled={busy} className={button} onClick={loadOfficialSample}>官方基础练习</button>}</div>
      </div>}
      {message && <p role="status" className="px-4 pb-4 text-center text-sm leading-6 text-[#999]">{message}</p>}
    </>}
    <input ref={files} type="file" accept="image/png,image/jpeg,.pdf,.musicxml,.mxl,.xml" className="hidden" aria-label="选择曲谱文件" onChange={(event) => selectedFile("files", event.currentTarget)} />
    <input ref={photos} type="file" accept="image/*" className="hidden" aria-label="从相册选择曲谱" onChange={(event) => selectedFile("photos", event.currentTarget)} />
    <input ref={camera} type="file" accept="image/*" capture="environment" className="hidden" aria-label="拍照识谱" onChange={(event) => selectedFile("camera", event.currentTarget)} />
    <dialog ref={dialog} data-workspace={panel === "view" || panel === "practice"} aria-labelledby="score-panel-title" onCancel={() => { traceDialog("cancel", dialog.current, panel); setPanel(null); }} onClose={() => { traceDialog("close-event", dialog.current, panel); setPanel(null); }} onClick={(event) => { traceDialog(event.target === event.currentTarget ? "backdrop-click" : "inside-click", dialog.current, panel); if (event.target === event.currentTarget && !busy) setPanel(null); }} className={`scores-dialog fixed rounded-[20px] border-0 p-5 font-sans backdrop:bg-black/70 ${isDark ? "bg-[#191919] text-white" : "bg-white text-[#333]"}`}>
      {(panel === "view" || panel === "practice") && selected ? <ScoreWorkspace practice={panel === "practice"} name={selected.name} format={selected.format} file={selected.file} job={selected.job} recordIdentity={selected.id} practiceSource={selected.personal ? { kind: "personal", scoreId: selected.personal.id, revision: selected.personal.revision } : selected.officialId ? { kind: "official", scoreId: selected.officialId, revision: 1 } : undefined} orientationNotice={orientationNotice} onJob={async (job) => { await acceptJob(job, selected); }} onClose={() => setPanel(null)} onSave={async (file) => {
        const score = selected, scope = captureScoreScope(score);
        const personal = score.personal || score.officialId && account.current ? await scopedAccountWrite(() => operationStillCurrent(scope), () => file.text(), (xml) => score.personal ? account.updateScore(score.personal, xml) : account.createScore(`${score.name} · 校对版`, xml, createUUID())) : undefined;
        if (!operationStillCurrent(scope)) throw new CloudError("账户已切换，请重新打开曲谱。", 409, "identity_changed");
        const updated = { ...score, file, ...(personal ? { id: personal.id, personal, officialId: undefined, name: personal.title } : {}) }; await save(updated);
        if (!operationStillCurrent(scope)) throw new CloudError("账户已切换，请重新打开曲谱。", 409, "identity_changed");
        setSelected(updated);
      }} /> : <>
      <h2 id="score-panel-title" className="mb-3 break-all text-lg font-bold">{title}</h2>
      {panel === "import" ? <>
        <p className="mb-4 text-xs leading-6 text-[#999]">支持 PNG、JPEG、PDF 和 MusicXML。{account.current ? "选择文件即可开始识谱" : "登录账户后即可选择文件识谱"}；完成后可校对并导出 MusicXML、MIDI。</p>
        <div className="grid gap-3">
          <button type="button" disabled={busy} className={button} onClick={() => void chooseFile()}>选择文件</button>
          <button type="button" disabled={busy} className={button} onClick={() => chooseImage("photos", photos.current)}>从相册选择</button>
          <button type="button" disabled={busy} className={button} onClick={() => chooseImage("camera", camera.current)}>拍照识谱</button>
          <button type="button" disabled={busy} className={button} onClick={loadSample}>载入示例曲谱</button>
          {account.current && <button type="button" disabled={busy} className={button} onClick={loadOfficialSample}>官方基础练习</button>}
        </div>
      </> : panel === "rename" ? <form onSubmit={(event) => { event.preventDefault(); if (name.trim()) void confirmEdit(); }}>
        <input aria-label="曲谱名称" autoFocus value={name} maxLength={160} onChange={(event) => setName(event.currentTarget.value)} className={`mb-4 w-full rounded-xl border-2 bg-transparent p-3 ${outline}`} />
        <button type="submit" disabled={busy || !name.trim()} className={`${button} w-full`}>保存</button>
      </form> : panel === "delete" ? <><p className="mb-4 text-sm leading-6">{selected?.job || selected?.personal ? `从本机曲谱列表移除「${selected.name}」？账户曲谱和练习历史会保留。` : `确定删除「${selected?.name}」？删除后无法恢复。`}</p><button type="button" disabled={busy} className={`${button} w-full !text-[#e16c6c]`} onClick={confirmEdit}>确认删除</button></> : null}
      {message && <p role="status" className="mt-3 text-sm leading-6 text-[#999]">{message}</p>}
      <button type="button" disabled={busy} className={`${button} mt-3 w-full !text-[#999]`} onClick={() => setPanel(null)}>{panel === "import" || panel === "delete" || panel === "rename" ? "取消" : "关闭"}</button>
      </>}
    </dialog>
  </section>;
}
