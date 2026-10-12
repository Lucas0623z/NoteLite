import test from "node:test";
import assert from "node:assert/strict";
import { AccountFileSelection, cancelNativeFileRequests, CloudClient, CloudError, createUUID, errorMessage, nativeRequest, recheckImportAuthentication, scopedAccountWrite, type AccountOperationScope, type ScoreFileSource } from "../src/app/cloud.ts";
import { completedJobNotice, uploadedJobNotice } from "../src/app/job-notice.ts";

const id = "11111111-1111-4111-8111-111111111111";
const job = { id, filename: "练习.pdf", state: "succeeded", revision: 2, scores: [], artifacts: {} };

for (const source of ["files", "photos", "camera"] as ScoreFileSource[]) test(`account import guard prevents ${source} opened by A from uploading to B or a renewed A session`, async () => {
  const selections = new AccountFileSelection();
  const original: AccountOperationScope = { owner: id, sessionId: "A-session", generation: 1 };
  let current = original, uploads = 0;
  const isCurrent = (scope: AccountOperationScope) => scope.owner === current.owner && scope.sessionId === current.sessionId && scope.generation === current.generation;
  const consume = async () => { if (selections.take(source, isCurrent)) uploads++; };
  selections.begin(source, original);
  current = { owner: "22222222-2222-4222-8222-222222222222", sessionId: "B-session", generation: 2 };
  await consume(); assert.equal(uploads, 0);
  current = original; selections.begin(source, original);
  current = { ...original, sessionId: "new-A-session", generation: 3 };
  await consume(); assert.equal(uploads, 0);
  current = original; selections.begin(source, original); selections.clear();
  await consume(); assert.equal(uploads, 0, "an account event explicitly invalidates an already open picker");
  selections.begin(source, current); await consume(); await consume();
  assert.equal(uploads, 1, "one unchanged account selection is accepted once");
});

for (const operation of ["official correction", "personal rename"] as const) test(`account import guard prevents ${operation} writing XML to a new account after an asynchronous read`, async () => {
  let current = true, writes = 0, release!: (value: string) => void;
  const source = new Promise<string>((resolve) => { release = resolve; });
  const saving = scopedAccountWrite(() => current, () => source, async () => { writes++; return job; });
  current = false; release("private A XML");
  await assert.rejects(saving, (error: unknown) => error instanceof CloudError && error.code === "identity_changed");
  assert.equal(writes, 0, "identity must be checked before the SDK chooses an account for the write");
});

test("account import guard rejects an old remote write reply before local/UI installation", async () => {
  let current = true, release!: (value: typeof job) => void, entered!: () => void, installed = 0;
  const write = new Promise<typeof job>((resolve) => { release = resolve; });
  const started = new Promise<void>((resolve) => { entered = resolve; });
  const saving = scopedAccountWrite(() => current, async () => "A XML", async () => { entered(); return write; }).then(() => { installed++; });
  await started; current = false; release(job);
  await assert.rejects(saving, (error: unknown) => error instanceof CloudError && error.code === "identity_changed");
  assert.equal(installed, 0);
});

test("account import guard confirms expiry through the account SDK before requesting sign-in", async () => {
  const original = { userId: id, sessionId: "A-session" };
  let identity: typeof original | null = original, reads = 0;
  const client = { get current() { return identity; }, me: async () => { reads++; identity = null; return null; } };
  const result = await recheckImportAuthentication(original, client, () => identity === original);
  assert.equal(result, "expired"); assert.equal(reads, 1); assert.equal(client.current, null);
  assert.equal(errorMessage(new CloudError("old device error", 401)), "请先登录账户，再上传或读取云端曲谱。");
});

test("account import guard preserves a still valid account when only OMR refuses authentication", async () => {
  const original = { userId: id, sessionId: "A-session" };
  const client = { current: original, me: async () => original };
  assert.equal(await recheckImportAuthentication(original, client, () => true), "active");
  assert.equal(client.current, original, "an OMR error cannot force a valid account to log out");
});

