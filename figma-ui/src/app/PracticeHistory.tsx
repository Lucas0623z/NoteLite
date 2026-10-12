import { useEffect, useRef, useState } from "react";
import { account, ACCOUNT_EVENT, type AccountIdentity } from "./account";
import { downloadBlob, errorMessage, isNativeCloud, nativeRequest } from "./cloud";
import { practiceRecords, PRACTICE_RECORD_EVENT, type PracticeRecord } from "./practice-records";
import { ownedPracticeRecords, type PracticeHistoryState } from "./practice-summary";

export function usePracticeHistory() {
  const [identity, setIdentity] = useState<AccountIdentity | null>(null);
  const [history, setHistory] = useState<PracticeHistoryState>({ status: "loading", owner: null, records: [], error: "" });
  const generation = useRef(0);
  const active = useRef(false);
  const resumedSession = useRef<string | null>(null);
  async function reload() {
    const request = ++generation.current;
    setIdentity(null); setHistory({ status: "loading", owner: null, records: [], error: "" });
    try {
      const current = await account.me();
      if (!active.current || request !== generation.current) return;
      setIdentity(current);
      const owner = current?.userId || "guest";
      // A restored Keychain/cookie login must resume an existing durable outbox too.
      // Mark the session first: each saved retry emits a history reload event.
      const session = current ? `${current.userId}|${current.sessionId}` : null;
      if (session && resumedSession.current !== session) {
        resumedSession.current = session;
        void practiceRecords.retry().catch(() => { /* The original pending records remain durable. */ });
      }
      if (!session) resumedSession.current = null;
      const records = await practiceRecords.list();
      if (!active.current || request !== generation.current || (account.current?.userId || "guest") !== owner) return;
      setHistory({ status: "ready", owner, records: records.filter((record) => record.userId === owner), error: "" });
    } catch (error) {
      if (active.current && request === generation.current) setHistory({ status: "error", owner: null, records: [], error: errorMessage(error) });
    }
  }
  useEffect(() => {
    active.current = true;
    const update = () => { void reload(); };
    window.addEventListener(ACCOUNT_EVENT, update); window.addEventListener(PRACTICE_RECORD_EVENT, update);
    void reload();
    return () => { active.current = false; generation.current++; window.removeEventListener(ACCOUNT_EVENT, update); window.removeEventListener(PRACTICE_RECORD_EVENT, update); };
  }, []);
  return { identity, history, reload };
}

function LocalRecordingControl({ record, onMessage }: { record: PracticeRecord; onMessage: (message: string) => void }) {
  const [status, setStatus] = useState<"checking" | "available" | "missing" | "error">("checking");
  const [retry, setRetry] = useState(0);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    setStatus("checking");
    if (record.userId === "guest") { setStatus("available"); return () => { active = false; }; }
    void nativeRequest<{ takeId: string; available: boolean; storage: string }>("notewise/recording/status", { takeId: record.eventId, expectedUserId: record.userId }).then((value) => {
      if (!active || account.current?.userId !== record.userId) return;
      if (value.takeId !== record.eventId || value.storage !== "device" || typeof value.available !== "boolean") throw new Error("本机录音状态尚未确认。");
      setStatus(value.available ? "available" : "missing");
    }).catch(() => { if (active && account.current?.userId === record.userId) setStatus("error"); });
    return () => { active = false; };
  }, [record.userId, record.eventId, retry]);
  if (status === "missing") return <p className="mt-2 text-[13px] leading-6 text-[#999]">录音仅在原设备保存，当前设备没有该录音。</p>;
  if (status === "error") return <button type="button" className="mt-2 text-[15px] font-bold text-[#67db23]" onClick={() => setRetry((value) => value + 1)}>重新检查本机录音</button>;
  return <button type="button" disabled={status !== "available" || busy} className="mt-2 text-[15px] font-bold text-[#67db23] disabled:text-[#999]" onClick={async () => {
    if ((account.current?.userId || "guest") !== record.userId) return;
    setBusy(true);
    try {
      await nativeRequest("notewise/recording/play", { takeId: record.eventId, ...(record.userId === "guest" ? {} : { expectedUserId: record.userId }) });
      if ((account.current?.userId || "guest") === record.userId) onMessage("本机录音已打开。");
    } catch (error) { if ((account.current?.userId || "guest") === record.userId) onMessage(errorMessage(error)); }
    finally { setBusy(false); }
  }}>{status === "checking" ? "正在检查本机录音…" : busy ? "正在打开录音…" : "播放本机演奏录音"}</button>;
}

