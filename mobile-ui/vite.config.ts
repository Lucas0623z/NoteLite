import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { readFileSync, writeFileSync } from "node:fs";
import { Script } from "node:vm";

const bridgeToken = process.env.NOTELITE_BRIDGE_TOKEN;
const bridgeOrigin = process.env.NOTELITE_BRIDGE_ORIGIN || "http://127.0.0.1:8765";
const bridgeURL = new URL(bridgeOrigin);
if (!["127.0.0.1", "localhost", "[::1]"].includes(bridgeURL.hostname)) throw new Error("Preview OMR proxy must target loopback.");

export default defineConfig({
  base: "./",
  experimental: { renderBuiltUrl(filename, { hostType }) { return hostType === "js" ? { runtime: `new URL(${JSON.stringify(filename)}, document.baseURI).href` } : { relative: true }; } },
  plugins: [react(), tailwindcss(), {
    name: "native-file-document",
    configureServer(server) { server.middlewares.use((req, res, next) => {
      if (!req.url?.startsWith("/omr/")) return next();
      const origin = req.headers.origin;
      if ((origin && origin !== `http://${req.headers.host}`) || req.headers["sec-fetch-site"] === "cross-site") { res.statusCode = 403; res.end("Cross-site OMR request denied."); return; }
      if (!bridgeToken) { res.statusCode = 503; res.setHeader("Content-Type", "application/json"); res.end(JSON.stringify({ error: "本机识谱联调服务尚未启动。" })); return; }
      next();
    }); },
    closeBundle() {
      const path = "dist/index.html"; const html = readFileSync(path, "utf8");
      const scripts = [...html.matchAll(/src="\.\/([^\"]+\.js)"/g)];
      for (const match of scripts) { const file = `dist/${match[1]}`; const source = `(() => {${readFileSync(file, "utf8")}\n})();`; try { new Script(source, { filename: file }); } catch { throw new Error("Native UI bundle is not a self-contained classic script."); } writeFileSync(file, source); }
      writeFileSync(path, html.replace(/ type="module"/g, " defer").replace(/ crossorigin(?:="[^"]*")?/g, ""));
    },
  }],
  build: { cssCodeSplit: false, rolldownOptions: { output: { codeSplitting: false } } },
  server: { host: "127.0.0.1", port: 5175, strictPort: true,
    proxy: bridgeToken ? { "/omr": { target: bridgeOrigin, rewrite: path => path.replace(/^\/omr/, ""), headers: { Authorization: `Bearer ${bridgeToken}` } } } : undefined,
  },
  preview: { host: "127.0.0.1", port: 5175, strictPort: true },
});
