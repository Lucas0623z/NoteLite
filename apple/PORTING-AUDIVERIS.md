# Audiveris 在 iPhone / iPad 上的本地移植

## 当前范围

目标是让应用在设备内完成 PDF / 图片到 MusicXML 的识别，用户无需安装 Java 或配置服务器。

`apple/AudiverisCore` 是这个目标的第一阶段：把当前 NoteLite 分支中的 Audiveris 图像二值化和前景游程算法移植到 Swift。游程是同一行或列中连续的黑色像素段。此阶段输出二值图和游程，**尚不能识别音符、节奏或生成 MusicXML**。应用中的“本地引擎移植测试”用于验证这部分本地处理。

本阶段的算法来源：

- `app/src/main/java/com/notelite/omr/image/AdaptiveFilter.java`
- `app/src/main/java/com/notelite/omr/image/VerticalFilter.java`
- `app/src/main/java/com/notelite/omr/image/GlobalFilter.java`
- `app/src/main/java/com/notelite/omr/run/RunsRetriever.java`

自适应阈值沿用 `meanCoefficient × mean + standardDeviationCoefficient × sqrt(abs(E[x²] − mean²))`，默认半窗口为 18 像素，两个系数为 0.7、0.9；像素值小于或等于阈值时为前景。边界裁剪、整数累加、浮点运算顺序和横纵坐标都需要与 Java 输出一致。

完整识别入口仍有后续工作；调试页面运行成功不代表完整 OMR 已移植。派生代码保留仓库原有 AGPL-3.0-or-later 来源和许可说明。

## 审计基线

审计日期：2026-09-28。当前产品基线是 NoteLite 提交 `4c0f1a6017b30e796e48e2dcd24897409eed2345`，不能用 Audiveris 最新主线的环境要求替代它。

| 项目 | 当前 NoteLite 分支 |
| --- | --- |
| 应用版本 | 5.13.0 |
| Java | 21，开启 preview features |
| JavaCPP | 1.5.12 |
| Tesseract / Leptonica | 5.5.1 / 1.85.0 |
| ImageJ | 1.54p |
| PDFBox | 3.0.6 |
| ProxyMusic | 4.0.3 |
| JAXB API / implementation | 2.3.1 / 2.3.1 |
| tessdata tag | 4.1.0 |

版本来自 `gradle.properties` 和 `app/build.gradle`。作为对照，另外读取的 Audiveris 上游 `7a36078e7ba0c006052c1f661b949cf9b729f505` 标记为 5.11.0，要求 Java 25；它不是本轮移植与等价测试的基线。

### 可重复的依赖审计

在仓库根目录运行，要求 Python 3.10 或更高版本，无第三方 Python 依赖：

```sh
python tools/audiveris-port/audit_dependencies.py
python tools/audiveris-port/audit_dependencies.py --format json --output build/audiveris-port-audit.json
python tools/audiveris-port/audit_dependencies.py --check-native-artifacts
```

默认只读取源代码。最后一个命令还会查询 Maven Central 上当前锁定版本的原生包列表。JSON 包含每条 import 的文件和行号、版本、依赖坐标、字体和分类器资源校验值，以及 Java 源码树的 SHA-256。

上述基线共有 993 个 Java 源文件；首次审计结果：

| 显式依赖 | 涉及文件数 | 位于 `ui` 目录之外的文件数 |
| --- | ---: | ---: |
| AWT 几何类型 | 378 | 275 |
| 其他 AWT 类型 | 237 | 93 |
| Swing | 148 | 24 |
| ImageJ | 71 | 67 |
| JAXB | 229 | 224 |
| 反射 | 24 | 14 |
| JavaCPP / 原生绑定 | 2 | 2 |

这些是源码 import 计数，类别之间存在重叠。仅排除了路径中名为 `ui` 的目录；“目录之外”不等于纯识别代码，也不等于运行时可达性。审计器不证明任何平台已经编译通过。

## 完整引擎移植的实际障碍

| 部分 | 源码证据 | 需要完成的工作 |
| --- | --- | --- |
| 图像与 PDF 输入 | `image/ImageLoading.java` 使用 ImageIO、PDFBox、BufferedImage；ImageJ 贯穿图像处理 | 将解码与栅格化放在 Apple 平台层，把稳定的灰度像素接口传给核心；明确 DPI、旋转、颜色转换和尺寸限制 |
| 模板与字体 | `image/TemplateFactory.java` 的模板构造调用 `MusicFont`、`symbol.buildImage`、`BufferedImage`；并非仅在显示界面时使用字体 | 验证 CoreText / CoreGraphics 的模板栅格化，或预生成模板；比较字形边界、像素、距离表和匹配结果 |
| 页面与符号图 | `sheet/Book.java`、`sheet/Sheet.java` 混用识别状态、桌面 UI 和持久化；AWT 几何类型广泛使用 | 提取页面、谱表、符号、关系与识别调度；用独立几何和像素类型取代桌面类型，隔离 UI 回调 |
| 文字识别 | `text/tesseract/TesseractOrder.java` 通过 ImageIO 编码 TIFF，再交给 Leptonica；使用 `TessBaseAPI` 和 `OEM_TESSERACT_ONLY` | 为 iOS device 与 simulator 编译 Tesseract / Leptonica，提供 C 接口与 Swift 桥接；确保训练数据支持当前使用的 legacy 模式，并验证坐标与文字结果 |
| 模型与资源 | `classifier/BasicClassifier.java`、`math/NeuralNetwork.java`，以及 `app/res/basic-classifier.zip`、音乐字体 | 移植相同特征提取、分类计算和模型加载；锁定资源版本；使用 Java 输出检查概率、类别和拒识行为 |
| 反射与 XML | `constant/UnitManager.java` 扫描类；JAXB 用于模型、状态与导出；ProxyMusic 用于 MusicXML | 用显式注册替代扫描；若采用 AOT，维护反射和资源配置；若采用 Swift，建立模型/文件格式兼容层并验证导出语义 |
| 生命周期 | `Main.java` 是桌面/命令行入口，含 `System.exit`；存在全局状态和线程池 | 提供可取消的库 API，避免退出进程；限定并发、内存和临时文件生命周期，覆盖前后台切换 |