test("account import guard ignores old401 recovery after another account logs in", async () => {
  const original = { userId: id, sessionId: "A-session" }, second = { userId: "22222222-2222-4222-8222-222222222222", sessionId: "B-session" };
  let identity: typeof original | null = original, release!: (value: typeof original | null) => void, reads = 0;
  const refresh = new Promise<typeof original | null>((resolve) => { release = resolve; });
  const client = { get current() { return identity; }, me: () => { reads++; return refresh; } };
  const recovery = recheckImportAuthentication(original, client, () => identity === original);
  identity = second; release(second);
  assert.equal(await recovery, "changed"); assert.equal(client.current, second);
  assert.equal(await recheckImportAuthentication(original, client, () => false), "changed");
  assert.equal(reads, 1, "a previously superseded401 must not even refresh the new account");
});

test("the upload notice follows its actual successful or failed recognition result", () => {
  const waiting = uploadedJobNotice({ id, state: "running", recognitionMode: "audiveris" });
  assert.match(waiting.text, /正在识别/);
  assert.match(completedJobNotice(waiting, { id, state: "succeeded" }).text, /识谱已完成/);
  assert.match(completedJobNotice(waiting, { id, state: "failed", error: "原稿不清晰" }).text, /识谱未完成.*原稿不清晰/);
  assert.match(uploadedJobNotice({ id, state: "succeeded", recognitionMode: "import" }).text, /曲谱已导入/);
});

test("a completed earlier job cannot replace a later upload or a user's new notice", () => {
  const laterUpload = uploadedJobNotice({ id: "22222222-2222-4222-8222-222222222222", state: "queued" });
  const userNotice = { text: "设备已连接，可以上传曲谱并保存校对。" };
  const completed = { id, state: "succeeded" as const };
  assert.equal(completedJobNotice(laterUpload, completed), laterUpload);
  assert.equal(completedJobNotice(userNotice, completed), userNotice);
});

