# NoteLite for iPhone / iPad / Mac

原生 SwiftUI 客户端，最低支持 **iOS 16 / iPadOS 16 / macOS 13**。界面采用 [NoteLite Figma 设计](https://www.figma.com/design/auKshwj0bSnA6UxzLpcqlN?node-id=22-4648)，分别使用手机导航、平板分栏和 Mac 工作区。

**完整 iOS 构建已接入应用内 Audiveris 引擎，完整 iPhone / iPad 识谱验收仍在进行。** 打包真实运行时的构建默认在设备上识别新导入的扫描谱，不要求用户配置服务器。只运行 `apple/project.yml` 得到的是基础客户端，不包含体积较大的 Java 运行时、OCR 库和识谱资源；该构建仍通过可选的 [桥接服务](../bridge/README.md) 识别扫描谱。直接导入 MusicXML 后练习，两种构建均可离线使用。原有 Java 桌面校谱工具继续可用。

练习页以本地 WKWebView 复用 NoteLite 的谱面排版和逐音评分，不需要联网加载脚本。MIDI 通过 CoreMIDI 输入，麦克风通过 AVAudioEngine 输入并在本机做 Pitchy 单音检测。麦克风不能可靠判断和弦或合奏；不评价踏板、音色或触键。原生硬件输入仍需要使用真实乐器做设备验收。

## 已实现

- iPhone 单栏导航；iPad 自适应侧栏与详情，支持旋转、分屏和可调整窗口、动态字体。
- 从“文件”导入 PDF / PNG / JPEG / TIFF / MusicXML / MXL，单文件上限 25 MiB（进入陪练时上限 15 MB）。MusicXML 可以直接练习；扫描谱完成识别后，打开生成的 MusicXML 练习。原稿复制到应用自己的存储，列表重启后仍在；文件协调与复制在后台线程进行。
- 完整 iOS 构建通过同进程 JNI 调用真正的 Audiveris，静态链接 OpenJDK Mobile Zero、JavaCPP、Leptonica 和 Tesseract，包含字体、分类器及完整英文 OCR 模型。生成的 MusicXML / MIDI 接入原有曲谱库、分享与练习流程。新任务默认使用本机；已有服务器任务继续在原服务器上查询和清理。
- 本机输入会校正图片 EXIF 方向、把透明区域合成白色，并限制解码尺寸；无需校正的 PNG / JPEG / TIFF 保留原字节，多页 TIFF 保留所有页面。PDF 保留完整文件，由 PDFBox 按 300 DPI 处理；预检全部页面的有效裁剪尺寸，过大时拒绝整份文件。输入准备、引擎执行和文件处理均在后台进行。
- 练习支持谱面乐器推断、手动调整、声部/小节选择、试听、校对确认、暂停继续、错音定位与重练。结束后的回顾保存在本机，最多保留 500 次，不包含录音。
- Quick Look 预览原稿、系统分享原稿；不要求连接服务器。
- 可选 HTTPS 服务器设置，按服务器分别把 bearer token 存入 Keychain。健康检查不验证令牌；正式请求会显示认证错误。不关闭 ATS，不跟随 HTTP 重定向。
- 真正的文件上传和上传进度、服务端任务状态轮询、失败重试、下载 MusicXML / MIDI / 引擎其他结果，通过系统分享菜单保存到“文件”或发送其他应用。
- 本地保存任务 ID、原服务器地址和已下载结果；后台停止跟踪，返回前台或重启后恢复已有任务。中断的上传需要手动重试，并明确提示服务器可能已接收导致重复任务。
- “暂停跟踪”只停止客户端网络活动，**不会取消服务器识谱**。服务器 API 没有取消运行中任务的接口。
- 可单独清理已完成的服务器任务并保留本地结果。本地删除、重新提交均先清理旧任务；运行中、离线或清理失败时保留原任务记录。服务器返回 404 视为已清理，409 要等待终态。

此版本不包含相机扫描、完整桌面手动校谱工具、独立 MIDI 播放器、账户体系或跨设备同步。识谱准确率、内存、耗时和后台行为仍需完整引擎的模拟器及真机验收。Zero 使用解释执行，不能把桌面引擎的速度视为移动端速度。没有以模拟识谱结果代替引擎执行。

## 是否需要苹果编译工具

**编译、模拟器运行及签名 iPhone / iPad 应用，需要 Mac 上的完整 Xcode 和 iOS SDK。** Windows 可以编辑代码和运行桥接服务；安装 Windows Swift 编译器不能获得 iOS SDK，也不能代替 Xcode 完成 iOS 构建。仓库 CI 使用 GitHub 的 macOS runner 构建并运行模拟器单元测试。

原生 Mac 客户端选择 `NoteLiteMac` scheme，当前使用基础客户端构建；完整嵌入引擎脚本面向 arm64 iPhone / iPad 真机和模拟器。原有 Java 桌面编辑器构建依赖仍是 JDK 21 和 Gradle，参见桌面打包说明。

## 基础客户端构建

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

工程来自 `project.yml`，生成的 `.xcodeproj` 不纳入版本控制。`NoteLite` scheme 用于 iPhone / iPad；`NoteLiteMac` 用于原生 Mac。练习资源从 `app/res/practice` 打包，所以应先运行上面的网页资源构建。该工程没有设置 `EMBEDDED_OMR_RUNTIME`，不会宣称内置完整识谱引擎。真机运行时在 Signing & Capabilities 中选择自己的 Team；无签名的设备构建不能直接安装到手机。

3. 基础客户端识别扫描谱时，按 [桥接服务说明](../bridge/README.md) 在电脑或服务器启动真实引擎，并配置手机可访问、证书受信任的 HTTPS 入口。应用内保存该地址和同一个访问令牌，再导入原稿并点“开始识别”。`localhost` 在手机上指手机本身。完整嵌入引擎构建使用下一节流程。

不提供通用明文 HTTP 开关。内网开发也请使用受信任的 HTTPS 代理 / 网关；无需更改应用的系统网络安全设置。上传内容发送到用户配置的服务器，服务端保留策略由该服务器控制。桥接服务当前是单个共享令牌，适合自己的服务，不提供多用户数据隔离。

## 完整 iPhone / iPad 引擎构建

以下为开发者构建流程，用户安装完整版本后无需执行这些步骤。编译环境使用 Apple Silicon Mac、完整 Xcode 26.6、XcodeGen 和 Python 3；编译 Java 引擎使用 JDK 21。运行时自身的引导 JDK 和配套工具要求见 [`build-mobile-jdk.sh`](../tools/audiveris-port/build-mobile-jdk.sh) 及 [运行时工作流](../.github/workflows/audiveris-mobile-runtime.yml)。

1. [运行时工作流](../.github/workflows/audiveris-mobile-runtime.yml) 构建 OpenJDK Mobile Zero 及无窗口的 `java.desktop`。使用产生完整 `headless/` 目录的构建结果。
2. [OCR 工作流](../.github/workflows/audiveris-ios-ocr.yml) 构建 Leptonica、Tesseract、PNG / JPEG / TIFF 编解码库和实际 JavaCPP JNI 静态库；它还在模拟器执行传统与 LSTM 两种 OCR 模式的测试。
3. [完整验收工作流](../.github/workflows/audiveris-ios-embedded-probe.yml) 接收前两项的运行 ID，分别组合真机和模拟器构建，先运行同进程 Java 识谱探针，再构建实际 NoteLite 应用并测试离线识谱至练习的流程。工作流保留原生符号、资源校验和、真实识谱导出文件、日志和界面截图。

也可在同一台 Mac 上，从已解压的真实依赖组合构建。`RUNTIME_DIR` 指向含 `include/`、`runtime/lib/modules`、`static-libs/` 的 `headless` 目录；`OCR_DIR` 指向含 `lib/`、`include/`、`share/tessdata/` 的 OCR `install` 目录。两个目录必须与选定 SDK 和 arm64 架构一致。

```sh
# 在仓库根目录运行；先完成上一节的练习网页资源构建。
export JAVA_HOME=$(/usr/libexec/java_home -v 21)
RUNTIME_DIR=/absolute/path/to/simulator/headless
OCR_DIR=/absolute/path/to/iphonesimulator-arm64/install
bash tools/audiveris-port/build-embedded-probe.sh iphonesimulator \
  "$RUNTIME_DIR" "$OCR_DIR" build/embedded-probe/iphonesimulator-arm64
bash tools/audiveris-port/build-embedded-app.sh iphonesimulator \
  build/embedded-probe/iphonesimulator-arm64/embedding \
  build/embedded-app/iphonesimulator-arm64

# SIMULATOR_ID 应来自 xcrun simctl list devices available。
bash tools/audiveris-port/run-embedded-probe.sh \
  build/embedded-probe/iphonesimulator-arm64/EmbeddedOMRProbe.app \
  SIMULATOR_ID build/embedded-probe/iphonesimulator-arm64/local-results
bash tools/audiveris-port/run-embedded-app-tests.sh \
  build/embedded-app/iphonesimulator-arm64 SIMULATOR_ID \
  build/embedded-app/iphonesimulator-arm64/local-ui-results
```

真机构建将 SDK 参数改为 `iphoneos`，并提供对应的 device 运行时和 `iphoneos-arm64` OCR 库。组合脚本会生成临时 Xcode 工程、链接真实静态库、打包资源并设置 `EMBEDDED_OMR_RUNTIME`；只手动打开这个编译标记不能构成完整引擎。依赖目录和组合探针的构建目录在应用构建及测试结束前必须保留。输出应用位于 `build/embedded-app/<SDK>-arm64/NoteLite.app`；脚本不执行分发签名。

设置 `NOTELITE_EMBEDDED_ARCHIVE=1` 后运行 `iphoneos` 的应用构建，还会生成并检查 `NoteLite.xcarchive.zip`。完整验收工作流启用此步骤，逐项确认归档保留同一套引擎资源。归档未经分发签名，不能直接安装到手机；现有 App Store 发布工作流仍使用基础客户端工程，不能把它的归档当作完整引擎产物。

**验收状态：原生 OCR 已在 iOS 模拟器实际运行；完整 Audiveris 在 iPhone / iPad 中生成并使用 MusicXML / MIDI 的验收尚未完成。** 单独编译成功、OCR 文本识别成功或桌面 Java 识谱成功，都不能替代完整移动端验收。签名真机安装、内存与耗时测量，以及上架仍是后续步骤。

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

`NoteLiteTests` 覆盖 HTTPS 地址与凭据边界、真实 API JSON 解码、路径遍历拒绝、导入副本和待办任务持久化、损坏清单保护、25 MiB 限制、HTTP 错误，以及清理远端后重新识别不得复用旧结果的回归。另有本机识谱结果安装、取消与失败后状态保留，以及 EXIF 八种方向、多页 TIFF、透明图片、PDF 完整保留和输入限制测试。练习测试覆盖 MIDI 字节流、MusicXML 直接导入和练习记录持久化。CI 在 Mac、iPhone 与 iPad 分别执行单元测试与界面测试；界面测试通过真实导入进入谱面，验证底部控件、返回以及 iPad 旋转，并保存截图。

基础客户端 CI 使用 Xcode 26.6 和匹配的 iOS 26 系列模拟器；最低部署版本仍为 iOS 16。DEBUG 菜单的“本地引擎移植测试”用于独立验证 Swift 图像预处理、二值化和像素游程，不输出音符或 MusicXML；完整引擎测试使用上节的实际嵌入应用。

真机验收需检查：iCloud 导入、iPad 分屏与旋转、本机完整识谱的准确率/内存/耗时、停止与重试、后台恢复、识谱后练习及分享 `.mxl` 和 `.mid`；启用服务器时还需检查无效令牌、清理服务器任务和删除本地文件。单元测试不覆盖 OMR 准确率或完整触摸交互。

API 契约：`GET /v1/health`；带认证的 `POST /v1/jobs?filename=...`（原始文件字节）、`GET /v1/jobs/{id}`、`GET /v1/jobs/{id}/artifacts/{name}`、`DELETE /v1/jobs/{id}`。结果下载始终在原服务器上根据校验过的文件名构造地址，不信任服务端返回的任意 URL。
