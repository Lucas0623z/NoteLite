# NoteLite v5.11.0 — MIDI 导出实现计划

> 这是 NoteLite 下一个版本（5.11.0）的核心新功能：**自带 MIDI 导出**，不依赖外部工具（MuseScore、Finale 等）。
>
> 本文档同时是**技术规范 + 接续手册**：任何人（包括未来对话的 Claude）拿到这份文档应该能从零启动 Stage 1 实现而不需重新摸代码。
>
> **预设阅读顺序**：
> 1. 节 §1–§3（背景、范围、当前状态）— 5 分钟看完
> 2. 节 §4（架构 / 调用链）— 必读，否则不知道从哪下手
> 3. 节 §5–§8（数据映射、Stage 实施、代码骨架、测试）— 实施时按顺序参考
> 4. 节 §9–§11（验收、风险、release notes 草稿）

---

## 1. 背景与现状

NoteLite 是 Audiveris OMR 引擎的一个 fork，由 Lucas0623z 维护，许可证 MIT。当前最新发行版 **v5.10.3**（2026-04-27 发布）只能导出 MusicXML（`.mxl` / `.xml`）。

用户需求：用户下载 NoteLite 后**开箱即用 MIDI 导出**，不需要再去装 MuseScore 等外部软件。

排除的方案：
- ❌ 打包 MuseScore 进发行包（MuseScore 安装包 ~200 MB，许可证不允许）
- ❌ 调外部 CLI（违背"开箱即用"前提）
- ❌ 用第三方 Maven 库（搜过，没有靠谱的 MusicXML→MIDI Java 库）

✅ 唯一方案：**自己写 `MusicXML→MIDI` 转换器**，复用项目已有的 `proxymusic ScorePartwise` 内存模型 + JDK 自带 `javax.sound.midi`。

---

## 2. 范围（**重要：第一版做什么 / 不做什么**）

### 第一版会做对的事（覆盖 ~80% 钢琴/管乐/人声谱子）

| 项 | 说明 |
|---|---|
| 普通有音高音符 | pitch + duration → NoteOn/NoteOff |
| 休止符 | 推进 tick，无事件 |
| 和弦 | 多 NoteOn 同 onset，duration 取 chord 第一 note |
| 连音线 (tied notes) | tie-stop 不重新触发，延长前一 NoteOff |
| Tempo 标记 | `<sound tempo="N">` → SetTempo meta 事件；默认 120 BPM |
| 拍号 | TimeSignature meta 事件 |
| 多 Part | 每个 Part 一个 MIDI Track，channel 1..16 轮转 |
| Program (乐器) | 从 `LogicalPart.getMidiProgram()` 读 |

### 第一版**不做**（明确 defer 到 Stage 2+）

| 项 | 不做的原因 |
|---|---|
| 力度记号 (pp/mf/ff) → MIDI velocity | 解析+映射规则复杂，第一版固定 velocity = 80 |
| 转调乐器 transpose | 需读 `<transpose>` 元素并改音高，第一版按记谱音高 |
| 鼓组 / 不定音高打击乐 → MIDI Channel 10 | DrumSet 映射表需仔细验证，第一版按普通音高出（听起来怪但不阻断） |
| 反复记号 / 跳跃 (D.S./D.C./Coda) 展开 | 第一版按谱面线性顺序，不展开 |
| 装饰音 (trill / mordent / turn) | 不展开为 MIDI 颤音 |
| 演奏标记（staccato 缩短时值等） | 不调整时值 |
| 圆滑线 → 连奏 legato | MIDI 上无明确表达，跳过 |
| 颤音 (tremolo) | 不展开成多个音符 |

> **以上都是知情的 trade-off**，写在 release notes 里告诉用户"试听用、不保证演奏级"。

### 用户体验要求

- 「文件」菜单新增两项：`导出文集为 MIDI...` / `导出谱页为 MIDI...`
- 默认文件路径：与 MusicXML 同目录、同 basename，扩展名换 `.mid`
- 文件冲突：复用 `BookActions.isTargetConfirmed()` 弹覆盖确认
- 中英文资源同步翻译

