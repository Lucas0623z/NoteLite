import { CloudError, cloud, createUUID, isNativeCloud, nativeRequest } from "./cloud.ts";
import type { NoteWiseAnalysis } from "./notewise.ts";

export type AccountIdentity = { authenticated: true; userId: string; username: string; sessionId: string; deviceName: string; expiresAt: string; kind: "browser" | "native" };
export type PersonalScore = { id: string; title: string; revision: number; etag: string; updatedAt: string; omr?: { jobId: string; scoreIndex: number; revision: number } };
export type CatalogScore = { id: string; title: string; composer: string; license: string; source: string };
export type PracticeAnalysis = Omit<Partial<NoteWiseAnalysis>, "status" | "source" | "errors" | "verifiedByServer"> & { status: string; source: string; errors: unknown[] | null; verifiedByServer: boolean; snapshotValidatedByServer?: boolean; serverNormalizerVersion?: string; serverMetrics?: Record<string, unknown> };
export type HistoryAnalysisMetadata = { version: number; parentVersion: number; requestId: string; sourceHash: string; analysisHash: string; createdAt: string; snapshotValidatedByServer: boolean };
export type HistoryAnalysisVersion = HistoryAnalysisMetadata & { analysis: PracticeAnalysis; duplicate?: boolean };
export type PracticeEvent = { eventId: string; sourceKind: "official" | "personal"; scoreId: string; mode: "free" | "strict" | "follow" | "playback"; durationSeconds: number; startedAt: string; endedAt: string; scoreRevision?: number; scoreSha256?: string; analysis?: PracticeAnalysis; receivedAt?: string; scoreValidated?: boolean; analysisVersion?: number; latestAnalysisVersion?: number; analysisHash?: string; snapshotValidatedByServer?: boolean };
export type Classroom = { id: string; title: string; role: "teacher" | "student"; teacher?: string; creator?: string; [key: string]: unknown };
export type Assignment = { id: string; courseId: string; courseScoreId: string; title: string; dueAt: string | null; requirements: string; createdAt: string };
export type Submission = { id: string; assignmentId: string; student: string; event: PracticeEvent; audioAvailable: boolean; analysis: { status: string; errors: unknown[] | null; source: string; verifiedByServer: boolean }; submittedAt: string; late: boolean };
export type AggregateFact = { factId: string; kind: "weakness" | "strength" | "progress" | "performance_observation" | "practice_investment" | "pending_review" | "data_quality" | "unavailable"; dimension: string; label: string; statement: string; displayValue: string | null; claimState: "verified_fact" | "provisional_pattern" | "pending_review" | "unavailable"; scope: string; confidence: "high" | "medium" | "low" | "unknown"; evidenceRefs: string[]; limitations: string[] };
export type AggregateObservation = { title: string; description: string; factIds: string[] };
export type PracticeInterpretation = { schemaVersion: "2.0"; status: "complete" | "partial" | "investment_only" | "pending_review" | "no_usable_data"; summary: string; observations: AggregateObservation[]; weaknesses: AggregateObservation[]; strengths: AggregateObservation[]; progress: AggregateObservation[]; pendingReview: AggregateObservation[]; suggestions: { title: string; action: string; successCheck: string; factIds: string[] }[]; limitations: string[] };
export type PracticeAnalysisResult = { id: string; output: PracticeInterpretation; facts: AggregateFact[]; generationStatus: "completed" | "fallback"; summarySource?: "program" | "model"; retryAllowed?: boolean; scope: { recordCount: number; hasMore: boolean; description: string }; provider: "DeepSeek"; model: string; cached: boolean };
export const ACCOUNT_EVENT = "notelite-account-changed";
export type AccountRequest = { path: string; method: "GET" | "POST" | "PUT" | "DELETE"; body?: unknown; etag?: string; response: "json" | "text" | "base64"; base64?: string; uploadOffset?: number; expectedUserId?: string };
const id = (value: string) => { if (!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value)) throw new CloudError("记录标识无效。"); return value; };
const catalogID = (value: string) => { if (!/^[A-Za-z0-9_-]{1,80}$/.test(value)) throw new CloudError("曲谱标识无效。"); return value; };

