# NoteLite 独立识谱模块

本模块仅包含谱面上传、Audiveris 识谱、识谱结果、谱面校对和 MusicXML/MIDI 导出。

识谱引擎是官方 Audiveris 5.11.0 Ubuntu 24.04 x86_64 发行包，自带 Java 25.0.3；服务器上的识谱入口为 `/usr/local/bin/audiveris-omr`。入口使用无图形模式、4GB Java 堆上限和单任务锁。OCR 采用官方完整 tessdata 4.1.0 的 eng、chi_sim、chi_tra 模型。

MusicXML 转 MIDI 复用 NoteLite 的 MidiExporter 算法，仅抽离了与桌面 Score/PartwiseBuilder 的耦合。MusicXML 修改成功并生成新 MIDI 后，才发布新修订。原始谱面、OMR 工程和已保存修订用于继续校对。

## 服务器文件

- `/opt/audiveris`：未经修改的官方引擎及 Java 运行库。
- `/opt/notelite-omr`：独立识谱、编辑、导出模块及其源码。
- `/var/lib/audiveris/jobs`：识谱任务和修订。
- `/var/lib/audiveris/tessdata`：OCR 模型。
- `/var/lib/audiveris/verification`：真实 PNG/PDF 验收记录。
- `notelite-omr.service`：以 audiveris 用户运行，内存和 CPU 有上限。

服务默认只监听 `127.0.0.1:8765`。访问口令由服务保存到仅 audiveris 和 root 可读的文件中；调用时使用 Authorization 请求头，避免把口令放进 URL。

## 谱面编辑

页面使用本地 OpenSheetMusicDisplay 渲染 MusicXML；可在音符列表选择音符，并在谱面查看蓝色高亮，再修改音高、升降号、八度、时值、附点、休止或删除。完整 MusicXML 编辑区可修改其他记谱内容。多乐章分别显示、保存和导出。原图、PDF 和 OMR 工程保持作为校对依据。

识谱结果需要人工核对，识谱处理和导出成功并不等于音符与原谱百分之百一致。页面保留识别警告和处理日志。

## MIDI 转换器构建

使用 Java 17 或更高版本的 JDK，把 `java/com/notelite/omr/score` 中的两个源文件编译为 JAR。编译依赖来自官方 Audiveris 安装目录 `lib/app` 中的 proxymusic、JAXB、SLF4J；运行入口为 `com.notelite.omr.score.OmrMidiConverter input.musicxml output.mid`。

## 来源和许可

Audiveris 官方版本：https://github.com/Audiveris/audiveris/releases/tag/5.11.0

NoteLite：https://github.com/Lucas0623z/NoteLite （抽取基线 b262b024d393dd744f328b21caa2c8f59ba5a3ef）。

抽取的 MIDI 代码及本模块按 AGPL-3.0-or-later 提供，对应源码随模块提供；保留 NoteLite 原项目 MIT 许可声明。OSMD 和其依赖的许可见 `web/vendor/THIRD-PARTY.txt`。OCR 模型含其 Apache-2.0 许可。
