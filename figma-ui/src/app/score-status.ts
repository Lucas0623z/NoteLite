export type ScoreStatusVersion = { jobId?: string; score: number; revision: number; xml: string };

function sameVersion(left: ScoreStatusVersion | undefined, right: ScoreStatusVersion): boolean {
  return !!left && left.jobId === right.jobId && left.score === right.score && left.revision === right.revision && left.xml === right.xml;
}

/** Persisted operation feedback belongs to a score version, independently of its async layout. */
export class ScoreStatus {
  private version?: ScoreStatusVersion;
  private feedback = "";
  private layout = "正在载入曲谱…";
  private layoutError = "";
  private generation = 0;
  private readonly changed: (message: string) => void;
  constructor(changed: (message: string) => void) { this.changed = changed; }

  select(version: ScoreStatusVersion) {
    if (sameVersion(this.version, version)) return;
    this.version = version;
    this.feedback = "";
    this.layout = "正在载入曲谱…";
    this.layoutError = "";
    this.generation++;
    this.publish();
  }

  beginOperation() { this.feedback = ""; this.publish(); }

  report(message: string, version?: ScoreStatusVersion) {
    if (version) this.select(version);
    this.feedback = message;
    this.publish();
  }

  beginLayout(version: ScoreStatusVersion) {
    this.select(version);
    const generation = ++this.generation;
    this.layout = "正在排版曲谱…";
    // Keep an existing error visible until a retry actually renders successfully.
    this.publish();
    const current = () => generation === this.generation && sameVersion(this.version, version);
    return {
      ready: (message: string) => {
        if (!current()) return;
        this.layout = message;
        this.layoutError = "";
        this.publish();
      },
      failed: (message: string) => {
        if (!current()) return;
        this.layoutError = message;
        this.publish();
      },
    };
  }

  private publish() { this.changed(this.layoutError || this.feedback || this.layout); }
}
