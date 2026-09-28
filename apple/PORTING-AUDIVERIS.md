# Audiveris 在 iPhone / iPad 上的本地移植

## 目标与当前实现

目标是让应用在设备内完成 PDF / 图片到 MusicXML 的识别，用户无需安装 Java 或配置服务器。

当前完整引擎路线是：在应用内静态链接 OpenJDK Mobile 的 Zero 解释器，保留原有 Java 识别算法、模型和 MusicXML 导出；移植它实际依赖的软件图像处理、字体和 OCR 库。Java 代码与运行时随应用打包，不要求用户安装 Java、配置 OMR 服务或下载可执行代码。

`apple/AudiverisCore` 是已经独立实现的 Swift 二值化与游程核心。游程是同一行或列中连续的黑色像素段。它输出二值图和游程，**尚不能识别音符、节奏或生成 MusicXML**。应用中的“本地引擎移植测试”验证这部分处理；完整引擎必须通过后文的嵌入式运行与导出验收。

本阶段的算法来源：

- `app/src/main/java/com/notelite/omr/image/AdaptiveFilter.java`
- `app/src/main/java/com/notelite/omr/image/VerticalFilter.java`
- `app/src/main/java/com/notelite/omr/image/GlobalFilter.java`
- `app/src/main/java/com/notelite/omr/run/RunsRetriever.java`

自适应阈值沿用 `meanCoefficient × mean + standardDeviationCoefficient × sqrt(abs(E[x²] − mean²))`，默认半窗口为 18 像素，两个系数为 0.7、0.9；像素值小于或等于阈值时为前景。边界裁剪、整数累加、浮点运算顺序和横纵坐标都需要与 Java 输出一致。

调试页面运行成功不代表完整 OMR 已移植。Audiveris 派生代码保留 AGPL-3.0-or-later 来源和许可；OpenJDK 适配代码使用 GPL-2.0 with Classpath Exception，并保留被修改上游文件的原有版权声明。

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
| 图像与 PDF 输入 | `image/ImageLoading.java` 使用 ImageIO、PDFBox、BufferedImage；ImageJ 贯穿图像处理 | 编译 OpenJDK 的软件 AWT、JPEG、色彩管理库；保持相同像素处理，验证 PNG / TIFF / PDF 的真实输入 |
| 模板与字体 | `image/TemplateFactory.java` 调用 `MusicFont`、`symbol.buildImage`、`BufferedImage`；字体参与识别 | 用真实 FreeType / HarfBuzz 与原音乐字体生成模板；替换要求 Cocoa / X11 的平台字体发现与图形环境，验证字形和完整识别结果 |
| 页面与符号图 | `sheet/Book.java`、`sheet/Sheet.java` 混用识别状态、桌面 UI 和持久化 | 保留 Java 模型与几何类，使用无窗口模式与库入口；测试每个识别步骤和状态保存 |
| 文字识别 | `text/tesseract/TesseractOrder.java` 编码 TIFF，再交给 Leptonica；使用 `TessBaseAPI` 与 `OEM_TESSERACT_ONLY` | 为 device / simulator 编译 Tesseract、Leptonica、图像编解码库及 JavaCPP JNI；使用含 legacy 模型的 tessdata 4.1.0 |
| 模型与资源 | `classifier/BasicClassifier.java`、`math/NeuralNetwork.java`、`app/res/basic-classifier.zip` | 保留相同代码和模型，打包资源并验证加载、分类与输出一致性 |
| 反射与 XML | 常量扫描、JAXB 模型与 ProxyMusic 导出使用反射 | Zero 运行时保留反射；验证 JAXB Unicode 往返、真实 ProxyMusic 模型和 MusicXML 文件语义 |
| 生命周期 | 桌面 `Main.java` 含 `System.exit`、全局状态和线程池 | 使用 `EmbeddedOmrEngine` 的进程内入口，验证沙盒、取消、错误恢复和重复调用，再测试移动端生命周期 |

表中 Java 路径均相对于 `app/src/main/java/com/notelite/omr/`。仅启用 `-batch` 会省去桌面窗口，无法消除以上算法依赖。

