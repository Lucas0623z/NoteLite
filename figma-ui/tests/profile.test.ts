import test from "node:test";
import assert from "node:assert/strict";
import { AccountClient } from "../src/app/account.ts";
import { AccountProfileStore } from "../src/app/profile-store.ts";
import { CloudError, downloadBlob } from "../src/app/cloud.ts";
import { exportOwnerLocalData, savePersonalDataExport } from "../src/app/profile-export.ts";
import { defaultPreferences, mergePreferences, validateAccountProfile, validateProfileChanges, type AccountProfile, type ProfileChanges } from "../src/app/profile-model.ts";
import { profileStorageKey, purgeProfileStorage } from "../src/app/profile-storage.ts";
import { purgeDeletedAccountData } from "../src/app/account-local-data.ts";
const A = "11111111-1111-4111-8111-111111111111", B = "22222222-2222-4222-8222-222222222222";
const session = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", session2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const identity = (userId = A, sessionId = session) => ({ authenticated: true as const, userId, username: "tester", sessionId, deviceName: "test", expiresAt: "2026-11-01T00:00:00Z", kind: "browser" as const });
class MemoryStorage implements Storage {
  values = new Map<string, string>();
  get length() { return this.values.size; }
  key(index: number) { return [...this.values.keys()][index] || null; }
  getItem(key: string) { return this.values.get(key) ?? null; }
  setItem(key: string, value: string) { this.values.set(key, value); }
  removeItem(key: string) { this.values.delete(key); }
  clear() { this.values.clear(); }
}
const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value));
const envelope = (owner = A, revision = 0, changes: ProfileChanges = {}): AccountProfile => ({ userId: owner, revision, etag: `"profile-${revision}"`, updatedAt: revision ? "2026-10-12T10:00:00Z" : null, preferences: mergePreferences(defaultPreferences(), changes) });
class TestAPI {
  current: ReturnType<typeof identity> | null = identity();
  profiles = new Map([[A, envelope(A)], [B, envelope(B)]]);
  writes: { owner: string; etag: string; changes: ProfileChanges; requestId: string }[] = [];
  receipts = new Map<string, AccountProfile>();
  offline = false;
  unavailable = false;
  loseAcknowledgement = false;
  beforeWrite?: () => Promise<void>;
  async profile() { if (this.offline) throw new CloudError("offline"); if (this.unavailable) throw new CloudError("not deployed", 404); return copy(this.profiles.get(this.current!.userId)!); }
  async updateProfile(etag: string, changes: ProfileChanges, requestId: string) {
    const owner = this.current!.userId;
    this.writes.push({ owner, etag, changes: copy(changes), requestId });
    if (this.offline) throw new CloudError("unknown", undefined, "write_status_unknown");
    if (this.unavailable) throw new CloudError("not deployed", 404);
    if (this.beforeWrite) await this.beforeWrite();
    const key = `${owner}|${requestId}`, receipt = this.receipts.get(key);
    if (receipt) return copy(receipt);
    const old = this.profiles.get(owner)!;
    if (old.etag !== etag) throw new CloudError("conflict", 412);
    const result = envelope(owner, old.revision + 1, mergePreferences(old.preferences, changes));
    this.profiles.set(owner, result); this.receipts.set(key, result);
    if (this.loseAcknowledgement) { this.loseAcknowledgement = false; throw new CloudError("unknown", undefined, "write_status_unknown"); }
    return copy(result);
  }
}
const setup = (api = new TestAPI(), storage = new MemoryStorage()) => {
  let counter = 1;
  return { api, storage, store: new AccountProfileStore(api, storage, () => `cccccccc-cccc-4ccc-8ccc-${String(counter++).padStart(12, "0")}`) };
};
const patch = (store: AccountProfileStore, changes: ProfileChanges) => store.patch(changes, store.getSnapshot().scope);
test("new device restores all actual account preferences, never unowned legacy values", async () => {
  const { api, storage, store } = setup();
  storage.setItem("music-display-name", "unowned"); storage.setItem("sheet-music-theme", "dark");
  api.profiles.set(A, envelope(A, 3, { displayName: "自己的名字", avatar: "custom", avatarImage: "data:image/png;base64,aGVsbG8=", email: "owner@example.invalid", phone: "123", selectedCourse: "铜管-上低音号", theme: "light", options: { "通知-每日练琴提醒": true } }));
  await store.bind(api.current);
  assert.deepEqual(store.getSnapshot().preferences, api.profiles.get(A)!.preferences);
  assert.equal(store.getSnapshot().status, "synced"); assert.equal(api.writes.length, 0);
});
test("legacy values migrate only into the separate guest namespace", async () => {
  const { api, storage, store } = setup(); storage.setItem("music-display-name", "guest-name");
  await store.bind(null); assert.equal(store.getSnapshot().preferences.displayName, "guest-name");
  patch(store, { theme: "dark" });
  await store.bind(api.current); assert.equal(store.getSnapshot().preferences.displayName, "名字"); assert.equal(store.getSnapshot().preferences.theme, "light");
  await store.bind(null); assert.equal(store.getSnapshot().preferences.theme, "dark"); assert.equal(api.writes.length, 0);
});
test("late A cloud read is fenced when UI switches to B", async () => {
  const api = new TestAPI(), storage = new MemoryStorage(); let resolve: (value: AccountProfile) => void = () => {};
  const read = new Promise<AccountProfile>(done => { resolve = done; });
  api.profile = async () => api.current!.userId === A ? read : copy(api.profiles.get(B)!);
  const { store } = setup(api, storage); const old = store.bind(api.current);
  const oldScope = store.getSnapshot().scope;
  api.current = identity(B); await store.bind(api.current);
  resolve(envelope(A, 9, { email: "A-private@example.invalid" })); await old;
  assert.equal(store.getSnapshot().owner, B); assert.equal(store.getSnapshot().preferences.email, "");
  assert.throws(() => store.patch({ displayName: "A-value" }, oldScope), /账户已切换/);
  assert.equal(storage.getItem(profileStorageKey(A)), null);
});
test("offline dirty settings survive close and reopen, then sync only the original owner", async () => {
  const { api, storage, store } = setup(); await store.bind(api.current); api.offline = true;
  patch(store, { displayName: "离线修改", theme: "dark" }); await store.sync();
  assert.equal(store.getSnapshot().status, "pending");
  const reopened = new AccountProfileStore(api, storage); await reopened.bind(api.current);
  assert.equal(reopened.getSnapshot().preferences.displayName, "离线修改");
  api.current = identity(B); await reopened.bind(api.current); assert.equal(reopened.getSnapshot().preferences.displayName, "名字");
  api.current = identity(A); api.offline = false; await reopened.bind(api.current);
  assert.equal(api.profiles.get(A)!.preferences.displayName, "离线修改"); assert.equal(api.profiles.get(B)!.preferences.theme, "light");
  assert.equal(reopened.getSnapshot().status, "synced");
});
test("unknown write is replayed with identical request ID, ETag and changes across reopen", async () => {
  const { api, storage, store } = setup(); await store.bind(api.current);
  patch(store, { displayName: "只写一次" }); api.loseAcknowledgement = true; await store.sync();
  assert.equal(store.getSnapshot().status, "pending"); assert.equal(api.profiles.get(A)!.revision, 1);
  const reopened = new AccountProfileStore(api, storage); await reopened.bind(api.current);
  assert.deepEqual(api.writes[1], api.writes[0]); assert.equal(api.profiles.get(A)!.revision, 1);
  assert.equal(reopened.getSnapshot().preferences.displayName, "只写一次");
});
test("uncertain receipt replay restores later other-device fields before claiming synced", async () => {
  const { api, storage, store } = setup(); await store.bind(api.current);
  patch(store, { displayName: "one write" }); api.loseAcknowledgement = true; await store.sync();
  api.profiles.set(A, envelope(A, 2, { displayName: "one write", theme: "dark", options: { "未来开关": true } }));
  const reopened = new AccountProfileStore(api, storage); await reopened.bind(api.current);
  assert.deepEqual(api.writes[1], api.writes[0]); assert.equal(api.profiles.get(A)!.revision, 2);
  assert.equal(reopened.getSnapshot().preferences.theme, "dark"); assert.equal(reopened.getSnapshot().preferences.options["未来开关"], true);
  assert.equal(reopened.getSnapshot().status, "synced");
});
test("412 merges only locally dirty fields and option keys into current remote revision", async () => {
  const { api, store } = setup(); await store.bind(api.current);
  patch(store, { displayName: "本机名字", options: { "音效": false } });
  let conflicted = false;
  api.beforeWrite = async () => { if (!conflicted) { conflicted = true; api.profiles.set(A, envelope(A, 4, { email: "other-device@example.invalid", theme: "dark", options: { "触觉反馈": false, "音效": true } })); } };
  await store.sync(); const prefs = store.getSnapshot().preferences;
  assert.equal(prefs.displayName, "本机名字"); assert.equal(prefs.email, "other-device@example.invalid"); assert.equal(prefs.theme, "dark");
  assert.deepEqual(prefs.options, { "触觉反馈": false, "音效": false });
  assert.equal(api.writes.length, 2); assert.notEqual(api.writes[0].requestId, api.writes[1].requestId);
  assert.equal(api.writes[1].etag, '"profile-4"'); assert.deepEqual(api.writes[1].changes, { displayName: "本机名字", options: { "音效": false } });
});
test("edits made while a PUT is in flight form a separate durable batch", async () => {
  const { api, store } = setup(); await store.bind(api.current); patch(store, { displayName: "first" });
  let release: () => void = () => {}; let entered: () => void = () => {};
  const ready = new Promise<void>(done => { entered = done; }), waiting = new Promise<void>(done => { release = done; });
  api.beforeWrite = async () => { entered(); await waiting; };
  const syncing = store.sync(); await ready; patch(store, { displayName: "second", phone: "456" }); release(); await syncing;
  assert.equal(api.writes.length, 2); assert.equal(api.profiles.get(A)!.preferences.displayName, "second");
  assert.equal(api.profiles.get(A)!.preferences.phone, "456"); assert.equal(store.getSnapshot().status, "synced");
});
test("session switch fences an old acknowledgement and safely replays owner outbox", async () => {
  const { api, storage, store } = setup(); await store.bind(api.current); patch(store, { phone: "789" });
  let release: () => void = () => {}, entered: () => void = () => {};
  const ready = new Promise<void>(done => { entered = done; }), wait = new Promise<void>(done => { release = done; });
  api.beforeWrite = async () => { entered(); await wait; };
  const old = store.sync(); await ready; const oldScope = store.getSnapshot().scope;
  api.current = identity(A, session2); const newBind = store.bind(api.current); release(); await Promise.all([old, newBind]);
  assert.equal(store.getSnapshot().preferences.phone, "789"); assert.equal(api.profiles.get(A)!.revision, 1);
  assert.throws(() => store.patch({ theme: "dark" }, oldScope), /账户已切换/);
  assert.equal(JSON.parse(storage.getItem(profileStorageKey(A))!).pending, null);
});
test("old server 404 explicitly stays local/pending and restores after endpoint deployment", async () => {
  const { api, store } = setup(); api.unavailable = true; await store.bind(api.current);
  assert.equal(store.getSnapshot().status, "unavailable"); patch(store, { selectedCourse: "木管-长笛" }); await store.sync();
  assert.equal(store.getSnapshot().status, "unavailable"); assert.match(store.getSnapshot().message, /本机.*待更新/);
  api.unavailable = false; await store.sync(); assert.equal(store.getSnapshot().status, "synced");
  assert.equal(api.profiles.get(A)!.preferences.selectedCourse, "木管-长笛");
});
test("a failed durable local write cannot show the changed value as saved", async () => {
  const { api, storage, store } = setup(); await store.bind(api.current);
  storage.setItem = () => { throw new Error("quota"); };
  assert.throws(() => patch(store, { displayName: "not durable" }), /quota/);
  assert.equal(store.getSnapshot().preferences.displayName, "名字"); assert.equal(api.writes.length, 0); assert.equal(store.getSnapshot().status, "error");
});
test("profile cleanup removes only the deleted owner cache/outbox across origins", () => {
  const storage = new MemoryStorage();
  for (const origin of ["https://124.221.211.156", "https://fixture.invalid"]) storage.setItem(profileStorageKey(A, origin), "A-private-and-outbox");
  storage.setItem(profileStorageKey(B), "B-private"); storage.setItem(profileStorageKey("guest"), "guest-private"); storage.setItem("music-avatar", "portrait");
  purgeProfileStorage(A, storage);
  assert.equal(storage.length, 3); assert.equal(storage.getItem(profileStorageKey(B)), "B-private"); assert.equal(storage.getItem(profileStorageKey("guest")), "guest-private");
});
test("deletion fence rejects late profile writers rather than recreating erased owner data", async () => {
  const owner = "dddddddd-dddd-4ddd-8ddd-dddddddddddd", api = new TestAPI(), storage = new MemoryStorage();
  api.current = identity(owner); api.profiles.set(owner, envelope(owner));
  const { store } = setup(api, storage); await store.bind(api.current); await purgeDeletedAccountData(owner);
  assert.throws(() => patch(store, { displayName: "late" }), /账户已切换/); assert.equal(api.writes.length, 0);
});
test("malformed cloud preferences and foreign owner cannot replace valid local data", async () => {
  const { api, store } = setup(); await store.bind(api.current);
  api.profile = async () => envelope(B, 99, { displayName: "foreign" }); await store.sync();
  assert.equal(store.getSnapshot().preferences.displayName, "名字"); assert.equal(store.getSnapshot().status, "error");
  assert.throws(() => validateAccountProfile({ ...envelope(), preferences: { displayName: "incomplete" } }, A));
  for (const invalid of [{ theme: "auto" }, { avatar: ["mascot"] }, { avatarImage: "https://external.invalid/photo" }, { options: { unknown: "wrong" } }, { selectedCourse: "fake" }, { phone: "1".repeat(41) }, { ownedOutfit: "locked" }]) assert.throws(() => validateProfileChanges(invalid));
  assert.equal(validateAccountProfile(envelope(A, 1, { avatar: "custom", avatarImage: null }), A).preferences.avatarImage, null);
  assert.equal(validateAccountProfile(envelope(A, 1, { avatar: "mascot", avatarImage: "data:image/png;base64,aGVsbG8=" }), A).preferences.avatar, "mascot");
});
test("profile SDK uses same-origin account auth, expected owner, If-Match and exact request ID", async () => {
  const calls: { path: string; init: RequestInit }[] = [];
  const client = new AccountClient(async (path, init = {}) => { calls.push({ path: String(path), init }); return new Response(JSON.stringify(String(path).endsWith("/me") ? { ...identity(), csrf: "safe-fixture" } : envelope(A, 1))); }, () => false, undefined, () => {});
  await client.me(); await client.profile(); await client.updateProfile('"profile-0"', { theme: "dark" }, A);
  const write = calls[2], headers = new Headers(write.init.headers);
  assert.equal(write.path, "/api/account/profile"); assert.equal(headers.get("If-Match"), '"profile-0"'); assert.equal(headers.get("X-NoteLite-Expected-User"), A); assert.equal(headers.get("X-NoteLite-CSRF"), "safe-fixture");
  assert.deepEqual(JSON.parse(write.init.body as string), { requestId: A, changes: { theme: "dark" } }); assert.equal(headers.has("Authorization"), false);
});
test("native profile and account export use structured account requests with owner guard", async () => {
  const calls: { action: string; payload: any }[] = [];
  const client = new AccountClient(() => { throw new Error("browser forbidden"); }, () => true, (async (action, payload) => {
    calls.push({ action, payload }); return payload.path === "/me" ? { ...identity(), kind: "native" } : payload.path === "/account/export" ? { user: { id: A }, profile: { userId: A }, scores: [], history: [] } : envelope(A, payload.method === "PUT" ? 1 : 0);
  }) as never, () => {});
  await client.me(); await client.profile(); await client.updateProfile('"profile-0"', { email: "personal@example.invalid" }, B); await client.exportData();
  assert.deepEqual(calls.slice(1).map(call => [call.action, call.payload.path, call.payload.expectedUserId]), [["account/request", "/profile", A], ["account/request", "/profile", A], ["account/request", "/account/export", A]]);
  assert.equal(calls[2].payload.etag, '"profile-0"');
});
test("SDK cannot return former profile/export after account or session changed during read", async () => {
  for (const endpoint of ["/profile", "/account/export"]) {
    let release: (response: Response) => void = () => {}, current = identity();
    const wait = new Promise<Response>(done => { release = done; });
    const client = new AccountClient(async path => String(path).endsWith("/me") ? new Response(JSON.stringify(current)) : wait, () => false, undefined, () => {});
    await client.me(); const old = endpoint === "/profile" ? client.profile() : client.exportData();
    current = identity(B, session2); await client.me(); release(new Response(JSON.stringify(endpoint === "/profile" ? envelope(A) : { userId: A })));
    await assert.rejects(old, /账户已切换/);
  }
});
test("guest export includes exact guest score bytes and history, excluding all account rows", async () => {
  const storage = new MemoryStorage(); storage.setItem(profileStorageKey("guest"), JSON.stringify({ version: 1, owner: "guest", guest: defaultPreferences() }));
  const read = async (_name: string, store: string) => store === "scores" ? [{ id: "guest-1", file: new Blob(["<score-partwise/>"], { type: "application/xml" }) }, { id: "guest-2", owner: "guest", removed: true }, { id: "private", owner: A, file: new Blob(["private XML"]) }] : [{ eventId: "guest-event", userId: "guest", sync: "local" }, { eventId: "private-event", userId: A }];
  const value = await exportOwnerLocalData("guest", () => true, read, storage);
  const scores = value.localScores as any[];
  assert.equal(scores.length, 2); assert.equal(atob(scores[0].file.base64), "<score-partwise/>"); assert.equal(scores[1].removed, true);
  assert.deepEqual(value.localPracticeRecords, [{ eventId: "guest-event", userId: "guest", sync: "local" }]);
  assert.equal(JSON.stringify(value).includes("private"), false);
});
test("owner export retains unsynced practice/profile changes and rejects a delayed read after switch", async () => {
  const { api, storage, store } = setup(); await store.bind(api.current); patch(store, { displayName: "pending-local" });
  const read = async (_name: string, kind: string) => kind === "scores" ? [{ id: "mine", owner: A }, { id: "theirs", owner: B }] : [{ eventId: "unsynced", userId: A, sync: "pending", pendingAnalysis: { requestId: "local" } }, { eventId: "other", userId: B }];
  const result = await exportOwnerLocalData(A, () => true, read, storage);
  assert.equal((result.localPracticeRecords as any[])[0].sync, "pending");
  assert.equal((result.localProfileState as any).dirty.displayName, "pending-local"); assert.equal(JSON.stringify(result).includes("theirs"), false);
  let current = true;
  await assert.rejects(exportOwnerLocalData(A, () => current, async () => { current = false; return []; }, storage), /账户已切换/);
});
test("personal JSON download carries expected identity, keeps guest separate and rejects oversized exports", async () => {
  const calls: any[] = [], download = async (blob: Blob, filename: string, scope: any) => { calls.push({ filename, scope, data: JSON.parse(await blob.text()) }); };
  await savePersonalDataExport({ localPending: ["actual"] }, identity(), () => true, download);
  assert.equal(calls[0].scope.expectedUserId, A); assert.equal(calls[0].scope.expectedSessionId, session); assert.deepEqual(calls[0].data, { localPending: ["actual"] });
  await savePersonalDataExport({ guest: true }, null, () => true, download); assert.equal(calls[1].scope.expectedUserId, "guest"); assert.equal(calls[1].scope.expectedSessionId, null); assert.equal(calls[1].scope.isCurrent(), true);
  await assert.rejects(savePersonalDataExport({ data: "x".repeat(16 * 1024 * 1024) }, identity(), () => true, download), /16 MiB/);
  assert.equal(calls.length, 2);
});
test("actual native save bridge rejects a switched owner during Blob conversion and forwards identity", async () => {
  const saved = globalThis.window; const calls: any[] = [];
  globalThis.window = { webkit: { messageHandlers: { noteLiteCloud: { postMessage(message: any) { calls.push(message); queueMicrotask(() => window.NoteLiteCloudNative!.resolve(message.requestId, { ok: true, result: {} })); } } } } } as Window & typeof globalThis;
  try {
    await downloadBlob(new Blob(["mine"]), "data.json", { expectedUserId: A, expectedSessionId: session, isCurrent: () => true });
    assert.equal(calls[0].payload.expectedUserId, A); assert.equal(calls[0].payload.expectedSessionId, session);
    let current = true; const blob = new Blob(["private-old"]); blob.arrayBuffer = async () => { current = false; return new ArrayBuffer(0); };
    await assert.rejects(downloadBlob(blob, "old.json", { expectedUserId: A, expectedSessionId: session, isCurrent: () => current }), /账户已切换/);
    assert.equal(calls.length, 1);
    await downloadBlob(new Blob(["guest"]), "guest.json", { isCurrent: () => true }); assert.equal(calls[1].payload.expectedUserId, undefined);
    await downloadBlob(new Blob(["scoped-guest"]), "guest.json", { expectedUserId: "guest", expectedSessionId: null, isCurrent: () => true }); assert.equal(calls[2].payload.expectedUserId, "guest"); assert.equal(calls[2].payload.expectedSessionId, null);
  } finally { globalThis.window = saved; }
});
test("account export rejects a foreign or ownerless successful response", async () => {
  for (const data of [{ user: { id: B }, profile: { userId: B } }, { scores: [] }]) {
    const client = new AccountClient(async path => new Response(JSON.stringify(String(path).endsWith("/me") ? identity() : data)), () => false, undefined, () => {});
    await client.me(); await assert.rejects(client.exportData(), /归属无效/);
  }
});
