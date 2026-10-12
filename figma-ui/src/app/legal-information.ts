import { isNativeCloud, nativeRequest } from "./cloud.ts";

export const LEGAL_RESEARCH_URL = "https://github.com/Lucas0623z/NoteLite/blob/codex/notewise-fusion-research/docs/NOTEWISE_ENGINE_RESEARCH.md";
export type LegalInformation = { sourceCommit: string; sourceArchiveURL: string; researchURL: string; license: string; notice: string };

function decode(value: unknown): LegalInformation {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("软件许可资料格式无效。");
  const entry = value as Record<string, unknown>;
  const names = ["sourceCommit", "sourceArchiveURL", "researchURL", "license", "notice"];
  if (Object.keys(entry).length !== names.length || names.some((name) => typeof entry[name] !== "string")) throw new Error("软件许可资料格式无效。");
  const result = entry as LegalInformation;
  if (!/^[a-f0-9]{40}$/.test(result.sourceCommit) || result.sourceArchiveURL !== `https://github.com/Lucas0623z/NoteLite/archive/${result.sourceCommit}.tar.gz` || result.researchURL !== LEGAL_RESEARCH_URL || !result.license || !result.notice || new TextEncoder().encode(result.license).length > 64 * 1024 || new TextEncoder().encode(result.notice).length > 16 * 1024) throw new Error("软件许可资料格式无效。");
  return result;
}

/** Read public installed resources only; browser preview does not make a network request. */
export async function installedLegalInformation(native: () => boolean = isNativeCloud, bridge: typeof nativeRequest = nativeRequest): Promise<LegalInformation | null> {
  if (!native()) return null;
  return decode(await bridge<unknown>("legal/information", {}, 10000));
}
