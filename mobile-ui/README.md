# 音伴手机界面

来自用户提供的 Figma Make 项目，保留其原始图像、唱片路径、头像、字体和浅色／深色设计。

## 构建

使用 Node.js 22.18 或更新版本：

```sh
npm ci
npm run typecheck
npm test
npm run build
```

`dist` 是 Apple App 的离线页面资源。构建使用单一、自包含的普通脚本，检查不支持的模块语法，并去掉 `type="module"` 和 `crossorigin`；字体与图片全部在本机加载。

## 与原生功能连接

`src/app/runtime.tsx` 定义 `YinbanState`、`ScoreRecord`。原生通过 `yinban-state` CustomEvent 推送真实曲谱、处理状态及练习记录；界面通过 `window.webkit.messageHandlers.yinban` 发送操作。服务器凭据不进入网页状态。

我的曲谱支持文件、相册、拍照、云端识谱、暂停、重试、预览、重命名、删除确认及多乐谱练习。练习记录、日历、连续天数、经验和装扮进度使用真实本机记录。首次正确率只计算已经评分的位置，旧记录缺少评分明细时显示「—」。AI 页面给出基于本机记录的规则建议。

## 本机联调预览

普通 `npm run dev` 支持 MusicXML 导入和本机练习。真实 OMR 联调使用仓库中的 `bridge/start_mobile_preview.py`，识谱进程与开发服务器绑定回环地址，并共享仅存在于进程中的临时凭据。

开发代理 `/omr` 只在启动器注入凭据后开启，校验服务地址为回环地址并拒绝跨站请求。客户端不获得令牌。识谱任务上传、轮询、下载经过检查的 MusicXML／MXL，保存在 IndexedDB 后清理服务器任务。手机端通过原生服务器设置连接 HTTPS 云端服务；浏览器联调不会自行连接外网识谱服务器。

浏览器练习使用项目原有 OpenSheetMusicDisplay／Pitchy 页面：音频在本机处理。完成与中途退出都保存一次真实练习记录，文件存储在 IndexedDB，预览元数据存储在 `yinban-preview`。这与 iPhone/iPad 原生资料库分开。

## 待提供的服务与资源

- 官方曲目目录有 150 个曲名，目前没有对应 MusicXML。保留其视觉目录并说明待曲谱资源，不能伪装试听或开始关卡。
- 账号同步、好友、二维码、课堂、推送和付费套餐尚未有后端服务。保留设计，说明未开通，禁用创建课堂／购买。
- 自定义头像、姓名和本机个人档案可以持久保存；使用者可以导出本机练习数据。
- 每完成 3 次练习依次解锁一套装扮；删除记录后重新计算进度。

Noto Sans SC 字体遵循 SIL Open Font License，许可副本位于 `src/fonts/OFL.txt` 和 `public/OFL-NotoSansSC.txt`。第三方练习组件许可位于 `public/practice/THIRD-PARTY.txt`。
