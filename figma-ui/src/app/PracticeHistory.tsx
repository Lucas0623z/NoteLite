import { useEffect, useRef, useState } from "react";
import { account, ACCOUNT_EVENT, type AccountIdentity } from "./account";
import { errorMessage } from "./cloud";
import { practiceRecords, PRACTICE_RECORD_EVENT } from "./practice-records";
import { ownedPracticeRecords, type PracticeHistoryState } from "./practice-summary";

export function usePracticeHistory() {
  const [identity, setIdentity] = useState<AccountIdentity | null>(null);
  const [history, setHistory] = useState<PracticeHistoryState>({ status: "loading", owner: null, records: [], error: "" });
  const generation = useRef(0);
  const active = useRef(false);
  async function reload() {
    const request = ++generation.current;
    setIdentity(null); setHistory({ status: "loading", owner: null, records: [], error: "" });
    try {
      const current = await account.me();
      if (!active.current || request !== generation.current) return;
      setIdentity(current);
      const owner = current?.userId || "guest";
      const records = await practiceRecords.list();
      if (!active.current || request !== generation.current || (account.current?.userId || "guest") !== owner) return;
      setHistory({ status: "ready", owner, records: records.filter((record) => record.userId === owner).slice(0, 200), error: "" });
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

export default function PracticeHistory({ history, owner, onReload }: { history: PracticeHistoryState; owner: string | null; onReload: () => void }) {
  const records = ownedPracticeRecords(history, owner);
  return <details className="mt-3 rounded-[20px] border-2 border-[#e5e5e5] px-3 py-3">
    <summary className="cursor-pointer text-[15px] font-bold">实际练习记录 · {history.status === "ready" ? `最近 ${records.length} 条` : history.status === "loading" ? "正在读取" : "读取未完成"}</summary>
    {history.status === "loading" ? <p role="status" className="mt-3 text-[13px] leading-6 text-[#999]">正在读取当前账户的练习记录…</p> : history.status === "error" ? <><p role="status" className="mt-3 text-[13px] leading-6 text-[#999]">{history.error}</p><button type="button" className="mt-3 text-[15px] font-bold text-[#67db23]" onClick={onReload}>重新读取记录</button></> : <>
      <p className="mt-3 text-[12px] leading-6 text-[#999]">{owner === "guest" ? "未登录的记录保留在本机。" : "显示当前账户最近 200 条保存记录。"}试听与实际演奏按记录模式区分；未听音的记录没有错音分析。</p>
      {!records.length && <p className="mt-3 text-[15px] text-[#999]">还没有实际保存的练习记录。</p>}
      <ul>{records.map((record) => <li key={record.eventId} className="mt-3 border-t border-[#e5e5e5] pt-3"><strong className="text-[15px]">{record.name}</strong><p className="mt-1 text-[13px] leading-6 text-[#999]">{new Date(record.startedAt).toLocaleString()} · {Math.round(record.durationSeconds)} 秒 · {{ free: "自由练习", strict: "严格节拍", follow: "跟谱", playback: "谱面试听" }[record.mode]} · {record.sync === "synced" ? "账户已保存" : record.sync === "pending" ? "本机已保存，待同步" : "本机记录"}</p>{record.error && <p className="text-[12px] leading-6 text-[#999]">{record.error}</p>}</li>)}</ul>
    </>}
  </details>;
}
