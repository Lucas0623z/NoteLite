import { CloudError, type CloudJob, type NoteListing } from "./cloud.ts";

export type SavedScore = { jobId: string; score: number; revision: number; kind: "notes" | "xml" };
export type RemoteSnapshot = { job: CloudJob; score: number; listing: NoteListing; musicxml: string };
export type RemoteLoadResult = { kind: "loaded"; snapshot: RemoteSnapshot } | { kind: "superseded" } | { kind: "failed"; error: unknown; saved?: SavedScore };
type Transport = { job: (id: string) => Promise<CloudJob>; notes: (id: string, score: number) => Promise<NoteListing>; score: (id: string, score: number) => Promise<string> };
type Callbacks = { loading: () => void; loaded: (snapshot: RemoteSnapshot, saved?: SavedScore) => void; failed: (error: unknown, saved?: SavedScore) => void };

/** Only the newest, internally consistent read may install a score or change its recovery state. */
export class RemoteScoreLoader {
  private generation = 0;
  private active = true;
  private installed?: { jobId: string; score: number; revision: number };
  private saved?: SavedScore;
  private transport: Transport;
  private callbacks: Callbacks;
  constructor(transport: Transport, callbacks: Callbacks) { this.transport = transport; this.callbacks = callbacks; }
  activate() { this.active = true; this.generation++; }
  deactivate() { this.active = false; this.generation++; }
  invalidate() { this.generation++; }
  isInstalled(job: CloudJob, score: number): boolean { return this.installed?.jobId === job.id && this.installed.score === score && this.installed.revision >= job.revision; }
  private savedFor(jobId: string, score: number) { return this.saved?.jobId === jobId && this.saved.score === score ? this.saved : undefined; }

  async save(write: () => Promise<CloudJob>, score: number, kind: SavedScore["kind"]): Promise<{ job: CloudJob; load: RemoteLoadResult }> {
    const job = await write();
    // A successful write response is authoritative even if the following GETs fail.
    this.saved = { jobId: job.id, score, revision: job.revision, kind };
    return { job, load: await this.load(job, score) };
  }

  async load(target: CloudJob, score: number): Promise<RemoteLoadResult> {
    if (!this.active) return { kind: "superseded" };
    const ticket = ++this.generation;
    const current = () => this.active && ticket === this.generation;
    this.callbacks.loading();
    try {
      for (let attempt = 0; attempt < 3; attempt++) {
        const before = await this.transport.job(target.id);
        if (!current()) return { kind: "superseded" };
        const listing = await this.transport.notes(target.id, score);
        if (!current()) return { kind: "superseded" };
        const musicxml = await this.transport.score(target.id, score);
        if (!current()) return { kind: "superseded" };
        const after = await this.transport.job(target.id);
        if (!current()) return { kind: "superseded" };
        const saved = this.savedFor(target.id, score);
        if (before.revision !== listing.revision || after.revision !== listing.revision || listing.revision < Math.max(target.revision, saved?.revision ?? 0)) continue;
        const snapshot = { job: after, score, listing, musicxml };
        this.callbacks.loaded(snapshot, saved);
        this.installed = { jobId: target.id, score, revision: listing.revision };
        if (saved) this.saved = undefined;
        return { kind: "loaded", snapshot };
      }
      throw new CloudError("曲谱正在更新，请重新载入最新版本。", 409);
    } catch (error) {
      if (!current()) return { kind: "superseded" };
      const saved = this.savedFor(target.id, score);
      this.callbacks.failed(error, saved);
      return { kind: "failed", error, saved };
    }
  }
}
