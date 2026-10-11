import { account, ACCOUNT_EVENT, type AccountClient, type PracticeEvent, type PracticeAnalysis } from "./account.ts";
import { openOwnedDatabase, ownedStores, guardAccountWrite, isDeletedAccountOwner } from "./account-local-data.ts";
import { createUUID } from "./cloud.ts";
import type { NoteWiseAnalysis } from "./notewise.ts";

export const PRACTICE_RECORD_EVENT = "notelite-practice-records-changed";
export type PracticeRecord = {
  eventId: string; userId: string; name: string; scoreIdentity: string; musicxml: string;
  sourceKind: "local" | "official" | "personal"; scoreId?: string; scoreRevision?: number;
  startedAt: string; endedAt: string; durationSeconds: number; mode: PracticeEvent["mode"];
  sync: "local" | "pending" | "synced"; interrupted?: boolean; error?: string; analysis?: PracticeAnalysis | NoteWiseAnalysis;
  scoreSha256?:string; analysisVersion?:number; latestAnalysisVersion?:number; analysisHash?:string;
  localAnalyses?:PracticeAnalysis[]; pendingAnalysis?:{requestId:string;parentVersion:number;sourceHash:string;analysis:NoteWiseAnalysis};
};
type RecordStore = { put: (record: PracticeRecord) => Promise<void>; getAll: () => Promise<PracticeRecord[]> };
async function recordsDB<T>(mode: IDBTransactionMode, operation: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const database = await openOwnedDatabase("notelite-practice-records", "records", "eventId");
  return new Promise<T>((resolve, reject) => {
    const transaction = database.transaction(ownedStores("records"), mode), request = operation(transaction.objectStore("records"));
    transaction.oncomplete = () => { database.close(); resolve(request.result); };
    transaction.onerror = transaction.onabort = () => { database.close(); reject(transaction.error || new Error("本机练习记录未能保存。")); };
  });
}
const storage: RecordStore = { put: async (record) => {
  const database = await openOwnedDatabase("notelite-practice-records", "records", "eventId");
  return new Promise<void>((resolve, reject) => {
    const transaction = database.transaction(ownedStores("records"), "readwrite");
    guardAccountWrite(transaction, record.userId, () => transaction.objectStore("records").put(record));
    transaction.oncomplete = () => { database.close(); resolve(); };
    transaction.onabort = transaction.onerror = () => { database.close(); reject(new Error("账户已注销，练习记录不再保存。")); };
  });
}, getAll: () => recordsDB("readonly", (store) => store.getAll()) };
type RecordAccount = Pick<AccountClient, "current" | "createScore" | "addHistory" | "history"> & Partial<Pick<AccountClient,"addHistoryAnalysis"|"historyAnalyses"|"historyAnalysis">>;

