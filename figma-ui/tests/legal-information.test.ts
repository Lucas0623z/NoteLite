import test from "node:test";
import assert from "node:assert/strict";
import { installedLegalInformation, LEGAL_RESEARCH_URL } from "../src/app/legal-information.ts";
import type { nativeRequest } from "../src/app/cloud.ts";

const commit = "a".repeat(40);
const valid = { sourceCommit: commit, sourceArchiveURL: `https://github.com/Lucas0623z/NoteLite/archive/${commit}.tar.gz`, researchURL: LEGAL_RESEARCH_URL, license: "synthetic public license", notice: "synthetic public notice" };
const response = (value: unknown) => (async () => value) as typeof nativeRequest;

test("browser legal fallback requires no login, file reader or network call", async () => {
  assert.equal(LEGAL_RESEARCH_URL, "https://github.com/Lucas0623z/NoteLite/blob/codex/notewise-fusion-research/docs/NOTEWISE_ENGINE_RESEARCH.md");
  let requests = 0;
  const result = await installedLegalInformation(() => false, (async () => { requests++; throw new Error("must not call"); }) as typeof nativeRequest);
  assert.equal(result, null); assert.equal(requests, 0);
});

test("installed legal information uses only the empty public route and returns this version's exact source", async () => {
  const calls: unknown[][] = [];
  const bridge = (async (...args: unknown[]) => { calls.push(args); return valid; }) as typeof nativeRequest;
  assert.deepEqual(await installedLegalInformation(() => true, bridge), valid);
  assert.deepEqual(calls, [["legal/information", {}, 10000]]);
});

test("malformed, oversized, private-extra and nonexact public-source replies are rejected", async () => {
  for (const value of [null, [], {}, { ...valid, token: "must not expose" }, { ...valid, sourceCommit: "main" },
      { ...valid, sourceArchiveURL: "https://124.221.211.156/private" }, { ...valid, sourceArchiveURL: "https://github.com/Lucas0623z/NoteLite/archive/main.tar.gz" },
      { ...valid, researchURL: "https://example.invalid" }, { ...valid, researchURL: "https://github.com/Lucas0623z/NoteLite/blob/main/docs/NOTEWISE_ENGINE_RESEARCH.md" },
      { ...valid, license: "中".repeat(22000) }, { ...valid, notice: "x".repeat(16 * 1024 + 1) }, { ...valid, notice: "" }]) {
    await assert.rejects(installedLegalInformation(() => true, response(value)), /软件许可资料格式无效/);
  }
});

test("an unavailable bundle is reported without inventing a source commit or falling back to user storage", async () => {
  await assert.rejects(installedLegalInformation(() => true, (async () => { throw new Error("bundled resource missing"); }) as typeof nativeRequest), /bundled resource missing/);
});
