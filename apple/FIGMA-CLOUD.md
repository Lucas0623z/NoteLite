# Figma 界面与云识谱 Apple 客户端

当前入口完整加载 `figma-ui` 的 Figma Make 成品页面，SwiftUI 不重画页面，也不叠加原生导航栏。源设计为 https://www.figma.com/make/pixNf29vNFHLDrih3Xcikc/iPhone-App-Page-Design 。比例与响应布局的浏览器检查、Apple 编译/模拟器截图、真实设备检查是不同验收项，不能互相替代。

## 构建

先构建原练习资源（保留旧客户端测试），再构建最新页面并复制到 Apple 的资源目录：

```sh
npm --prefix practice-web ci
npm --prefix practice-web run build
npm install --global pnpm@11.25.0
pnpm --dir figma-ui install --frozen-lockfile --ignore-scripts
pnpm --dir figma-ui typecheck
pnpm --dir figma-ui test
pnpm --dir figma-ui build
python3 apple/scripts/prepare-figma-ui.py
cd apple
xcodegen generate --spec project.yml
xcodebuild build -project NoteLite.xcodeproj -scheme NoteLite \
  -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO
```

`apple/FigmaUI` 是生成目录，不提交 Git。XcodeGen 将它完整打包进 iOS/macOS 应用。WKWebView 只从 `notelite-ui://app` 读取这份本地资源，拒绝越界、外部符号链接及远程页面；文件导入内容不能获得原生接口。iPhone/iPad 的原生壳使用 `.ignoresSafeArea()` 与 `contentInsetAdjustmentBehavior = .never`，页面通过 `env(safe-area-inset-*)` 自己处理安全区，避免重复偏移。macOS 壳保留标题栏安全区，页面占满标题栏下的实际内容区，防止 WebView 延伸到标题栏下而被裁掉。

`.github/workflows/apple-client.yml` 检查 runner 实际安装的稳定 Xcode，然后构建 iOS、Mac、无签名真机应用，运行保留的旧功能测试和新界面测试，保存截图。不以 Windows 浏览器截图声称 Apple 实机通过。

## 原生云桥接

网页发送 `window.webkit.messageHandlers.noteLiteCloud.postMessage({requestId, action, payload})`，requestId 是唯一字符串。原生只接受受信任本地 origin 的主 frame，最多 16 个并发请求。返回 `window.NoteLiteCloudNative.resolve(requestId, {ok:true,result})`，错误为 `{ok:false,error:{code,message,status?}}`。上传进度通过 `.event({type:'uploadProgress',requestId,progress})`。

| action | payload / 返回 |
| --- | --- |
| `configuration/get` | 返回 baseURL、hasCredentials、platform、native、listeningEnabled:false |
| `configuration/set` | `{baseURL}`；只接受无额外路径的 HTTPS origin |
| `device/pair` | `{code,deviceName}`；调用 `/api/pair` 的 native 模式，返回设备元数据，删除响应 token |
| `device/unpair` | 在线撤销本设备云会话后移除 Keychain 凭据；离线失败保留凭据，不删除云端曲谱 |
| `health` / `session` | 网关健康 / 本设备认证状态 |
| `jobs/list` / `jobs/get` | 网关原始任务 JSON；get 的参数 `{jobId}` |
| `jobs/upload` | `{filename,base64}`，返回任务；支持 PDF、PNG、JPEG、XML/MXL，上限 32 MiB |
| `jobs/import` | 原生文件选择后上传，等待完成并返回任务；取消为 cancelled |
| `score/get` | `{jobId,score}`，返回 MusicXML 字符串 |
| `notes/get` | `{jobId,score}`，返回音符列表与修订号 |
| `notes/patch` | `{jobId,score,revision,edits}`，成功返回新任务 JSON |
| `score/put` | `{jobId,score,revision,musicxml}`，原始 XML + If-Match 请求 |
| `files/get` | `{jobId,score,kind}`，小文件返回 base64；大文件使用导出 |
| `files/export` | `{jobId,score,kind,filename?}`，原生下载后选择保存位置，返回 saved 与 filename |
| `files/save` | `{filename,base64}`，保存本机示例/校对的结果（上限16 MiB），同样等待用户选择保存位置 |
| `files/view` | `{jobId,score,kind:'original',filename}`，下载 PDF/PNG/JPEG 原稿，交系统 Quick Look 预览（上限32 MiB），关闭后清理临时文件 |
| `request/cancel` | `{targetRequestId}`，取消尚未返回的本机请求，关闭文件选择/保存窗口并释放等待状态；不会回滚服务器已经提交的修改 |
| `orientation/set` | `{mode:'landscape'|'restore'}` |

默认服务地址为 `https://124.221.211.156`。新设备用一次性配对码获得自身凭据，凭据只在 Keychain 中，按 HTTPS origin 分开保存，不同步、不发给 JavaScript。请求不跟随重定向，也不接受任意下载 URL。应用未包含 OMR 内部管理员令牌。缺少配对码时可使用原有“载入示例曲谱”本地功能；它明确标为示例，并不声称运行了云识谱。

保存修改调用网关的修订接口；只有服务器同步发布新的 MusicXML/MIDI 后，才返回成功。409 要重新读取并复核，不能盲目覆盖。没有调用旧 `/v1` 的任务删除逻辑。

写请求允许最长 240 秒无响应、总计 300 秒，覆盖服务器同步生成 MIDI 的时限。网络中断时返回 `write_status_unknown`，需要重新载入任务确认最终修订号。原生导入与保存使用有明确成功/取消回调的系统文件窗口，支持 iOS 16 / macOS 13；正常取消不会遗留等待状态。原稿预览不执行文件中的网页脚本，也不授予子 frame 原生接口。