---

## 3. 当前项目状态（写于 v5.10.3 发布后）

| 项 | 状态 |
|---|---|
| 仓库 | <https://github.com/Lucas0623z/NoteLite>（main 分支单 commit `22ea65a1c`） |
| 本地 | `D:\NoteLite\audiveris\`（**注意：文件夹仍叫 audiveris，非 NoteLite**，是历史遗留） |
| 上一版本 | v5.10.3（zh_CN 汉化 + Versions NPE 修 + JDK 21 build）已发，含 `MIDI_EXPORT_PLAN.md` |
| 上一版作者 | Lucas0623z 一人（force-push 清掉了上游历史） |
| CI | **无**（`.github/workflows/` 在 5.10.3 时已全删） |
| MIDI 相关现存代码 | `score/MidiAbstractions.java`（GM 128 乐器名 + `.mid` 常量） + `LogicalPart.getMidiProgram()` + `createScorePart` 已设 MidiInstrument |

**接续工作的人需要确认**：
1. 工作树是否干净 (`git status`)
2. JDK 21 在不在 PATH（参考 `memory/project_paths.md`）
3. 当前是不是在 `D:\NoteLite\audiveris\` 目录下

---

## 4. 架构 / 调用链（**必读**）

### 4.1 现有 mxl 导出的完整调用链

```
菜单：File → Export book                           (BookActions.java:644)
   ↓
ExportBookTask.doInBackground()                   (BookActions.java:2146)
   ↓
Book.export(stubs, scores)                        (Book.java)
   ↓ 对每个 Score
ScoreExporter(score).export(path, name, signed, compressed)
                                                  (ScoreExporter.java:156)
   ├─ STAGE A: ScorePartwise sp = PartwiseBuilder.build(score)
   │           ↑ 这是模型转换：NoteLite Score → proxymusic ScorePartwise
   │
   └─ STAGE B: Marshalling.marshal(sp, ostream, signed, indent=2)
               ├─ if compressed: 包装在 Mxl.Output (zip + RootFile entry)
               └─ if uncompressed: 直接 marshal 到 .xml stream
```

**关键洞察**：MIDI 实现**完全复用 STAGE A**，只替换 STAGE B。拿到 `ScorePartwise` 对象后用 `javax.sound.midi` 遍历它写 MIDI 文件。

### 4.2 PartwiseBuilder 的递归结构（**这就是 MIDI 要遍历的对象树**）

```
processScore()                                     PartwiseBuilder.java:2859
  └─ processPartList()                                              :2688
      ├─ 对每个 LogicalPart:
      │     createScorePart(logicalPart)                            :549
      │     ↑ 这里设了 MidiInstrument 元数据：channel/program/volume
      │       普通乐器: channel = 1 + ((id-1) % 16); program = midi program
      │       鼓组:    channel = 10; setMidiUnpitched(每个 drum sound)
      │
      └─ 对每个 SheetStub in score.getStubs():
            processStub(stub, partMap)                              :3145
              └─ 对每个 (LogicalPart, ScorePartwise.Part) entry:
                    processLogicalPart(...)                         :1856
                      └─ 对页内每个 SystemInfo:
                            processSystem(system)                   :3209
                              └─ processPart(systemPart)            :2666
                                  └─ 对每个 Measure:
                                        processMeasure(measure)     :1962  ★ 时间核心
                                          ├─ 创建 pmMeasure
                                          ├─ if 首小节:
                                          │     getAttributes().setDivisions(
                                          │       page.simpleDurationOf(QUARTER))
                                          │     ↑ 这就是 MIDI PPQ
                                          ├─ processKeys() / processTime()
                                          ├─ 对每个 Voice:
                                          │     insertBackup(delta)              :923
                                          │     对每个 Slot:
                                          │       insertForward(delta, chord)    :944
                                          │       processChord(chord)            :1389
                                          │         └─ 对每个 Note:
                                          │               processNote(note)      :2244
                                          └─ processBarline(右)
