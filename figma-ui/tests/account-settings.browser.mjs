/** Isolated real-browser UI regression. Synthetic responses; never a production account. */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import react from "@vitejs/plugin-react";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.NOTELITE_PLAYWRIGHT_MODULE || "playwright");
const root = fileURLToPath(new URL("../", import.meta.url));
const fixture = `
import React from "react";
import { createRoot } from "react-dom/client";
import AccountSettings from "/src/app/AccountSettings.tsx";
import { account } from "/src/app/account.ts";
const identity = {authenticated:true,userId:"11111111-1111-4111-8111-111111111111",sessionId:"22222222-2222-4222-8222-222222222222",username:"Lucas",deviceName:"Synthetic browser",kind:"browser",expiresAt:"2030-01-01T00:00:00Z"};
window.fixture = { scenario:"wrong-login", calls:[] };
window.fetch = async (path, init={}) => {
  window.fixture.calls.push({path:String(path),method:init.method});
  let result = identity, status = 200;
  if (String(path).endsWith("/login")) {
    if (window.fixture.scenario==="wrong-login") { status=401;result={error:"用户名或密码不正确。"}; }
    else { await new Promise(resolve=>setTimeout(resolve,30));result={...identity,csrf:"synthetic-proof"}; }
  } else if (String(path).endsWith("/register")) { status=409;result={error:"用户名已被使用。"}; }
  else if (String(path).endsWith("/logout")) result={authenticated:false};
  else if (String(path).endsWith("/account")) {
    if (window.fixture.scenario==="wrong-deletion") { status=403;result={error:"当前密码不正确，账户未注销。"}; }
    else result={authenticated:false,accountDeleted:true,deletionRequested:true,deleted:true,status:"completed"};
  } else result={...identity,csrf:"synthetic-proof"};
  return new Response(JSON.stringify(result),{status,headers:{"Content-Type":"application/json"}});
};
function Harness() {
  const [current,setCurrent]=React.useState(null);
  return React.createElement(AccountSettings,{identity:current,field:"field",action:"action",onReload:()=>setCurrent(account.current)});
}
createRoot(document.getElementById("root")).render(React.createElement(Harness));
`;
const server = await createServer({ root, configFile: false, plugins: [react(), {
  name: "isolated-account-fixture",
  resolveId(id) { if (id === "/__account_fixture.js") return "\0isolated-account-fixture"; },
  load(id) { if (id === "\0isolated-account-fixture") return fixture; },
  configureServer(vite) { vite.middlewares.use(async (request, response, next) => {
    if (request.url !== "/__account_test") return next();
    response.setHeader("Content-Type", "text/html");
    response.end(await vite.transformIndexHtml("/__account_test", '<!doctype html><title>Synthetic account UI regression</title><div id="root"></div><script type="module" src="/__account_fixture.js"></script>'));
  }); }
}], server: { host: "127.0.0.1", port: 0, strictPort: false }, logLevel: "error" });
let browser;
try {
  await server.listen();
  browser = await chromium.launch({ headless: true, ...(process.env.NOTELITE_BROWSER_EXECUTABLE ? { executablePath: process.env.NOTELITE_BROWSER_EXECUTABLE } : {}) });
  const context = await browser.newContext();
  // Network is confined to this isolated fixture, including any accidental request.
  const base = "http://127.0.0.1:" + server.httpServer.address().port;
  await context.route("**/*", route => route.request().url().startsWith(base + "/") ? route.continue() : route.abort());
  const page = await context.newPage();
  await page.goto(base + "/__account_test");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.getByRole("alert").filter({ hasText: "请输入用户名" }).waitFor();
  assert.equal(await page.evaluate(() => window.fixture.calls.length), 0);
  await page.getByLabel("账户用户名").fill("Lucas");
  await page.getByLabel("账户密码").fill("synthetic");
  assert.equal(await page.getByRole("button", { name: "登录", exact: true }).isEnabled(), true);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.getByRole("alert").filter({ hasText: "用户名或密码不正确" }).waitFor();
  assert.equal((await page.getByRole("alert").innerText()).includes("识谱"), false);
  await page.getByRole("button", { name: "注册新账户", exact: true }).click();
  await page.getByLabel("账户密码").fill("synthetic");
  await page.getByRole("button", { name: "创建账户", exact: true }).click();
  await page.getByRole("alert").filter({ hasText: "至少需要 15" }).waitFor();
  assert.equal(await page.evaluate(() => window.fixture.calls.length), 1);
  await page.getByLabel("账户密码").fill("synthetic sufficiently long");
  await page.getByRole("button", { name: "创建账户", exact: true }).click();
  await page.getByRole("alert").filter({ hasText: "用户名已被使用" }).waitFor();
  await page.getByRole("button", { name: "已有账户，返回登录", exact: true }).click();
  await page.getByLabel("账户密码").fill("synthetic");
  await page.evaluate(() => { window.fixture.scenario = "success"; const button = [...document.querySelectorAll("button")].find(value => value.textContent === "登录"); button.click(); button.click(); });
  await page.getByRole("button", { name: "退出登录", exact: true }).waitFor();
  assert.equal(await page.evaluate(() => window.fixture.calls.filter(value => value.path.endsWith("/login")).length), 2);
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await page.getByRole("status").filter({ hasText: "已退出当前设备" }).waitFor();
  await page.getByLabel("账户密码").fill("synthetic");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.getByRole("button", { name: "退出登录", exact: true }).waitFor();
  await page.getByText("永久注销账户", { exact: true }).click();
  await page.getByLabel("注销确认密码").fill("synthetic");
  await page.getByRole("button", { name: "继续注销", exact: true }).click();
  await page.getByRole("alertdialog", { name: "确认永久注销账户" }).waitFor();
  await page.evaluate(() => { window.fixture.scenario = "wrong-deletion"; });
  await page.getByRole("button", { name: "确认永久注销", exact: true }).click();
  await page.getByRole("alert").filter({ hasText: "当前密码不正确" }).waitFor();
  assert.equal(await page.getByRole("button", { name: "退出登录", exact: true }).isVisible(), true);
  await page.evaluate(() => { window.fixture.scenario = "success"; });
  await page.getByRole("button", { name: "确认永久注销", exact: true }).click();
  await page.getByRole("status").filter({ hasText: "账户及关联资料已永久注销" }).waitFor();
  assert.equal(await page.getByRole("button", { name: "登录", exact: true }).isVisible(), true);
  console.log(JSON.stringify({ engine: "actual browser; synthetic HTTP responses", shortLogin: "submitted", registrationPolicy: "15 Unicode characters", errors: "visible account-specific", doubleSubmit: "one call", logoutNotice: "retained", deletionConfirmation: "short existing credential accepted", wrongDeletion: "identity retained", deletedNotice: "retained" }));
} finally {
  if (browser) await browser.close();
  await server.close();
}
