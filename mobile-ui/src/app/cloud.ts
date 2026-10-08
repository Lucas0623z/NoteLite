import JSZip from "jszip";
export interface CloudJob { id: string; state: string; error?: string; artifacts?: { name: string }[]; }
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
export class CloudError extends Error { constructor(message: string, public status: number) { super(message); } }
export async function request(path: string, init: RequestInit = {}) {
  const response = await fetch(`/omr/v1/${path}`, { ...init, redirect: "error", cache: "no-store" });
  if (!response.ok) {
    const message = await response.json().then(body => String(body.error || "")).catch(() => "");
    throw new CloudError(message || `识谱服务请求失败（${response.status}）。请启动本机联调服务。`, response.status);
  }
  return response;
}
export function checkedJob(value: CloudJob): CloudJob { if (!uuid.test(value.id) || !["queued", "running", "succeeded", "failed"].includes(value.state)) throw new Error("云端任务格式无效。"); return value; }
export function validArtifact(name: string) { return name.length <= 255 && !/[\/\\\x00-\x1f\x7f]/.test(name) && /\.(musicxml|xml|mxl)$/i.test(name); }
export async function validateScore(bytes: ArrayBuffer) {
  if (bytes.byteLength === 0 || bytes.byteLength > 15 * 1024 * 1024) throw new Error("识谱结果为空或超过 15 MB。");
  let xml: string;
  const signature = new Uint8Array(bytes.slice(0, 4));
  if (signature[0] === 0x50 && signature[1] === 0x4b) {
    const archive = await JSZip.loadAsync(bytes);
    const files = Object.values(archive.files);
    if (files.length > 128) throw new Error("压缩乐谱包含过多文件。");
    let path = "";
    const container = archive.file("META-INF/container.xml");
    if (container) {
      const document = new DOMParser().parseFromString(await boundedText(container, 64 * 1024), "application/xml");
      path = document.querySelector("rootfile")?.getAttribute("full-path") || "";
    } else throw new Error("压缩乐谱缺少 META-INF/container.xml。");
    if (!path || path.startsWith("/") || path.split("/").includes("..")) throw new Error("压缩乐谱缺少有效的 MusicXML 根文件。");
    const file = archive.file(path);
    if (!file) throw new Error("压缩乐谱根文件不存在。");
    xml = await boundedText(file, 30 * 1024 * 1024);
  } else xml = new TextDecoder().decode(bytes);
  if (xml.length > 30 * 1024 * 1024 || /<!ENTITY/i.test(xml)) throw new Error("MusicXML 文件过大或包含不支持的实体。");
  const document = new DOMParser().parseFromString(xml, "application/xml");
  if (document.querySelector("parsererror") || document.documentElement.localName !== "score-partwise" || !document.querySelector("part measure note")) throw new Error("服务器没有返回可练习的 MusicXML 乐谱。");
}
function boundedText(file: JSZip.JSZipObject, limit: number) { return new Promise<string>((resolve, reject) => {
  let bytes = 0, text = "", failed = false; const decoder = new TextDecoder();
  // JSZip exposes this documented stream method, but its bundled typings omit it.
  const stream = (file as JSZip.JSZipObject & { internalStream(type: "uint8array"): JSZip.JSZipStreamHelper<Uint8Array> }).internalStream("uint8array");
  stream.on("data", chunk => {
    if (failed) return; bytes += chunk.byteLength;
    if (bytes > limit) { failed = true; stream.pause(); reject(new Error("解压后的乐谱超过允许大小。")); return; }
    text += decoder.decode(chunk, { stream: true });
  }).on("error", reject).on("end", () => { if (!failed) resolve(text + decoder.decode()); }).resume();
}); }
export async function boundedDownload(response: Response, limit = 15 * 1024 * 1024) {
  const declared = Number(response.headers.get("Content-Length"));
  if (declared > limit) throw new Error("识谱结果超过允许大小。");
  if (!response.body) throw new Error("识谱结果为空。");
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let bytes = 0;
  try { while (true) { const value = await reader.read(); if (value.done) break; bytes += value.value.byteLength; if (bytes > limit) throw new Error("识谱结果超过允许大小。"); chunks.push(value.value); } }
  finally { await reader.cancel(); }
  const result = new Uint8Array(bytes); let offset = 0; for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.byteLength; }
  return result.buffer;
}
export function delay(signal: AbortSignal) { return new Promise<void>((resolve, reject) => {
  const timer = window.setTimeout(() => { signal.removeEventListener("abort", cancel); resolve(); }, 1500);
  const cancel = () => { window.clearTimeout(timer); reject(new DOMException("已暂停", "AbortError")); };
  signal.addEventListener("abort", cancel, { once: true });
  if (signal.aborted) cancel();
}); }