表中 Java 路径均相对于 `app/src/main/java/com/notelite/omr/`。仅启用 `-batch` 会省去桌面窗口，无法消除以上算法依赖。

本轮实际查询的 [Tesseract 5.5.1-1.5.12](https://repo.maven.apache.org/maven2/org/bytedeco/tesseract/5.5.1-1.5.12/) 与 [Leptonica 1.85.0-1.5.12](https://repo.maven.apache.org/maven2/org/bytedeco/leptonica/1.85.0-1.5.12/) 包列表均包含 Android、Linux、macOS、Windows，没有 `ios-*` 包。`macosx-arm64` 不能作为 `iphoneos-arm64` 库链接。当前 [JavaCPP Tesseract 构建脚本](https://github.com/bytedeco/javacpp-presets/blob/master/tesseract/cppbuild.sh) 也没有 iOS 分支；需要增加对应构建，不能只修改 Gradle 的 `targetOS`。

## Java 转原生路线的结论

- **Gluon / GraalVM AOT**：官方文档支持把 Java 库构建为 iOS 静态库，值得用完整核心做后续可行性实验。但它不会自动替换 AWT、ImageJ、反射或 JNI 依赖。官方要求在 macOS 上生成 iOS 构建；需要先确定与 Java 21 preview 字节码兼容的工具链，再验证所有依赖的 iOS 链接。参见 [Gluon 平台与静态库文档](https://docs.gluonhq.com/)。
- **J2ObjC**：能把 Java 业务代码转换为 Objective-C，支持多项 Java 语言与运行时特性，但不提供跨平台 UI 工具包。其官方构建要求 macOS、Xcode 和 JDK。上述桌面类型和原生绑定仍需适配；不能直接把整套 Audiveris JAR 转成可用引擎。参见 [J2ObjC 项目说明](https://github.com/google/j2objc)。
- **OpenJDK Mobile**：官方项目把 iOS Java 库、原生桥接和框架打包列为发展方向，路线图还包含 Zero interpreter 和 AOT 探索。它可以继续观察，但当前文档不足以证明本项目有现成可交付的运行时。参见 [iOS Java 库](https://openjdk-mobile.github.io/ios/library/) 和 [路线图](https://openjdk-mobile.github.io/roadmap/)。

本轮选择先移植可独立验证的 Swift 算法核心，以消除第一批 JVM 与桌面库依赖。后续可以按阶段比较直接移植和 AOT 的实际成本；不预先声称全量 AOT 不可能。

## 阶段与验收条件

1. **二值化与游程**：Swift 包在本机处理像素；使用当前分支的原始 Java 实现产生固定样例，逐像素比较二值图，逐项比较横向与纵向游程。覆盖边缘窗口、小图、均匀图、阈值相等、非方形图和噪声图；监测大图内存与取消。
2. **谱表与基础几何**：移植尺度估计、去斜、线段和谱表构建，比较谱线坐标、间距和前景连通结果。输入包含不同扫描分辨率、倾斜与弱线条。
3. **符号与文字**：移植特征、分类器、模板和符号关系，接入设备内的 Tesseract。验证音符头、符干、连梁、谱号、调号和文本；记录与 Java 的差异。
4. **音乐语义与导出**：重建小节、声部、时值、连线和跨页关系，输出兼容 MusicXML。用人工校验曲谱衡量音高、时值、节奏完整性与导出可读性。
5. **产品接入**：完整识别在飞行模式下通过，移除用户必须配置服务器的依赖；在 iPhone 和 iPad 真机验证时间、峰值内存、热状态、取消和后台中断，再开放正式入口。

## 构建与测试结果应如何记录

- Swift 包测试、Java 对照测试、iOS Release 编译、iPhone 模拟器、iPad 模拟器、两种真机测试应分别记录结果，不能互相替代。
- CI 配置已经写入并不表示任务已执行；必须保留实际运行状态和日志。
- 此次开发主机是 Windows。审计时 PATH 中有 Java 21，但没有 `native-image`、`xcodebuild` 或 `xcrun`；本机无法生成或验证 Apple SDK 产物。macOS 构建与设备验证需要由相应 runner / 设备执行。
- 在完成第五阶段验收前，不应把第一阶段的调试输出或远端识别结果标记为“完整 Audiveris 已在 iPhone / iPad 本地运行”。
