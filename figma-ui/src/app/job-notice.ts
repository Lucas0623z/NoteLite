import type { CloudJob } from "./cloud.ts";

export type ScoreNotice = { text: string; jobId?: string };
type JobProgress = Pick<CloudJob, "id" | "state" | "recognitionMode" | "error">;

export function uploadedJobNotice(job: JobProgress): ScoreNotice {
  const imported = job.recognitionMode === "import";
  const text = job.state === "succeeded"
    ? `${imported ? "曲谱已导入" : "识谱已完成"}，可查看、校对并导出 MusicXML、MIDI。`
    : job.state === "failed"
      ? `识谱未完成。${job.error || "请检查原稿清晰度后重新导入。"}`
      : `曲谱正在${imported ? "导入" : "识别"}，完成后可查看、校对和导出。`;
  return { text, jobId: job.id };
}

export function completedJobNotice(current: ScoreNotice, job: JobProgress): ScoreNotice {
  // A poll owns only the notice from its upload, not later user actions or other jobs.
  if (current.jobId !== job.id || (job.state !== "succeeded" && job.state !== "failed")) return current;
  return uploadedJobNotice(job);
}
