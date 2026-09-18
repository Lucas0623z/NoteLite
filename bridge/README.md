# NoteLite 识谱桥接服务

为 iPhone、iPad 和其他 HTTP 客户端提供真正的 NoteLite 识谱接口。服务把上传的 PDF / PNG / JPEG / TIFF 交给本仓库的 Java 批处理引擎，返回 MusicXML、MIDI 和引擎生成的 `.omr` 文件。识谱在运行本服务的电脑或服务器上完成，不在 iPhone / iPad 上运行 Java。

仅使用 Python 标准库，无需 `pip install`。需要 **Python 3.10+、JDK 21、本机平台的 NoteLite 分发包**，以及与桌面版相同的 OCR 语言数据。Java 21 的预览功能已启用，因此不要将 Java 21 构建的包直接换用其他主版本运行。服务不会自动下载 JDK、语言数据或启动模拟识谱引擎。

## 构建与启动

以下命令从仓库根目录执行。先用 JDK 21 构建与服务所在操作系统、CPU 架构一致的分发包：

```powershell
# Windows PowerShell
.\gradlew.bat :app:installDist
$env:NOTELITE_BRIDGE_TOKEN = python -c "import secrets; print(secrets.token_urlsafe(32))"
python bridge/notelite_bridge.py --distribution app/build/install/app --storage bridge/.notelite-bridge
```

```sh
# macOS / Linux
bash ./gradlew :app:installDist
export NOTELITE_BRIDGE_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 bridge/notelite_bridge.py --distribution app/build/install/app --storage bridge/.notelite-bridge
```

如果 JDK 21 不在 `PATH`，追加 `--java /绝对路径/bin/java`（Windows 为 `java.exe`）。`--distribution` 应包含 `lib/notelite.jar` 和 Gradle 收集的依赖；服务启动时验证主类和 Java 版本。Apple Silicon 的分发包不能拿到 Windows 上运行，反之亦然。

默认配置：

| 参数 | 默认值 | 含义 |
|---|---|---|
| `--host` | `127.0.0.1` | 仅监听本机，前置 HTTPS 代理 |
| `--port` | `8765` | HTTP 端口 |
| `--storage` | `bridge/.notelite-bridge` | 输入、输出、任务状态和日志目录 |
| `--heap` | `4g` | 每次识谱的 Java 最大堆大小 |
| `--timeout` | `600` | 每个 Java 进程的超时秒数 |
| `--queue-size` | `4` | 活动任务之外的队列容量 |
| `--max-jobs` | `100` | 包括已完成任务的最大保留数量 |
| `--token-env` | `NOTELITE_BRIDGE_TOKEN` | 保存访问令牌的环境变量名 |

令牌必须是至少 32 个无空白 ASCII 字符；所有任务接口都必须携带令牌。使用独立、随机生成的值，并妥善保存供客户端设置使用。不要将令牌提交到 Git。此版本使用一个共享令牌，没有多用户账户隔离；持有令牌的客户端可读取和删除已知 ID 的任务。

## Apple 客户端连接与 HTTPS

让 iPhone / iPad 使用能够访问到的 **HTTPS 地址**，例如 `https://omr.example.com`，并填入相同的令牌。`localhost` 在手机上指手机自身，不能指向你的电脑。

可让 Caddy、nginx 或已有的 HTTPS 网关代理到 `127.0.0.1:8765`。例如部署在有域名、DNS 和 TLS 条件的服务器上，Caddy 配置为：

```caddyfile
omr.example.com {
    request_body {
        max_size 26214400
    }
    reverse_proxy 127.0.0.1:8765
}
```

将域名换成自己的域名，并让代理保留 `Authorization` 请求头。桥接服务本身提供 HTTP；不要把携带令牌的明文 HTTP 直接暴露到公网，也不需要为正式 Apple 客户端关闭系统传输安全限制。通过 VPN 或内网访问时，同样使用设备信任的 HTTPS 证书。

建议用专门的系统账户运行服务，存储目录仅让该账户访问，并按实际乐谱大小配置磁盘空间。一个 Java 子进程串行处理识谱任务，最多 16 个 HTTP 请求同时处理；任务容量已满时返回 `503` 和 `Retry-After: 5`。进程隔离不是系统沙盒，处理不可信文件的公开部署还应使用操作系统或容器的资源限制。