/** The browser receives only HttpOnly sessions; native replies exclude their Keychain token. */
export class AccountClient {
  private csrf = "";
  private identity: AccountIdentity | null = null;
  private generation = 0;
  private fetcher: typeof fetch;
  private native: typeof isNativeCloud;
  private bridge: typeof nativeRequest;
  private changed: () => void;
  constructor(fetcher: typeof fetch = (...args) => fetch(...args), native = isNativeCloud, bridge = nativeRequest, changed: () => void = () => { cloud.resetSession(); window.dispatchEvent(new Event(ACCOUNT_EVENT)); }) { this.fetcher = fetcher; this.native = native; this.bridge = bridge; this.changed = changed; }
  get current(): AccountIdentity | null { return this.identity; }
  private async request<T>(input: AccountRequest): Promise<T> {
    const generation = this.generation;
    input = { ...input, expectedUserId: input.path === "/me" || ["/register", "/login"].includes(input.path) ? undefined : this.identity?.userId };
    if (this.native()) return this.bridge<T>("account/request", input, input.base64 ? 300000 : input.path === "/practice-analysis" ? 180000 : 60000);
    const publicWrite = ["/register", "/login"].includes(input.path);
    if (input.method !== "GET" && !publicWrite && !this.csrf) { if (!await this.me()) throw new CloudError("请先登录账户。", 401); }
    if (generation !== this.generation) throw new CloudError("账户已切换，请重新执行此操作。", 409);
    const headers = new Headers();
    if (input.expectedUserId) headers.set("X-NoteLite-Expected-User", input.expectedUserId);
    if (input.method !== "GET" && !publicWrite) headers.set("X-NoteLite-CSRF", this.csrf);
    if (input.etag) headers.set("If-Match", input.etag);
    if (input.uploadOffset !== undefined) headers.set("Upload-Offset", String(input.uploadOffset));
    let body: BodyInit | undefined;
    if (input.base64 !== undefined) { body = Uint8Array.from(atob(input.base64), (char) => char.charCodeAt(0)); headers.set("Content-Type", "application/octet-stream"); }
    else if (input.body !== undefined) { body = JSON.stringify(input.body); headers.set("Content-Type", "application/json"); }
    const abort = new AbortController(), timer = setTimeout(() => abort.abort(), input.base64 ? 300000 : input.path === "/practice-analysis" ? 180000 : 60000);
    try {
      let result: Response;
      try { result = await this.fetcher(`/api/account${input.path}`, { method: input.method, headers, body, credentials: "same-origin", signal: abort.signal }); }
      catch { throw new CloudError(input.method === "GET" ? "账号服务暂时无法连接。" : "提交结果待确认，请重新读取后重试。", undefined, input.method === "GET" ? "network" : "write_status_unknown"); }
      if (!result.ok) {
        if (result.status === 401 && generation === this.generation) { this.csrf = ""; this.identity = null; }
        let message = result.status === 401 ? "请先登录账户。" : `账号服务暂时无法处理请求（${result.status}）。`;
        try { const value = await result.json(); if (typeof value.error === "string") message = value.error; } catch { /* Proxy response may be HTML. */ }
        throw new CloudError(message, result.status);
      }
      if (input.response === "text") return await result.text() as T;
      if (input.response === "base64") return await result.blob() as T;
      const value = await result.json();
      if (typeof value.csrf === "string" && generation === this.generation) this.csrf = value.csrf;
      return value as T;
    } finally { clearTimeout(timer); }
  }
  private retain(value: AccountIdentity): AccountIdentity {
    // Copy public fields explicitly, so a service regression cannot persist a token in JS state.
    this.identity = { authenticated: true, userId: value.userId, username: value.username, sessionId: value.sessionId, deviceName: value.deviceName, expiresAt: value.expiresAt, kind: value.kind };
    return this.identity;
  }
  async me(): Promise<AccountIdentity | null> {
    const generation = this.generation;
    try { const value = await this.request<AccountIdentity>({ path: "/me", method: "GET", response: "json" }); return generation === this.generation ? this.retain(value) : this.identity; }
    catch (error) { if (error instanceof CloudError && error.status === 401) return generation === this.generation ? null : this.identity; throw error; }
  }
  async authenticate(mode: "register" | "login", username: string, password: string): Promise<AccountIdentity> {
    const generation = ++this.generation;
    const value = await this.request<AccountIdentity>({ path: `/${mode}`, method: "POST", body: { username, password, mode: this.native() ? "native" : "browser", deviceName: this.native() ? "黑白键 Apple" : "黑白键浏览器" }, response: "json" });
    if (generation !== this.generation) throw new CloudError("账户操作已更新，请重新读取当前账户。");
    this.retain(value); this.changed(); return this.identity!;
  }
  async logout(): Promise<void> { const generation = ++this.generation; await this.request({ path: "/logout", method: "POST", response: "json" }); if (generation !== this.generation) return; this.identity = null; this.csrf = ""; this.changed(); }
  sessions() { return this.request<{ sessions: { sessionId: string; deviceName: string; kind: string; createdAt: string; expiresAt: string }[] }>({ path: "/sessions", method: "GET", response: "json" }); }
  revoke(sessionId: string) { return this.request({ path: `/sessions/${id(sessionId)}`, method: "DELETE", response: "json" }); }
  catalog() { return this.request<{ scores: CatalogScore[] }>({ path: "/catalog", method: "GET", response: "json" }); }
  officialXML(scoreId: string) { return this.request<string>({ path: `/catalog/${catalogID(scoreId)}/musicxml`, method: "GET", response: "text" }); }
  scores() { return this.request<{ scores: PersonalScore[] }>({ path: "/scores", method: "GET", response: "json" }); }
  createScore(title: string, musicxml: string, requestId?: string) { return this.request<PersonalScore>({ path: "/scores", method: "POST", body: { title, musicxml, ...(requestId ? { requestId: id(requestId) } : {}) }, response: "json" }); }
  attachOMR(title: string, jobId: string, scoreIndex: number, revision: number) { return this.request<PersonalScore>({ path: "/scores", method: "POST", body: { title, jobId: id(jobId), scoreIndex, revision }, response: "json" }); }
  scoreXML(scoreId: string) { return this.request<string>({ path: `/scores/${id(scoreId)}/musicxml`, method: "GET", response: "text" }); }
  updateScore(score: PersonalScore, musicxml: string, title = score.title) { return this.request<PersonalScore>({ path: `/scores/${id(score.id)}`, method: "PUT", body: { musicxml, title }, etag: score.etag, response: "json" }); }
  history(cursor?: string) { return this.request<{ events: PracticeEvent[]; nextCursor: string | null }>({ path: `/history?limit=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`, method: "GET", response: "json" }); }
  addHistory(event: PracticeEvent) { return this.request<{ event: PracticeEvent; duplicate: boolean }>({ path: "/history", method: "POST", body: event, response: "json" }); }
  historyXML(eventId: string) { return this.request<string>({ path: `/history/${id(eventId)}/musicxml`, method: "GET", response: "text" }); }
  historyAnalyses(eventId: string) { return this.request<{ analyses: HistoryAnalysisMetadata[]; latestVersion: number }>({ path: `/history/${id(eventId)}/analyses`, method: "GET", response: "json" }); }
  historyAnalysis(eventId: string, version: number) { if (!Number.isInteger(version) || version < 1) throw new CloudError("分析版本无效。"); return this.request<HistoryAnalysisVersion>({ path: `/history/${id(eventId)}/analyses/${version}`, method: "GET", response: "json" }); }
  addHistoryAnalysis(eventId: string, body: { requestId: string; parentVersion: number; sourceHash: string; analysis: PracticeAnalysis }) { if (!Number.isInteger(body.parentVersion) || body.parentVersion < 0 || !/^[0-9a-f]{64}$/.test(body.sourceHash)) throw new CloudError("原谱或分析版本无效。"); return this.request<HistoryAnalysisVersion>({ path: `/history/${id(eventId)}/analyses`, method: "POST", body: { ...body, requestId: id(body.requestId) }, response: "json" }); }
  analyzePractice(eventIds?: string[], requestId = createUUID()) { return this.request<PracticeAnalysisResult>({ path: "/practice-analysis", method: "POST", body: { requestId: id(requestId), ...(eventIds ? { eventIds: eventIds.map(id) } : {}) }, response: "json" }); }
  courses() { return this.request<{ courses: Classroom[] }>({ path: "/courses", method: "GET", response: "json" }); }
  createCourse(title: string) { return this.request<Classroom>({ path: "/courses", method: "POST", body: { title }, response: "json" }); }
  course(courseId: string) { return this.request<Classroom>({ path: `/courses/${id(courseId)}`, method: "GET", response: "json" }); }
  addCourseScore(courseId: string, sourceKind: "official" | "personal", scoreId: string) { return this.request<{ id: string; title: string }>({ path: `/courses/${id(courseId)}/scores`, method: "POST", body: { sourceKind, scoreId }, response: "json" }); }
  createCode(courseId: string) { return this.request<{ code: string; codeId: string; expiresAt: string }>({ path: `/courses/${id(courseId)}/codes`, method: "POST", body: {}, response: "json" }); }
  previewCode(code: string) { return this.request<{ courseId: string; title: string; teacher: string; sharingScope: string }>({ path: "/course-codes/preview", method: "POST", body: { code }, response: "json" }); }
  joinCode(code: string) { return this.request<Classroom>({ path: "/course-codes/join", method: "POST", body: { code }, response: "json" }); }
  assignments(courseId: string) { return this.request<{ assignments: Assignment[] }>({ path: `/courses/${id(courseId)}/assignments`, method: "GET", response: "json" }); }
  createAssignment(courseId: string, body: { title: string; courseScoreId: string; dueAt?: string; requirements?: string }) { return this.request<Assignment>({ path: `/courses/${id(courseId)}/assignments`, method: "POST", body, response: "json" }); }
  submissions(assignmentId: string) { return this.request<{ submissions: Submission[] }>({ path: `/assignments/${id(assignmentId)}/submissions`, method: "GET", response: "json" }); }
  submissionXML(submissionId: string) { return this.request<string>({ path: `/submissions/${id(submissionId)}/musicxml`, method: "GET", response: "text" }); }
  submit(assignmentId: string, eventId: string, uploadId?: string, analysisVersion?: number) { if (analysisVersion !== undefined && (!Number.isInteger(analysisVersion) || analysisVersion < 0)) throw new CloudError("分析版本无效。"); return this.request<Submission>({ path: `/assignments/${id(assignmentId)}/submissions`, method: "POST", body: { eventId: id(eventId), ...(uploadId ? { uploadId: id(uploadId) } : {}), ...(analysisVersion !== undefined ? { analysisVersion } : {}) }, response: "json" }); }
  async audio(submissionId: string): Promise<Blob> {
    const value = await this.request<Blob | { base64: string; mime: string }>({ path: `/submissions/${id(submissionId)}/audio`, method: "GET", response: "base64" });
    return value instanceof Blob ? value : new Blob([Uint8Array.from(atob(value.base64), (char) => char.charCodeAt(0))], { type: value.mime });
  }
  async playAudio(submissionId: string): Promise<boolean> { if (!this.native()) return false; await this.bridge("account/audio/view", { submissionId: id(submissionId), expectedUserId: this.identity?.userId }, 300000); return true; }
  private async fileDigest(file: Blob): Promise<string> {
    if (crypto.subtle) {
      const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
      return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
    }
    if (!this.native()) throw new CloudError("请使用 HTTPS 页面提交录音。");
    const { digestId } = await this.bridge<{ digestId: string }>("account/digest/start", { size: file.size });
    try {
      for (let offset = 0; offset < file.size; offset += 1024 * 1024) {
        const chunk = new Uint8Array(await file.slice(offset, offset + 1024 * 1024).arrayBuffer()), strings: string[] = [];
        for (let index = 0; index < chunk.length; index += 32768) strings.push(String.fromCharCode(...chunk.subarray(index, index + 32768)));
        await this.bridge("account/digest/update", { digestId, offset, base64: btoa(strings.join("")) });
      }
      const { sha256 } = await this.bridge<{ sha256: string }>("account/digest/finish", { digestId });
      if (!/^[0-9a-f]{64}$/.test(sha256)) throw new CloudError("录音完整性校验未完成。");
      return sha256;
    } catch (error) { await this.bridge("account/digest/cancel", { digestId }).catch(() => {}); throw error; }
  }
  async uploadRecording(assignmentId: string, file: Blob): Promise<string> {
    if (!file.size || file.size > 100 * 1024 * 1024) throw new CloudError("录音需小于 100 MB，且不能为空。");
    const sha256 = await this.fileDigest(file);
    const upload = await this.request<{ uploadId: string; offset: number }>({ path: "/uploads", method: "POST", body: { assignmentId: id(assignmentId), size: file.size, mime: file.type, sha256 }, response: "json" });
    for (let offset = upload.offset; offset < file.size; offset += 1024 * 1024) {
      const chunk = new Uint8Array(await file.slice(offset, Math.min(offset + 1024 * 1024, file.size)).arrayBuffer()), strings: string[] = [];
      for (let index = 0; index < chunk.length; index += 32768) strings.push(String.fromCharCode(...chunk.subarray(index, index + 32768)));
      await this.request({ path: `/uploads/${id(upload.uploadId)}`, method: "PUT", base64: btoa(strings.join("")), uploadOffset: offset, response: "json" });
    }
    await this.request({ path: `/uploads/${id(upload.uploadId)}/complete`, method: "POST", body: {}, response: "json" });
    return upload.uploadId;
  }
}
export const account = new AccountClient();
