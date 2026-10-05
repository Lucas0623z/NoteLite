# 音伴-你的音乐搭子 苹果端适配

完整桌面界面使用 Java 21 / Swing，识别引擎依赖 Java 桌面 API、Tesseract 和 Leptonica。
macOS 保留完整桌面应用，也提供独立 SwiftUI 客户端。App Store iPhone / iPad 版本已内置
Orpheus AI 识谱引擎，新导入的 PDF 和图片在设备上处理，无需账号或识谱服务器。
原生 macOS 客户端的 PDF 和图片识谱仍使用自行配置的服务；MusicXML 可直接本机练习。

## 是否需要安装苹果编译工具

| 工作 | 所需环境 |
| --- | --- |
| 在 Windows 编辑代码、测试识别服务和 Java 引擎 | JDK 21、Python 3.10+，不需要 Xcode |
| 构建 macOS 桌面 DMG | 对应架构的 Mac、JDK 21、Xcode Command Line Tools |
| 编译 iPhone / iPad 应用、运行苹果模拟器 | Mac、完整 Xcode、iOS SDK、XcodeGen |
| 安装到本人 iPhone / iPad 测试 | Xcode 中配置 Apple ID、签名和设备 |
| TestFlight / App Store 分发 | 配置 Apple Developer Program 账户及对应签名 |

Xcode 不能安装在 Windows 上。没有本地 Mac 时，可让 GitHub Actions 的 macOS 运行器
进行编译；云端编译不会自动提供真机验证、签名证书或 App Store 发布。选择与 Mac 系统
版本兼容的 Xcode，提交应用前再核对苹果当时的 SDK 要求。

参考：[Xcode](https://developer.apple.com/xcode/)、
[系统要求](https://developer.apple.com/support/xcode/)、
[命令行工具](https://developer.apple.com/documentation/xcode/installing-the-command-line-tools)。
Java 官方文档说明，`jpackage` 必须在目标系统运行，签名和自定义 DMG 图标需要
[苹果命令行工具](https://docs.oracle.com/en/java/javase/21/jpackage/packaging-overview.html)。

## macOS 桌面端

- 继续本地识别、人工校正、导出，无需连接识别服务。
- 使用 Java Desktop / Taskbar API 接入“关于”“设置”“退出”和 Finder 打开文件。
- 应用菜单快捷键转换为 Command，状态和进度信息留在窗口内。
- 分别构建 Apple Silicon 与 Intel 安装包，包含对应 Java 和原生依赖。
- 修正图标路径，使用 macOS 自带工具生成图标，刷新打包依赖，统一启动参数。

构建、签名与公证操作见 [macOS 打包说明](../packaging/MACOS.md)。默认 CI 产物是未签名
安装包，正式发布前仍需 GUI、实际识别、签名与公证验证。

## iOS / iPadOS

SwiftUI 客户端面向 iOS 16 / iPadOS 16 及以上，支持手机导航和 iPad 分栏布局。
App Store 版本使用系统文件选择器导入 PDF、PNG、JPEG、TIFF，在本地保存原稿，
通过内置引擎识谱，查看处理进度并分享生成的 MusicXML 和 MIDI。

```text
iPhone / iPad 导入乐谱
        ↓ 设备内处理
随应用附带的 Orpheus AI 识谱引擎
        ↓
MusicXML + MIDI → 本机练习 / 分享
```

新任务不上传原稿，也不会在本机识谱失败后自动切换服务器。识谱时需保持应用在前台；
耗时取决于设备、页数和谱面复杂度。进入后台或选择停止后，引擎在安全处理边界响应取消。
包含多个部分的结果可以分别练习，识别结果需先试听或校对。

客户端支持麦克风单音旋律和 MIDI 乐器练习反馈，谱面按书写顺序练习，暂不展开反复和跳转。
麦克风不支持和弦评分；多声部请使用 MIDI。未提供桌面版逐符号人工校正、iCloud 同步或多人
账户系统。MusicXML 的专业排版编辑应交给支持该格式的软件。

1. 按 [apple/README.md](../apple/README.md) 准备内置引擎资源、生成 Xcode 工程并构建。
2. 导入测试乐谱，进入详情并选择“开始识别”，保持应用在前台。
3. 识谱完成后分享 MusicXML / MIDI，或选择“开始练习”。已有 MusicXML 可直接导入练习。

“服务器设置”保留用于兼容已有远端任务，填写地址不会改变新导入曲谱的本机识谱方式。
已有远端任务继续通过原服务器查询、下载和清理；重新识别远端任务时会重新上传原稿。
详细行为见[支持文档](app-store/support.md)和[隐私政策](app-store/privacy.md)。

## 原生 macOS 客户端与识谱服务

独立 SwiftUI macOS 客户端当前使用自己配置的识谱服务处理 PDF 和图片，完整本地识谱与
人工校正可使用前述 Java 桌面应用。原生客户端也可直接导入 MusicXML / MXL 本机练习。

1. 按 [bridge/README.md](../bridge/README.md) 构建 Java 分发包并启动自己的识谱服务。
2. 提供可访问、证书可信的 HTTPS 地址，并配置服务访问令牌。
3. 在原生客户端设置中填写地址与令牌，导入测试乐谱，识谱后下载或分享结果。

服务调用的命令入口仍使用内部程序名：

```sh
音伴-你的音乐搭子 -batch -transcribe -export -export-midi -output output -- score.pdf
```

`-export-midi` 可与 `-export` 一起使用，多乐章生成独立 MIDI 文件。
文字识别还需要 Tesseract 语言数据；缺少语言包时，歌词、标题等文字不会正常识别。

## 发布前验证

仓库提供 macOS 桌面与 iOS 模拟器构建工作流。Windows 上的 Java/服务测试不能替代 Mac
编译、iPhone/iPad 真机或 macOS GUI 测试。发布前确认：

- iPhone 竖屏、横屏、较大字体和网络中断后的恢复。
- iPad 横竖屏、分屏、外接键盘以及后台恢复任务。
- 从“文件”导入、原谱预览、识别失败提示、结果保存与分享。
- Mac 两种架构上的窗口、Command 快捷键、Finder 打开、取消退出以及识别导出。

首个 iPhone / iPad 版本已提交 App Store 审核，提交审核不等于已在商店公开上架。
后续版本仍需核对构建、签名、审核状态和实际分发情况。自行构建时，证书、团队 ID、
应用标识和分发渠道由项目所有者配置。
