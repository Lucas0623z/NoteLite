# NoteWise 引擎研究、许可边界与技术路线

核查日期：2026-10-12。现有行为审计基线：`0979fb2e3f982758219e17e95a2ebb4cae47c0de`。本文区分已经运行的实现、旧发行包中的依赖和后续研发路线。新的融合代码以其所在提交及该提交的测试结果为准，不能把这份研究当作全部乐器的准确率验收或法律意见。

## 1. 现有技术实际做了什么

目前可以将产品统一称为 **NoteLite 识谱 / NoteWise 听音**。统一的是输入、乐器配置、实际演奏事件、跟谱和反馈接口；底层包含自行实现的 DSP、第三方模型及录后基线。现有实现没有经过自有数据训练的通用多乐器模型，不能向投资人描述为“所有模型均为自研”。

| 组件、固定版本 | 真实部署和调用 | 许可及主来源 | 本地证据 |
| --- | --- | --- | --- |
| NoteWise MPM/YIN 原生实现 | Apple：AVAudioEngine/CoreMIDI，`nw_create_profile → nl_pitch_push → nl_events_push`；Windows：NoteLiteAudio.exe | 自写代码文件声明 MIT，按公开方程实现；不是 Pitchy 源码的 C 改名版。[MPM 作者论文](https://www.cs.otago.ac.nz/tartini/papers/A_Smarter_Way_to_Find_Pitch.pdf)、[YIN 作者论文](https://audition.ens.fr/adc/pdf/2002_JASA_YIN.pdf)。论文链接可核实来源，本轮未取得两篇完整正文，未作逐行原创性鉴定。 | [pitch.c](../native/audio/pitch.c)、[events.c](../native/audio/events.c)、[NoteWiseDSP.c](../apple/NoteLite/NoteWiseDSP.c) |
| miniaudio 0.11.25 | Windows 采音、录音、播放及 aubio adapter 的 WAV 解码；Apple 使用平台音频 API | 双许可中选 MIT-0，保留第三方子组件 notice。[固定版官方许可](https://github.com/mackron/miniaudio/blob/0.11.25/LICENSE) | [原生第三方说明](../native/audio/THIRD_PARTY_NOTICES.md)、[main.c](../native/audio/main.c) |
| Pitchy 4.1.0 | 旧 practice-web 的浏览器麦克风 fallback；不是当前原生 C 检测器 | **MIT，架构图中写 BSD 不准确**。[官方固定版许可](https://github.com/ianprime0509/pitchy/blob/v4.1.0/LICENSE) | [package.json](../practice-web/package.json)、[app.js](../practice-web/src/app.js) |
| Spotify Basic Pitch 0.4.0 / ICASSP_2022 | Apple 实际打包 CoreML，录后推理和 Swift 事件解码；Windows 可选本地 ONNX 录后推理 | Apache-2.0，需保留原始许可、NOTICE 和修改说明。[许可](https://github.com/spotify/basic-pitch/blob/v0.4.0/LICENSE)、[NOTICE](https://github.com/spotify/basic-pitch/blob/v0.4.0/NOTICE)、[原作者论文](https://arxiv.org/abs/2203.09893) | [MODEL-LOCK](../apple/NoteWiseModels/MODEL-LOCK.json)、[Swift decoder](../apple/NoteLite/NoteWiseBasicPitchDecoder.swift)、[录后 transcriber](../apple/NoteLite/NoteWisePolyphonicTranscriber.swift)、[Windows 调用](../local-analysis/analyze.py) |
| aubio 0.4.9 | Windows 可选录后 AubioMono.exe，实际调用 yinfast pitch / complex onset；独立进程且静态链接 aubio | GPL-3.0-or-later；不是 MIT 核心的一部分。进程隔离不能单独证明许可豁免。[固定版 COPYING](https://github.com/aubio/aubio/blob/0.4.9/COPYING)、[官方许可说明](https://aubio.org/) | [adapter](../native/audio/aubio_mono.c)、[运行时安装](../local-analysis/install_runtime.py)、[录后调用](../local-analysis/mono_analysis.py) |
| librosa pYIN 0.10.2.post1 | Windows 本地单音录后 F0、有声状态、onset 分割；不在当前 Apple 原生包 | 算法代码 ISC；其二进制依赖需另查。[固定版许可](https://github.com/librosa/librosa/blob/0.10.2.post1/LICENSE.md)、[pYIN 官方接口](https://librosa.org/doc/0.10.2/generated/librosa.pyin.html) | [Windows lock](../local-analysis/windows-lock.json)、[mono_analysis.py](../local-analysis/mono_analysis.py) |
| CREPE tiny | Windows 官方 HDF5 tiny 权重转换 ONNX；架构参考 `c9b71ce61491454125a0693f584f7244f29d9884`，权重来源 `bb29b8d99a89924476d112d27ed470e4ac5617c0` | 上游仓库 MIT。本轮未发现单独不同的权重许可；这不构成训练数据或专利权的全量保证。[固定源码许可](https://github.com/marl/crepe/blob/c9b71ce61491454125a0693f584f7244f29d9884/LICENSE)、[原作者论文](https://arxiv.org/abs/1802.06182) | [来源及转换说明](../local-analysis/vendor/README.md)、[crepe_onnx.py](../local-analysis/crepe_onnx.py)、[Windows lock](../local-analysis/windows-lock.json) |
| torchcrepe | 架构提到过；当前 lock、实际 Windows runtime 和 Apple 包中均未安装、未调用 | MIT，属于候选对照。[官方仓库](https://github.com/maxrmorrison/torchcrepe)、[许可](https://github.com/maxrmorrison/torchcrepe/blob/master/LICENSE) | 当前已实现的 `crepe_onnx.py` 不能标成 torchcrepe；没有其固定发行版本 |
| Partitura 1.9.0 | Windows MusicXML 规范化、反复展开、原谱 ID/实际音高、`load_musicxml` / `notes_tied`；Apple 有自己的谱面事件解析 | Apache-2.0。[固定版官方许可](https://github.com/CPJKU/partitura/blob/v1.9.0/LICENSE) | [score_tools.py](../local-analysis/score_tools.py)、[requirements-windows](../local-analysis/requirements-windows.txt) |
| Parangonar 3.3.3 | Windows 录后 `DualDTWNoteMatcher` 对照；项目支持其他方法不等于产品已经调用 | 实际固定 wheel metadata/许可证标 Apache-2.0。[官方仓库及许可](https://github.com/sildater/parangonar)。本轮没有发现可解析的 `v3.3.3` Git tag，不能伪造源码 commit。 | [score_tools.py](../local-analysis/score_tools.py)、[固定 wheel 与 SHA](../local-analysis/windows-lock.json) |
| Nakamura AlignmentTool_v240109 | Windows 九个编译工具，实际录后通过转换、HMM、ErrorDetection、RealignmentMOHMM 链路；不是实时跟谱检测器 | MIT，2019 Eita Nakamura；官方下载包 SHA256 `cf75af54435c6ad83a7b578b691724866f6df5701e8529d86ae2a3db1e85bddd`。[作者工具与手册](https://midialignment.github.io/)、[官方手册](https://midialignment.github.io/MANUAL.pdf) | [LICENCE.txt](../local-analysis/vendor/nakamura/LICENCE.txt)、[编译及 I/O 检查](../native/audio/build-analysis-tools.ps1)、[调用](../local-analysis/score_tools.py) |
| OpenSheetMusicDisplay | Figma/Apple lock 2.2.0；旧 practice-web 和服务端独立改谱网页 2.1.3。显示 MusicXML、指针和音符标记，不负责听音或 OMR | BSD-3-Clause。[2.2.0 官方许可](https://github.com/opensheetmusicdisplay/opensheetmusicdisplay/blob/2.2.0/LICENSE)；打包还需保留 VexFlow 等依赖声明。 | [Figma lock](../figma-ui/pnpm-lock.yaml)、[ScoreWorkspace](../figma-ui/src/app/ScoreWorkspace.tsx)、[服务器前端 notice](../server/standalone-omr/web/vendor/THIRD-PARTY.txt) |
| PianoBooster | 旧 Java 入口选外部安装程序并发送 MIDI；不属于当前 NoteWise 麦克风识音核心，外部版本未知 | GPL-3.0-or-later。[官方项目说明](https://github.com/pianobooster/PianoBooster) | [旧外部启动桥](../app/src/main/java/com/notelite/omr/practice/PianoBoosterLauncher.java) |
| Audiveris / Swift AudiverisCore | 服务器文档记录官方 5.11.0 OMR；旧 Java 代码和 Apple 部分 Swift 派生代码是不同边界。标准 Apple 项目仍链接 Swift 预处理包 | AGPL-3.0-or-later。[官方 5.11.0 LICENSE](https://github.com/Audiveris/audiveris/blob/5.11.0/LICENSE)。贡献身份不等于其他权利人的版权转让。 | [服务器边界](../server/standalone-omr/README.md)、[现有 package NOTICE](../apple/AudiverisCore/NOTICE.md)、[project.yml](../apple/project.yml)、[LocalOMRProcessor](../apple/NoteLite/LocalOMRProcessor.swift) |

Basic Pitch Apple 原始权重 SHA256 为 `691a6b63c7ddcdde0ee131ff3986dcb1250df47cd738612efde966ba9b4c99cd`。CoreML `divide_no_nan` 修改是数值安全的图修改，未重训/修改权重，详见 [图修改记录](../apple/NoteWiseModels/DIVIDE-NO-NAN-PATCH.json) 和 [原始模型 notice](../apple/NoteWiseModels/THIRD-PARTY.txt)。独立自写融合规则不能把这个模型改写成自有训练成果。

### 二进制依赖仍需单独看

Windows 已有包中找到 58 个实际 Python distribution 的 LICENSE/METADATA，包含上述直接依赖和传递依赖。去掉 aubio 并不意味着整个 Python runtime 都是 MIT/Apache：

- python-soxr 0.5.0.post1 的 libsoxr 部分为 LGPL-2.1-or-later。[官方固定版许可](https://github.com/dofuuz/python-soxr/blob/v0.5.0/LICENSE.txt)
- soundfile 0.12.1 的 Python 包为 BSD；随包 libsndfile 是 LGPL 库。[官方打包说明](https://github.com/bastibe/python-soundfile/blob/0.12.1/README.rst)
- NumPy/SciPy wheel 内的 OpenBLAS、GCC runtime exception / libquadmath 有各自条件。必须按实际 wheel 的 license 和链接形式核查，不以顶层 Python 包许可证代替。
- JSZip 提供 MIT 或 GPL 双许可，可选 MIT；在 notice 中出现 GPL 一词不自动代表程序必然按 GPL 授权。原始依赖声明仍应保留。

本次没有重新部署服务器，也没有读取生产用户数据、录音或 API 密钥。

## 2. 能力边界与融合设计

### 乐器自动路由应依据什么

识谱后的 `score-part` 名称、乐器名、显式 MIDI program、声部、谱号、移调值，是可用的谱面证据。缺失、互相矛盾或只有默认 Piano 的信息，应返回 `unknown` / 待确认，保留用户手动选择。不能把 OMR 自动填入的 GM Piano 当作声学分类结果。多乐器谱应按所选练习声部路由，而不是把整份谱都套到第一个声部。

统一 NoteWise 应记录 `instrumentId`、证据来源、置信度、所选声部、实音移调、设备输入、能力与模型版本。相同谱子在浏览器、Windows 和 Apple 需要共用乐器定义；采音由平台适配。乐器推断与听音路由是可以现在实现并测试的软件功能，**从任意录音准确识别乐器**属于另一项待训练/评测能力。

### 各输入的职责

| 场景 | 应用路径 | 必須保留的不确定性 |
| --- | --- | --- |
| MIDI 乐器 | 平台 MIDI → 独立音符起止/力度事件 → 跟谱与反馈 | MIDI 不提供实际声学音准或踏板后的听感；velocity 0 是 note-off，不能凭谱面补音 |
| 单音旋律实时练习 | 本地 MPM/YIN → 噪声/周期性/重起音判断 → 实際事件 | 低音窗口、颤音、滑音、强泛音、静音与噪声；持续同音和重弹同音要区分 |
| 钢琴/吉他和弦麦克风 | 当下实时单音结果只报告已有能力；录后 Basic Pitch 多音复核 | 不能将一个实时 F0 说成“全和弦正确”；当前 Basic Pitch 是录后，不宣称全复音即时评分 |
| 录后单音复核 | Windows pYIN / CREPE / 可选 aubio 独立对照 | 模型冲突标待复核，保留原始候选及来源，不能强行投票为正确 |
| 原谱匹配 | 实际事件进入在线状态机；Nakamura/Parangonar 仅作录后基线 | 允许错音、漏音、多音、重来、重复段和停顿；未判断不等于漏音/错音 |
| 评分 | 自有规则、置信度与教学反馈 | 音高身份、音分、起音、时值与未判状态分开；严格节拍和自由跟谱使用不同节奏约束 |

Basic Pitch 原作者明确说明模型支持多音乐器、面向跨乐器转录，单乐器同时演奏是更合适的输入；它没有“检测出具体乐器”接口。[官方 0.4.0 使用说明](https://github.com/spotify/basic-pitch/blob/v0.4.0/README.md) 基线的 88 键/MIDI 音域和 contour 输出分辨率不保证任意低音、高音或专业音分评分。其窗口推理也不能直接替代当前实时链路。

CREPE 的有限频域和置信度不是全音域保证。torchcrepe 官方说明 CREPE 未用静音训练，静音可能仍给高置信度；有声/能量门禁应独立建立。[官方解码与静音说明](https://github.com/maxrmorrison/torchcrepe#filtering-and-thresholding) 阈值必须用产品数据校准，不能照搬语音例子的参数当乐器验收。

### 融合规则的关键设计

1. **先听实际演奏，再跟谱。** 检测器输入只有音频/输入事件及乐器能力配置，不以当前应弹音强迫替换预测。谱面只用于后续位置搜索及教学提示，避免“拿答案改检测结果”。
2. 保留 blind acoustic candidates、能量、有声状态、onset、release、时间来源和 detector/model version。针对八度误判、重弹与长音建立可解释的拒绝/复核规则。
3. 各模型置信度先校准，再融合。多个高度相关模型“都说同一个音”不意味着独立证据；尤其不能只以检测器数量抵消噪声。
4. 单音/复音、自然 release/停止录音截断、MIDI/麦克风须显式区分。不同通道的时间基准要统一，结束 session 不应伪造自然音符结束。
5. 快速纠错可先给“疑似错误/待复核”，录后再增加证据。尚无证据时保持 0 条观察或未判断，不能生成满分、练习天数或既有演奏记录。

## 3. 已核实的版权与 Apple 发行边界

### 已知与未知

- 自有代码的 MIT 声明只适用于有权独立授权的部分，不替换 Audiveris/AGPL、aubio/GPL、Spotify/Apache 的条件。组合后的发行义务需按实际结合方式判断。提供源码和保留 notice 是必要工程补齐，不等于所有法律问题已结束。
- AudiverisCore 与官方 5.10.0 commit `b02fd4f8e31bf3dee1124bf4956e60fcca7f00a0` 的六个 Java 算法正文，经忽略注释、空白和恢复包名后匹配。该 reference 可复核，但 fork 导入历史没有上游 ancestry，唯一原始 fork 点未知。没有为了填表而把服务器 5.11.0 commit 填成 Swift 派生代码来源。[完整本地 provenance](../apple/Legal/AUDIVERISCORE-PROVENANCE.json)
- 已有 Build 14 IPA 检查可见相关模块/派生类型名且缺少完整 AGPL notice 资源；这是实际包和源码发现，不是完整 Mach-O 可达性证明，也不单凭字符串作法律侵权结论。本轮保留此功能，并加入完整 license/provenance/source-offer 资源。
- 当前客户端未包含完整 OMR/JDK，并不代表它完全没有 AGPL：静态 Swift 部分仍是实际依赖。客户端/服务器分开部署和独立进程只是工程边界，不能据此自动认定都是许可意义的独立作品。
- 未看到覆盖所有权利人的 App Store 特别许可、版权转让或专利授权文件。维护者/贡献者通常能授权其自有贡献，不能由此推定能替其他作者或其雇主授权。[GNU 关于权利人和额外许可的说明](https://www.gnu.org/licenses/gpl-faq.en.html#GPLIncompatibleLibs)

### Apple 附加限制需要另行处理

AGPL 第 6 节涉及对象码对应源码及某些场景的安装信息；第 10、12 节涉及附加限制及冲突；修改后的网络服务另有第 13 节源码获取义务。[GNU AGPL 原文](https://www.gnu.org/licenses/agpl-3.0.en.html) 因此“服务器才放 OMR”不使修改服务的源码义务消失，“公开一个 repo”也不能自动解决所有对象码/安装问题。

Apple 当前标准 EULA 有设备/使用规则、转让/分发限制，同时在禁止修改/反向工程的段落为开源许可保留了例外。[Apple 当前 EULA](https://www.apple.com/legal/internet-services/itunes/dev/stdeula/) FSF 对 App Store/GPL 的官方解释明确讨论了附加限制，并说明其观点适用于 GPL 和 AGPL。[FSF 原始解释（2010，历史材料）](https://www.fsf.org/blogs/licensing/more-about-the-app-store-gpl-enforcement) 旧案例不能直接当作本应用在 2026 年的最终裁决；当前的 Apple 协议、渠道、DRM、安装信息及所有相关权利人的额外许可应一起审查。

可行路径是核实完整权利链并取得有效渠道例外/商业授权，或在保留云端 OMR 的前提下评估今后用独立原创/许可适配的客户端预处理替代该派生依赖。**本轮没有擅自替换或移除 Audiveris 功能，也没有声明已完全法律合规。** 如所有相关义务不能同时满足，就不能靠改名、加壳或一个 NOTICE 宣称可以发行。

### 这次工程补齐的可验证范围

[Apple 法律资源](../apple/Legal/) 包含完整 AGPL 文本、具体上游/本地源路径、修改说明和重建方法。`SOURCE-OFFER.json` 在构建时从本次 `GITHUB_SHA` 生成，指向公开仓库对应 commit 的 tree/archive，而不是写死审计基线或浮动 `main`。

[legal_resources.py](../apple/release/legal_resources.py) 与 [cloud_release.py](../apple/release/cloud_release.py) 验证**实际 app/archive/IPA**的 license/notice 字节、完整 AGPL 文本 hash、对应源码 hash 与 commit。缺文件、缩成 URL、替换 notice、陈旧 offer 或多余法律资源均应拒绝。门禁结果明确记录 `distributionCompatibilityEstablished: false`；它验证工程证据，不代替发行权利审查。发布者仍须维持公开源码可获取，并遵守相应源代码与安装信息义务。

## 4. 可以形成技术壁垒的路线

下列是研发建议及衡量标准，不是已完成的模型或已有专利。公开上游算法、自有 MIT 源码和别人合法收到的许可，不会因重命名、混淆或换仓库而失效。加密模型资源、代码签名、授权与完整性检查只能提高复制/篡改成本，不能保证客户端永远不可解包。技术竞争力应落在独有授权数据、实测结果和持续教学反馈上。

### 第一阶段：可解释融合与产品数据质量

- 统一跨端事件和乐器能力协议、模型/配置版本、离线回放 fixture 和错误案例归档。
- 优先针对弱音、低音、八度泛音、同音重弹、长音、混响和踏板，做 onset/release/quality 校准。保留旧检测器独立结果，要求新融合优于最强单基线而不是只优于一个过时检测器。
- 建立“未知/待复核”质量曲线：降低误报的同时记录拒绝率，不能用拒绝全部困难样本换取表面准确率。
- 用教师核对“系统是否指出了真正的错音、小节定位是否准确、是否打断练习”评价教学体验，而不仅是模型帧准确率。

### 第二阶段：有明确商业授权的数据集

自行委托/合作采集成对音频与 MIDI/人工标签，建立数据条目：乐器及型号、音域、演奏者、授权范围、房间/设备、曲目/版本、音符起止、踏板、错音/漏音/多音、噪声、人工审核。采集演奏权、曲谱/作品权、录音权和训练/商用权要明确，版权和隐私授权分开记录。

用户现有选择是**曲谱和练习数据同步，录音留本机**；不得为了训练而默认上传录音。训练用途需要另行明确同意、可撤回/删除流程，测试 fixture 只用可公开、获许可的非个人录音。

公开数据能辅助研究，但应按精确版本逐个核查。例如 [MAESTRO 官方数据说明](https://magenta.tensorflow.org/datasets/maestro) 标注 CC BY-NC-SA 4.0，不能默认用于商业训练；[NSynth 官方说明](https://magenta.tensorflow.org/datasets/nsynth) 标注 CC BY 4.0，可用作经审查的单音/音色研究输入，但它的短单音样本不证明真实手机环境连续演奏表现。使用现成模型蒸馏，也须先核查模型、数据及授权，不将“模型输出”当作可以绕过条件的捷径。

训练/验证/测试必须按演奏者、乐器实体、设备、房间和曲目分组，防止相同录音切片或同曲复制进入训练和测试。每个比较模型使用相同测试音频、事件匹配容差和评分规则。真实学生错误比一首全部正确的示范曲更有辨识价值。

### 第三阶段：独立自有模型与可衡量优势

在授权数据上开发因果流式多任务模型：有声状态、起音、单/复音、release、音高/音分、质量与失败原因。先按乐器家族做 profile/专家能力，再评估共享编码器＋小型专家头，避免每个乐器重复携带一个大型 runtime。已有 Basic Pitch 与 pYIN/CREPE 保持为对照，不伪装成自有权重；第三方基线可依授权继续使用。

| 验证项 | 应记录的指标与产品判断 |
| --- | --- |
| 单音实际事件 | onset/pitch/release F1、八度错误、低音/高音分桶、同音重弹召回；音分误差只在有可靠连续 F0 的场景评分 |
| 复音 | 按和弦大小、踏板、乐器分别统计 note F1；不能用单音准确率代替复音能力 |
| 不确定性 | ECE/可靠性图、错误提示 precision、拒绝率及 coverage-risk 曲线；强调“疑似错误”与确认错误分离 |
| 跟谱 | 小节/音符绑定准确率、跳段与反复段恢复时间、停止重来后的错误累积；自由/严格节拍分别评估 |
| 实时体验 | 音频时间戳到 UI 的端到端 P50/P95/P99、欠载/丢帧、低音窗口成本；在目标真机持续演奏，不用模型内核耗时替代 |
| 移动端性能 | CPU、峰值内存、模型常驻内存、耗电与温度、后台恢复；按机型、系统、麦克风逐项留证据 |
| 稳定及数据迁移 | 实际账户间隔离、曲谱和练习历史换机还原、退出/注销清理；同期录音仍按用户意愿保留本机 |
| 教学效果 | 每分钟误打断次数、老师核对率、学生重练完成率；与检测准确率并列，不把 AI 文字分析替代原始事件证据 |

只有在冻结测试集上验证新模型/融合达到优势，且版权链完整、目标设备的端到端体验通过，才可以对外说明相应自主技术能力。专利可行性还需要新颖性/现有技术和权利要求审查，本轮研究不保证可专利或自由实施。

## 5. 验证证据应如何解读

本轮审计阅读了实际已有 Apple 1.0.0 Build 14 IPA 和 Windows `b262b02` 的 5.13.1 包；Windows `runtime-ready.json` 是旧提交的实际运行 smoke 证据，不能当作新融合代码的实跑。目录存在、锁文件有名称、测试 mock 返回成功，都不等于该模型正在目标设备中运行。

本轮新增 release 法律资源门禁测试，在 Windows 执行 20 项：19 项通过，1 项依赖 macOS 真实 codesign 的测试按平台跳过。新增用例覆盖实际 app 缺失/篡改许可证和 notice、缩水为 URL、源/包一起被改、错误源码 commit/archive、源码包改变、陈旧 offer 与 dirty source。测试中的模拟 app 只证明门禁逻辑，不能代替 Xcode 实际资源入包、真机听音或发行合法性的验收。

所有后续报告应同时列出 source SHA、模型 SHA、平台/机型、是否真实音频、输入来源和不通过/未测试项目。Apple CI 应在同一个提交上实际构建 simulator/device/macOS，并检查 actual bundle；全乐器真人录音和 TestFlight 实机验证仍需要其自身证据。

## 6. 本轮已经落地的融合核心

这是**已有检测器＋原创融合与产品规则**，没有重新训练第三方权重，也没有把多个依赖重新命名后声明成独立自研模型。Audiveris 的识谱实现保持原有职责；NoteWise 接收其 MusicXML 元数据和实际演奏输入。

- 35 个跨端乐器 profile 共用名称、音域、移调变体和带版本的融合策略。路由依据所选声部、逐音符 instrument ID、明确乐器名/GM 信息、谱面移调或用户确认。谱号和音域不单独作为乐器身份依据；不存在任意录音的声学乐器分类器。
- MIDI 直接使用实际事件。麦克风实时保留原生 MPM/YIN 单音能力；和弦不会因其中一个音正确而被宣称整体正确，结束后在本机复核录音。
- Windows 单音使用 pYIN 与 CREPE 独立事件对应，复音使用 Basic Pitch 与独立 PCM 起音/频谱证据。CREPE 有限频域之外的候选不能因复核器没有结果被当作漏音。可选 aubio、旧手动检测器和录后匹配基线仍保留。
- Apple 单音使用原生 MPM/YIN 与已打包的 Basic Pitch CoreML 交叉复核，复音使用 Basic Pitch 与 PCM 证据。主检测器与复核器冲突、独立证据缺失、超出乐器或模型能力范围均保留不确定区间。Apple 当前要求一次练习确认一个乐器；Windows 仅允许同一声部、不重叠、已明确标注的同家族顺序换乐器，其他多声源仍需用户分声部。
- 所有检测器只获取实际音频和宽泛乐器能力范围。谱面预期音高只进入后续匹配，不用于把预测修成应弹音。交叉一致并未被伪装成经过校准的正确概率，评分仍区分音高、起音、时值、音准与未判断。

确定 bug 已修：长谱的逐音符配置误触发乐器数量上限；GM 7/8/22/23/24 映射；不明乐器引用；未知手动谱制静默回退；实音谱标记后手动重复移调；缺少录后置信度被当成正确；批处理状态残留为 uncertain；输入/乐器/调音在同次录音恢复时改变；采样数固定按 48 kHz 计算。普通停止将等待 native 输入尾事件后才结束匹配，取消、注销与账号切换继续隔离原账户。

性能修复用 source/occurrence 索引代替每次线性找原音符，匹配器不再排序修改调用者数组，录后批处理跳过不需要的界面反馈。相同 Windows 环境、相同 4,000 个合成 MIDI note-on、同一匹配器的事件处理阶段：旧默认空反馈约 24,078 ms，本轮无界面回调约 2.32 ms，带当前反馈回调约 1,113 ms；全部匹配完成且覆盖数一致。此结果不包含 XML 解析、录音、模型推理或 UI 绘制，不是手机端延迟/功耗，也不能作为模型准确率。

复现入口：`pnpm --dir figma-ui typecheck`、`pnpm --dir figma-ui test`、`npm --prefix practice-web test`、本地分析的 `test_fusion.py` 与 `test_score_tools.py`、原生 `NoteWise*Tests`、`FigmaLegalInformationTests` 和发布门禁。实际 Windows 模型测试使用已锁定的本地 runtime；新增 native 案例必须在 macOS、iPhone/iPad 模拟器执行才算通过。公开仓库源文件、提交、CI 叶测试与实际 app 资源证据分别保留，不能用本地语法检查代替。

仍需后续优化和目标设备实测：长录音的 CoreML 窗口/峰值内存、密集复核候选的时间索引、连续 UI 反馈的增量更新、真实低音/踏板/混响的拒绝率与误报，以及经授权真人录音的模型比较。当前没有全乐器真机评测，也没有证明融合精度优于最强单模型；这些是下一阶段测量项，不能先写成已完成的商业优势。
