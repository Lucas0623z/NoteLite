# NoteLite 云识谱设备网关

本目录实现新的 Figma 界面接入已有腾讯云 OMR/改谱服务的网关；不包含听音、评分或音频模型。原 OMR `127.0.0.1:8765` 不改动；网关监听 `127.0.0.1:8770`，nginx 提供同源 HTTPS 页面与 `/api`。

## 设备配对

安装后在服务器 root 终端生成一次性文件：

```sh
/opt/notelite-gateway/deploy/issue-pairing.sh \
  --output /var/lib/notelite-gateway/iphone.pairing.json --ttl 600
```

文件仅 audiveris/root 可读，包含 `code`、`expiresAt`、`owner`、`origin`。默认期限 10 分钟，只能兑换一次；生成命令不在终端输出配对码。不将文件放进静态页面、源码包或日志。通过已有可信通道交给设备，输入界面已有服务器配置的配对位置。每增加一个设备重新生成码；默认同一主体，iPhone/iPad/Mac 可访问自己的同一组任务。要隔离其他使用者，增加 `--owner` 与独立 UUID。

原生 Apple 请求：

```http
POST /api/pair
Content-Type: application/json

{"code":"一次性配对码","deviceName":"我的 iPhone","mode":"native"}
```

成功 `201` 返回 `{deviceId, owner, deviceName, expiresAt, token}`。`token` 是此设备专用凭据，不是内部管理员口令；Swift 将它按 HTTPS origin 写入 Keychain，并在 JS 回调前删除 token。之后原生请求携带 `Authorization: Bearer <device token>`，有效期 90 天，重新配对可生成新凭据。

浏览器请求相同接口，改为 `mode: "browser"`，必须从实际同源 HTTPS 页面发出。成功返回 `{deviceId,owner,deviceName,expiresAt,csrf}`，并设置 `__Host-notelite-session` 的 Secure/HttpOnly/SameSite=Strict cookie，有效期 30 天；响应不包含设备 token。`GET /api/session` 可在刷新后取得 csrf。所有修改、上传、退出请求带 `X-NoteLite-CSRF: <csrf>`；浏览器自动提供 Origin，fetch 使用同源相对路径与 credentials: "same-origin"。`POST /api/session/logout` 撤销当前设备并清除 cookie。

## 数据接口与隔离

除了 `/api/health`、首次 `/api/pair`，所有接口需要设备认证。每项创建的任务在 SQLite 内记录主体，读取、修改、导出均检查所有者；列表只返回本人任务，其他主体/原管理员验收任务返回 404。共享内部口令仅由网关读取 `/var/lib/audiveris/access-token` 并用于内部转发，它不能用于公网设备认证，不会下发客户端。

- `POST /api/jobs?filename=URL编码文件名`：原始文件体，32 MiB；202 返回真实 job。
- `GET /api/jobs`、`GET /api/jobs/{UUID}`：任务列表/状态，包含 `scores`（所有乐章）、`revision`、`artifacts` 字典。
- `GET /api/jobs/{UUID}/score/notes?score=0`：逐音符数据。
- `PATCH /api/jobs/{UUID}/score/notes`：JSON `{revision,score,edits}`，必须提交当前修订号。
- `PUT /api/jobs/{UUID}/score?score=0`：完整 MusicXML，10 MiB；必须带 `If-Match: "修订号"`。
- `GET /api/jobs/{UUID}/score/musicxml?score=0` 与 `/score/midi?score=0`：按乐章下载，保留 ETag 修订号。
- `GET …/original`、`…/project/omr`、`…/log`：本人任务的原稿/原始识谱项目/诊断；网页 XML 修改不回写原 `.omr`。

没有 DELETE 接口。后台清理必须另行实现，不能让前端把本地删除显示成服务已清理。保存冲突 409 时保留本地修改；下载 XML/MIDI 后比较 ETag，避免读取不同修订。API 转发固定 localhost，覆盖 Host，验证外部 Origin 后清除内部 Origin，不转发浏览器 cookie/任意代理请求头。每设备请求限流与每来源配对限流、16 并发上限、上传限制共同限制资源占用。

## TLS 安装与续签

详细安装顺序见 [deploy/README.md](deploy/README.md)。例如已上传 gateway 源码与真实 Figma 前端 dist 后：

```sh
bash deploy/install.sh bootstrap --gateway gateway.py --static-dist /root/notelite-ui/dist
```

首次仅配置 HTTP ACME challenge，不访问 CA，也不更改云防火墙。由用户确认 CA 条款/选择联系人之后单独申请：

```sh
/opt/notelite-gateway/deploy/request-certificate.sh --agree-tos --email 真实邮箱
# 如果明确选择不提交邮箱：--agree-tos --without-email
/opt/notelite-gateway/deploy/install.sh https
/opt/notelite-gateway/deploy/check-health.sh
```

这里的示例邮箱不是默认值；申请脚本未提供显式 --agree-tos 就失败退出。IP 证书需要 Certbot 5.4+ webroot/shortlived，160 小时有效期，安装每小时随机执行正常 renew（不强制反复签发）、deploy hook 测试配置并 reload nginx。健康检查要求真实可信证书、IP SAN、至少剩余 36 小时、服务/timer 正常、HTTPS 网关与 OMR 健康；本机公网路由通过后仍须从外部设备验证。

官方依据：[Certbot IP 证书说明](https://letsencrypt.org/2026/03/11/shorter-certs-certbot)、[IP/160 小时证书已全面可用](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability)。

## 本地测试

```sh
python3 -m unittest -v test_gateway
```

HTTP 回归使用严格 localhost Host/Origin 的独立测试上游，检查真实代理请求与设备/主体隔离、一次性配对、有效期、重启持久化、CSRF、退出撤销、修订冲突、路径白名单、超限和凭据不泄漏。这些测试不代替真实 Audiveris 识谱、不证明 TLS 签发成功。发布前仍要在实际 HTTPS 入口上传 PNG/PDF 并校验编辑后的 XML/MIDI。