## 方向与验收边界

iPhone/iPad 进入看谱或练习页面，网页经生产桥接请求本机横屏；退出时请求恢复进入前的界面方向。使用 iOS 16 的 UIWindowScene 几何 API 与 UIApplicationDelegate 的支持方向回调，没有私有 KVC 旋转。iPad 分屏或窗口模式拒绝方向变更时，会返回 orientationError 事件并显示中文指引，不能伪装旋转成功。iPadOS 26 的窗口模式不保证接受自动旋转，应用不能通过公开 API 强制用户切换系统全屏模式。Mac 按实际窗口宽高响应，方向请求不改变窗口。

Mac UI 测试另以 DEBUG 专用启动参数设置真实 AppKit 内容窗口为 1440×900 与 900×1440，核对 WKWebView 实際尺寸、窗口装饰高度和原生导航栏，保存窗口截图及 runner 屏幕尺寸。若 runner 显示器容不下整个竖向窗口，证据会明确记录，不能把截到的屏幕区域声称为完整竖向视觉验收。该参数不会修改生产窗口、CSS 或内容排版。

`FigmaShellUITests` 将本机读谱/文件窗口、修改后的持久化、严格方向分成独立用例。原有功能用例在 Apple 模拟器运行正式“导入曲谱 → 载入示例曲谱 → 查看曲谱 → 返回”的界面流程，断言实际 MusicXML 排版成功和四个完整音符控件，实际点击 D4 核对选中状态与音名字段 D，再切回 C4；重启后再次从本机读取示例，进入练习页检查未接入听音的提示，并保存真实屏幕截图。该原有用例只选择音符。方向用例单独严格断言看谱及练习实际横屏、关闭恢复原方向；系统拒转时该用例继续失败，不遮住其他功能结果。

新增 `testNewInteractionsLocalPitchTempoPersistenceAndExport` 通过真实八度下拉框将本机示例首音 C4 改为 C5，点击“保存校对”，重新启动应用后要求实际排版与音符列表仍为 C5/D4/E4/F4。随后通过“编辑谱面前置信息”展开控件，填写数值速度 96 并保存，再次重启检查速度仍为 96。Mac 额外经系统 Save 窗口真正保存文件，读取磁盘上的 XML，严格检查 C5/D4/E4/F4、原始四个时值、四分音符速度标记与播放速度均为 96，并把实际文件作为附件保留。iOS 用例不声称已验证保存到系统目标位置的文件字节。所有操作使用公开 XCTest 控件、键盘或滚动接口，不执行 JavaScript 修改谱面。新增用例在 Windows 仅能准备代码，须由对应提交的真实 Apple CI 运行后才能报告通过；此前 bcb80a5 原生基线不包含这项新验证。

这些本机界面测试不运行云 OMR、不使用假识谱，也不验证带凭据的真实云配对。`CloudOMRTests` 使用明确标注的 URLProtocol 传输替身测试新 API、凭据与修改契约。服务器真实识谱/编辑验收另有实际 PNG/PDF 结果。

本机导出会实际打开系统保存窗口并取消两次，确认可立即重新打开；Mac 第三次通过系统 Save 保存到测试临时目录，读取磁盘上的 MusicXML 并核对四个音符，结果作为附件保存。这不是带凭据的云导入取消／重试验收，后者还需实际配对的 Apple 设备验证。

原 `LibraryView`、设备嵌入识谱和 `PracticeView` 保留。DEBUG 的旧 `--uitesting-import-*` 启动参数继续进入旧界面，使其单元/界面测试仍有意义；生产启动一律进入 Figma 新界面。谱面试听是用户主动开启的乐谱合成播放，指针跟随实际播放事件；它不表示系统正在识别用户演奏。当前阶段没有启动原生音频输入、听音检测或演奏评分，须 UI 与云服务检查后再接入。

## 原生账号与录音桥接

`CloudAccountClient` 只请求用户配置的 HTTPS origin 下明确列出的 `/api/account` 路由。注册与登录强制使用 `native` 模式；token、用户 ID 和会话 ID 保存在独立的 origin-scoped Keychain，回复网页仅包含公开账号字段。退出或撤销当前会话只清除账号凭据，保留原有设备配对。账号 401 不删除本地账号凭据、不回退旧设备身份；必须显式退出或重新登录。账号及 OMR 请求都禁止 Cookie、任意自定义请求头和跨地址重定向，使用捕获账号的身份一致性字段。写请求的超时、代理失败及损坏的成功回复会报告“提交结果尚未确认”。

`account/digest/start/update/finish/cancel` 使用 CryptoKit 增量 SHA-256，单块最多 1 MiB、声明总长最多 100 MiB、偏移必须连续，最多四个未完成摘要且五分钟过期；摘要限定当前 origin、用户及会话，地址/登录变更会清理。`account/audio/view` 通过带权限的服务接口下载最多 100 MiB 的录音至随机临时目录，校验 MIME 与文件头，再核验 Apple 播放器是否可播放后打开系统播放界面。取消、关闭及账号切换会清理文件。网页只收到 `previewOpened`，不接收原生文件路径或大段音频 Base64；不支持的格式会明确提示。这是已录制文件的播放与提交，不表示已接入 NoteWise 听音或实时音频采集。

`CloudAccountTests` 的 16 项原生模型测试使用内存凭据与 URLProtocol 替身，覆盖 native 登录、公开回复、401/退出、身份一致性、ETag、分块上传、固定路由、摘要与音频格式/大小边界。源码准备不等于测试通过：该扩展仍需对应提交的真实 Apple CI 编译执行，带真实账号的原生云端全流程另需单独验收；此前原生基线不包含账号扩展。