test("a nonterminal poll preserves the currently owned progress notice", () => {
  const waiting = uploadedJobNotice({ id, state: "queued" });
  assert.equal(completedJobNotice(waiting, { id, state: "running" }), waiting);
});
type Call = { path: string; init: RequestInit; headers: Headers };
function mock(routes: Record<string, unknown | ((call: Call) => Response)>, previewEnabled?: () => boolean) {
  const calls: Call[] = [];
  const fetcher = async (path: string | URL | Request, init: RequestInit = {}) => {
    const call = { path: String(path), init, headers: new Headers(init.headers) }; calls.push(call);
    const route = routes[`${init.method || "GET"} ${path}`];
    if (typeof route === "function") return route(call);
    assert.notEqual(route, undefined, `Unexpected request ${init.method || "GET"} ${path}`);
    return new Response(JSON.stringify(route), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  return { client: new CloudClient(fetcher as typeof fetch, () => false, nativeRequest, { read: 30000, write: 300000 }, previewEnabled), calls };
}

test("browser pairing uses a cookie session and CSRF; no Bearer or token is put in the UI", async () => {
  const { client, calls } = mock({ "POST /api/pair": { csrf: "csrf-example" }, "POST /api/jobs?filename=%E7%BB%83%E4%B9%A0.pdf": job });
  await client.pair("  pairing-code  ", "Test device");
  await client.upload(new Blob(["%PDF"], { type: "application/pdf" }), "练习.pdf");
  assert.deepEqual(JSON.parse(calls[0].init.body as string), { code: "pairing-code", deviceName: "Test device", mode: "browser" });
  assert.equal(calls[1].headers.get("X-NoteLite-CSRF"), "csrf-example");
  assert.equal(calls[1].headers.has("Authorization"), false);
  assert.equal(calls[1].init.credentials, "same-origin");
  assert.ok(calls[1].init.body instanceof Blob);
});

test("a browser reload obtains CSRF from the existing HttpOnly session before edits", async () => {
  const { client, calls } = mock({ "GET /api/session": { authenticated: true, csrf: "session-csrf" }, [`PATCH /api/jobs/${id}/notes?score=3`]: job });
  const edits = [{ partId: "P2", measureIndex: 8, noteIndex: 2, pitch: { step: "F", alter: 1, octave: 5 }, duration: 6, dot: 1 }];
  await client.patch(id, 3, 1, edits);
  assert.equal(calls[0].path, "/api/session");
  assert.equal(calls[1].headers.get("X-NoteLite-CSRF"), "session-csrf");
  assert.deepEqual(JSON.parse(calls[1].init.body as string), { revision: 1, score: 3, edits });
});

test("full MusicXML PUT includes If-Match and preserves the selected movement", async () => {
  const { client, calls } = mock({ "GET /api/session": { authenticated: true, csrf: "c" }, [`PUT /api/jobs/${id}/score?score=4`]: job });
  const xml = '<score-partwise version="4.0" />'; await client.put(id, 4, 7, xml);
  assert.equal(calls[1].headers.get("If-Match"), '"7"');
  assert.equal(calls[1].headers.get("Content-Type"), "application/vnd.recordare.musicxml+xml");
  assert.equal(calls[1].init.body, xml);
});

test("conflicting edits surface status 409 without an automatic overwrite", async () => {
  const { client, calls } = mock({ "GET /api/session": { authenticated: true, csrf: "c" }, [`PATCH /api/jobs/${id}/notes?score=0`]: () => new Response(JSON.stringify({ error: "revision changed" }), { status: 409 }) });
  await assert.rejects(client.patch(id, 0, 1, [{ partId: "P1", measureIndex: 0, noteIndex: 0, rest: true }]), (error) => error instanceof CloudError && error.status === 409 && errorMessage(error).includes("重新载入"));
  assert.equal(calls.length, 2);
});

test("authorization failures direct the user to account login", async () => {
  const { client } = mock({ "GET /api/jobs": () => new Response(JSON.stringify({ error: "unauthorized" }), { status: 401 }) });
  await assert.rejects(client.jobs(), (error) => error instanceof CloudError && errorMessage(error).includes("登录账户") && !errorMessage(error).includes("连接设备"));
});

test("account-cookie upload and XML editing use the existing login without configuration or pairing", async () => {
  const { client, calls } = mock({ "GET /api/session": { authenticated: true, csrf: "account-csrf", owner: id },
    "POST /api/jobs?filename=score.png": job, [`GET /api/jobs/${id}`]: job,
    [`GET /api/jobs/${id}/score/musicxml?score=0`]: () => new Response("<score-partwise/>"),
    [`PUT /api/jobs/${id}/score?score=0`]: { ...job, revision: 3 },
  });
  client.useAccount(id);
  assert.equal((await client.upload(new Blob(["synthetic image"]), "score.png")).id, id);
  assert.equal((await client.job(id)).revision, 2);
  assert.equal(await client.score(id, 0), "<score-partwise/>");
  assert.equal((await client.put(id, 0, 2, "<score-partwise version=\"4.0\"/>")).revision, 3);
  assert.ok(calls.every((call) => call.headers.get("X-NoteLite-Expected-User") === id));
  assert.ok(calls.every((call) => call.init.credentials === "same-origin" && !call.headers.has("Authorization")));
  assert.equal(calls.filter((call) => call.path.includes("pair") || call.path.includes("configure")).length, 0);
  assert.equal(calls[1].headers.get("X-NoteLite-CSRF"), "account-csrf");
  assert.equal(calls[4].headers.get("If-Match"), '"2"');
});

test("native account import, notes, XML and MIDI exports preserve the account without a device code", async () => {
  const calls: { action: string; payload: Record<string, unknown> }[] = [];
  const client = new CloudClient(async () => { throw new Error("native must not use browser fetch"); }, () => true,
    async <T>(action: string, payload: unknown = {}): Promise<T> => { calls.push({ action, payload: payload as Record<string, unknown> }); return job as T; });
  client.useAccount(id);
  await client.importNative(); await client.notes(id, 0);
  await client.export(id, 0, "musicxml", "score.musicxml"); await client.export(id, 0, "midi", "score.mid");
  assert.deepEqual(calls.map((call) => call.action), ["jobs/import", "notes/get", "files/export", "files/export"]);
  assert.ok(calls.every((call) => call.payload.expectedUserId === id));
  assert.deepEqual(calls.slice(2).map((call) => call.payload.kind), ["musicxml", "midi"]);
});

test("switching accounts while CSRF is loading prevents the old selected file from being uploaded", async () => {
  let resolve!: (response: Response) => void;
  const waiting = new Promise<Response>((yes) => { resolve = yes; });
  const paths: string[] = [];
  const client = new CloudClient(async (path) => { paths.push(String(path)); return waiting; }, () => false);
  client.useAccount(id);
  const upload = client.upload(new Blob(["A's score"]), "score.png");
  client.useAccount("22222222-2222-4222-8222-222222222222");
  resolve(new Response(JSON.stringify({ authenticated: true, csrf: "old-csrf" })));
  await assert.rejects(upload, (error) => error instanceof CloudError && error.code === "identity_changed");
  assert.deepEqual(paths, ["/api/session"], "the POST must not use a new account's cookie with an old file");
});

test("logout or a same-user new session rejects the previous native picker result", async () => {
  for (const sameUser of [false, true]) {
    let resolve!: (value: unknown) => void;
    const result = new Promise<unknown>((yes) => { resolve = yes; });
    const client = new CloudClient(async () => { throw new Error("unused"); }, () => true,
      async <T>() => await result as T);
    client.useAccount(id);
    const importing = client.importNative();
    if (sameUser) client.resetSession(); else client.useAccount(null);
    resolve(job);
    await assert.rejects(importing, (error) => error instanceof CloudError && error.code === "identity_changed");
  }
});

test("an account switch during response body reading cannot install the previous cloud result", async () => {
  let release!: (value: unknown) => void;
  const body = new Promise<unknown>((yes) => { release = yes; });
  const response = { ok: true, json: () => body } as Response;
  const client = new CloudClient(async () => response, () => false);
  client.useAccount(id);
  const reading = client.job(id);
  await Promise.resolve();
  client.useAccount(null); release(job);
  await assert.rejects(reading, (error) => error instanceof CloudError && error.code === "identity_changed");
});

test("a delayed old-account 401 body cannot clear the new account's upload session", async () => {
  let release!: (value: unknown) => void;
  const oldBody = new Promise<unknown>((yes) => { release = yes; });
  const second = "22222222-2222-4222-8222-222222222222";
  let sessions = 0;
  const client = new CloudClient(async (path, init = {}) => {
    if (String(path) === `/api/jobs/${id}`) return { ok: false, status: 401, json: () => oldBody } as Response;
    if (String(path) === "/api/session") { sessions++; return new Response(JSON.stringify({ authenticated: true, csrf: "new-account-csrf" })); }
    assert.equal(new Headers(init.headers).get("X-NoteLite-Expected-User"), second);
    assert.equal(new Headers(init.headers).get("X-NoteLite-CSRF"), "new-account-csrf");
    return new Response(JSON.stringify(job));
  }, () => false);
  client.useAccount(id);
  const stale = client.job(id); await Promise.resolve();
  client.useAccount(second);
  await client.upload(new Blob(["B's first score"]), "first.png");
  release({ error: "expired" });
  await assert.rejects(stale, (error) => error instanceof CloudError && error.code === "identity_changed");
  await client.upload(new Blob(["B's second score"]), "second.png");
  assert.equal(sessions, 1, "an old 401 may not erase the newer session's CSRF");
});

test("a lost write response is marked unknown so the UI must reload before another edit", async () => {
  const { client } = mock({ "GET /api/session": { authenticated: true, csrf: "c" }, [`PUT /api/jobs/${id}/score?score=0`]: () => { throw new Error("connection lost"); } });
  await assert.rejects(client.put(id, 0, 1, "<score-partwise/>"), (error) => error instanceof CloudError && error.code === "write_status_unknown" && errorMessage(error).includes("重新载入"));
});

test("gateway 5xx responses after a write require a reload, preserving their actual HTTP status", async () => {
  for (const status of [500, 502, 503, 504]) {
    const { client } = mock({ "GET /api/session": { authenticated: true, csrf: "c" }, [`PATCH /api/jobs/${id}/notes?score=0`]: () => new Response(JSON.stringify({ error: "upstream error" }), { status }) });
    await assert.rejects(client.patch(id, 0, 1, [{ partId: "P1", measureIndex: 0, noteIndex: 0, rest: true }]), (error) => error instanceof CloudError && error.status === status && error.code === "write_status_unknown");
  }
});

test("the network timeout covers body reading after response headers", async () => {
  const fetcher = async (_path: string | URL | Request, init: RequestInit = {}) => new Response(new ReadableStream({
    start(controller) { init.signal!.addEventListener("abort", () => controller.error(new DOMException("aborted", "AbortError")), { once: true }); },
  }));
  const client = new CloudClient(fetcher as typeof fetch, () => false, nativeRequest, { read: 10, write: 20 });
  await assert.rejects(client.score(id, 0), (error) => error instanceof CloudError && error.code === "network");
});

test("restored cloud originals can be read without a cached local upload", async () => {
  const { client, calls } = mock({ [`GET /api/jobs/${id}/original?score=0`]: () => new Response("%PDF-1.7", { headers: { "Content-Type": "application/pdf" } }) });
  const blob = await client.original(id, 0, "original.pdf");
  assert.equal(blob?.type, "application/pdf"); assert.equal(await blob?.text(), "%PDF-1.7"); assert.equal(calls.length, 1);
});

test("invalid task identifiers, movements and revisions never reach the network", async () => {
  const { client, calls } = mock({});
  await assert.rejects(client.job("../other-owner")); await assert.rejects(client.notes(id, -1));
  await assert.rejects(client.patch(id, 0, 0, [])); await assert.rejects(client.put(id, 0, NaN, "xml"));
  assert.equal(calls.length, 0);
});

test("empty or oversized uploads are rejected before sending", async () => {
  const { client, calls } = mock({});
  await assert.rejects(client.upload(new Blob([]), "empty.pdf"));
  await assert.rejects(client.upload(new Blob([new Uint8Array(32 * 1024 * 1024 + 1)]), "large.pdf"), (error) => error instanceof CloudError && error.status === 413);
  assert.equal(calls.length, 0);
});

test("XML and notes use the selected movement and accept uncompressed XML text", async () => {
  const { client, calls } = mock({ [`GET /api/jobs/${id}/score/musicxml?score=2`]: () => new Response("<score-partwise/>"), [`GET /api/jobs/${id}/notes?score=2`]: { jobId: id, revision: 2, score: 2, parts: [], notes: [] } });
  assert.equal(await client.score(id, 2), "<score-partwise/>");
  assert.equal((await client.notes(id, 2)).score, 2); assert.equal(calls.length, 2);
});

test("native requests preserve actions, selected score, revisions and export filenames", async () => {
  const calls: { action: string; payload: unknown; timeout?: number }[] = [];
  const bridge = async <T>(action: string, payload: unknown = {}, timeout?: number): Promise<T> => { calls.push({ action, payload, timeout }); return job as T; };
  const client = new CloudClient(async () => { throw new Error("native must not use browser fetch"); }, () => true, bridge);
  await client.pair("connection-code", "iPad"); await client.patch(id, 2, 9, [{ partId: "P1", measureIndex: 1, noteIndex: 0, delete: true }]);
  await client.export(id, 2, "original", "original.pdf");
  assert.equal(calls[0].action, "device/pair");
  assert.deepEqual(calls[1].payload, { jobId: id, score: 2, revision: 9, edits: [{ partId: "P1", measureIndex: 1, noteIndex: 0, delete: true }] });
  assert.deepEqual(calls[2].payload, { jobId: id, score: 2, kind: "original", filename: "original.pdf" });
  assert.equal(calls[1].timeout, 300000);
});

test("native bridge resolves callbacks and propagates native failures", async () => {
  const saved = globalThis.window;
  globalThis.window = { webkit: { messageHandlers: { noteLiteCloud: { postMessage(message) {
    const reply = message.action === "health" ? { ok: true as const, result: { status: "ok" } } : { ok: false as const, error: { code: "cancelled", message: "cancelled", status: 499 } };
    queueMicrotask(() => window.NoteLiteCloudNative!.resolve(message.requestId, reply));
  } } } } } as Window & typeof globalThis;
  try { assert.deepEqual(await nativeRequest("health"), { status: "ok" }); await assert.rejects(nativeRequest("jobs/import"), (error) => error instanceof CloudError && error.code === "cancelled" && error.status === 499); }
  finally { globalThis.window = saved; }
});

test("closing a workspace cancels a pending native file preview", async () => {
  const saved = globalThis.window; const messages: { action: string; payload: unknown }[] = [];
  globalThis.window = { webkit: { messageHandlers: { noteLiteCloud: { postMessage(message) { messages.push(message); } } } } } as Window & typeof globalThis;
  try {
    const request = nativeRequest("files/view", { jobId: id });
    const rejected = assert.rejects(request, (error) => error instanceof CloudError && error.code === "cancelled");
    cancelNativeFileRequests(); await rejected;
    assert.equal(messages[1].action, "request/cancel"); assert.ok((messages[1].payload as { targetRequestId: string }).targetRequestId);
  } finally { globalThis.window = saved; }
});

test("HTTPS configuration rejects insecure URLs and credential-bearing URLs", async () => {
  const client = new CloudClient(async () => { throw new Error("unused"); }, () => true, async <T>() => ({} as T));
  for (const address of ["http://124.221.211.156", "https://user:secret@example.com", "https://example.com/api", "https://example.com/?secret=x"]) await assert.rejects(client.configure(address));
  await client.configure("https://124.221.211.156");
});

test("explicit development proxy allows only the current loopback origin, then reaches pairing", async () => {
  const saved = globalThis.window; globalThis.window = { location: { origin: "http://localhost:8891" } } as Window & typeof globalThis;
  try {
    const { client, calls } = mock({ "GET /api/session": () => new Response(JSON.stringify({ error: "not paired" }), { status: 401 }), "POST /api/pair": { csrf: "paired-csrf" } }, () => true);
    const initial = await client.configuration();
    assert.equal(initial.baseURL, "http://localhost:8891"); assert.equal(initial.hasCredentials, false);
    await client.configure(initial.baseURL); await client.pair("one-time-code", "Browser");
    assert.equal(calls[1].path, "/api/pair"); assert.equal(calls[1].init.credentials, "same-origin");
    await assert.rejects(client.configure("http://127.0.0.1:8891"));
    await assert.rejects(client.configure("https://124.221.211.156"));
  } finally { globalThis.window = saved; }
});

test("HTTP loopback is rejected without the development proxy flag, including production", async () => {
  const saved = globalThis.window; globalThis.window = { location: { origin: "http://localhost:8891" } } as Window & typeof globalThis;
  try {
    await assert.rejects(mock({}, () => false).client.configure("http://localhost:8891"), /显式启用开发代理/);
    await assert.rejects(mock({}).client.configure("http://localhost:8891"), /显式启用开发代理/);
    const native = new CloudClient(async () => { throw new Error("unused"); }, () => true, nativeRequest, { read: 30, write: 30 }, () => true);
    await assert.rejects(native.configure("http://localhost:8891"), /原生设备需要 HTTPS/);
  } finally { globalThis.window = saved; }
});

test("development flag cannot permit a non-loopback HTTP site; same-origin HTTPS remains valid", async () => {
  const saved = globalThis.window;
  try {
    globalThis.window = { location: { origin: "http://example.com" } } as Window & typeof globalThis;
    await assert.rejects(mock({}, () => true).client.configure("http://example.com"));
    globalThis.window = { location: { origin: "https://124.221.211.156" } } as Window & typeof globalThis;
    await mock({}, () => false).client.configure("https://124.221.211.156");
    await assert.rejects(mock({}, () => true).client.configure("https://other.example.com"));
  } finally { globalThis.window = saved; }
});

test("UUID fallback works in the custom WebView scheme without randomUUID", () => {
  const original = crypto.randomUUID; Object.defineProperty(crypto, "randomUUID", { value: undefined, configurable: true });
  try { assert.match(createUUID(), /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/); }
  finally { Object.defineProperty(crypto, "randomUUID", { value: original, configurable: true }); }
});
