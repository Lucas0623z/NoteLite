/** Local-only UI acceptance fixture. It never contacts an account or OMR server. */
import { createServer } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const fixture = `
import React from "react";
import { createRoot } from "react-dom/client";
import App from "/src/app/App.tsx";
import "/src/index.css";
const scenario = new URL(location.href).searchParams.get("scenario") || "empty";
const RealDate = Date;
const now = new RealDate(2026, 9, 12, 12).getTime();
class FixtureDate extends RealDate {
  constructor(...args) { super(...(args.length ? args : [now])); }
  static now() { return now; }
}
window.Date = FixtureDate;
const identity = {authenticated:true,userId:"11111111-1111-4111-8111-111111111111",sessionId:"22222222-2222-4222-8222-222222222222",username:"Synthetic practice",deviceName:"Local fixture",kind:"browser",expiresAt:"2030-01-01T00:00:00Z",csrf:"local-only"};
let profile = {userId:identity.userId,revision:0,etag:'"profile-0"',updatedAt:null,preferences:{displayName:"验收账户",avatar:"mascot",avatarImage:null,email:"",phone:"",selectedCourse:null,theme:"light",options:{}}};
function event(index, day, mode="free") {
  return {eventId:"00000000-0000-4000-8000-"+String(index).padStart(12,"0"),sourceKind:"personal",scoreId:"33333333-3333-4333-8333-333333333333",mode,durationSeconds:60,startedAt:new RealDate(2026,9,day,10).toISOString(),endedAt:new RealDate(2026,9,day,10,1).toISOString()};
}
let events = [];
if (scenario === "actual") events = [event(1,11),event(2,10),event(3,10),event(4,8)];
if (scenario === "dense") events = [...Array.from({length:201},(_,index)=>event(index+1,12)),event(202,11),event(203,10)];
if (scenario === "playback") events = [event(1,11,"playback"),event(2,10,"playback")];
window.fetch = async (path, options={}) => {
  const url = new URL(String(path), location.href);
  if (url.origin !== location.origin || !url.pathname.startsWith("/api/account/")) throw new Error("Network confined to the local practice fixture");
  let value = {}, status = 200;
  if (url.pathname.endsWith("/me")) value = identity;
  else if (url.pathname.endsWith("/profile")) {
    if (options.method === "PUT") { const {changes} = JSON.parse(options.body); profile = {...profile,revision:profile.revision+1,etag:'"profile-'+(profile.revision+1)+'"',updatedAt:new RealDate(now).toISOString(),preferences:{...profile.preferences,...changes,options:{...profile.preferences.options,...changes.options}}}; }
    value = profile;
  }
  else if (url.pathname.endsWith("/history")) {
    if (scenario === "error") { status = 503; value = {error:"本地验收：历史读取失败"}; }
    else { const offset = Number(url.searchParams.get("cursor") || 0); value = {events:events.slice(offset,offset+200),nextCursor:offset+200<events.length?String(offset+200):null}; }
  } else if (url.pathname.endsWith("/scores")) value = {scores:[],nextCursor:null};
  else if (url.pathname.endsWith("/catalog")) value = {scores:[]};
  else if (url.pathname.endsWith("/classrooms")) value = {classrooms:[]};
  else if (url.pathname.endsWith("/sessions")) value = {sessions:[]};
  else { status=404; value={error:"No fixture for this local-only request"}; }
  return new Response(JSON.stringify(value),{status,headers:{"Content-Type":"application/json"}});
};
createRoot(document.getElementById("root")).render(React.createElement(App));
`;
const server = await createServer({
  root, configFile:false, plugins:[react(),tailwindcss(),{
    name:"isolated-streak-preview",
    resolveId(id) { if (id === "/__streak_fixture.js") return "\0isolated-streak-preview"; },
    load(id) { if (id === "\0isolated-streak-preview") return fixture; },
    configureServer(vite) { vite.middlewares.use(async (request,response,next) => {
      if (request.url?.split("?")[0] !== "/__streak_test") return next();
      response.setHeader("Content-Type","text/html");
      response.end(await vite.transformIndexHtml("/__streak_test",'<!doctype html><html lang="zh"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>连胜统计本地验收 · 合成记录</title></head><body><div id="root"></div><script type="module" src="/__streak_fixture.js"></script></body></html>'));
    }); }
  }], server:{host:"127.0.0.1",port:8892,strictPort:true},logLevel:"error"
});
await server.listen();
console.log("Local-only streak acceptance: http://127.0.0.1:8892/__streak_test?scenario=empty");
