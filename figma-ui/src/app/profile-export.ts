import { CloudError, downloadBlob } from "./cloud.ts";
import { openOwnedDatabase, isDeletedAccountOwner } from "./account-local-data.ts";
import { profileStorageKey } from "./profile-storage.ts";
import type { ProfileIdentity } from "./profile-store.ts";
const MAX_EXPORT = 16 * 1024 * 1024;
type LocalRow = Record<string, unknown>;
async function readLocalRows(name: string, store: string, keyPath: string): Promise<LocalRow[]> {
  const db = await openOwnedDatabase(name, store, keyPath);
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(store, "readonly"), request = transaction.objectStore(store).getAll();
    transaction.oncomplete = () => { db.close(); resolve(request.result as LocalRow[]); };
    transaction.onerror = transaction.onabort = () => { db.close(); reject(new Error("本机资料读取失败，导出尚未完成。")); };
  });
}
const base64 = (bytes: Uint8Array) => { const chunks: string[] = []; for (let index = 0; index < bytes.length; index += 32768) chunks.push(String.fromCharCode(...bytes.subarray(index, index + 32768))); return btoa(chunks.join("")); };
export async function exportOwnerLocalData(owner: string, isCurrent: () => boolean, read = readLocalRows, storage: Storage | undefined = typeof localStorage === "undefined" ? undefined : localStorage): Promise<Record<string, unknown>> {
  const guard = () => { if (!isCurrent() || isDeletedAccountOwner(owner)) throw new CloudError("账户已切换，已取消旧资料导出。", 409); };
  guard();
  const [scores, records] = await Promise.all([read("heibaikey-scores", "scores", "id"), read("notelite-practice-records", "records", "eventId")]); guard();
  const localScores: LocalRow[] = []; let fileBytes = 0;
  for (const value of scores.filter(row => (row.owner || "guest") === owner)) {
    const { file, ...metadata } = value;
    if (file instanceof Blob) {
      fileBytes += file.size;
      if (fileBytes > MAX_EXPORT) throw new Error("本机资料超过 16 MiB，请分别导出曲谱和练习记录。");
      const bytes = await file.arrayBuffer(); guard();
      localScores.push({ ...metadata, file: { mime: file.type, size: file.size, base64: base64(new Uint8Array(bytes)) } });
    } else localScores.push(metadata);
  }
  const raw = storage?.getItem(profileStorageKey(owner));
  const localProfileState = raw ? JSON.parse(raw) as { owner?: string; version?: number } : null;
  if (localProfileState && (localProfileState.owner !== owner || localProfileState.version !== 1)) throw new Error("本机个人设置归属无法核验，导出尚未完成。");
  guard();
  return { owner, localScores, localPracticeRecords: records.filter(row => row.userId === owner), localProfileState, note: "本机曲谱文件、练习记录原样保留各自同步状态，个人设置包含待同步队列；录音文件不包含在此 JSON 中。" };
}
export async function savePersonalDataExport(data: unknown, expected: ProfileIdentity | null, isCurrent: () => boolean, download = downloadBlob): Promise<void> {
  if (!isCurrent()) throw new CloudError("账户已切换，已取消旧资料导出。", 409);
  const text = JSON.stringify(data, null, 2), bytes = new TextEncoder().encode(text);
  if (bytes.length > MAX_EXPORT) throw new Error("个人数据导出超过 16 MiB，请分别导出曲谱和练习记录。");
  await download(new Blob([bytes], { type: "application/json" }), "黑白键-个人数据.json", expected ? { expectedUserId: expected.userId, expectedSessionId: expected.sessionId, isCurrent } : { expectedUserId: "guest", expectedSessionId: null, isCurrent });
  if (!isCurrent()) throw new CloudError("账户已切换，旧资料保存结果需在原账户核对。", 409);
}
