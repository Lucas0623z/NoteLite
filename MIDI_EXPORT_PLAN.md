# MIDI Export 功能实现计划

## 1. 背景与目标

NoteLite 当前只支持把识别结果导出为 **MusicXML**（`.mxl` 压缩 / `.xml` 普通）。本计划增加**自带的 MIDI（`.mid`）导出能力**，无需用户额外安装 MuseScore、Finale 等外部软件，做到「下载即用」。

* 目标：在「文件」菜单和「文集 / 谱页」相关动作里，直接出现「导出为 MIDI...」选项，导出符合 General MIDI 规范的 Standard MIDI File (SMF) Type 1 文件。
* 不目标：取代专业排版软件的 MIDI 输出。我们的 MIDI 用于**试听 / 验证识谱结果是否正确**，不追求演奏级表现力。

---

## 2. 约束与判断

| 项 | 决策 | 理由 |
|---|---|---|
| 是否打包外部软件 | **不打包** | MuseScore 安装包 ~200MB，许可与体积都不可接受 |
| 转换路径 | `内存 ScorePartwise` → `javax.sound.midi.Sequence` → `.mid` | 复用现有 `PartwiseBuilder` 输出，不重新解析 XML |
| MIDI 库 | **JDK 自带 `javax.sound.midi`** | 0 依赖，跨平台 |
| MIDI 文件类型 | **SMF Type 1**（多 Track） | 每个 Part 一个 Track，最直观 |
| Tempo 默认 | 120 BPM (500000 µs/quarter) | 标准默认 |
| MIDI 分辨率 | 480 PPQ | 通用值，可整除常见分母 |
| Velocity | 全部音符 80 | 不读 MusicXML 力度记号（第一版） |

---

## 3. 数据流

```
用户点击「导出为 MIDI...」
        │
        ▼
  BookActions.exportSheetAsMidi(...)   /   exportBookAsMidi(...)
        │
        ▼
  ExportMidiTask（继承 PathTask，后台运行）
        │
        ▼
  PartwiseBuilder.build(score)  ← 已有逻辑，返回 ScorePartwise
        │
        ▼
  MidiExporter.export(scorePartwise, outputPath)   ← 新增，本计划核心
        │
        │  walks ScorePartwise:
        │   - 每个 ScorePart  →  一个 MIDI Track
        │   - 每个 Note       →  NoteOn + NoteOff（按 division 换算 tick）
        │
        ▼
  javax.sound.midi.MidiSystem.write(sequence, 1, file)
        │
        ▼
  .mid 文件落盘
```

---

## 4. 文件改动清单

### 新增

| 文件 | 用途 |
|---|---|
| `app/src/main/java/com/notelite/omr/score/MidiExporter.java` | MusicXML→MIDI 主转换器（~300 行） |
| `app/src/main/java/com/notelite/omr/sheet/ui/ExportMidiTask.java` | 后台任务包装（~80 行） |
| `app/src/test/java/com/notelite/omr/score/MidiExporterTest.java` | 单元测试（~150 行，至少覆盖：单音、和弦、休止、连音线、多 Part） |

### 修改

| 文件 | 改动 |
|---|---|
| `app/src/main/java/com/notelite/omr/sheet/ui/BookActions.java` | 加 `exportSheetAsMidi`、`exportBookAsMidi` 两个 `@Action`；加 `.mid` 文件过滤器 |
| `app/src/main/java/com/notelite/omr/sheet/ui/resources/BookActions.properties` | 加菜单项英文文案 |
| `app/src/main/java/com/notelite/omr/sheet/ui/resources/BookActions_zh_CN.properties` | 加菜单项中文文案 |
| `app/src/main/java/com/notelite/omr/sheet/ui/resources/BookActions_fr.properties` | 加菜单项法文文案（保持上游风格） |
| `app/src/main/java/com/notelite/omr/OMR.java` | 加常量 `MIDI_EXTENSION = ".mid"` |
| `docs/_pages/...`（如有） | 更新用户文档说明 MIDI 导出 |