本轮实际查询的 [Tesseract 5.5.1-1.5.12](https://repo.maven.apache.org/maven2/org/bytedeco/tesseract/5.5.1-1.5.12/) 与 [Leptonica 1.85.0-1.5.12](https://repo.maven.apache.org/maven2/org/bytedeco/leptonica/1.85.0-1.5.12/) 包列表均包含 Android、Linux、macOS、Windows，没有 `ios-*` 包。`macosx-arm64` 不能作为 `iphoneos-arm64` 库链接。当前 [JavaCPP Tesseract 构建脚本](https://github.com/bytedeco/javacpp-presets/blob/master/tesseract/cppbuild.sh) 也没有 iOS 分支；需要增加对应构建，不能只修改 Gradle 的 `targetOS`。

## 运行时路线与可重复构建

选用官方 [OpenJDK Mobile](https://github.com/openjdk/mobile/tree/c1ed06aaef34c8dccf71e236d1ffa20918a77cfb)，固定提交 `c1ed06aaef34c8dccf71e236d1ffa20918a77cfb`。该源码版本是 JDK 28，允许 JDK 26 / 27 / 28 作为 bootstrap；本轮使用 JDK 26。NoteLite 当前构建输出的 Java 21 普通 class 文件可由后续 JVM 读取；开启编译器 preview 选项本身不等于每个输出 class 都使用 preview 格式，仍需检查实际产物。

上游支持 iOS arm64 的 Zero 静态解释器，但 `make/modules/java.desktop/Lib.gmk` 在 iOS 上排除了 AWT / 2D 原生库；Java 类又沿用 macOS 的 Cocoa 字体与图形入口。因此仅编译官方 `libjvm.a` 不足以运行 Audiveris。

本仓库提供：

- `tools/audiveris-port/build-mobile-jdk.sh`：固定源码、libffi 3.5.2 及其 SHA-256；分别编译 iPhoneOS / iPhoneSimulator arm64，保留原始运行时基线和补丁后的产物。
- `tools/audiveris-port/build-mobile-jdk-tools.sh` 与 `package-mobile-modules.py`：从同一固定源码独立构建 macOS JDK 28 工具，再把 iOS 编译出的全部类、配置、资源与许可打包成运行时模块映像。
- `tools/audiveris-port/patch-mobile-desktop.py`：检查固定上游上下文，启用软件 AWT / FreeType / HarfBuzz / LCMS / JPEG；排除需要 X11、FontConfig、CUPS 和桌面窗口的路径。
- `tools/audiveris-port/mobile-desktop/`：用 `MobileGraphicsEnvironment`、`MobileToolkit` 与 `MobileFontManager` 接入真实软件渲染和打包字体。字体轮廓来自原 `app/res` 文件，默认文本后备字体为 `FinaleJazzText.otf`。
- `.github/workflows/audiveris-mobile-runtime.yml`：macOS 26 / Xcode 26.6 实际编译，上传每次日志与产物。构建成功和运行成功分开记录。

在 macOS 的仓库根目录执行：

```sh
bash tools/audiveris-port/build-mobile-jdk-tools.sh
tar -xzf build/mobile-tools/artifacts/mobile-jdk-host-tools.tar.gz -C build/mobile-tools
export MOBILE_JDK_HOST_HOME="$PWD/build/mobile-tools/jdk"
bash tools/audiveris-port/build-mobile-jdk.sh device
bash tools/audiveris-port/build-mobile-jdk.sh simulator
```

默认输出在 `build/mobile-jdk/<platform>/artifacts/headless/`：`static-libs/lib/` 包含真实静态库，`include/` 为 JNI 头文件，`jmods/` 为目标模块，`runtime/` 包含 `lib/modules`、配置、许可和原字体。模块映像由源码构建出的匹配 JDK 28 工具生成，不能直接交给 bootstrap JDK 26 的 `jlink`。嵌入应用时必须保留并导出静态 JNI 符号；Zero 从应用进程中解析它们。

第一次实际编译遇到 libffi 生成器仍配置 ARMv7、Xcode 26 已移除该目标；第二次发现项目文件仍引用 ARMv7 源与头文件。脚本已同时去除生成调用和对应项目记录，没有建立空源文件来掩盖缺失。修复后必须重新编译验证。

第三次的 device / simulator 均越过 libffi，进入 OpenJDK C++ 编译；直接构建 iOS `jmods` 时触发了上游尚未适配的动态库与交叉宿主构建，Apple 链接器拒绝 Linux 风格的 `-soname`。构建已改为官方 ios-tools 的静态库加目标 class 文件路线，使用独立 macOS 工具生成模块映像；CI 保存失败日志并重新验证该路线。

第四轮 [CI 36406804700](https://github.com/Lucas0623z/NoteLite/actions/runs/36406804700) 已实际构建匹配的 macOS JDK 28 工具，以及 device / simulator 两种 arm64 各 24 个运行时静态库（包括原始 Zero）。追加图形适配时，Java 编译因两个必须实现的旧 Toolkit 方法触发 deprecation 警告而失败；已对这两个方法分别添加抑制注解，并保留构建的严格警告检查。此轮尚未产出完整图形库和模块映像，不能作为完整引擎成功的证明。

静态链接还隔离了 JDK 自带 IJG JPEG 与 OCR 的 libjpeg-turbo：JDK JPEG 的 102 个 C 符号加独立前缀，JNI 名称保留，防止同一进程中两种实现错误互相调用。JDK 使用外部 zlib API，避免重复打包到 `libzip.a`。

固定上游的通用代码缓存仍请求可执行内存，但 Zero 不生成机器码：`assembler_zero.hpp` 说明其代码缓冲区保存入口记录，`zeroInterpreterGenerator.hpp` 写入 `ZeroEntry`，`entry_zero.hpp` 再调用已经编译的 C++ 函数。因此补丁仅在 `__IOS__ && ZERO` 条件下把 `CodeMemoryReserver` 的这块存储设为可读写，不请求执行权限，也不添加 JIT entitlement。其他平台和 VM 类型保留原行为；补丁检查原分配调用必须恰好出现一次。这项修改仍需随嵌入式运行时实际验证。

### 已执行的宿主适配测试

2026-09-28，在 Windows Java 21 上用相同的六个适配类替换 `java.desktop` 平台入口，实际执行了平台探针和完整进程内识别测试：

- 原 Bravura 音符头渲染为 200 个前景像素；灰度像素 SHA-256 为 `eea016321d734c624626efc4dd5805dcf2fc9f47aceb1a3bd8642b79cec86c18`。
- PNG 输出、ImageIO JPEG / TIFF 往返、JAXB Unicode、ProxyMusic 上下文、JavaCPP JPEG / TIFF 与 legacy OCR 调用通过；JPEG 同时执行 JDK 与 Leptonica 两条实现路径。
- 6 个嵌入式测试全部通过；`chula.png` 两次识别均导出 151 个有音高的音符和 220 个 MIDI note-on 事件，第三次通过 JNI 形式的 JSON 入口成功导出。
- `verify_embedded_score.py` 已对包括此适配器在内的 8 组宿主导出进行语义比较：19 个小节、151 个有音高音符及 7 个其他音符的音高、起点、时值、声部、延音线和 MIDI 事件均与基准相同。

这些结果说明平台 Java 适配没有阻断该样例的完整识别；它们使用宿主原生库，**不能证明 iOS 原生库或运行时已经通过**。可在 Java 21 宿主上重跑：

```sh
./gradlew -I tools/audiveris-port/oracle.gradle \
  -I tools/audiveris-port/test-mobile-desktop.gradle \
  :app:portProbe :app:embeddedOmrTest
```

设置 `TESSDATA_PREFIX` 为完整 tessdata 4.1.0 目录，至少包含支持 legacy 模式的 `eng.traineddata`。测试结果保存在 `app/build/port-probe/` 和 `app/build/test-results/embeddedOmrTest/`。

另一个 CI 作业 `host_runtime_validation` 使用上述固定源码构建的 macOS JDK 28：Gradle 与引擎编译仍用 Java 21，六个平台适配类改用该 JDK 28 的 `javac` 编译，探针和完整识别测试改由该 JDK 28 执行。此作业独立于 iOS 交叉编译；[CI 36410992236 的宿主作业](https://github.com/Lucas0623z/NoteLite/actions/runs/36410992236/job/108891052271) 已通过：

- 11 个测试，0 个跳过、失败或错误；重复识别、故障恢复、取消及其调用时序、沙盒、固定 PDF 分辨率和 JSON 库入口均完成。
- 单页重复导出各 151 个有音高音符 / 220 个 MIDI note-on；两页 TIFF 和 PDF 各导出 302 个有音高音符 / 440 个 MIDI note-on。
- 5 组单页导出的完整 MusicXML / MIDI 语义比较通过，差异列表为空。
- 图像、XML、legacy OCR 和真实 PDF 栅格化探针通过。Bravura 光栅为 197 个前景像素，SHA-256 为 `a38f07a0bc9d820d190c62b323bf642f005fb65aee56cbc62d5096f3133a749e`，与 Windows Java 21 的 200 像素结果不同。因此字体不是跨平台逐像素一致；这个完整曲谱样例的识别语义仍一致。

在已准备好 `MOBILE_JDK_HOST_HOME` 的 macOS 主机上，可切换 `JAVA_HOME` 到 Java 21 后运行：

```sh
./gradlew -I tools/audiveris-port/oracle.gradle \
  -I tools/audiveris-port/test-host-mobile-runtime.gradle \
  :app:portProbe :app:embeddedOmrTest
```

这样可以单独发现 JDK 28 API 与运行行为的差异；该宿主检查仍不能替代 iOS 静态运行时的实机执行。

## 其他路线的评估

- **Gluon / GraalVM AOT**：官方文档支持把 Java 库构建为 iOS 静态库，值得用完整核心做后续可行性实验。但它不会自动替换 AWT、ImageJ、反射或 JNI 依赖。官方要求在 macOS 上生成 iOS 构建；需要先确定与 Java 21 preview 字节码兼容的工具链，再验证所有依赖的 iOS 链接。参见 [Gluon 平台与静态库文档](https://docs.gluonhq.com/)。
- **J2ObjC**：能把 Java 业务代码转换为 Objective-C，支持多项 Java 语言与运行时特性，但不提供跨平台 UI 工具包。其官方构建要求 macOS、Xcode 和 JDK。上述桌面类型和原生绑定仍需适配；不能直接把整套 Audiveris JAR 转成可用引擎。参见 [J2ObjC 项目说明](https://github.com/google/j2objc)。
- **Swift 全量重写**：已实现的像素算法适合逐项验证；但重写完整符号图、模板、音乐语义和导出会扩大行为差异。当前继续保留这部分测试，同时推进完整 Java 引擎在设备内运行。

## 阶段与验收条件

1. **编译与链接**：device / simulator 的 Zero、软件图形字体库和 OCR JNI 均以真实 Apple SDK 编译；应用实际链接全部必需符号。
2. **平台能力运行**：在应用进程中创建 JVM，实际渲染 Bravura 音符头，完成 PNG / TIFF、JAXB / ProxyMusic 和 legacy OCR 探针。宿主 Windows 通过不能替代本步骤。
3. **完整识别与导出**：同一张曲谱在设备内经过全部识别步骤，导出有真实音符的 MusicXML 与 MIDI；比较音高、时值、声部、节拍和 MIDI 事件，并验证失败后恢复、重复识别和取消。
4. **产品接入**：完整识别在飞行模式下通过，移除用户必须配置服务器的依赖；在 iPhone 和 iPad 真机验证时间、峰值内存、热状态、取消和后台中断，再开放正式入口。

## 构建与测试结果应如何记录

- Swift 包测试、Java 对照测试、iOS Release 编译、iPhone 模拟器、iPad 模拟器、两种真机测试应分别记录结果，不能互相替代。
- CI 配置已经写入并不表示任务已执行；必须保留实际运行状态和日志。
- 此次开发主机是 Windows。审计时 PATH 中有 Java 21，但没有 `native-image`、`xcodebuild` 或 `xcrun`；本机无法生成或验证 Apple SDK 产物。macOS 构建与设备验证需要由相应 runner / 设备执行。
- 在完成完整识别验收前，不应把 Swift 调试输出、宿主测试或远端识别结果标记为“完整 Audiveris 已在 iPhone / iPad 本地运行”。
