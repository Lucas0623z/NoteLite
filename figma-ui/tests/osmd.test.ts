import test from "node:test";
import assert from "node:assert/strict";
import { resolveOSMDConstructor } from "../src/app/osmd.ts";

test("OSMD resolves Vite 8's UMD default export used by the actual browser prebundle", () => {
  class Constructor {}
  assert.equal(resolveOSMDConstructor({ default: { OpenSheetMusicDisplay: Constructor } }), Constructor);
});
test("OSMD also accepts an explicit named export", () => {
  class Constructor {}
  assert.equal(resolveOSMDConstructor({ OpenSheetMusicDisplay: Constructor }), Constructor);
});
test("an invalid OSMD module fails explicitly instead of reporting a rendered score", () => {
  for (const module of [null, {}, { default: {} }, { OpenSheetMusicDisplay: "invalid" }]) assert.throws(() => resolveOSMDConstructor(module), /未能加载/);
});
