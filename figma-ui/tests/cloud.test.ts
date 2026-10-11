import test from "node:test";
import assert from "node:assert/strict";
import { cancelNativeFileRequests, CloudClient, CloudError, createUUID, errorMessage, nativeRequest } from "../src/app/cloud.ts";

const id = "11111111-1111-4111-8111-111111111111";
const job = { id, filename: "练习.pdf", state: "succeeded", revision: 2, scores: [], artifacts: {} };
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

test("authorization failures surface an actionable connection message", async () => {
  const { client } = mock({ "GET /api/jobs": () => new Response(JSON.stringify({ error: "unauthorized" }), { status: 401 }) });
  await assert.rejects(client.jobs(), (error) => error instanceof CloudError && errorMessage(error).includes("云端识谱设置"));
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
