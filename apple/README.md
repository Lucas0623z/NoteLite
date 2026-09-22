# NoteLite for iPhone / iPad / Mac

原生 SwiftUI 客户端，最低支持 **iOS 16 / iPadOS 16 / macOS 13**。界面采用 [NoteLite Figma 设计](https://www.figma.com/design/auKshwj0bSnA6UxzLpcqlN?node-id=22-4648)，分别使用手机导航、平板分栏和 Mac 工作区。识谱继续通过 [桥接服务](../bridge/README.md) 调用 Java 引擎；原有 Java 桌面校谱工具继续可用。

练习页以本地 WKWebView 复用 NoteLite 的谱面排版和逐音评分，不需要联网加载脚本。MIDI 通过 CoreMIDI 输入，麦克风通过 AVAudioEngine 输入并在本机做 Pitchy 单音检测。麦克风不能可靠判断和弦或合奏；不评价踏板、音色或触键。原生硬件输入仍需要使用真实乐器做设备验收。

## 已实现

- iPhone 单栏导航；iPad 自适应侧栏与详情，支持旋转、分屏和可调整窗口、动态字体。
- 从“文件”导入 PDF / PNG / JPEG / TIFF / MusicXML / MXL，单文件上限 25 MiB（进入陪练时上限 15 MB）。MusicXML 可以直接练习；扫描谱完成识别后，打开下载的 MusicXML 练习。原稿复制到应用自己的存储，列表重启后仍在；文件协调与复制在后台线程进行。
- 练习支持谱面乐器推断、手动调整、声部/小节选择、试听、校对确认、暂停继续、错音定位与重练。结束后的回顾保存在本机，最多保留 500 次，不包含录音。
- Quick Look 预览原稿、系统分享原稿；不要求连接服务器。
- HTTPS 服务器设置，按服务器分别把 bearer token 存入 Keychain。健康检查不验证令牌；正式请求会显示认证错误。不关闭 ATS，不跟随 HTTP 重定向。
- 真正的文件上传和上传进度、服务端任务状态轮询、失败重试、下载 MusicXML / MIDI / 引擎其他结果，通过系统分享菜单保存到“文件”或发送其他应用。
- 本地保存任务 ID、原服务器地址和已下载结果；后台停止跟踪，返回前台或重启后恢复已有任务。中断的上传需要手动重试，并明确提示服务器可能已接收导致重复任务。
- “暂停跟踪”只停止客户端网络活动，**不会取消服务器识谱**。服务器 API 没有取消运行中任务的接口。
- 可单独清理已完成的服务器任务并保留本地结果。本地删除、重新提交均先清理旧任务；运行中、离线或清理失败时保留原任务记录。服务器返回 404 视为已清理，409 要等待终态。

此版本不包含设备离线 OMR、相机扫描、手动校谱、MIDI 播放器、账户体系或跨设备同步。识谱结果取决于现有桌面引擎；移动版不提供完整桌面编辑功能。没有占位演示任务或模拟识谱结果。

## 是否需要苹果编译工具

**编译、模拟器运行及签名 iPhone / iPad 应用，需要 Mac 上的完整 Xcode 和 iOS SDK。** Windows 可以编辑代码和运行桥接服务；安装 Windows Swift 编译器不能获得 iOS SDK，也不能代替 Xcode 完成 iOS 构建。仓库 CI 使用 GitHub 的 macOS runner 构建并运行模拟器单元测试。

原生 Mac 客户端选择 `NoteLiteMac` scheme。原有 Java 桌面编辑器构建依赖仍是 JDK 21 和 Gradle，参见桌面打包说明。

## 在 Mac 上运行

1. 安装完整 Xcode，打开一次完成 SDK / 模拟器安装及许可确认。在 Xcode Settings → Locations 中选中对应 Command Line Tools。
2. 安装 [XcodeGen](https://github.com/yonaskolb/XcodeGen)，在仓库执行：

```sh
brew install xcodegen
cd practice-web
npm ci
npm run build
cd ..
cd apple
xcodegen generate --spec project.yml
open NoteLite.xcodeproj
```

工程来自 `project.yml`，生成的 `.xcodeproj` 不纳入版本控制。`NoteLite` scheme 用于 iPhone / iPad；`NoteLiteMac` 用于原生 Mac。练习资源从 `app/res/practice` 打包，所以应先运行上面的网页资源构建。真机运行时在 Signing & Capabilities 中选择自己的 Team。对外分发还需要签名配置、应用图标、隐私声明和发布资料；本改动不包含已签名安装包或商店发布。

3. 按 [桥接服务说明](../bridge/README.md) 在电脑或服务器启动真实引擎，并配置手机可访问、证书受信任的 HTTPS 入口。应用内保存该地址和同一个访问令牌，再导入原稿并点“开始识别”。`localhost` 在手机上指手机本身。

不提供通用明文 HTTP 开关。内网开发也请使用受信任的 HTTPS 代理 / 网关；无需更改应用的系统网络安全设置。上传内容发送到用户配置的服务器，服务端保留策略由该服务器控制。桥接服务当前是单个共享令牌，适合自己的服务，不提供多用户数据隔离。

## 验证

```sh
cd apple
xcodegen generate --spec project.yml
xcodebuild build -project NoteLite.xcodeproj -scheme NoteLite \
  -configuration Release -destination 'generic/platform=iOS Simulator' \
  CODE_SIGNING_ALLOWED=NO
xcodebuild -showdestinations -project NoteLite.xcodeproj -scheme NoteLite
# 将下面的 ID 替换为上一条列出的 iPhone 或 iPad 模拟器 ID。
xcodebuild test -project NoteLite.xcodeproj -scheme NoteLite \
  -destination 'platform=iOS Simulator,id=SIMULATOR_ID' CODE_SIGNING_ALLOWED=NO
```

`NoteLiteTests` 覆盖 HTTPS 地址与凭据边界、真实 API JSON 解码、路径遍历拒绝、导入副本和待办任务持久化、损坏清单保护、25 MiB 限制、HTTP 错误，以及清理远端后重新识别不得复用旧结果的回归。练习测试还覆盖 MIDI 字节流、MusicXML 直接导入和练习记录持久化。CI 在 Mac、iPhone 与 iPad 分别执行单元测试与界面测试；界面测试通过真实导入进入谱面，验证底部控件、返回以及 iPad 旋转，并保存实拍截图。

Xcode 16.4 的 iOS 18.5 模拟器存在 [WebKit 已确认的动态库加载问题](https://bugs.webkit.org/show_bug.cgi?id=293831)：支持较早 iOS 的应用使用 `callAsyncJavaScript` 等接口时，可能在启动时找不到 `libswiftWebKit.dylib`。CI 按官方方案将所选模拟器的 `Contents/Resources/RuntimeRoot/System/Cryptexes/OS/usr/lib/swift` 加入测试进程和应用的 `DYLD_FALLBACK_LIBRARY_PATH`，没有提高应用最低系统版本。使用此模拟器在 Xcode 手动运行时，也需在 Scheme → Run → Arguments 中设置对应运行时路径；这属于模拟器环境设置，不能将此路径写入真机应用。

真机验收需检查：iCloud 导入、iPad 分屏与旋转、后台恢复、无效令牌、失败重试、真实服务器识谱后分别分享 `.mxl` 和 `.mid`、清理服务器任务以及删除本地文件。单元测试不覆盖 OMR 准确率或完整触摸交互。

API 契约：`GET /v1/health`；带认证的 `POST /v1/jobs?filename=...`（原始文件字节）、`GET /v1/jobs/{id}`、`GET /v1/jobs/{id}/artifacts/{name}`、`DELETE /v1/jobs/{id}`。结果下载始终在原服务器上根据校验过的文件名构造地址，不信任服务端返回的任意 URL。