```

### 4.3 输出对象 ScorePartwise 的结构（proxymusic 类）

```
ScorePartwise
├── identification (软件元信息)
├── defaults (页面布局、字体)
├── partList
│   └── List<ScorePart>
│       ├── id ("P1", "P2", ...)
│       ├── partName, partAbbreviation
│       └── midiInstrument (channel, program, volume, midiUnpitched if drum)
└── List<ScorePartwise.Part>          ← MIDI 遍历这里
    ├── id (引用 ScorePart.id)
    └── List<ScorePartwise.Part.Measure>
        └── List<Object> noteOrBackupOrForward()       ← 关键
            ├── Note     — pitch/rest/unpitched + duration + chord/grace/tie
            ├── Backup   — duration only (回退时间)
            ├── Forward  — duration + voice (前进时间)
            ├── Direction — 含 <sound tempo="..."> 等
            ├── Attributes — divisions / key / time / clef
            ├── Barline / Print / ...
            └── (这是 mixed content list, 用 instanceof 分支)
```

**MIDI 实现核心：遍历 `Part.getMeasure().get(i).getNoteOrBackupOrForward()` 这个 list，按 instanceof 派发。**

### 4.4 关键数据点（ScorePartwise → MIDI 直接映射）

| ScorePartwise 字段 | MIDI 对应 | 取值方法 |
|---|---|---|
| `Attributes.getDivisions()` | Sequence PPQ | 第一个 measure 的 attributes 拿到 |
| `Note.getPitch().getStep()` | NoteOn 音高 step | A/B/C/D/E/F/G |
| `Note.getPitch().getOctave()` | 音高 octave | int |
| `Note.getPitch().getAlter()` | 音高半音偏移 | -2..+2 (BigDecimal, 可能 null) |
| `Note.getDuration()` | tick 数 | BigDecimal 转 long |
| `Note.getChord()` | chord 标记 | 非 null 表示与上音同 onset |
| `Note.getRest()` | 休止 | 非 null 跳过 NoteOn |
| `Note.getGrace()` | 装饰音 | 非 null 时无 duration，发短 ON/OFF |
| `Note.getTie()` | 连音线 | List<Tie>, 检查 type=START/STOP |
| `Backup.getDuration()` | tick 后退 | currentTick -= duration |
| `Forward.getDuration()` | tick 前进 | currentTick += duration |
| `Direction.getSound().getTempo()` | SetTempo meta | BigDecimal BPM |
| `Attributes.getTime()` | TimeSignature meta | beats / beat-type |
| `ScorePart.getMidiDeviceAndMidiInstrument()` | ProgramChange | channel/program from MidiInstrument |

### 4.5 MIDI pitch 公式

```java
int midiPitch(Pitch pitch) {
    int[] stepSemitones = {9, 11, 0, 2, 4, 5, 7};   // ABCDEFG 索引
    Step step = pitch.getStep();
    int octave = pitch.getOctave();
    int alter = pitch.getAlter() != null ? pitch.getAlter().intValue() : 0;
    return (octave + 1) * 12 + stepSemitones[step.ordinal()] + alter;
}
// A4 (la) = (4+1)*12 + 9 + 0 = 69 ✓
// Middle C = (4+1)*12 + 0 + 0 = 60 ✓
```

> ⚠️ **验证 Step.ordinal() 顺序**：proxymusic `Step` enum 是 `A, B, C, D, E, F, G`（按字母）。如果 ordinal 是 `C, D, E, F, G, A, B`（音乐惯例），公式要换。**写代码时第一件事是测一下 Step.A.ordinal() 返回什么**。

---

## 5. 文件改动清单

### 新增文件

| 文件 | 用途 | 预计行数 |
|---|---|---|
| `app/src/main/java/com/notelite/omr/score/MidiExporter.java` | MusicXML→MIDI 主转换器 | 250-350 |
| `app/src/main/java/com/notelite/omr/sheet/ui/ExportMidiTask.java` | 后台任务 | ~80 |
| `app/src/test/java/com/notelite/omr/score/MidiExporterTest.java` | 单元测试 | ~150 |

### 修改文件

| 文件 | 改动 |
|---|---|
| `app/src/main/java/com/notelite/omr/sheet/ui/BookActions.java` | 加 `@Action exportSheetAsMidi` / `exportBookAsMidi`；加 `.mid` 文件过滤器 |
| `app/src/main/java/com/notelite/omr/sheet/ui/resources/BookActions.properties` | 加菜单项英文文案 |
| `app/src/main/java/com/notelite/omr/sheet/ui/resources/BookActions_zh_CN.properties` | 加菜单项中文文案 |
| `app/src/main/java/com/notelite/omr/sheet/ui/resources/BookActions_fr.properties` | 加菜单项法文文案（可选） |
| `app/build.gradle` | 版本 `5.10.3` → `5.11.0` |

---

## 6. 实施分阶段（**严格按这个顺序做**）

### Stage 1: MidiExporter 核心 + 单元测试

**目标**：能把一个手工构造的 ScorePartwise 转成 MIDI，5 个单元测试全过。

**步骤**：

1. 新建 `app/src/main/java/com/notelite/omr/score/MidiExporter.java`：
   - 构造方法接受 `Score score`
   - `public void export(Path path)` 顶层方法
   - 内部：`PartwiseBuilder.build(score)` → `ScorePartwise sp` → 自己遍历 → 写文件
   - 用 §7 的代码骨架

2. 新建 `app/src/test/java/com/notelite/omr/score/MidiExporterTest.java`：
   - 用 `ObjectFactory` 手工构造 ScorePartwise
   - 5 个测试用例（见 §8）

3. 跑测试 `gradlew :app:test --tests MidiExporterTest`，全过才能进 Stage 2

**完成判定**：5 个 test 全 PASS，且能用 `MidiSystem.getSequence(file)` 反读出预期事件。

### Stage 2: 菜单接线 + 资源

**目标**：界面上能点 "Export book as MIDI"，跑完产出 .mid 文件。

**步骤**：

1. 新建 `ExportMidiTask`（照抄 `BookActions.ExportSheetTask` 第 2187 行模板，把 `sheet.export(path)` 换成 `new MidiExporter(score).export(path)`）

2. 在 `BookActions.java` 加：
   ```java
   @Action(enabledProperty = STUB_IDLE)
   public Task<Void, Void> exportSheetAsMidi(ActionEvent e) { ... }

   @Action(enabledProperty = BOOK_IDLE)
   public Task<Void, Void> exportBookAsMidi(ActionEvent e) { ... }
   ```

3. 在 `BookActions.properties` / `BookActions_zh_CN.properties` 各加 4 行：
   ```properties
   exportSheetAsMidi.Action.text = Export sheet as MIDI...
   exportSheetAsMidi.Action.shortDescription = Export current sheet as MIDI file
   exportBookAsMidi.Action.text = Export book as MIDI...
   exportBookAsMidi.Action.shortDescription = Export current book as MIDI file
   ```

4. **手工**测试：跑 `:app:run`，导入 PDF，用菜单导出 MIDI，看文件是否生成。

### Stage 3: 端到端验证（用真实谱子）

1. 用之前用过的 `IMSLP909050 - Stamitz 长笛协奏曲` PDF：
   - 启动应用，导入 PDF
   - 等转写完成
   - File → Export book as MIDI...
   - 用 Windows Media Player / VLC / MuseScore 4 打开 .mid 播放
   - 验证：能播、音高对、节奏大致对、不崩溃

2. 修发现的问题（特别是 backup/forward、tied notes、chord 的边界情况）

### Stage 4: Release

1. 改 `app/build.gradle:26` 的 version 5.10.3 → 5.11.0
2. commit "chore(release): bump version to 5.11.0"
3. `gradlew :app:distZip --no-daemon`
4. 重命名为 `NoteLite-5.11.0.zip`
5. `git tag -a v5.11.0 -m "NoteLite 5.11.0 - bundled MIDI export"`
6. `git push origin main && git push origin v5.11.0`
7. `gh release create v5.11.0 --repo Lucas0623z/NoteLite --title "NoteLite 5.11.0" --notes-file release-notes.md NoteLite-5.11.0.zip`

---

## 7. MidiExporter 代码骨架

> 这是给实施者参考的**最小可工作骨架**，编译能过、逻辑骨架对，细节自己补。

```java
package com.notelite.omr.score;

