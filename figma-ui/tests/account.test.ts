import test from "node:test";
import assert from "node:assert/strict";
import { AccountClient } from "../src/app/account.ts";
import { CloudError } from "../src/app/cloud.ts";

const owner = "11111111-1111-4111-8111-111111111111";
const identity = { authenticated: true, userId: owner, username: "tester", sessionId: owner, deviceName: "Browser", expiresAt: "2026-11-01T00:00:00Z", kind: "browser" };
test("browser account writes use same-origin cookie, CSRF and expected owner; never a Bearer token", async () => {
  const calls: { path: string; init: RequestInit }[] = [];
  const client = new AccountClient(async (path, init = {}) => { calls.push({ path: String(path), init }); return new Response(JSON.stringify(String(path).endsWith("/me") ? { ...identity, csrf: "proof" } : { id: owner, etag: '"1"' })); }, () => false, undefined, () => {});
  await client.me(); await client.createScore("练习", "<score-partwise/>", owner);
  const headers = new Headers(calls[1].init.headers);
  assert.equal(headers.get("X-NoteLite-CSRF"), "proof"); assert.equal(headers.get("X-NoteLite-Expected-User"), owner);
  assert.equal(headers.has("Authorization"), false); assert.equal(calls[1].init.credentials, "same-origin");
  assert.equal(JSON.parse(calls[1].init.body as string).requestId, owner);
  assert.equal(Object.hasOwn(client.current!, "csrf"), false);
});
test("native account requests stay structured and public identity never retains a returned token", async () => {
  const calls: unknown[] = [];
  const bridge = async (action: string, payload: unknown) => { calls.push({ action, payload }); return { ...identity, kind: "native", token: "must-not-persist" }; };
  const client = new AccountClient(() => { throw new Error("Browser fetch forbidden"); }, () => true, bridge as never, () => {});
  await client.authenticate("login", "tester", "example-not-a-real-password"); await client.history();
  assert.equal(Object.hasOwn(client.current!, "token"), false);
  assert.deepEqual(calls[1], { action: "account/request", payload: { path: "/history?limit=200", method: "GET", response: "json", expectedUserId: owner } });
});
test("an expired account clears its identity; an unavailable service is reported instead of empty success", async () => {
  let status = 200;
  const client = new AccountClient(async () => new Response(JSON.stringify(status === 200 ? identity : { error: "unavailable" }), { status }), () => false, undefined, () => {});
  await client.me(); status = 401; assert.equal(await client.me(), null); assert.equal(client.current, null);
  status = 503; await assert.rejects(client.me(), (error) => error instanceof CloudError && error.status === 503);
});
test("personal score saves carry the actual version and cannot turn a conflict into a successful overwrite", async () => {
  const writes: Headers[] = [];
  const client = new AccountClient(async (path, init = {}) => {
    if (String(path).endsWith("/me")) return new Response(JSON.stringify({ ...identity, csrf: "proof" }));
    writes.push(new Headers(init.headers)); return new Response(JSON.stringify({ error: "Changed on another device" }), { status: 409 });
  }, () => false, undefined, () => {});
  await assert.rejects(client.updateScore({ id: owner, title: "曲谱", revision: 2, updatedAt: "", etag: '"snapshot:2"' }, "<score-partwise/>"), (error) => error instanceof CloudError && error.status === 409);
  assert.equal(writes.length, 1); assert.equal(writes[0].get("If-Match"), '"snapshot:2"');
});

test("a late identity or expired response cannot overwrite a newer login", async () => {
  const other = { ...identity, userId: "22222222-2222-4222-8222-222222222222", username: "new-account" };
  let completeOld: (value: Response) => void = () => {};
  const oldResponse = new Promise<Response>((resolve) => { completeOld = resolve; });
  const client = new AccountClient(async (path) => String(path).endsWith("/me") ? oldResponse : new Response(JSON.stringify({ ...other, csrf: "new-proof" })), () => false, undefined, () => {});
  const oldMe = client.me();
  await client.authenticate("login", other.username, "example-not-a-real-password");
  completeOld(new Response(JSON.stringify({ error: "Expired" }), { status: 401 }));
  assert.equal((await oldMe)?.userId, other.userId);
  assert.equal(client.current?.userId, other.userId);
});

test("a write waiting for session discovery is stopped when the account changes", async () => {
  let completeOld: (value: Response) => void = () => {};
  const oldResponse = new Promise<Response>((resolve) => { completeOld = resolve; });
  const calls: string[] = [];
  const other = { ...identity, userId: "22222222-2222-4222-8222-222222222222" };
  const client = new AccountClient(async (path) => {
    calls.push(String(path));
    return String(path).endsWith("/me") ? oldResponse : new Response(JSON.stringify({ ...other, csrf: "new-proof" }));
  }, () => false, undefined, () => {});
  const oldWrite = client.createScore("原账户谱子", "<score-partwise/>");
  const rejection = assert.rejects(oldWrite, (error) => error instanceof CloudError && error.status === 409);
  await client.authenticate("login", "new-account", "example-not-a-real-password");
  completeOld(new Response(JSON.stringify({ ...identity, csrf: "old-proof" })));
  await rejection;
  assert.equal(calls.some((path) => path.endsWith("/scores")), false);
  assert.equal(client.current?.userId, other.userId);
});

test("analysis retains its request identity and uses only the authenticated account route", async () => {
  const calls: { path: string; init: RequestInit }[] = [];
  const client = new AccountClient(async (path, init = {}) => {
    calls.push({ path: String(path), init });
    return new Response(JSON.stringify(String(path).endsWith("/me") ? { ...identity, csrf: "proof" } : { generationStatus: "fallback" }));
  }, () => false, undefined, () => {});
  await client.me();
  await client.analyzePractice([owner], owner);
  assert.equal(calls[1].path, "/api/account/practice-analysis");
  assert.deepEqual(JSON.parse(calls[1].init.body as string), { requestId: owner, eventIds: [owner] });
  assert.equal(new Headers(calls[1].init.headers).get("X-NoteLite-Expected-User"), owner);
});