---

## 5. 核心转换映射规则（MusicXML → MIDI）

### 5.1 时间换算

* MusicXML 用 `<divisions>`（每四分音符的子单位数），每个 `<note>` 有 `<duration>`（以 division 为单位）。
* 我们固定 MIDI PPQ = **480**。
* `midiTick = noteDuration × (480 / divisions)`

### 5.2 音高换算

```
MIDI pitch = (octave + 1) × 12 + stepOffset[step] + alter
stepOffset: C=0, D=2, E=4, F=5, G=7, A=9, B=11
```

例：A4（标准音 La）= (4+1)×12 + 9 = 69 ✓

### 5.3 元素处理

| MusicXML 元素 | MIDI 处理 |
|---|---|
| `<note>` 普通音 | NoteOn @ 当前 tick, NoteOff @ +duration |
| `<note>` 含 `<chord/>` | 与上一个音 **同 onset**，不推进 tick |
| `<note>` 含 `<rest/>` | 仅推进 tick，无事件 |
| `<note>` 含 `<tie type="start">` | NoteOn 正常，记录 pending tie |
| `<note>` 含 `<tie type="stop">` | **不发新 NoteOn**，把上一个 NoteOff 推迟 +duration |
| `<note>` 含 `<grace/>` | 短时值（30 ticks）后立即 NoteOff |
| `<backup>` | 当前 tick **后退** `<duration>` |
| `<forward>` | 当前 tick **前进** `<duration>` |
| `<sound tempo="N"/>` | Tempo Meta Event @ 当前 tick |
| `<time>` 拍号 | TimeSignature Meta Event |
| `<key>` 调号 | KeySignature Meta Event（可选） |
| `<score-instrument>` + `<midi-instrument>` | Track 起始的 ProgramChange |

### 5.4 Track 结构

```
Track 0: 全局 meta（tempo, time signature, copyright）
Track 1..N: 每个 ScorePart 一个
  ├─ ProgramChange (instrument)
  ├─ NoteOn / NoteOff 序列
  └─ EndOfTrack
```

---

## 6. 第一版**不**做的事（明确给后续留口子）

| 项目 | 不做的原因 |
|---|---|
| 力度记号 (pp/mf/ff) → MIDI velocity | MusicXML `<dynamics>` 解析与映射规则复杂，先固定 velocity=80 |
| 转调乐器 transpose | 需读 `<transpose>` 元素并改音高，先按记谱音高 |
| 鼓组 / 不定音高打击乐 → MIDI Channel 10 | `DrumSet` 映射表需仔细验证，先按普通音高出（听起来怪但不阻断） |
| 反复记号、跳跃 (repeat / D.S. / Coda) 展开 | 第一版按谱面线性顺序，不展开反复 |
| 装饰音 (trill / mordent / turn) | 不展开为 MIDI 颤音事件 |
| 圆滑线 / 连奏 → MIDI legato | 不影响时长，跳过 |
| 颤音 (tremolo) | 不展开成多个音符 |
| 演奏标记（staccato 缩短时值等） | 不调整 |

这些都列入 **Stage 2** 增强项，第一版不阻塞 release。

---

## 7. UI / 用户体验

### 菜单项位置

```
File
├── Input...
├── Open books...
├── Save book
├── Save book as...
├── Export book                ← 现有，导出 MusicXML
├── Export book as...          ← 现有，导出 MusicXML
├── Export book as MIDI...     ← 新增 ★
├── Export sheet as...         ← 现有
├── Export sheet as MIDI...    ← 新增 ★
└── ...
```

中文菜单：

* `导出文集为 MIDI...`
* `导出谱页为 MIDI...`

### 文件选择器

* 默认扩展名 `.mid`
* 默认路径：与 MusicXML 同目录、同 basename，扩展名换 `.mid`
* 文件名冲突时复用 `isTargetConfirmed(...)` 弹覆盖确认

---

## 8. 测试计划

### 8.1 单元测试 `MidiExporterTest.java`

最少 5 个用例：