import org.audiveris.proxymusic.*;
import javax.sound.midi.*;
import java.math.BigDecimal;
import java.nio.file.Path;
import java.util.*;

public class MidiExporter {
    private static final int DEFAULT_VELOCITY = 80;
    private static final int DEFAULT_TEMPO_BPM = 120;

    private final Score score;

    public MidiExporter(Score score) {
        this.score = Objects.requireNonNull(score);
    }

    public void export(Path path) throws Exception {
        // STAGE A: 复用现有逻辑
        ScorePartwise sp = PartwiseBuilder.build(score);

        // 抽出 PPQ（用第一个 part 第一个 measure 的 divisions）
        int ppq = extractFirstDivisions(sp);
        Sequence sequence = new Sequence(Sequence.PPQ, ppq);

        // Track 0 = 全局 meta（tempo / time sig / copyright）
        Track meta = sequence.createTrack();
        addCopyrightMeta(meta, "NoteLite");

        // 每个 Part 一个 Track
        int partIndex = 0;
        for (ScorePartwise.Part part : sp.getPart()) {
            Track track = sequence.createTrack();

            // 从 ScorePart 的 MidiInstrument 拿 channel/program
            ScorePart scorePart = (ScorePart) part.getId();
            int[] channelProgram = extractChannelProgram(scorePart, partIndex);
            int channel = channelProgram[0];
            int program = channelProgram[1];

            // ProgramChange at tick 0
            ShortMessage pc = new ShortMessage();
            pc.setMessage(ShortMessage.PROGRAM_CHANGE, channel, program - 1, 0);
            track.add(new MidiEvent(pc, 0));

            // 遍历 measure
            walkPart(part, track, meta, channel, ppq);
            partIndex++;
        }

        // 写文件
        MidiSystem.write(sequence, 1, path.toFile());
    }

