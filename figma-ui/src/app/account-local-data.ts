/** Account deletion fences late IndexedDB writers without removing another owner or guest. */
import { purgeProfileStorage } from "./profile-storage.ts";
const OWNERS = "deletedOwners";
const DELETED_KEY = "notelite-deleted-account-owners-v1";
const ownerID = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
const deletedOwners = new Set<string>();
try {
  const saved: unknown = typeof localStorage === "undefined" ? [] : JSON.parse(localStorage.getItem(DELETED_KEY) || "[]");
  if (Array.isArray(saved)) for (const value of saved) if (typeof value === "string" && ownerID.test(value)) deletedOwners.add(value);
} catch { /* IndexedDB contains the durable write fence when localStorage is unavailable. */ }
export const isDeletedAccountOwner = (owner: string) => owner !== "guest" && deletedOwners.has(owner);
export function openOwnedDatabase(name: string, store: string, keyPath: string): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(name, 2);
    let blocked = false;
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(store)) db.createObjectStore(store, { keyPath });
      if (!db.objectStoreNames.contains(OWNERS)) db.createObjectStore(OWNERS);
    };
    request.onsuccess = () => { if (blocked) { request.result.close(); return; } request.result.onversionchange = () => request.result.close(); resolve(request.result); };
    request.onerror = () => reject(request.error);
    request.onblocked = () => { blocked = true; reject(new Error("请关闭其他旧版应用窗口，再重试清理本机账户资料。")); };
  });
}
export const ownedStores = (store: string) => [store, OWNERS];
export function guardAccountWrite(transaction: IDBTransaction, owner: string, write: () => void): void {
  if (isDeletedAccountOwner(owner)) { transaction.abort(); return; }
  const request = transaction.objectStore(OWNERS).get(owner);
  request.onsuccess = () => { if (request.result === true || isDeletedAccountOwner(owner)) transaction.abort(); else write(); };
}
async function purgeDatabase(name: string, store: string, keyPath: string, owner: string, field: string): Promise<void> {
  const db = await openOwnedDatabase(name, store, keyPath);
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(ownedStores(store), "readwrite");
    transaction.objectStore(OWNERS).put(true, owner);
    const cursor = transaction.objectStore(store).openCursor();
    cursor.onsuccess = () => {
      const value = cursor.result;
      if (!value) return;
      if (value.value[field] === owner) value.delete();
      value.continue();
    };
    transaction.oncomplete = () => { db.close(); resolve(); };
    transaction.onabort = transaction.onerror = () => { db.close(); reject(transaction.error || new Error("本机账户资料清理待重试。")); };
  });
}
export async function purgeDeletedAccountData(owner: string): Promise<void> {
  if (!ownerID.test(owner)) throw new Error("注销账户标识无效。");
  deletedOwners.add(owner);
  try { if (typeof localStorage !== "undefined") localStorage.setItem(DELETED_KEY, JSON.stringify([...deletedOwners])); } catch { /* Each database also persists its own owner tombstone. */ }
  // Profile cache and its durable outbox belong to this exact account only.
  purgeProfileStorage(owner);
  if (typeof indexedDB === "undefined") return;
  await Promise.all([
    purgeDatabase("notelite-practice-records", "records", "eventId", owner, "userId"),
    purgeDatabase("heibaikey-scores", "scores", "id", owner, "owner"),
  ]);
}
if (typeof indexedDB !== "undefined") {
  for (const owner of deletedOwners) void purgeDeletedAccountData(owner).catch(() => { /* Retried on next launch, and the owner cannot write again. */ });
}
