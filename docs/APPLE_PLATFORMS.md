# NoteLite 苹果端适配

原有界面使用 Java 21 / Swing，识别引擎依赖 Java 桌面 API、Tesseract 和 Leptonica。
macOS 保留完整桌面应用，iOS / iPadOS 使用独立原生客户端，通过自己的识别服务复用
现有引擎。此次移动端采用联网识别方案。

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

新的 SwiftUI 客户端面向 iOS 16 / iPadOS 16 及以上，支持手机导航和 iPad 分栏布局，
使用系统文件选择器导入 PDF、PNG、JPEG、TIFF，在本地保存原始乐谱，提交后台识别任务，
查看任务状态并下载、分享结果。服务地址由使用者配置，访问令牌保存在 Keychain。

```text
iPhone / iPad 导入乐谱
        ↓ HTTPS + 访问令牌
自己的识别服务（Python）
        ↓ 有限队列、独立 Java 进程
NoteLite OMR 引擎
        ↓
MusicXML + MIDI → 下载 / 分享
```

识别需要网络和已运行的服务。未提供完全离线 OMR、桌面版逐符号人工校正、音频演奏评测、
iCloud 同步或多人账户系统。MIDI 沿用现有引擎的试听用途及其限制。客户端可以预览导入
的原谱；MusicXML 的专业排版编辑应交给支持该格式的软件。

1. 按 [bridge/README.md](../bridge/README.md) 构建 Java 分发包并启动自己的识别服务。
2. 为移动设备提供可访问、证书可信的 HTTPS 地址，配置服务访问令牌。
3. 按 [apple/README.md](../apple/README.md) 生成 Xcode 工程，在模拟器或真机运行。
4. 在客户端设置中填写服务地址与令牌，导入测试乐谱，识别后下载 MusicXML / MIDI。

服务直接调用此命令能力：

```sh
NoteLite -batch -transcribe -export -export-midi -output output -- score.pdf
```

`-export-midi` 是本次新增参数，可与 `-export` 一起使用，多乐章生成独立 MIDI 文件。
文字识别还需要 Tesseract 语言数据；缺少语言包时，歌词、标题等文字不会正常识别。

## 发布前验证

仓库提供 macOS 桌面与 iOS 模拟器构建工作流。Windows 上的 Java/服务测试不能替代 Mac
编译、iPhone/iPad 真机或 macOS GUI 测试。发布前确认：

- iPhone 竖屏、横屏、较大字体和网络中断后的恢复。
- iPad 横竖屏、分屏、外接键盘以及后台恢复任务。
- 从“文件”导入、原谱预览、识别失败提示、结果保存与分享。
- Mac 两种架构上的窗口、Command 快捷键、Finder 打开、取消退出以及识别导出。

CI 编译通过也不等于已完成 App Store 发布。证书、团队 ID、应用标识和分发渠道应由
项目所有者在准备发布时配置。