    private void walkPart(ScorePartwise.Part part, Track track, Track meta,
                          int channel, int ppq) throws InvalidMidiDataException {
        long currentTick = 0;
        Map<Integer, Long> pendingNoteOff = new HashMap<>();  // pitch -> noteOff tick (for ties)

        for (ScorePartwise.Part.Measure measure : part.getMeasure()) {
            long measureStartTick = currentTick;
            long lastChordTick = currentTick;  // 上一个 chord 的 onset，用于 chord 标记跳过 advance

            for (Object item : measure.getNoteOrBackupOrForward()) {
                if (item instanceof Note note) {
                    handleNote(note, track, channel, ppq, currentTick,
                               lastChordTick, pendingNoteOff);
                    if (note.getChord() == null) {
                        // 非 chord-continuation，正常推进 tick
                        long dur = note.getDuration() != null ?
                                   note.getDuration().longValue() : 0;
                        lastChordTick = currentTick;
                        currentTick += dur;
                    }
                    // 注意 grace note 不推进 tick (Note.getGrace() != null 时 duration 为 null)
                } else if (item instanceof Backup backup) {
                    long dur = backup.getDuration().longValue();
                    currentTick -= dur;
                } else if (item instanceof Forward forward) {
                    long dur = forward.getDuration().longValue();
                    currentTick += dur;
                } else if (item instanceof Direction direction) {
                    handleDirection(direction, meta, currentTick);
                } else if (item instanceof Attributes attrs) {
                    handleAttributes(attrs, meta, currentTick);
                }
                // Barline / Print / etc. — 第一版忽略
            }

            // 小节末，currentTick 应该等于 measureStartTick + measureDuration
            // （由 backup/forward 的累计平衡保证）
        }

        // flush 所有 pending NoteOff
        for (Map.Entry<Integer, Long> e : pendingNoteOff.entrySet()) {
            addNoteOff(track, channel, e.getKey(), e.getValue());
        }
    }

