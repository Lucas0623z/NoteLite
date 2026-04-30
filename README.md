# NoteLite

<div align="center">

**基于 OMR 的乐谱轻量化结构化、纠错与音乐教育评测平台**

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Release](https://img.shields.io/badge/release-v5.11.0-brightgreen.svg)](https://github.com/Lucas0623z/NoteLite/releases/latest)
[![Status](https://img.shields.io/badge/status-In%20Development-yellow.svg)]()
[![GitHub](https://img.shields.io/badge/GitHub-Lucas0623z-blue?logo=github)](https://github.com/Lucas0623z)

[功能特性](#功能特性) • [技术架构](#技术架构) • [安装部署](#安装部署) • [开发路线](#开发路线) • [联系方式](#联系方式)

</div>

---

## 项目简介

NoteLite 是一个面向音乐教育场景的智能乐谱处理平台。基于光学乐谱识别(OMR)技术,结合轻量化编码、曲谱比对与错误检测,构建从"扫描识谱"到"数据库管理"再到"教学反馈"的完整闭环。

### 背景与动机

现有 OMR 工具(如 Audiveris、oemer、homr)已能将乐谱图像转换为 MusicXML 等机器可读格式,但在音乐教育平台的实际需求上仍存在空白:

- 缺乏适合数据库存储的轻量化结构数据
- 缺乏与标准曲谱的自动匹配与差异比对
- 缺乏扫描谱面的疑似错误检测
- 缺乏基于音频的演奏正确性评估

NoteLite 正是为填补这些空白而设计,**不是重复造一个 OMR 引擎**,而是以成熟开源方案为基础,向上构建教育应用层。

---

## 最新发行版 (v5.11.0, 2026-04-29)

NoteLite 当前以 Audiveris OMR 引擎为基础进行二次开发,已发布的桌面版本包含:

- **完整 OMR 流程**: PDF / 图像 → 转写 → MusicXML 导出
- **MIDI 导出**(本版本新增): 文件类型下拉支持 `.mxl` / `.xml` / `.mid`,无需安装 MuseScore 等外部软件
- **中文界面**: 菜单 / 对话框 / 工具栏全量汉化 (zh_CN)
- **JDK 21 构建**: 解压即用,无需自行编译

下载: [`NoteLite-5.11.0.zip`](https://github.com/Lucas0623z/NoteLite/releases/latest)

> MIDI 导出仅供试听校对,首版固定 velocity 80,鼓组 / 反复记号 / 转调乐器等高级表现暂不支持。详见 release notes。

---

## 功能特性

### 核心功能

| 功能模块 | 描述 | 状态 |
|---------|------|------|
| **乐谱识别** | 支持扫描图、拍照图、PDF 乐谱的自动识别 | 开发中 |
| **轻量编码** | 将乐谱转为极小结构化数据,优化存储与检索 | 开发中 |
| **曲谱匹配** | 自动匹配标准谱,进行序列级差异分析 | 计划中 |
| **智能纠错** | 检测漏音、错音、节奏异常、升降号错误等 | 计划中 |
| **演奏评测** | 基于音频识别,粗粒度评估演奏正确性 | 计划中 |

### 创新点

1. **乐谱轻量化编码**
   设计适合数据库的压缩表示格式,相比完整 MusicXML 大幅减小存储体积

2. **标准谱驱动的差异检测**
   新扫描谱不仅被识别,还会与数据库中的标准版本自动校验

3. **教育应用闭环**
   从纸质谱面到在线教学反馈的一体化流程

---

## 技术架构

### 系统分层

```
┌─────────────────────────────────────────────────┐
│              应用层 (Application)                │
│  乐谱上传 | 曲谱匹配 | 扫描纠错 | 演奏评测       │
└─────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────┐
│          数据库与检索层 (Database)               │
│  标准曲谱 | 用户上传 | 版本管理 | 片段索引       │
└─────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────┐
│          轻量编码层 (Encoding)                   │
│  相对音高 | Token化 | 哈希指纹 | 压缩算法       │
└─────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────┐
│        乐谱结构化层 (Structuring)                │
│  谱号 | 调号 | 拍号 | 音符 | 时值 | 演奏标记    │
└─────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────┐
│          OMR 识别层 (Recognition)                │
│  图像预处理 | 五线谱检测 | 符号识别 | 音高恢复  │
└─────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────┐
│            输入层 (Input)                        │
│  扫描图 | 拍照图 | PDF | 演奏录音               │
└─────────────────────────────────────────────────┘
```

### 技术栈

- **OMR 引擎**: Audiveris / oemer / homr (可选方案)
- **数据格式**: MusicXML, JSON, 自定义压缩格式
- **匹配算法**: 编辑距离, 动态规划, 哈希指纹
- **音频识别**: (待定,用于演奏评测)

---

## 安装部署

### 方式一: 直接下载 (推荐)

适用于普通用户,无需自行编译:

1. 从 [Releases](https://github.com/Lucas0623z/NoteLite/releases/latest) 下载 `NoteLite-5.11.0.zip`
2. 解压到任意目录
3. 运行 `bin/NoteLite.bat` (Windows) 或 `bin/NoteLite` (Linux/macOS)
4. 需要本机有 **Java 21** 运行时

### 方式二: 从源码构建

适用于二次开发或贡献代码:

```bash
# 克隆仓库
git clone https://github.com/Lucas0623z/NoteLite.git
cd NoteLite

# 设置 JDK 21 (确保 java -version 显示 21.x)
export JAVA_HOME=/path/to/jdk-21

# 运行
./gradlew :app:run --no-daemon

# 打包发行版
./gradlew :app:distZip --no-daemon
# 产物在 app/build/distributions/app-<version>.zip
```

Windows 下用 `.\gradlew` 替代 `./gradlew`。

### 长期规划 (教育平台层)

教育应用层 (轻量编码 / 标准谱匹配 / 演奏评测) 仍在设计阶段,届时会引入:

- Python 3.8+ (匹配算法 / 数据处理)
- Node.js 16+ (前端)
- PostgreSQL / MySQL (数据库)

---

## 数据库设计

### 核心表结构

#### 1. 曲谱主表 (scores)

| 字段 | 类型 | 说明 |
|------|------|------|
| score_id | INT | 主键 |
| title | VARCHAR | 曲目名称 |
| composer | VARCHAR | 作曲家 |
| key_signature | VARCHAR | 调号 |
| time_signature | VARCHAR | 拍号 |
| measure_count | INT | 小节数 |
| canonical_version_id | INT | 标准版本ID |

#### 2. 曲谱内容表 (score_content)

| 字段 | 类型 | 说明 |
|------|------|------|
| score_id | INT | 外键 |
| raw_musicxml | TEXT | 原始 MusicXML |
| structured_json | JSON | 结构化数据 |
| compressed_code | VARCHAR | 轻量编码 |
| midi_url | VARCHAR | MIDI 文件路径 |

#### 3. 比对结果表 (comparisons)

| 字段 | 类型 | 说明 |
|------|------|------|
| compare_id | INT | 主键 |
| uploaded_score_id | INT | 上传谱ID |
| matched_standard_id | INT | 匹配标准谱ID |
| similarity_score | FLOAT | 相似度 |
| error_positions | JSON | 错误位置 |

---

## 开发路线

### Phase 1: MVP (当前阶段)

- [x] 项目架构设计
- [x] OMR 引擎集成 (基于 Audiveris fork, v5.10.x)
- [x] 结构化数据输出 (MusicXML / MIDI)
- [x] 中文界面汉化 (v5.10.0+)
- [x] 自带 MIDI 导出 (v5.11.0)
- [ ] 轻量编码实现
- [ ] 基础数据库搭建

### Phase 2: 标准谱匹配与纠错

- [ ] 标准谱数据库建立
- [ ] 曲谱指纹索引
- [ ] 差异分析算法
- [ ] 错误高亮界面

### Phase 3: 识别层优化

- [ ] 手机拍照场景优化
- [ ] 教学谱例微调
- [ ] 误识别规则修正

### Phase 4: 演奏评测

- [ ] 音频上传功能
- [ ] 音高/节奏提取
- [ ] 与标准谱比对
- [ ] 学习报告生成

---

## 轻量编码示例

### 设计思路

传统 MusicXML 体积大,不适合大规模数据库存储。NoteLite 设计了自定义轻量格式:

```
# MusicXML (数百行)
<score-partwise>
  <part id="P1">
    <measure number="1">
      <note>
        <pitch><step>G</step><octave>4</octave></pitch>
        <duration>1</duration>
        <type>quarter</type>
      </note>
      ...
    </measure>
  </part>
</score-partwise>

# NoteLite 编码 (一行)
TS:4/4;KS:G;M1:G4/q,A4/q,B4/h|M2:C5/q,B4/q,A4/h

# Token 形式 (相对音高)
4/4|G|+0:q,+2:q,+4:h|+5:q,+4:q,+2:h
```

**优势**:
- 存储体积减少 90%+
- 数据库索引简单
- 相似谱匹配高效
- 易于版本管理

---

## 技术细节

### 曲谱匹配算法

采用多层检索策略:

1. **粗筛**: 调号 + 拍号 + 小节数
2. **中筛**: 旋律指纹哈希
3. **精筛**: 序列级编辑距离

### 差异检测能力

| 错误类型 | 检测方法 | 示例 |
|---------|---------|------|
| 漏音/多音 | 序列长度比对 | 标准谱8音符,扫描谱7音符 |
| 音高错误 | 逐符号比对 | 标准C5,扫描D5 |
| 时值错误 | 节奏模式匹配 | 标准四分音符,扫描八分音符 |
| 升降号遗漏 | 调性分析 | 标准F#,扫描F |
| 小节拍数异常 | 拍数累加 | 4/4拍小节内时值总和≠4拍 |

---

## 贡献指南

欢迎贡献代码、报告问题或提出建议!

### 如何贡献

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

### 开发规范

- 代码风格: PEP 8 (Python)
- 提交信息: [Conventional Commits](https://www.conventionalcommits.org/)
- 文档: 所有公共 API 需要 docstring

---

## 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

---

## 作者

**张悦轩 (Yuexuan Zhang)**

伊利诺伊大学厄巴纳-香槟分校(UIUC)本科生
研究兴趣: 计算机科学、智能系统、教育技术、音乐信息处理

### 联系方式

- **Email**: Lucas.z0623@outlook.com
- **GitHub**: [@Lucas0623z](https://github.com/Lucas0623z)
- **个人网站**: [https://personal-website-tau-lake.vercel.app/](https://personal-website-tau-lake.vercel.app/)

---

## 致谢

感谢以下开源项目和社区:

- [Audiveris](https://github.com/Audiveris/audiveris) - 传统 OMR 框架
- [oemer](https://github.com/BreezeWhite/oemer) - 现代深度学习 OMR
- [homr](https://github.com/TimeEscaper/homr) - 端到端 OMR 模型
- GitHub 开源社区在音乐信息检索领域的长期积累

---

## 项目状态

- **当前版本**: v5.11.0 (桌面端 OMR + MIDI 导出)
- **开发状态**: 积极开发中
- **最后更新**: 2026-04-29

---

<div align="center">

**如果这个项目对你有帮助,欢迎 Star**

Made by [张悦轩](https://github.com/Lucas0623z)

</div>
