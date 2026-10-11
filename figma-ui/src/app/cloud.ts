/** OMR transport only. Credentials stay in HttpOnly cookies or the native Keychain. */
export type CloudScore = { id: string; index: number; name: string; noteCount: number; musicxml: string; midi: string };
export type CloudJob = {
  id: string; filename: string; state: "queued" | "running" | "succeeded" | "failed";
  revision: number; scores: CloudScore[]; artifacts: Partial<Record<"musicxml" | "midi" | "original" | "omr" | "log", string>>;
  createdAt?: string; updatedAt?: string; error?: string | null; warnings?: string[];
  recognitionMode?: "import" | "audiveris";
};
export type CloudNote = {
  partId: string; measureIndex: number; noteIndex: number; measure: string; sourceNoteId: string;
  divisions: number; duration: number; type: string; dot: number; rest: boolean;
  pitch: { step: string; alter: number; octave: number } | null;
  voice: string; staff: string; chord: boolean; grace: boolean; ties: string[];
};
export type NoteListing = { jobId: string; revision: number; score: number; parts: { id: string; name: string }[]; notes: CloudNote[] };
export type NoteEdit = Pick<CloudNote, "partId" | "measureIndex" | "noteIndex"> & Partial<Pick<CloudNote, "duration" | "type" | "dot" | "rest">> & { pitch?: NonNullable<CloudNote["pitch"]>; delete?: boolean };
export type CloudConfiguration = { baseURL: string; hasCredentials: boolean; native?: boolean; platform?: string; listeningEnabled?: boolean };
type NativeReply = { ok: true; result: unknown } | { ok: false; error: { code?: string; message: string; status?: number } };
type NativeReceiver = { resolve: (requestId: string, reply: NativeReply) => void; event: (event: Record<string, unknown>) => void };
declare global {
  interface Window {
    webkit?: { messageHandlers?: { noteLiteCloud?: { postMessage: (message: { requestId: string; action: string; payload: unknown }) => void } } };
    NoteLiteCloudNative?: NativeReceiver;
  }
}

export class CloudError extends Error {
  status?: number;
  code?: string;
  constructor(message: string, status?: number, code?: string) { super(message); this.name = "CloudError"; this.status = status; this.code = code; }
}
export function errorMessage(error: unknown): string {
  if (error instanceof CloudError && error.status === 401) return "请先在云端识谱设置中连接设备。";
  if (error instanceof CloudError && error.status === 409) return "曲谱已更新或正在保存。请重新载入最新版本，再校对。";
  if (error instanceof CloudError && error.status === 413) return "文件太大，请使用小于 32 MB 的曲谱。";
  if (error instanceof CloudError && error.code === "write_status_unknown") return "保存结果待确认，请重新载入最新版本后再修改。";
  return error instanceof Error ? error.message : "连接失败，请稍后重试。";
}

const pending = new Map<string, { action: string; resolve: (result: unknown) => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> }>();
export function createUUID(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16)); bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
}
export function isNativeCloud(): boolean { return typeof window !== "undefined" && !!window.webkit?.messageHandlers?.noteLiteCloud; }
function developmentProxyEnabled(): boolean { return import.meta.env?.DEV === true && import.meta.env?.NOTELITE_DEV_PROXY_ENABLED === true; }
export function nativeRequest<T>(action: string, payload: unknown = {}, timeout = 30000): Promise<T> {
  const handler = typeof window !== "undefined" && window.webkit?.messageHandlers?.noteLiteCloud;
  if (!handler) return Promise.reject(new CloudError("当前设备没有原生连接桥接。"));
  if (!window.NoteLiteCloudNative) {
    window.NoteLiteCloudNative = {
      resolve(requestId, reply) {
        const entry = pending.get(requestId);
        if (!entry) return;
        clearTimeout(entry.timer); pending.delete(requestId);
        if (reply.ok) entry.resolve(reply.result);
        else entry.reject(new CloudError(reply.error.message, reply.error.status, reply.error.code));
      },
      event(event) { window.dispatchEvent(new CustomEvent("notelite-cloud-event", { detail: event })); },
    };
  }
  return new Promise<T>((resolve, reject) => {
    const requestId = createUUID();
    const timer = setTimeout(() => {
      pending.delete(requestId);
      try { handler.postMessage({ requestId: createUUID(), action: "request/cancel", payload: { targetRequestId: requestId } }); } catch { /* The native view may already have closed. */ }
      const writing = action === "notes/patch" || action === "score/put";
      reject(new CloudError(writing ? "保存结果待确认，请重新载入最新版本。" : "连接超时，请检查网络或重新读取任务状态。", undefined, writing ? "write_status_unknown" : "timeout"));
    }, timeout);
    pending.set(requestId, { action, resolve: (value) => resolve(value as T), reject, timer });
    try { handler.postMessage({ requestId, action, payload }); }
    catch (error) { clearTimeout(timer); pending.delete(requestId); reject(error); }
  });
}

