# 独立 OMR 接口

Python 3.10 及以上，仅标准库。启动入口与现有 systemd 单元兼容：

```sh
python3 /opt/notelite-omr/server.py --host 127.0.0.1 --port 8765 \
  --storage /var/lib/audiveris/jobs \
  --token-file /var/lib/audiveris/access-token
```

`--bind` 是 `--host` 的别名，只允许 `127.0.0.1`。默认 `--omr /usr/local/bin/audiveris-omr`、`--midi /usr/local/bin/omr-midi`、识谱超时 900 秒、MIDI 超时 120 秒；可用 `--timeout`、`--midi-timeout` 修改。需要命令前缀含多个参数时，使用 `OMR_ENGINE_COMMAND`、`OMR_MIDI_COMMAND` 的 JSON 字符串数组。执行不经过 shell。

未提供现成令牌时，服务用随机令牌创建 `--token-file`，权限为 `0600`。本机管理员读取该文件后将令牌填写到页面“连接设置”。令牌仅通过 `Authorization: Bearer …` 请求头传输，不放入 URL。服务不打印令牌。`OMR_TOKEN` 可显式覆盖令牌。

页面 `/` 与 `GET /api/health` 不要求令牌；其余 API 全部要求令牌。Host 仅接受 localhost 或 127.0.0.1；带 Origin 的请求须与 Host 的主机、端口相同。没有开放跨域接口。

## 上传与状态

内部网关上传可带 `X-NoteLite-Job-Id: UUID`，由服务按该预留标识创建任务，已有标识返回 409 且保留原文件。该头只在内部 Bearer 认证后接受；公网客户端不能覆盖网关生成的标识。网关在转发前持久登记归属，因此上游响应丢失也能继续查询和注销清理。

`DELETE /api/jobs/{id}` 仅供经过认证的本机内部服务使用，返回 200 `{id,deleted:true,alreadyAbsent}`。它取消排队任务，停止运行中的整个进程组，等待该任务写入线程退出后实际删除原稿、日志、工程和全部修订。不存在的任务可幂等重试；仍在接收上传、停止或文件删除失败返回 503，不能当作删除完成。任务归属必须先由账号适配器在网关数据库锁内核实。公网网关不提供此 DELETE 接口。

`POST /api/jobs?filename=原稿.pdf` 的请求体直接使用文件原字节，并提供 Content-Length。上传最大 32 MiB，支持 PDF、PNG、JPEG、score-partwise MusicXML 和 MXL；扩展名与内容必须对应。单份 XML 最大 10 MiB。MXL 不解压到文件系统，解析所有声明的乐章入口，最多 64 份，压缩包总展开内容最多 64 MiB。XML 拒绝实体及内部 DTD；允许外部 MusicXML DOCTYPE，解析时不获取网络资源。

上传返回 HTTP 202。`GET /api/jobs/{id}` 查询任务，`GET /api/jobs` 列出保存的任务。id 为严格 UUID。状态为 `queued`、`running`、`succeeded`、`failed`；`status` 是 `state` 的别名。示例：

```json
{
  "id": "任务 UUID",
  "filename": "原稿.pdf",
  "state": "succeeded",
  "status": "succeeded",
  "revision": 1,
  "sourceType": "pdf",
  "recognitionMode": "audiveris",
  "warnings": [],
  "error": null,
  "scores": [{"id":"0","index":0,"name":"input.mvt1","noteCount":42,
    "musicxml":"/api/jobs/任务UUID/score/musicxml?score=0",
    "midi":"/api/jobs/任务UUID/score/midi?score=0"}],
  "artifacts": {"musicxml":"…","midi":"…","original":"…","omr":"…","log":"…"}
}
```

还包含 `createdAt`、`updatedAt`。缺少的输出不会出现在 artifacts 中。XML/MXL 导入的 `recognitionMode` 为 `import`，不会运行图像识谱。识谱采用单队列；最多同时保留一个处理中任务和四个等待/上传中的任务。默认保存 100 个任务，达到上限返回 503，需管理员备份及整理存储。重启恢复保存的任务，未完成任务标失败并保留原稿，不自动重复识谱。

## 文件与音符

所有 score 端点接受 `?score=0`，索引从 0 开始，默认第一乐章。

| 方法和路径 | 内容 |
| --- | --- |
| GET `/api/jobs/{id}/score/musicxml` | 实际解压后的 MusicXML XML 字节 |
| GET `/api/jobs/{id}/score/midi` | 同一已发布修订的实际 MIDI 字节 |
| GET `/api/jobs/{id}/original` | 未改动的上传原字节 |
| GET `/api/jobs/{id}/project/omr` | Audiveris 工程原文件，若生成 |
| GET `/api/jobs/{id}/log` | 识谱及 MIDI 转换日志 |
| GET `/api/jobs/{id}/score/notes` | 当前乐章音符 JSON |

`/notes` 是 `/score/notes` 的别名。返回：

```json
{"jobId":"任务UUID","revision":1,"score":0,
 "parts":[{"id":"P1","name":"Flute"}],
 "notes":[{"partId":"P1","measureIndex":0,"noteIndex":0,
   "measure":"1","sourceNoteId":"P1:0","divisions":4,"duration":4,
   "type":"quarter","dot":0,"rest":false,
   "pitch":{"step":"C","alter":0,"octave":4},
   "voice":"1","staff":"1","chord":false,"grace":false,"ties":[]}]}
```

measureIndex 是该声部小节序号；noteIndex 是小节内直接 note 子节点序号，包含休止和和弦音。二者均从 0 开始。duration 是 MusicXML 原 divisions 单位，四分音符拍数为 duration/divisions。sourceNoteId 是当前 XML 修订的声部与全声部 note 顺序标识，删除后序号可能改变。XML 移调、重复、连线和乐器 MIDI 信息仍交由原导出算法处理。

## 持久校对

`PATCH /api/jobs/{id}/notes?score=0` 请求体：

```json
{"revision":1,"score":0,"edits":[
 {"partId":"P1","measureIndex":0,"noteIndex":0,
  "pitch":{"step":"F","alter":1,"octave":5},
  "duration":6,"type":"quarter","dot":1}
]}
```

revision 是读取时的修订号，提供它可避免覆盖他人更新。最多 200 项修改，所有定位针对修改前同一 XML。未指定字段保留；支持 pitch（step C–B、alter 整数 -2–2、octave -1–9 且 MIDI 0–127）、duration 正数、type、dot 整数 0–4、rest 布尔和 delete 布尔。休止转换会移除音高、升降号及该音符的延音绑定；delete 删除该 note。暂不支持通过 PATCH 新增音符。

`PUT /api/jobs/{id}/score?score=0` 请求体为完整 XML，建议带 `If-Match: "1"` 修订号，可编辑 PATCH 未覆盖的记谱内容。

两个编辑入口均同步生成所有乐章的 MIDI，然后才原子发布新 revision 并返回更新后的任务 JSON。任一 XML/MIDI 转换或元数据持久化失败均保留旧谱面和旧 MIDI。原稿及原 .omr 不改动；`revisions/00000001` 等目录保存已发布历史。相同任务识谱或编辑期间，第二次编辑返回 409。修订过期也返回 409，需要重新读取。

测试脚本 `test_server.py` 与 `test_server_independent.py` 使用真实独立 MIDI 转换器验证事务和接口。可在部署机器设置 `OMR_TEST_MIDI_COMMAND='["/usr/local/bin/omr-midi"]'`、`OMR_TEST_CONVERTER='["/usr/local/bin/omr-midi"]'` 后运行；图像识谱验收另使用服务器实际 PNG/PDF 输出证据。
