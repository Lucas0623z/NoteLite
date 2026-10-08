新增录音验证覆盖 21 个原始乐器采样和 3 段完整人声演唱。所有选定录音都经过生产版 Windows 原生事件引擎，保留整段逐帧输出、起音、放音及不确定区间；没有按目标音高限制检测范围，也没有删除失败样本。此次最后打包编译后，被测 `native/audio/build/NoteLiteAudio.exe` 的 SHA256 为 `f00521c280e44e9f6d699846593957f99ff7c5970227bf7a3091d5d99f1b45c3`。

同一文件重跑 168 项合成音频回归和 12 项原生事件回归，全部通过。全部 21+3 原录音也重新执行，24 份完整逐帧文件的 SHA256 与上一轮 `ff101bd7...` 冻结基准相同；下列结果均来自最后打包编译的文件。本轮合成/离线回归没有占用话筒，硬件生命周期和现场声学准确率不包含在这些通过计数中。

最后打包文件另外完成实际 Windows 回放与 WASAPI 回环验证：1 个输入、4 个输出设备；200–800 ms 片段回放 28800 帧，回环检测到知道音高 MIDI 69；120 BPM 连续节拍间隔为 500/500/500/500 ms。250 ms 余拍相位恢复时，首个声学点击在回环捕获起点 320 ms，后续间隔 500/500 ms；进程启动/输出缓冲延迟没有从测值中隐去。部分回放 STOP/EOF 均正常停止。完整证据为 `native/audio/test-output/package-final/hardware/events-results.json`。临时回环录音已删除；这些硬件功能检查仍不是现场演奏准确率验收。

| 乐器与来源 | 采样数 | 首音与原始标签一致 | 不一致的音符事件 | 额外起音事件 |
| --- | ---: | ---: | ---: | ---: |
| 中提琴组，VSCO2 CE | 3 | 3 | 0 | 8 |
| 中提琴独奏，University of Iowa | 3 | 3 | 0 | 0 |
| 竖琴，VSCO2 CE | 3 | 2 | 0 | 0 |
| 双簧管，VSCO2 CE | 3 | 3 | 0 | 0 |
| 圆号，VSCO2 CE | 3 | 2 | 1 | 1 |
| 长号，VSCO2 CE | 3 | 3 | 0 | 0 |
| 大号，VSCO2 CE | 3 | 3 | 0 | 1 |

最终执行总计首音一致 19/21。低音竖琴 G1（MIDI 31）没有得到可靠音符事件，保留为未判断。圆号 F3（MIDI 53；原始文件采用 F2 命名）开头产生 MIDI 52，40 毫秒后转为 MIDI 53。额外起音全部列出；采样没有独立的起音真值，因此不把所有额外起音都说成误判。中提琴组也不能代替独奏验证，因此另外加入了 Iowa 独奏样本。最初基线中提琴组额外起音为 6，修复柔和起音的通用包络条件后最终为 8，保留这项变化，没有隐藏。

| 完整人声录音 | 起音事件数 | 与人工注释 1 音高及时间邻域一致 | 与人工注释 2 一致 | 与人工 F0 相差小于 50 音分的有声帧 |
| --- | ---: | ---: | ---: | ---: |
| vocadito 1 | 60 | 46/60 | 47/60 | 1398/1561 |
| vocadito 2 | 61 | 53/61 | 49/61 | 1781/2114 |
| vocadito 3 | 45 | 41/45 | 40/45 | 765/895 |

第二段人声有 61 帧八度差异。两位注释者的边界和音高划分存在差异，两份比较都保留。这些结果表明当前实时人声仍会有明显的待复核和音符划分问题，不能承诺现场人声或所有 16 类乐器都准确。上低音号 / 次中音号没有找到本次指定原始来源中的真实样本，没有用长号或大号替代它来宣布通过。

来源与许可由原始机构提供，并保存在 manifest.json 及 documents：

- [VSCO2 CE 原始样本](https://github.com/sgossner/VSCO-2-CE)和原始 SFZ 映射，固定 Git 提交，CC0-1.0。使用 SFZ 的数字 pitch_keycenter 作为音高标签，避免文件名的八度命名差异。
- [Iowa 中提琴独奏](https://theremin.music.uiowa.edu/MIS-Pitches-2012/MISViola2012.html)，演奏者 Manuel Tabora；[原始使用许可](https://theremin.music.uiowa.edu/MIS.html)允许下载用于任何项目，没有重新标成 CC0。
- [vocadito 原始 Zenodo 记录](https://zenodo.org/records/5578807)，CC-BY-4.0，Bittner、Pasalo、Bosch、Meseguer-Brocal、Rubinstein；保留两份人工音符注释与人工校正的 F0。下载档案 MD5 与源记录一致，另保存 SHA256。

从项目根目录使用已安装本地运行时执行：

```powershell
& local-analysis/runtime/python/python.exe native/audio/fetch_profile_recordings.py native/audio/test-output/profile-recordings --voice
& local-analysis/runtime/python/python.exe native/audio/benchmark_profile_recordings.py native/audio/test-output/profile-recordings/manifest.json --exe native/audio/build/NoteLiteAudio.exe --output native/audio/test-output/profile-recordings-results
```

抓取程序要求 numpy 和 soundfile，已包含在本地分析运行时中。默认下载 18 个固定 VSCO 文件和 3 个固定 Iowa 独奏文件；`--voice` 加入原始 vocadito 档案中的完整演唱 1/2/3 与两份人工注释。下载体积约 110 MB，原始 vocadito 档案完整性按上游 MD5 校验，Iowa 档案按固定 SHA256 校验，VSCO 文件按固定 Git blob SHA 校验，manifest 再保存每个原文件和解码 PCM 的 SHA256。

benchmark 导入实际 instruments.js 的宽音域和窗口设置，并冻结被测可执行文件与 source-manifest.json，防止同时构建混入不同版本。它需要 Node，可用项目开发依赖提供的 Node。最终打包文件的完整证据位于 `native/audio/test-output/package-final/profile-recordings/results.json` 及旁边的完整 frames.json；合成/事件/原录音的统一 JSON 汇总为 `native/audio/test-output/package-final/native-final-summary.json`。上一轮冻结证据位于 `native/audio/test-output/profile-recordings-final/results.json`，历史基线位于本机 `work/profile-recordings/native-results-21`，通用起音修复后的首次执行位于 `work/profile-recordings/native-results-after-onset-fix`。`test-output` 已被 Git 忽略；不要把原始样本、解码 PCM、录音档案或冻结的 exe 加入源码。它们是原始录音离线重放验证，不是现场话筒、房间或真实用户体验证。