/** Prevent a closed score workspace from later opening a native preview or save dialog. */
export function cancelNativeFileRequests(): void {
  const handler = typeof window !== "undefined" && window.webkit?.messageHandlers?.noteLiteCloud;
  if (!handler) return;
  for (const [requestId, entry] of pending) {
    if (!["files/view", "files/export", "files/save"].includes(entry.action)) continue;
    clearTimeout(entry.timer); pending.delete(requestId);
    try { handler.postMessage({ requestId: createUUID(), action: "request/cancel", payload: { targetRequestId: requestId } }); } catch { /* View already closed. */ }
    entry.reject(new CloudError("已取消文件操作。", undefined, "cancelled"));
  }
}

function jobPath(jobId: string, suffix = "", score?: number): string {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(jobId)) throw new CloudError("任务标识无效。");
  if (score !== undefined && (!Number.isInteger(score) || score < 0)) throw new CloudError("乐章标识无效。");
  return `/api/jobs/${jobId}${suffix}${score === undefined ? "" : `?score=${score}`}`;
}

/** Injectable transport lets tests verify actual HTTP contracts without exposing credentials. */
export class CloudClient {
  private csrf = "";
  private fetcher: typeof fetch;
  private native: typeof isNativeCloud;
  private bridge: typeof nativeRequest;
  private timeouts: { read: number; write: number };
  private previewEnabled: () => boolean;
  constructor(fetcher: typeof fetch = (...args) => fetch(...args), native = isNativeCloud, bridge = nativeRequest, timeouts = { read: 30000, write: 300000 }, previewEnabled = developmentProxyEnabled) { this.fetcher = fetcher; this.native = native; this.bridge = bridge; this.timeouts = timeouts; this.previewEnabled = previewEnabled; }
  private async request(path: string, init: RequestInit = {}, response: "json" | "text" | "blob" = "json"): Promise<unknown> {
    const method = (init.method || "GET").toUpperCase();
    if (method !== "GET" && method !== "HEAD" && path !== "/api/pair" && !this.csrf) await this.session();
    const headers = new Headers(init.headers);
    if (method !== "GET" && method !== "HEAD" && path !== "/api/pair") headers.set("X-NoteLite-CSRF", this.csrf);
    let result: Response;
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), method === "GET" ? this.timeouts.read : this.timeouts.write);
    try {
    try { result = await this.fetcher(path, { ...init, headers, credentials: "same-origin", signal: abort.signal }); }
    catch { throw new CloudError(abort.signal.aborted ? "连接超时，请重新读取任务状态。" : "无法连接识谱服务，请检查网络后重试。", undefined, method === "PATCH" || method === "PUT" ? "write_status_unknown" : "network"); }
    if (!result.ok) {
      let message = `识谱服务暂时无法处理请求（${result.status}）。`;
      try { const body = await result.json(); if (typeof body.error === "string") message = body.error; else if (body.error?.message) message = body.error.message; }
      catch { /* A reverse proxy may return an HTML error page. */ }
      if (result.status === 401) this.csrf = "";
      throw new CloudError(message, result.status, (method === "PATCH" || method === "PUT") && result.status >= 500 ? "write_status_unknown" : undefined);
    }
    try { return await (response === "text" ? result.text() : response === "blob" ? result.blob() : result.json()); }
    catch { throw new CloudError("服务响应未完整收到，请重新读取任务状态。", undefined, method === "PATCH" || method === "PUT" ? "write_status_unknown" : "network"); }
    } finally { clearTimeout(timer); }
  }
  private async session(): Promise<{ authenticated: boolean; csrf: string }> {
    const session = await this.request("/api/session") as { authenticated: boolean; csrf: string };
    if (!session.authenticated || !session.csrf) throw new CloudError("请先连接设备。", 401);
    this.csrf = session.csrf; return session;
  }
  async configuration(): Promise<CloudConfiguration> {
    if (this.native()) return this.bridge<CloudConfiguration>("configuration/get");
    let hasCredentials = false;
    try { await this.session(); hasCredentials = true; } catch (error) { if (!(error instanceof CloudError && error.status === 401)) throw error; }
    return { baseURL: window.location.origin, hasCredentials, native: false, listeningEnabled: false };
  }
  async configure(baseURL: string): Promise<void> {
    const url = new URL(baseURL);
    if (url.username || url.password || url.search || url.hash || (url.pathname !== "/" && url.pathname !== "")) throw new CloudError("请填写不包含路径或账号信息的服务地址。");
    if (this.native()) {
      if (url.protocol !== "https:") throw new CloudError("原生设备需要 HTTPS 识谱服务地址。");
      await this.bridge("configuration/set", { baseURL: url.origin }); return;
    }
    if (url.origin !== window.location.origin) throw new CloudError("浏览器请打开该服务地址再连接，曲谱请求使用当前页面的安全连接。");
    const localPreview = this.previewEnabled() && url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname);
    if (url.protocol !== "https:" && !localPreview) throw new CloudError("浏览器需要 HTTPS；回环预览须显式启用开发代理。");
  }
  async pair(code: string, deviceName: string): Promise<void> {
    if (!code.trim()) throw new CloudError("请输入设备连接码。");
    if (this.native()) { await this.bridge("device/pair", { code: code.trim(), deviceName }); return; }
    const session = await this.request("/api/pair", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: code.trim(), deviceName, mode: "browser" }) }) as { csrf: string };
    if (!session.csrf) throw new CloudError("连接未完成，请重试。");
    this.csrf = session.csrf;
  }
  async health(): Promise<unknown> { return this.native() ? this.bridge("health") : this.request("/api/health"); }
  async jobs(): Promise<CloudJob[]> {
    const result = this.native() ? await this.bridge<{ jobs: CloudJob[] }>("jobs/list") : await this.request("/api/jobs") as { jobs: CloudJob[] };
    return result.jobs;
  }
  async job(jobId: string): Promise<CloudJob> {
    const path = jobPath(jobId);
    return this.native() ? this.bridge<CloudJob>("jobs/get", { jobId }) : this.request(path) as Promise<CloudJob>;
  }
  async upload(file: Blob, filename: string): Promise<CloudJob> {
    if (file.size > 32 * 1024 * 1024) throw new CloudError("文件太大，请使用小于 32 MB 的曲谱。", 413);
    if (!file.size) throw new CloudError("曲谱文件为空。");
    if (this.native()) {
      const bytes = new Uint8Array(await file.arrayBuffer());
      const chunks: string[] = [];
      for (let index = 0; index < bytes.length; index += 32768) chunks.push(String.fromCharCode(...bytes.subarray(index, index + 32768)));
      return this.bridge<CloudJob>("jobs/upload", { filename, base64: btoa(chunks.join("")) }, 300000);
    }
    return this.request(`/api/jobs?filename=${encodeURIComponent(filename)}`, { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file }) as Promise<CloudJob>;
  }
  async importNative(): Promise<CloudJob> { return this.bridge<CloudJob>("jobs/import", {}, 600000); }
  async original(jobId: string, score: number, filename?: string): Promise<Blob | undefined> {
    const path = jobPath(jobId, "/original", score);
    if (this.native()) { await this.bridge("files/view", { jobId, score, kind: "original", filename }, 300000); return; }
    return this.request(path, {}, "blob") as Promise<Blob>;
  }
  async score(jobId: string, score: number): Promise<string> {
    const path = jobPath(jobId, "/score/musicxml", score);
    return this.native() ? this.bridge<string>("score/get", { jobId, score }) : this.request(path, {}, "text") as Promise<string>;
  }
  async notes(jobId: string, score: number): Promise<NoteListing> {
    const path = jobPath(jobId, "/notes", score);
    return this.native() ? this.bridge<NoteListing>("notes/get", { jobId, score }) : this.request(path) as Promise<NoteListing>;
  }
  async patch(jobId: string, score: number, revision: number, edits: NoteEdit[]): Promise<CloudJob> {
    const path = jobPath(jobId, "/notes", score);
    if (!Number.isInteger(revision) || revision < 1) throw new CloudError("请重新载入当前曲谱版本。");
    return this.native() ? this.bridge<CloudJob>("notes/patch", { jobId, score, revision, edits }, 300000) : this.request(path, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ revision, score, edits }) }) as Promise<CloudJob>;
  }
  async put(jobId: string, score: number, revision: number, musicxml: string): Promise<CloudJob> {
    const path = jobPath(jobId, "/score", score);
    if (!Number.isInteger(revision) || revision < 1) throw new CloudError("请重新载入当前曲谱版本。");
    return this.native() ? this.bridge<CloudJob>("score/put", { jobId, score, revision, musicxml }, 300000) : this.request(path, { method: "PUT", headers: { "Content-Type": "application/vnd.recordare.musicxml+xml", "If-Match": `"${revision}"` }, body: musicxml }) as Promise<CloudJob>;
  }
  async export(jobId: string, score: number, kind: "musicxml" | "midi" | "original" | "omr", filename: string): Promise<void> {
    const suffix = { musicxml: "/score/musicxml", midi: "/score/midi", original: "/original", omr: "/project/omr" }[kind];
    const path = jobPath(jobId, suffix, score);
    if (this.native()) { await this.bridge("files/export", { jobId, score, kind, filename }, 600000); return; }
    await downloadBlob(await this.request(path, {}, "blob") as Blob, filename);
  }
}
export async function downloadBlob(blob: Blob, filename: string): Promise<void> {
  if (isNativeCloud()) {
    if (blob.size > 16 * 1024 * 1024) throw new CloudError("本机导出文件大于 16 MB，请使用云端文件导出。");
    const bytes = new Uint8Array(await blob.arrayBuffer()); const chunks: string[] = [];
    for (let index = 0; index < bytes.length; index += 32768) chunks.push(String.fromCharCode(...bytes.subarray(index, index + 32768)));
    await nativeRequest("files/save", { filename, base64: btoa(chunks.join("")) }, 600000); return;
  }
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a"); link.href = objectUrl; link.download = filename; link.click();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}
export const cloud = new CloudClient();
