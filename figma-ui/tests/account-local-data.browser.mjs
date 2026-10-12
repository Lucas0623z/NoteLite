/** Real browser IndexedDB acceptance; uses a fresh isolated browser profile. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.NOTELITE_PLAYWRIGHT_MODULE || "playwright");
const ts = require("typescript");
const source = await readFile(new URL("../src/app/account-local-data.ts", import.meta.url), "utf8");
const code = ts.transpile(source, { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 });
const server = createServer((request, response) => {
  response.setHeader("Content-Type", request.url === "/helper.js" ? "text/javascript" : "text/html");
  response.end(request.url === "/helper.js" ? code : "<!doctype html><title>Isolated IndexedDB deletion test</title>");
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
let browser;
try {
  browser = await chromium.launch({ headless: true, ...(process.env.NOTELITE_BROWSER_EXECUTABLE ? { executablePath: process.env.NOTELITE_BROWSER_EXECUTABLE } : {}) });
  const context = await browser.newContext();
  const pages = [await context.newPage(), await context.newPage()];
  const url = "http://127.0.0.1:" + server.address().port;
  const owner = "77777777-7777-4777-8777-777777777777", other = "88888888-8888-4888-8888-888888888888";
  for (const page of pages) await page.goto(url);
  await pages[0].evaluate(async ({ owner, other }) => {
    for (const [name, store, key, field] of [["notelite-practice-records", "records", "eventId", "userId"], ["heibaikey-scores", "scores", "id", "owner"]]) {
      const db = await new Promise((resolve, reject) => { const request = indexedDB.open(name, 1); request.onupgradeneeded = () => request.result.createObjectStore(store, { keyPath: key }); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
      await new Promise((resolve, reject) => { const tx = db.transaction(store, "readwrite"); for (const value of [owner, other, "guest"]) tx.objectStore(store).put({ [key]: value, [field]: value, privateContent: "synthetic-only" }); tx.oncomplete = resolve; tx.onabort = reject; });
      db.close();
    }
  }, { owner, other });
  // Import in the second tab before deletion: its memory cannot know the deleted
  // UUID. The shared IndexedDB owner tombstone must fence its late writer.
  await pages[1].evaluate(async () => { window.helper = await import("/helper.js"); });
  await pages[0].evaluate(async (owner) => { const helper = await import("/helper.js"); await helper.purgeDeletedAccountData(owner); }, owner);
  const late = await pages[1].evaluate(async (owner) => {
    const db = await window.helper.openOwnedDatabase("notelite-practice-records", "records", "eventId");
    return new Promise((resolve) => { const tx = db.transaction(window.helper.ownedStores("records"), "readwrite"); window.helper.guardAccountWrite(tx, owner, () => tx.objectStore("records").put({ eventId: "late", userId: owner })); tx.oncomplete = () => { db.close(); resolve("incorrectly-written"); }; tx.onabort = () => { db.close(); resolve("blocked"); }; });
  }, owner);
  assert.equal(late, "blocked");
  async function inventory(page) {
    return page.evaluate(async () => {
      const helper = await import("/helper.js"), values = {};
      for (const [name, store, key, field] of [["notelite-practice-records", "records", "eventId", "userId"], ["heibaikey-scores", "scores", "id", "owner"]]) {
        const db = await helper.openOwnedDatabase(name, store, key);
        values[name] = await new Promise((resolve, reject) => { const tx = db.transaction(store, "readonly"), request = tx.objectStore(store).getAll(); tx.oncomplete = () => { db.close(); resolve(request.result.map((row) => row[field]).sort()); }; tx.onabort = reject; });
      }
      return values;
    });
  }
  const expected = { "notelite-practice-records": [other, "guest"].sort(), "heibaikey-scores": [other, "guest"].sort() };
  assert.deepEqual(await inventory(pages[0]), expected);
  await pages[0].reload();
  assert.deepEqual(await inventory(pages[0]), expected);
  await pages[0].evaluate(async (owner) => { const helper = await import("/helper.js"); await helper.purgeDeletedAccountData(owner); }, owner);
  assert.deepEqual(await inventory(pages[0]), expected);
  console.log(JSON.stringify({ engine: "actual Chromium IndexedDB", migratedFromVersion: 1, schemaVersion: 2, deletedOwnerRows: 0, guestAndOtherOwnerPreserved: true, lateCrossTabWrite: "blocked", reloadAndRetry: "passed" }));
} finally {
  if (browser) await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