1. **单声部单音符**：构造一个 ScorePartwise（A4, 四分音符），导出后用 `MidiSystem.getSequence(file)` 反读，断言 NoteOn 在 tick 0 / pitch 69 / NoteOff 在 tick 480。
2. **和弦**：3 个音同 onset，断言 3 个 NoteOn tick 相同。
3. **连音线**：两个相同音通过 tie 连接，断言只有 1 次 NoteOn / 1 次 NoteOff，总时值是两个 duration 之和。
4. **休止符**：休止符后接音符，断言音符 NoteOn 的 tick 包含休止时长。
5. **多 Part**：两个 Part 各一个音符，断言生成 Type 1 sequence 有 2 个 Track（不算 meta track）。

### 8.2 端到端验证

用之前用过的 `IMSLP909050 - Stamitz Flute Concerto` PDF：

1. 启动应用，导入 PDF，转写完成
2. `File → Export book as MIDI...`，保存 `Stamitz.mid`
3. 用任意 MIDI 播放器（VLC / Windows Media / `timidity`）打开播放
4. 验证：能播放、音高与谱面一致、节奏大致对、整本播完不崩溃

### 8.3 兼容性 smoke

目标 MIDI 能被以下软件正常打开：

* Windows Media Player
* MuseScore 4
* macOS GarageBand
* Linux `timidity`

---

## 9. Release Notes 草稿

```markdown
# NoteLite v5.10.3 (2026-04-XX)

## 新功能

- ★ **MIDI 导出**：`File → Export book/sheet as MIDI...` 直接生成 `.mid` 文件，
  无需安装 MuseScore 等外部软件。
  支持单声部、多声部、和弦、连音线、休止符、Tempo 标记。
- 中文（简体）界面汉化（菜单、对话框、面板标题、步骤名）

## 已知限制（第一版）

- 力度记号未映射到 MIDI velocity（统一 80）
- 鼓组按普通音高输出（听起来与原谱不一致）
- 反复记号不展开
- 转调乐器按记谱音高输出

## 修复

- 修复启动时 GitHub 版本检查 NPE
- 修复 JDK 21 编译时 source release 错误（要求 JDK 21+）
```

---

## 10. 实施分阶段

| 阶段 | 内容 | 预计 |
|---|---|---|
| Stage 1 | `MidiExporter` 核心 + 单元测试（5 例全过） | 2–3 小时 |
| Stage 2 | `ExportMidiTask` + `BookActions` 接线 + 资源文件 | 1 小时 |
| Stage 3 | 端到端跑 Stamitz PDF，听感验证，修明显问题 | 1–2 小时 |
| Stage 4 | 整理 commit、写 CHANGELOG、打 tag、cut release | 0.5 小时 |

总计：**4.5–6.5 小时**，可一次性完成。

---

## 11. 风险与回退

| 风险 | 应对 |
|---|---|
| 复杂谱子导出后时序错乱 | 把 `<backup>` / `<forward>` 处理写得保守，配合 ScorePartwise 单元测试 |
| 多声部 voice 串道 | 第一版每个 Part 单 channel；多 voice 在同 Part 共享 channel，依赖 NoteOn/NoteOff 配对（不依赖 voice 信息） |
| `MidiSystem.write` 在某些 JDK 下抛异常 | 已知 OpenJDK 21 GA 稳定；测试 CI 加 smoke |
| 用户报"我的谱子转出来不对" | release notes 明确"试听用、不保证演奏级"；若是常见模式，进 Stage 2 修 |

---

## 12. 验收标准

* [ ] `gradlew :app:test` 全过（含 5 个 MidiExporterTest）
* [ ] 端到端：Stamitz 长笛协奏曲 PDF → MIDI → MuseScore 4 能播放、音高节奏目测正确
* [ ] 菜单项 `导出文集为 MIDI...` / `导出谱页为 MIDI...` 中英文显示正确
* [ ] release notes 写完，tag `v5.10.3` 已打
* [ ] GitHub release 页面有可下载的 jar / installer