    private void handleNote(Note note, Track track, int channel, int ppq,
                            long currentTick, long lastChordTick,
                            Map<Integer, Long> pendingNoteOff)
            throws InvalidMidiDataException {
        if (note.getRest() != null) return;  // 休止只推进时间，无事件

        // chord-continuation 用 lastChordTick 作为 onset
        long onsetTick = note.getChord() != null ? lastChordTick : currentTick;

        long duration = note.getDuration() != null ? note.getDuration().longValue() : 0;
        if (note.getGrace() != null) duration = ppq / 16;  // 装饰音用很短时值

        Pitch pitch = note.getPitch();
        if (pitch == null) return;  // 不处理 unpitched (drum) - 第一版

        int midiPitch = computeMidiPitch(pitch);

        // 检查 tie type
        boolean isTieStop = false, isTieStart = false;
        for (Tie tie : note.getTie()) {
            if (tie.getType() == StartStop.STOP) isTieStop = true;
            if (tie.getType() == StartStop.START) isTieStart = true;
        }

        if (isTieStop && pendingNoteOff.containsKey(midiPitch)) {
            // 不发新 NoteOn，把旧的 NoteOff 推迟
            pendingNoteOff.put(midiPitch, onsetTick + duration);
        } else {
            // 正常发 NoteOn
            addNoteOn(track, channel, midiPitch, onsetTick);
            if (isTieStart) {
                pendingNoteOff.put(midiPitch, onsetTick + duration);
            } else {
                addNoteOff(track, channel, midiPitch, onsetTick + duration);
            }
        }
    }

    // -- helper methods --

    private static int computeMidiPitch(Pitch pitch) {
        // 注意：proxymusic Step enum 实际顺序，编码前先验证一下
        Map<Step, Integer> stepSemi = Map.of(
            Step.C, 0, Step.D, 2, Step.E, 4, Step.F, 5,
            Step.G, 7, Step.A, 9, Step.B, 11
        );
        int alter = pitch.getAlter() != null ? pitch.getAlter().intValue() : 0;
        return (pitch.getOctave() + 1) * 12 + stepSemi.get(pitch.getStep()) + alter;
    }

    private static void addNoteOn(Track t, int ch, int pitch, long tick)
            throws InvalidMidiDataException {
        ShortMessage m = new ShortMessage();
        m.setMessage(ShortMessage.NOTE_ON, ch, pitch, DEFAULT_VELOCITY);
        t.add(new MidiEvent(m, tick));
    }

    private static void addNoteOff(Track t, int ch, int pitch, long tick)
            throws InvalidMidiDataException {
        ShortMessage m = new ShortMessage();
        m.setMessage(ShortMessage.NOTE_OFF, ch, pitch, 0);
        t.add(new MidiEvent(m, tick));
    }

    private static void handleDirection(Direction direction, Track meta, long tick)
            throws InvalidMidiDataException {
        Sound sound = direction.getSound();
        if (sound == null || sound.getTempo() == null) return;
        int bpm = sound.getTempo().intValue();
        int microsecondsPerQuarter = 60_000_000 / bpm;
        byte[] data = {
            (byte)((microsecondsPerQuarter >> 16) & 0xFF),
            (byte)((microsecondsPerQuarter >>  8) & 0xFF),
            (byte)(microsecondsPerQuarter & 0xFF)
        };
        MetaMessage tempo = new MetaMessage();
        tempo.setMessage(0x51, data, 3);
        meta.add(new MidiEvent(tempo, tick));
    }

    private static void handleAttributes(Attributes attrs, Track meta, long tick)
            throws InvalidMidiDataException {
        for (Time time : attrs.getTime()) {
            // 解析 beats / beat-type 写 TimeSignature meta (FF 58 04 nn dd cc bb)
            // 实现略，参考 §4.4 公式
        }
    }