## API v1

所有响应 JSON 使用 UTF-8。错误响应为 `{"error":"说明"}`。除健康检查外，均要求：

```http
Authorization: Bearer <NOTELITE_BRIDGE_TOKEN>
```

### `GET /v1/health`

无需认证，返回 `200 {"status":"ok"}`。表示 HTTP 服务可访问，不能替代真实识谱测试。

### `POST /v1/jobs?filename=<URL编码的原文件名>`

请求体直接放文件内容，**不是 multipart**。必须有准确的 `Content-Length`；不接受 chunked / 压缩传输。文件大小为 1 字节至 **25 MiB（26,214,400 字节）**，扩展名与文件签名须匹配。支持 `.pdf`、`.png`、`.jpg`、`.jpeg`、`.tif` 和 `.tiff`。签名检查并非完整文件校验；引擎负责解析实际文档。文件名不能包含路径分隔符或控制字符。

成功返回 `202`：

```json
{
  "id": "1096a6c1-32ce-4d06-a72f-e565700ecde2",
  "state": "queued",
  "filename": "乐谱.pdf",
  "error": null,
  "artifacts": []
}
```

服务仅通过固定的参数数组启动真实引擎，不经过 shell：

```text
java <固定JVM选项> -cp <distribution>/lib/* NoteLite
  -batch -transcribe -export -export-midi -output <任务输出目录> -- <任务输入文件>
```

### `GET /v1/jobs/{id}`

返回 `200` 和同样的任务结构。`state` 为 `queued`、`running`、`succeeded` 或 `failed`。客户端可每 2 秒查询一次；收到 `succeeded` 或 `failed` 后停止查询。

完成后，`artifacts` 包含文件的安全名称和相对地址：

```json
{
  "id": "1096a6c1-32ce-4d06-a72f-e565700ecde2",
  "state": "succeeded",
  "filename": "乐谱.pdf",
  "error": null,
  "artifacts": [
    {"name": "01-score.mid", "path": "/v1/jobs/1096a6c1-32ce-4d06-a72f-e565700ecde2/artifacts/01-score.mid"},
    {"name": "02-score.mxl", "path": "/v1/jobs/1096a6c1-32ce-4d06-a72f-e565700ecde2/artifacts/02-score.mxl"}
  ]
}
```

文件列表取决于引擎实际产出，多个乐章可以生成多个文件。引擎返回非零退出码、超时或没有生成 MusicXML 时，任务为 `failed`，`error` 提供说明。只有输出文件真实存在且非空才会提供下载。

### `GET /v1/jobs/{id}/artifacts/{name}`

下载任务列出的一个文件，必须携带令牌。`200` 返回原始字节，附有 `Content-Length` 和下载文件名；路径遍历、未列出的文件和服务器日志均不可下载。客户端应将 API 返回的相对路径与已配置的服务地址组合。

### `DELETE /v1/jobs/{id}`

删除已完成或失败任务的输入、输出、状态和日志，成功返回 `204`。运行中 / 排队中的任务返回 `409`；不存在的任务返回 `404`。建议客户端在本地保存所需结果后删除服务器任务。

任务状态保存在存储目录，重启后可重新查询已完成任务。重启时遗留的排队 / 执行中任务会标记为失败，需重新上传。没有自动过期删除；达到 `--max-jobs` 后必须删除旧任务才能继续上传。管理员也可在服务停止后清理整个专用存储目录。

## 验证

```sh
python3 -m unittest discover -s bridge/tests -v

# 构建分发包后，用仓库自带真实乐谱验证上传、识别、两种格式下载及删除
python3 bridge/smoke_real_engine.py
```

测试覆盖 HTTP 上传、认证、下载、删除、任务恢复、格式与大小边界、队列容量、失败退出码和子进程超时。`tests/fake_engine.py` **仅是测试专用的子进程替身，不会识谱，也从不用于正式服务启动**。这些测试不证明 OMR 准确率；真实验证须构建分发包、启动服务、上传一份真实乐谱并检查导出的 MusicXML / MIDI。每项任务的详细引擎日志保存在 `<storage>/<id>/engine.log`。
