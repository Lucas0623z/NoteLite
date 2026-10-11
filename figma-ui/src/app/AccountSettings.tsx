import { useEffect, useRef, useState } from "react";
import { account, type AccountIdentity } from "./account";
import { errorMessage } from "./cloud";

export default function AccountSettings({ identity, field, action, onReload }: { identity: AccountIdentity | null; field: string; action: string; onReload: () => void }) {
  const [username, setUsername] = useState(""), [password, setPassword] = useState("");
  const [mode, setMode] = useState<"login" | "register">("login");
  const [busy, setBusy] = useState(false), [message, setMessage] = useState("");
  const [sessions, setSessions] = useState<Awaited<ReturnType<typeof account.sessions>>["sessions"]>([]);
  const generation = useRef(0);
  useEffect(() => { generation.current++; setSessions([]); setPassword(""); setMessage(""); return () => { generation.current++; }; }, [identity?.userId]);
  async function perform(task: () => Promise<void>) {
    if (busy) return;
    const request = generation.current;
    setBusy(true); setMessage("");
    try { await task(); } catch (error) { if (request === generation.current) setMessage(errorMessage(error)); }
    finally { setBusy(false); }
  }
  return <>
    {identity ? <>
      <label className="mb-4 block text-[19px] font-bold">用户名<input readOnly value={identity.username} autoComplete="username" className={field} /></label>
      <p className="mb-5 text-[12px] leading-6 text-[#999]">当前已登录账户。姓名、邮箱与电话号码是本机偏好；不会用于账号认证。</p>
      <button type="button" disabled={busy} className={action} onClick={() => void perform(async () => { await account.logout(); setSessions([]); onReload(); })}>退出登录</button>
      <details className="my-4"><summary className="cursor-pointer text-[17px] font-bold">登录设备与会话</summary>
        <button type="button" disabled={busy} className={`${action} mt-3`} onClick={() => void perform(async () => { const owner = identity.userId, request = generation.current; const result = await account.sessions(); if (request === generation.current && account.current?.userId === owner) setSessions(result.sessions); })}>读取登录设备</button>
        <ul>{sessions.map((session) => <li key={session.sessionId} className="mt-3 text-[13px] leading-6 text-[#999]">{session.deviceName} · {session.kind === "native" ? "Apple 设备" : "网页"} · 到期 {new Date(session.expiresAt).toLocaleString()}<button type="button" disabled={busy} className="ml-3 font-bold text-[#67db23]" onClick={() => void perform(async () => { await account.revoke(session.sessionId); if (session.sessionId === identity.sessionId) { onReload(); setSessions([]); } else setSessions((previous) => previous.filter((value) => value.sessionId !== session.sessionId)); })}>{session.sessionId === identity.sessionId ? "退出当前设备" : "撤销会话"}</button></li>)}</ul>
      </details>
    </> : <form onSubmit={(event) => { event.preventDefault(); void perform(async () => { await account.authenticate(mode, username.trim(), password); setPassword(""); onReload(); }); }}>
      <label className="mb-4 block text-[19px] font-bold">用户名<input aria-label="账户用户名" value={username} onChange={(event) => setUsername(event.currentTarget.value)} autoComplete="username" required minLength={3} maxLength={32} pattern="[A-Za-z0-9][A-Za-z0-9_.-]{2,31}" placeholder="3 至 32 位字母、数字、点、下划线或连字符" className={field} /></label>
      <label className="mb-4 block text-[19px] font-bold">密码<input aria-label="账户密码" type="password" disabled={busy} value={password} onChange={(event) => setPassword(event.currentTarget.value)} autoComplete={mode === "register" ? "new-password" : "current-password"} required minLength={15} maxLength={256} placeholder="15 至 256 个字符" className={`${field} text-[14px]`} /></label>
      <button type="submit" disabled={busy || !username.trim() || password.length < 15} className={`${action} disabled:cursor-default disabled:opacity-50`}>{busy ? "正在连接…" : mode === "login" ? "登录" : "创建账户"}</button>
      <button type="button" disabled={busy} className={`${action} mt-3`} onClick={() => { setMode(mode === "login" ? "register" : "login"); setMessage(""); }}>{mode === "login" ? "注册新账户" : "已有账户，返回登录"}</button>
    </form>}
    <p role="status" className="mt-4 text-[13px] leading-6 text-[#999]">{message}</p>
  </>;
}