/** A queued record belongs to its original account, never the next account that logs in. */
export class PracticeRecords {
  private syncing = new Map<string, Promise<PracticeRecord>>();
  private store: RecordStore;
  private client: RecordAccount;
  private changed: () => void;
  constructor(store: RecordStore = storage, client: RecordAccount = account, changed: () => void = () => window.dispatchEvent(new Event(PRACTICE_RECORD_EVENT))) { this.store = store; this.client = client; this.changed = changed; }
  private async put(record: PracticeRecord): Promise<void> {
    if (isDeletedAccountOwner(record.userId)) throw new Error("账户已注销，练习记录不再保存。");
    await this.store.put(record);
  }
  async save(input: Omit<PracticeRecord, "userId" | "sync">, owner = this.client.current?.userId || "guest"): Promise<PracticeRecord> {
    if (!Number.isFinite(input.durationSeconds) || input.durationSeconds < 0 || input.durationSeconds > 86400) throw new Error("练习时长无效，记录未保存。");
    const record: PracticeRecord = { ...input, userId: owner, sync: owner === "guest" ? "local" : "pending" };
    await this.put(record); this.changed();
    return record;
  }
  async local(): Promise<PracticeRecord[]> {
    const owner = this.client.current?.userId || "guest";
    return (await this.store.getAll()).filter((record) => record.userId === owner).sort((left, right) => right.endedAt.localeCompare(left.endedAt));
  }
  async sync(record: PracticeRecord): Promise<PracticeRecord> {
    if (record.userId === "guest" || this.client.current?.userId !== record.userId) return record;
    if(record.sync==="synced")return record.pendingAnalysis?this.syncAnalysis(record):record;
    const previous = this.syncing.get(record.eventId); if (previous) return previous;
    const promise = this.performSync(record); this.syncing.set(record.eventId, promise);
    try { return await promise; } finally { this.syncing.delete(record.eventId); }
  }
  private async performSync(original: PracticeRecord): Promise<PracticeRecord> {
    let record = { ...original };
    try {
      if (!record.scoreId) {
        const earlier = (await this.store.getAll()).find((item) => item.userId === record.userId && item.scoreId && item.sourceKind === "personal" && item.scoreIdentity === record.scoreIdentity && item.musicxml === record.musicxml);
        if (earlier) { record = { ...record, sourceKind: "personal", scoreId: earlier.scoreId, scoreRevision: earlier.scoreRevision }; await this.put(record); }
      }
      if (!record.scoreId) {
        if (this.client.current?.userId !== record.userId) return record;
        // Store a snapshot of what was actually practiced. A later edited score must not rewrite history.
        const score = await this.client.createScore(record.name, record.musicxml, record.eventId);
        if (this.client.current?.userId !== record.userId) throw new Error("账户已切换，记录保留在原账户待同步。");
        record = { ...record, sourceKind: "personal", scoreId: score.id, scoreRevision: score.revision };
        await this.put(record);
      }
      if (this.client.current?.userId !== record.userId) return record;
      const result = await this.client.addHistory({ eventId: record.eventId, sourceKind: record.sourceKind === "official" ? "official" : "personal", scoreId: record.scoreId!, ...(record.scoreRevision ? { scoreRevision: record.scoreRevision } : {}), mode: record.mode, durationSeconds: record.durationSeconds, startedAt: record.startedAt, endedAt: record.endedAt, ...(record.analysis ? {analysis:record.analysis} : {}) });
      record = { ...record, analysis: result.event.analysis,scoreSha256:result.event.scoreSha256,analysisVersion:result.event.analysisVersion,latestAnalysisVersion:result.event.latestAnalysisVersion,analysisHash:result.event.analysisHash, sync: "synced", error: undefined };
    } catch (error) { record = { ...record, sync: "pending", error: error instanceof Error ? error.message : "记录待同步。" }; }
    await this.put(record); this.changed(); return record.sync==="synced"&&record.pendingAnalysis?this.syncAnalysis(record):record;
  }
  async reviseAnalysis(record:PracticeRecord,analysis:NoteWiseAnalysis):Promise<PracticeRecord>{
    if(record.userId!=="guest" && this.client.current?.userId!==record.userId)return record;
    const updated:PracticeRecord={...record,localAnalyses:[...(record.localAnalyses||[]),...(record.analysis?[structuredClone(record.analysis)]:[])].slice(-20),
      ...(record.userId==="guest"?{analysis}:{pendingAnalysis:{requestId:createUUID(),parentVersion:record.latestAnalysisVersion||record.analysisVersion||1,sourceHash:record.scoreSha256||analysis.sourceScoreSha256,analysis}})};
    await this.put(updated);this.changed();return updated.userId==="guest"?updated:this.syncAnalysis(updated);
  }
  private async syncAnalysis(record:PracticeRecord):Promise<PracticeRecord>{
    const pending=record.pendingAnalysis;
    if(!pending||record.sync!=="synced"||this.client.current?.userId!==record.userId||!this.client.addHistoryAnalysis)return record;
    try {
      const result=await this.client.addHistoryAnalysis(record.eventId,pending);
      if(this.client.current?.userId!==record.userId)return record;
      record={...record,analysis:result.analysis,analysisVersion:result.version,latestAnalysisVersion:result.version,analysisHash:result.analysisHash,pendingAnalysis:undefined,error:undefined};
    }catch(error){record={...record,error:`录后分析已保存在本机，追加版本待确认：${error instanceof Error?error.message:"连接失败"}`};}
    await this.put(record);this.changed();return record;
  }
  async retry(): Promise<void> { for (const record of await this.local()) if (record.sync === "pending"||record.pendingAnalysis) await this.sync(record); }
  async list(): Promise<PracticeRecord[]> {
    const owner = this.client.current?.userId, local = await this.local();
    if (!owner) return local;
    const values = new Map(local.map((record) => [record.eventId, record]));
    const { events } = await this.client.history();
    if (this.client.current?.userId !== owner) return [];
    for (const event of events) {
      const existing = values.get(event.eventId);
      values.set(event.eventId, { ...existing, ...event, userId: owner, name: existing?.name || (event.sourceKind === "official" ? "官方曲谱练习" : "个人曲谱练习"), musicxml: existing?.musicxml || "", scoreIdentity: existing?.scoreIdentity || event.scoreId, sync: "synced" });
    }
    return Array.from(values.values()).sort((left, right) => right.endedAt.localeCompare(left.endedAt));
  }
}
export const practiceRecords = new PracticeRecords();
export const newPracticeEventId = createUUID;
if (typeof window !== "undefined") {
  window.addEventListener("online", () => { void practiceRecords.retry(); });
  window.addEventListener(ACCOUNT_EVENT, () => { void practiceRecords.retry(); window.dispatchEvent(new Event(PRACTICE_RECORD_EVENT)); });
}
