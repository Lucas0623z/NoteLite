# NoteLite Figma 界面与云端识谱

本目录来自用户提供的 Figma Make 成品 `pixNf29vNFHLDrih3Xcikc`，2026-10-11 导出的版本 129。完整源文件的路径、大小与 SHA-256 见 `docs/figma-source-manifest.json`。原始 ZIP SHA-256 为 `b10fef42579d4bb0e318a2e4851535a90e41031f21ab4416ae84ede333e585fe`。

保留原版 App、练习页、主题、谱面布局、图片与 SVG。识谱功能在原来的“我的曲谱”“云端识谱设置”和“曲谱预览与校对”中接入，没有重画界面。唯一字体资源变更是将同一 Noto Sans SC 官方 WOFF2 改为随应用打包；字体 family、weight、display 和 unicode-range 保持一致，来源与哈希见 `docs/font-provenance.json`，许可见 `public/NotoSansSC-OFL.txt`。

## 本地构建

使用 Node 22.12 及以上，CI 与本地使用 pnpm 11.25.0。保留唯一的原始 Figma pnpm 锁文件；冻结安装，不升级依赖。

```sh
pnpm install --frozen-lockfile
pnpm typecheck
pnpm test
pnpm build
```

`dist` 使用相对资源路径，可由 Apple 应用的 `notelite-ui://app/index.html` 加载。Apple 资源准备脚本为 `apple/scripts/prepare-figma-ui.py`。OSMD 使用 SVG 排版；可选的原生 headless GL 插件无需运行安装脚本。

## 连接方式

原生应用通过 `noteLiteCloud` 消息桥调用上传、识谱、校对和导出。每个请求有独立 requestId；回调为 `window.NoteLiteCloudNative.resolve`。设备凭据由原生 Keychain 保存，不返回给网页。服务默认地址为 `https://124.221.211.156`，设置页可修改 HTTPS 地址并输入服务器提供的设备连接码。进入看谱或练习时通过原生方向接口切换横屏，退出时恢复进入前方向；浏览器保留 Figma 原有 fullscreen/orientation 与手动横屏提示。

浏览器使用当前页面的同源 `/api`，以 HttpOnly Secure SameSite cookie 连接，写操作携带由 `/api/session` 返回的 CSRF。浏览器不保存服务管理令牌，也不直接跨域请求另一台服务器。

根任务要求服务器只部署 OMR 与网关，完整 App 不上传服务器。需要本地浏览器预览时，可显式启用仅开发用的回环代理：

```powershell
$env:NOTELITE_DEV_GATEWAY='https://124.221.211.156'
pnpm dev
```

固定使用 `http://localhost:8891/`，不要混用 localhost 和 127.0.0.1。该代理仅在开发服务器生效，绑定回环，验证本地 Host、Origin 与 Sec-Fetch-Site 后才转发并改写远端 Origin；远端 HTTPS 证书验证保持开启，Set-Cookie 原样保留。生产构建不包含代理。若服务器证书或公网入口尚未启用，页面会显示连接失败，不会假称识谱成功。

## 已接入的曲谱流程

PNG、JPEG、PDF、MusicXML 和 MXL 上传后进入服务器真实任务队列。曲谱列表保存任务信息并轮询排队、处理中、完成、失败状态；重开页面读取当前设备可访问的任务。MXL/Audiveris 多乐章结果可分别选择、校对、导出。云端 XML 与音符列表通过读取前后修订号核对一致，避免将旧音符位置应用到新曲谱。

音符校对支持音高、时值、记谱时值、附点、休止转换与删除；完整 MusicXML 可编辑或导入校对文件。写操作提交当前 revision/If-Match，409 时明确提示并提供“重新载入最新版本”，不自动覆盖其他更新。服务器只有在 XML 与 MIDI 都生成成功后发布新版本。下载包含当前乐章 MusicXML、MIDI、原稿及已有 Audiveris 工程；校对不重写原始 .omr 工程。

“删除曲谱”对云端任务仅移除本机列表，页面明确告知云端原稿与版本仍保留，符合当前服务器没有 DELETE 接口的事实。原版离线四音符示例仍可载入、校对和导出，便于离线检查谱面和方向。示例不冒充云端识谱结果。

## 验证范围

类型检查和生产构建已通过；14 项自动测试覆盖 cookie/CSRF、原始字节上传、乐章、版本冲突、完整 XML If-Match、错误提示、大小限制、原生接口/回调、文件名与自定义 scheme 的 UUID fallback。测试通过不是公网部署完成或 Apple 真机验证的证明。后续公网验收、浏览器布局对照与 Apple CI 的结果由根任务单独记录。

听音引擎尚未加入此新界面。按照用户要求，界面与识谱/改谱检查供用户确认后，再接入听音。