    private static int extractFirstDivisions(ScorePartwise sp) {
        for (ScorePartwise.Part part : sp.getPart()) {
            for (ScorePartwise.Part.Measure m : part.getMeasure()) {
                for (Object item : m.getNoteOrBackupOrForward()) {
                    if (item instanceof Attributes a && a.getDivisions() != null) {
                        return a.getDivisions().intValue();
                    }
                }
            }
        }
        return 480;  // safe default
    }

    private static int[] extractChannelProgram(ScorePart sp, int fallbackIndex) {
        // 默认值
        int channel = 1 + (fallbackIndex % 16);
        int program = 1;  // Acoustic Grand Piano
        for (Object o : sp.getMidiDeviceAndMidiInstrument()) {
            if (o instanceof MidiInstrument mi) {
                if (mi.getMidiChannel() != null) channel = mi.getMidiChannel();
                if (mi.getMidiProgram() != null) program = mi.getMidiProgram();
                break;
            }
        }
        return new int[]{channel - 1, program};  // MIDI channel is 0-indexed in javax
    }

    private static void addCopyrightMeta(Track meta, String text)
            throws InvalidMidiDataException {
        byte[] bytes = text.getBytes();
        MetaMessage m = new MetaMessage();
        m.setMessage(0x02, bytes, bytes.length);  // 0x02 = Copyright Notice
        meta.add(new MidiEvent(m, 0));
    }
}
```

> **注意**：这个骨架**没编译过**，作为思路参考。实施时按这个走，一个一个方法补完，让 unit test 拉着前进。

---

## 8. 测试用例（**Stage 1 必过的 5 个**）

### 文件位置
`app/src/test/java/com/notelite/omr/score/MidiExporterTest.java`

### Test 1: 单声部单音符
- 构造 ScorePartwise：1 个 Part、1 个 Measure、divisions=480、1 个 Note (A4, quarter, duration=480)
- 导出 MIDI 到临时文件
- 用 `MidiSystem.getSequence(file)` 反读
- 断言：tracks.length == 2（meta + 1 part），track[1] 含 NoteOn(channel=0, pitch=69, tick=0) 和 NoteOff(pitch=69, tick=480)

### Test 2: 和弦
- 1 Part 1 Measure，3 个 Note 同 onset：A4, C5, E5 都是 quarter
- 第一个 Note 无 chord 标记，第二三个有 chord 标记
- 断言：3 个 NoteOn 的 tick 都是 0；3 个 NoteOff 的 tick 都是 480

### Test 3: 连音线
- 2 个 Note 都是 A4 quarter，第一个有 tie type=START，第二个有 tie type=STOP
- 断言：只有 1 个 NoteOn (tick=0) 和 1 个 NoteOff (tick=960)，总时长是两个 duration 之和

### Test 4: 休止符
- 序列：rest(quarter) → A4(quarter)
- 断言：A4 的 NoteOn 在 tick=480

### Test 5: 多 Part
- 2 个 Part，各自 1 measure 1 note
- 断言：sequence.getTracks().length == 3（meta + 2 parts），各 part 在自己的 channel

### 测试启动命令

```powershell
cd D:\NoteLite\audiveris
.\gradlew :app:test --tests "com.notelite.omr.score.MidiExporterTest" --no-daemon
```

---

## 9. 验收标准

- [ ] `gradlew :app:test --tests MidiExporterTest` 全过
- [ ] 端到端：Stamitz 长笛协奏曲 PDF → MIDI → MuseScore 4 能播放、音高节奏目测正确
- [ ] 菜单项 `导出文集为 MIDI...` / `导出谱页为 MIDI...` 中英文显示正确
- [ ] `gradlew :app:run --no-daemon` 启动正常，导入 PDF + 导出 MIDI 完整流程不抛异常
- [ ] 版本号 `5.11.0`，tag `v5.11.0` 已打
- [ ] GitHub Release 发出，有可下载的 `NoteLite-5.11.0.zip`
- [ ] release notes 写明已知限制（velocity 固定、不支持鼓 / 转调 / 反复 / 装饰音）
- [ ] Contributors 仍只有 Lucas0623z（push 后立即用 `gh api repos/Lucas0623z/NoteLite/contributors` 验证）

---

## 10. 风险与回退

| 风险 | 应对 |
|---|---|
| `Step.ordinal()` 顺序不是预期 | 在 unit test 第一个就断言 `Step.A.ordinal()` 等值，编码前先确定 |
| 复杂谱子 backup/forward 累积错误导致时序乱 | unit test 覆盖；端到端如果发现，加日志打印 currentTick 在每个 measure 末的值 |
| 多声部 voice 串道 | 第一版每个 Part 用单 channel，多 voice 共享，依赖 NoteOn/NoteOff 配对（不依赖 voice id 区分） |
| `MidiSystem.write` 在某些 JDK 抛异常 | 已知 OpenJDK 21 GA 稳定 |
| 用户报"我的谱子转出来不对" | release notes 明确"试听用、不保证演奏级"；具体修复进 5.11.1 patch |
| 内存里 Score 对象有 null 字段没处理 | 用 try/catch 包住每个 measure 的处理，单个 measure 失败不阻断后续 |

---

## 11. Release Notes 草稿（v5.11.0）

```markdown
## NoteLite 5.11.0 — 自带 MIDI 导出

