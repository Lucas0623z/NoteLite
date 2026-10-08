import test from "node:test";
import assert from "node:assert/strict";
import ts from "typescript";
import JSZip from "jszip";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
const require = createRequire(import.meta.url);
const zipURL = pathToFileURL(require.resolve("jszip")).href;
const source = readFileSync(new URL("../src/app/cloud.ts", import.meta.url), "utf8").replace('from "jszip"', `from ${JSON.stringify(zipURL)}`);
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { checkedJob, validArtifact, validateScore, boundedDownload } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

test("real bridge protocol uses state and validates all four task states", () => {
  for (const state of ["queued", "running", "succeeded", "failed"]) {
    const fixture = { id: "3133998d-5346-4a08-b715-86a3fcc8b7bf", filename: "score.png", state, error: null, artifacts: [] };
    assert.deepEqual(checkedJob(fixture), fixture);
  }
  assert.throws(() => checkedJob({ id: "3133998d-5346-4a08-b715-86a3fcc8b7bf", status: "running" }), /格式无效/);
  assert.throws(() => checkedJob({ id: "../../jobs", state: "queued" }), /格式无效/);
});
test("result filenames cannot leave their task directory", () => {
  assert.equal(validArtifact("score.mxl"), true); assert.equal(validArtifact("score.musicxml"), true);
  for (const name of ["../score.mxl", "folder/score.xml", "folder\\score.xml", "score.pdf", "score\n.xml"]) assert.equal(validArtifact(name), false);
});
test("MXL without a container is rejected consistently with practice renderer", async () => {
  const zip = new JSZip(); zip.file("score.musicxml", "<score-partwise><part><measure><note/></measure></part></score-partwise>");
  await assert.rejects(validateScore(await zip.generateAsync({ type: "arraybuffer" })), /container.xml/);
});
test("download cap is enforced for declared and streaming sizes", async () => {
  await assert.rejects(boundedDownload(new Response("1234", { headers: { "Content-Length": "4" } }), 3), /允许大小/);
  await assert.rejects(boundedDownload(new Response("1234"), 3), /允许大小/);
  assert.equal((await boundedDownload(new Response("123"), 3)).byteLength, 3);
});
