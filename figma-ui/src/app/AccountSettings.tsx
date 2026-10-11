import { useEffect, useRef, useState } from "react";
import { account, type AccountIdentity } from "./account";
import { errorMessage } from "./cloud";

export default function AccountSettings({ identity, field, action, onReload }: { identity: AccountIdentity | null; field: string; action: string; onReload: () => void }) {
  const [username, setUsername] = useState(""), [password, setPassword] = useState("");
  const [deletePassword, setDeletePassword] = useState(""), [confirmDelete, setConfirmDelete] = useState(false), [deletionNotice, setDeletionNotice] = useState("");
  const [mode, setMode] = useState<"login" | "register">("login");
  const [busy, setBusy] = useState(false), [message, setMessage] = useState("");
  const [sessions, setSessions] = useState<Awaited<ReturnType<typeof account.sessions>>["sessions"]>([]);
  const generation = useRef(0);
  useEffect(() => { generation.current++; setSessions([]); setPassword(""); setDeletePassword(""); setConfirmDelete(false); setMessage(""); return () => { generation.current++; }; }, [identity?.userId]);
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
      <details className="my-4"><summary className="cursor-pointer text-[17px] font-bold">永久注销账户</summary>
        <p className="my-3 text-[13px] leading-6 text-[#999]">注销后无法恢复。账户、全部登录会话、个人曲谱、练习记录、分析和录音将删除，老师无法再查看你已提交的记录。你创建的课堂及作业会关闭；其他用户已领取到个人谱库的曲谱和他们自己的练习记录会保留。</p>
        <form onSubmit={(event) => { event.preventDefault(); if (!busy) setConfirmDelete(true); }}>
          <label className="mb-4 block text-[17px] font-bold">再次输入当前密码<input aria-label="注销确认密码" type="password" value={deletePassword} onChange={(event) => { setDeletePassword(event.currentTarget.value); setConfirmDelete(false); }} autoComplete="current-password" disabled={busy} required minLength={15} maxLength={256} className={`${field} text-[14px]`} /></label>
          {!confirmDelete ? <button type="submit" disabled={busy || deletePassword.length < 15} className={`${action} disabled:opacity-50`}>继续注销</button> : <div role="alertdialog" aria-label="确认永久注销账户">
            <p className="mb-3 text-[13px] leading-6 text-[#999]">确认永久注销 {identity.username}？所有设备都会退出登录，此操作无法撤销。</p>
            <button type="button" disabled={busy} className={`${action} disabled:opacity-50`} onClick={() => void perform(async () => {
              try { const result = await account.deleteAccount(deletePassword); setDeletionNotice(result.localCleanupPending ? result.localCleanupMessage || "账户已注销，本机资料清理待重试。请重新打开应用。" : result.deleted ? "账户及关联资料已永久注销。" : "账户已注销，全部设备已退出。剩余识谱与录音文件正在服务器上自动清理。"); setDeletePassword(""); setConfirmDelete(false); setSessions([]); }
              finally { if (!account.current) onReload(); }
            })}>{busy ? "正在注销…" : "确认永久注销"}</button>
            <button type="button" disabled={busy} className={`${action} mt-3`} onClick={() => setConfirmDelete(false)}>取消，保留账户</button>
          </div>}
        </form>
      </details>
    </> : <form onSubmit={(event) => { event.preventDefault(); void perform(async () => { await account.authenticate(mode, username.trim(), password); setPassword(""); onReload(); }); }}>
      <label className="mb-4 block text-[19px] font-bold">用户名<input aria-label="账户用户名" value={username} onChange={(event) => setUsername(event.currentTarget.value)} autoComplete="username" required minLength={3} maxLength={32} pattern="[A-Za-z0-9][A-Za-z0-9_.-]{2,31}" placeholder="3 至 32 位字母、数字、点、下划线或连字符" className={field} /></label>
      <label className="mb-4 block text-[19px] font-bold">密码<input aria-label="账户密码" type="password" disabled={busy} value={password} onChange={(event) => setPassword(event.currentTarget.value)} autoComplete={mode === "register" ? "new-password" : "current-password"} required minLength={15} maxLength={256} placeholder="15 至 256 个字符" className={`${field} text-[14px]`} /></label>
      <button type="submit" disabled={busy || !username.trim() || password.length < 15} className={`${action} disabled:cursor-default disabled:opacity-50`}>{busy ? "正在连接…" : mode === "login" ? "登录" : "创建账户"}</button>
      <button type="button" disabled={busy} className={`${action} mt-3`} onClick={() => { setMode(mode === "login" ? "register" : "login"); setMessage(""); }}>{mode === "login" ? "注册新账户" : "已有账户，返回登录"}</button>
    </form>}
    {deletionNotice && <p role="status" className="mt-4 text-[13px] leading-6 text-[#999]">{deletionNotice}</p>}
    <p role="status" className="mt-4 text-[13px] leading-6 text-[#999]">{message}</p>
  </>;
}