export default function PracticeHistory({ history, owner, onReload }: { history: PracticeHistoryState; owner: string | null; onReload: () => void }) {
  const records = ownedPracticeRecords(history, owner);
  const visibleRecords = records.slice(0, 200);
  const [message,setMessage]=useState("");
  const [openRecordings, setOpenRecordings] = useState<Set<string>>(new Set());
  const [downloading, setDownloading] = useState<string | null>(null);
  useEffect(() => { setMessage(""); setOpenRecordings(new Set()); }, [owner]);
  return <details className="mt-3 rounded-[20px] border-2 border-[#e5e5e5] px-3 py-3">
    <summary className="cursor-pointer text-[15px] font-bold">实际练习记录 · {history.status === "ready" ? `共 ${records.length} 条${records.length > visibleRecords.length ? `（显示最近 ${visibleRecords.length} 条）` : ""}` : history.status === "loading" ? "正在读取" : "读取未完成"}</summary>
    {history.status === "loading" ? <p role="status" className="mt-3 text-[13px] leading-6 text-[#999]">正在读取当前账户的练习记录…</p> : history.status === "error" ? <><p role="status" className="mt-3 text-[13px] leading-6 text-[#999]">{history.error}</p><button type="button" className="mt-3 text-[15px] font-bold text-[#67db23]" onClick={onReload}>重新读取记录</button></> : <>
      <p className="mt-3 text-[12px] leading-6 text-[#999]">{owner === "guest" ? "未登录的记录保留在本机。" : "显示当前账户保存记录，列表最多展示最近 200 条。"}试听与实际演奏按记录模式区分；未听音的记录没有错音分析。</p>
      {!records.length && <p className="mt-3 text-[15px] text-[#999]">还没有实际保存的练习记录。</p>}
      <ul>{visibleRecords.map((record) => <li key={record.eventId} className="mt-3 border-t border-[#e5e5e5] pt-3"><strong className="text-[15px]">{record.name}</strong><p className="mt-1 text-[13px] leading-6 text-[#999]">{new Date(record.startedAt).toLocaleString()} · {Math.round(record.durationSeconds)} 秒 · {{ free: "自由练习", strict: "严格节拍", follow: "跟谱", playback: "谱面试听" }[record.mode]} · {record.sync === "synced" ? "账户已保存" : record.sync === "pending" ? "本机已保存，待同步" : "本机记录"}</p>{record.error && <p className="text-[12px] leading-6 text-[#999]">{record.error}</p>}{(record.musicxml || record.sync === "synced") && <button type="button" disabled={downloading === record.eventId} className="mt-2 text-[13px] font-bold text-[#67db23] disabled:text-[#999]" onClick={async () => {
        const session = account.current;
        if ((session?.userId || "guest") !== record.userId) return;
        setDownloading(record.eventId);
        try {
          const xml = await practiceRecords.snapshot(record);
          if (account.current?.userId !== session?.userId || account.current?.sessionId !== session?.sessionId) return;
          await downloadBlob(new Blob([xml], { type: "application/vnd.recordare.musicxml+xml" }), `${record.name}-练习原谱.musicxml`, { expectedUserId: session?.userId || "guest", expectedSessionId: session?.sessionId || null, isCurrent: () => account.current?.userId === session?.userId && account.current?.sessionId === session?.sessionId });
        } catch (error) { if (account.current?.userId === session?.userId && account.current?.sessionId === session?.sessionId) setMessage(errorMessage(error)); }
        finally { setDownloading(null); }
      }}>{downloading === record.eventId ? "正在读取原谱…" : "下载当时练习的原谱"}</button>}{record.analysis?.schemaVersion===2&&<details className="mt-2 text-[13px] leading-6 text-[#999]" onToggle={(event) => { const open = event.currentTarget.open; setOpenRecordings((previous) => { const next = new Set(previous); if (open) next.add(record.eventId); else next.delete(record.eventId); return next; }); }}><summary className="cursor-pointer">演奏反馈 · 分析版本 {record.latestAnalysisVersion||record.analysisVersion||1}{record.pendingAnalysis?" · 录后版本待同步":""}</summary><p>仅统计实际进入的演奏机会；未演奏、输入不清晰或未覆盖的维度不会算作正确。</p>{record.analysis.coverageByDimension&&<p>音高：已评估 {record.analysis.coverageByDimension.pitch?.evaluated??0} 次 · 待复核 {record.analysis.coverageByDimension.pitch?.pending??0} 次</p>}<ul>{record.analysis.errors?.map((error,index)=>{const value=error as {type?:string;kind?:string;measure?:number;expectedMidi?:number;playedMidi?:number};return<li key={index}>{value.measure?`第 ${value.measure} 小节 · `:""}{{wrong:"错音或音准",missed:"漏音",extra:"多音",rhythm:"节奏或时值",uncertain:"待复核"}[value.type||""]||"待复核"}{value.expectedMidi!==undefined?` · 谱面 ${value.expectedMidi}`:""}{value.playedMidi!==undefined?` · 演奏 ${value.playedMidi}`:""}</li>})}</ul>{record.analysis.recording?.available && (isNativeCloud() ? openRecordings.has(record.eventId) && <LocalRecordingControl record={record} onMessage={setMessage} /> : <p className="mt-2">录音仅在原设备保存。</p>)}</details>}</li>)}</ul>
      {message&&<p role="status" className="mt-2 text-[13px] leading-6 text-[#999]">{message}</p>}
    </>}
  </details>;
}