### 新增
- ★ **MIDI 导出**：`File → Export book/sheet as MIDI...` 直接生成 `.mid` 文件，
  无需安装 MuseScore 等外部软件
- 支持单声部、多声部、和弦、连音线、休止符、Tempo 标记
- 每个 Part 独立 MIDI Track，channel 自动分配，乐器从 LogicalPart 设置读取

### 已知限制（第一版）
- 力度记号未映射到 MIDI velocity（统一 80）
- 鼓组按普通音高输出（听起来与原谱不一致）
- 反复记号 / D.S. / D.C. / Coda 不展开
- 转调乐器按记谱音高输出（不应用 transpose）
- 装饰音用固定短时值，不展开

### 用法
导入 PDF / 图像 → 等转写完成 → 菜单「文件 → 导出文集为 MIDI...」→ 选保存路径

### 下载
- `NoteLite-5.11.0.zip` — 解压运行 `bin/NoteLite.bat`（Win）或 `bin/NoteLite`（Linux/macOS）
- 需要 Java 21 运行时
```

---

## 12. 给接续工作者的检查清单

打开新对话后，照下面顺序验证状态：

```bash
# 1. 进入项目目录
cd D:/NoteLite/audiveris

# 2. 工作树是否干净
git status                              # 应该 nothing to commit

# 3. 当前 commit 是不是 5.10.3 release
git log --oneline -3                    # 顶部应该是 22ea65a1c "Initial release: NoteLite 5.10.3"
                                        # 或者后续基于它的 commit

# 4. 远程指对了
git remote -v                           # origin = Lucas0623z/NoteLite

# 5. JDK 21 能用
$env:JAVA_HOME = "C:\Users\zhang\.jdks\jdk-21.0.6"
$env:Path = "$env:JAVA_HOME\bin;$env:Path"
java -version                           # 21.x.x

# 6. 可以构建
.\gradlew :app:compileJava --no-daemon  # BUILD SUCCESSFUL

# 7. 可以测试
.\gradlew :app:test --no-daemon         # 应该全过（暂时无 MidiExporterTest）
```

如果以上全过 → 直接进 Stage 1，新建 `MidiExporter.java`。

如果有不过 → 先修，问用户是否要先解决环境问题再继续。

---

## 附录 A: 提示词模板（给下一个对话的 Claude）

```
看一下 D:\NoteLite\audiveris\MIDI_EXPORT_PLAN.md，
按 §6 Stage 1 的步骤实现 MidiExporter 的 5 个单元测试。
约束：参考 §4 的架构、§5 的文件清单、§7 的代码骨架。
测试通过后告诉我，再进 Stage 2。
```
