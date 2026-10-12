# 124.221.211.156 的同源 HTTPS 部署材料

这里只准备了文件，未操作服务器、未申请证书、未接受 CA 条款、未修改腾讯云防火墙。

目标：Ubuntu 24.04；原识谱服务 `127.0.0.1:8765`；新增认证网关 `127.0.0.1:8770`；同一个 `https://124.221.211.156` 提供 Figma 构建后的静态页面和 `/api/`。nginx 向网关发送公开 IP 的 Host；由网关验证来源、认证、所有权后转发给原服务。原服务的共享口令不会写进 nginx 配置或静态页面。gateway.py 的配对命令另见网关文档。

本材料不改变原 nginx 默认站点或原识谱服务，不执行 UFW、腾讯云防火墙、重启实例等操作。未知的同名配置和服务单元会拒绝覆盖。安装命令会安装软件、发布新静态文件、启动新增服务并使 nginx 监听 80/443；实际执行应在已获得部署授权后进行。

## 执行顺序

先把 gateway.py、deploy 目录、真实 Figma 构建后的 dist 上传到服务器的暂存目录。以下示例假设位于 `/root/notelite-release`；路径参数须对应实际文件。

```bash
bash /root/notelite-release/deploy/install.sh bootstrap \
  --gateway /root/notelite-release/gateway.py \
  --static-dist /root/notelite-release/dist \
  --certbot-version 5.4.0
```

bootstrap 只增加 HTTP ACME challenge 站点，其他 HTTP 请求跳转 HTTPS。此时 HTTPS 尚未启用。确认腾讯云安全组允许外部访问 80（本脚本不会设置）后，先可显式执行 staging 测试，再申请受信任生产证书。staging 使用独立目录，不能替代生产证书。

```bash
# 下列 --agree-tos 表示明确同意 CA 条款；材料本身没有接受条款。
/opt/notelite-gateway/deploy/request-certificate.sh --agree-tos --email YOUR_EMAIL --staging
/opt/notelite-gateway/deploy/request-certificate.sh --agree-tos --email YOUR_EMAIL
# 如明确选择不登记邮箱，改为 --agree-tos --without-email；不能两者同时传入。
bash /opt/notelite-gateway/deploy/install.sh https
```

Certbot 5.4.0 为可复现固定基线，不代表当前最新版本；可以显式指定更高的已审查精确版本。IP 证书采用 `--ip-address`、webroot 和 `shortlived` profile，而不是 `-d IP` 或 nginx 插件。生产文件固定在 `/etc/letsencrypt/live/124.221.211.156/{fullchain,privkey}.pem`。

每小时 timer 带 10 分钟随机延迟，调用 Certbot 正常到期判断，不强制每小时重新签发。成功更新后 deploy hook 检查 nginx 配置并 reload。运行失败及证书剩余少于 36 小时都会返回非零状态，保留 systemd 日志供外部监控；材料没有虚构已经启用的告警通知。

```bash
systemctl start notelite-cert-renew.service
journalctl -u notelite-cert-renew.service --no-pager -n 50
/opt/notelite-gateway/deploy/check-health.sh
systemctl list-timers notelite-cert-renew.timer --all
# 在服务器以外的电脑也必须验证可信 TLS 和公网可达性：
curl --fail --show-error https://124.221.211.156/api/health
```

`check-health.sh` 不读取或打印口令。它检查证书剩余时间、服务和 timer 状态、本机 OMR、通过可信 HTTPS 的同源网关和公网地址。服务器自身访问公网 IP 不能替代外部设备实测。Windows 上只能检查模板与脚本语法，Linux nginx 配置、systemd、实际 CA 签发及外部可达性必须在部署阶段验证。

依据：[Let's Encrypt：Certbot 的 IP / 短周期证书支持](https://letsencrypt.org/2026/03/11/shorter-certs-certbot)、[IP 证书正式可用](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability)。
