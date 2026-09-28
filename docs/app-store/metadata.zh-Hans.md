# App Store 简体中文资料草稿

本文件供发布者录入 App Store Connect。下面的公开文案依据当前 Apple 客户端编写；最后的审核信息和发布前核对项不属于商店描述。资料保存到公开主分支并验证可访问后，才能将相应网页地址填入商店。

## 基本信息

| 字段 | 内容 |
| --- | --- |
| 名称 | 音伴-你的音乐搭子 |
| 副标题 | 乐谱整理、逐音练习与错音回顾 |
| 主要语言 | 简体中文（zh-Hans） |
| 主要类别建议 | 音乐 |
| 次要类别建议 | 教育 |
| 定价 | 免费（发布者已确认） |
| 销售地区 | 包含中国大陆；需先补齐该地区要求的备案信息 |
| App Store Connect Apple ID | 6816881910 |
| 关键词 | 乐谱,陪练,识谱,练琴,五线谱,音准,节奏,钢琴,MIDI,MusicXML,曲谱,练习记录 |
| 支持网址（发布后验证） | https://github.com/Lucas0623z/NoteLite/blob/main/docs/app-store/support.md |
| 隐私政策网址（发布后验证） | https://github.com/Lucas0623z/NoteLite/blob/main/docs/app-store/privacy.md |
| 营销网址（可选） | https://github.com/Lucas0623z/NoteLite |
| 版权 | 2026 Yuexuan Zhang |

## 宣传文本

把乐谱整理和日常练习放在一起。导入 MusicXML，在本机通过麦克风或 MIDI 乐器练习，查看错音与节奏回顾。PDF 和图片识谱需配置自己的兼容服务器。

## 描述

音伴-你的音乐搭子，让每一次练习都有谱可循。

【整理自己的乐谱】
从“文件”导入 PDF、PNG、JPEG、TIFF、MusicXML 或 MXL。原稿和已下载的识谱结果保存在设备上，方便预览与分享。

【逐音练习与回顾】
直接导入 MusicXML，选择声部和小节，使用麦克风或已连接的 MIDI 乐器练习。通过音符和节奏反馈找到需要再练的地方，并在本机查看练习记录。

【连接自己的识谱服务器】
配置 NoteLite 兼容的 HTTPS 服务器和访问令牌后，将 PDF 或图片上传识别。识别成功后下载 MusicXML 等结果，继续练习或导出。

【按自己的节奏练习】
支持小节选择、试听、暂停继续、错音定位与重练。iPhone 和 iPad 界面随屏幕空间调整，便于在谱架旁使用。

使用说明：
• MusicXML 练习可在本机进行。
• PDF 和图片识谱需要用户自行配置可访问的兼容服务器及令牌，应用不提供预设公共识谱服务或设备离线识谱引擎。点选识别后，原稿和文件名会发送到所选服务器。
• 麦克风适合单音旋律，不能可靠识别和弦或合奏。反馈供练习参考，不评价踏板、音色或触键。
• 单份导入文件上限为 25 MiB，进入练习的 MusicXML 或 MXL 文件上限为 15 MiB。

支持：https://github.com/Lucas0623z/NoteLite/issues

## 本版本更新说明草稿

采用音伴名称与应用图标，增加应用内隐私政策及支持入口。支持乐谱导入、MusicXML 本地练习、练习回顾，以及连接自选服务器识别扫描谱。

## App Review 审核说明草稿（仅审核信息字段）

The app supports local MusicXML practice and optional recognition through a user-configured NoteLite-compatible HTTPS server. The app itself has no user account or login. PDF/image recognition requires a server address and bearer token; it is not performed offline on the device.

To test local practice, download the sample at https://raw.githubusercontent.com/Lucas0623z/NoteLite/main/practice-web/src/demo.musicxml and save it to Files, then import it, open the imported score, and choose Practice. A compatible MIDI instrument or microphone permission is required for live performance input. Microphone analysis supports monophonic input and runs on device without saving or uploading audio. Practice summaries are stored locally.

To test recognition, open Server Settings, enter the review server URL and token supplied privately in App Review Information, import a PDF or image, and select Start Recognition. Completed results are downloaded to the device. The health check verifies connectivity only; the upload validates the token. Deleting a local score with a server job first requests deletion from that server, so the server must be reachable and the job must be finished.

Privacy Policy and Support are available under Server Settings > Privacy and Support.

### 提交前仍需补齐

- 可供 Apple 实际访问并完成真实识谱的 HTTPS 审核服务器、有效令牌和测试乐谱。将凭据填在 App Store Connect 私有审核资料中，不写入仓库或公开页面。
- 审核联系人姓名、电话和电子邮件由发布者确认。仓库公开支持邮箱为 `Lucas.z0623@outlook.com`；这不等于已确认的审核联系方式。
- 已签名并成功上传的构建、对应 iPhone / iPad 截图及实际真机验收结果。
- 发布者已选择免费且包含中国大陆，当前尚无 ICP 备案信息；中国大陆发布所需信息未补齐前不能视为可提交发布。年龄分级、内容权利及出口合规问卷仍需按真实情况填写。

## 隐私申报依据（不复制到商店描述）

发布者已确认不运营识谱服务器；当前客户端没有预设后端、账户体系、广告、行为分析或遥测。根据 Apple 对“收集”的定义，结合这一部署事实，当前 `PrivacyInfo.xcprivacy` 的 `NSPrivacyCollectedDataTypes` 为空，`NSPrivacyTracking` 为 `false`。App Store Connect 可据此填写开发者及合作伙伴不收集本应用数据。

这一判断不意味着应用从不发送数据。用户独立配置识谱服务器后，原稿、文件名、认证令牌和任务请求会发送给该运营者，原文件不会自动脱敏。具体行为及清理限制已在隐私政策中说明。独立服务器不因用户填入地址而自动成为开发者的合作伙伴。若未来由开发者或合作伙伴提供识谱服务、收集分析数据，必须重新核对收集类别、关联状态、用途和留存政策，并更新清单及商店申报；不能沿用当前的空收集声明。

麦克风声音、MIDI 输入及练习历史只在本机处理或保存。桥接服务的共享令牌用于认证，不是客户端创建的用户账户 ID。用户选择的服务器是否保留 IP 地址、认证信息和网关日志，需由对应运营者说明。支持联系通过外部邮件或 GitHub 页面进行，用户主动提交的信息按隐私政策处理。归档时还应核对所有随包依赖是否引入额外的数据收集。

`UserDefaults` 仅保存应用自身的服务器设置，使用必需理由 `CA92.1`。源码核对未发现读取设备启动时间、磁盘剩余空间、活动键盘列表或文件时间戳的覆盖 API；文件大小限制使用 `URLResourceValues.fileSize`。归档后还需生成 Xcode Privacy Report 并检查完整应用与依赖。

参考 Apple 官方资料（2026 年 9 月 28 日核对）：

- [App privacy details on the App Store](https://developer.apple.com/app-store/app-privacy-details/)
- [Required reason API 类别与理由](https://developer.apple.com/documentation/bundleresources/app-privacy-configuration/nsprivacyaccessedapitypes/nsprivacyaccessedapitype)
- [隐私清单数据类型](https://developer.apple.com/documentation/bundleresources/app-privacy-configuration/nsprivacycollecteddatatypes/nsprivacycollecteddatatype)
