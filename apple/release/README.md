# 音伴 App Store 构建与上传

商店名称：**音伴-你的音乐搭子**。默认 Bundle ID：`com.lucas0623z.yinban`。工程名和 scheme 保留 `NoteLite`，不影响商店展示名称。

## 工作流

在 GitHub → Actions → **iOS App Store release** → Run workflow 运行。工作流文件需要先进入默认分支，手动运行入口才会出现；相关拉取请求会自动执行无签名校验。

| 设置 | 用途 |
| --- | --- |
| `engine: cloud`（默认） | 新手机 UI；OMR 通过 HTTPS 云端服务处理，音频/MIDI 在本机分析。设备 archive 不打包 JVM 和完整 OMR 资源。 |
| `engine: embedded` | 保留旧完整引擎归档和原生资源校验路线，用于旧嵌入版维护；新手机客户端使用云端策略。 |
| `mode: verify`（默认） | 构建真正的 iOS 设备 archive，检查版本、Bundle ID 和 SDK；无需 Apple 密钥。产物未签名，不能安装或上传。 |
| `mode: export` | 使用下面的签名密钥生成 App Store IPA 和 archive。 |
| `upload: false`（默认） | 只导出产物。 |
| `upload: true` | 必须选择 `export`；先调用 Apple 验证，再上传 App Store Connect。上传后仍需等待处理和 App Review。 |
| `bundle_id` / `team_id` | 必须与 Apple Developer 注册的 App ID、描述文件及 App Store Connect 记录一致。导出时必填 Team ID。 |
| `version` / `build_number` | 默认版本 `1.0.0`；空构建号使用工作流 run number。已上传的版本/构建号组合不能重复；重跑旧任务时请改用新的构建号。 |
| `acceptance_run_id` | `export` 必填：云端客户端要求同一源码提交的 **Apple clients** 成功运行编号，iPhone、iPad 和 native-clients 三项必须通过；旧嵌入路线仍要求同一源码及原生资源来源的完整引擎验收。 |

工作流使用 GitHub 的 `macos-26` runner，选择已安装的最高稳定 Xcode，并在构建前后验证 Xcode 26 / iOS SDK 26 最低要求。产物在 Actions 中保留 7 天，正式版本请下载保存。云端 `verify` 会测试并打包新 MobileUI 和本地练习模块，校验实际 archive/IPA 与网页资源哈希、设备架构、iPhone/iPad 支持，并拒绝意外混入完整 OMR 资源。Apple clients 运行新导航、真实 MusicXML 导入和保存后多部分练习的模拟器测试并导出截图。真机交互、麦克风和 MIDI 仍须验收；OMR 云服务地址和用户独立凭据需要另行配置。

## 防止发布包遗漏识谱引擎

发布流程从 `tools/audiveris-port/native-artifact-runs.json` 取得已成功构建的真机运行时和 OCR 产物，在当前 runner 重新组合完整工程，再由发布脚本归档。原始静态库、Java 模块、识谱代码、分类模型、OCR 模型、字体和练习资源都进入应用。产物缺失、过期或验证失败会中止构建。

`release.py` 要求 `RELEASE_EMBEDDED_BUILD` 指向 `build-embedded-app.sh iphoneos` 的完整输出目录；不能用普通 `apple/project.yml` 生成的工程代替。导出前还会检查实际 archive 中的资源校验和、设备平台和 JNI 入口。`embedded-archive-inventory.json` 与归档一起保存，构建来源和组合日志保存在单独的证据产物中。

先对准备发布的同一提交运行完整嵌入式验收，再把成功运行编号填入 `acceptance_run_id`。改变源码提交或原生构建来源后，需要重新验收；基础客户端构建成功不能满足正式导出的条件。若固定的原生产物已过期，重新运行对应构建，更新编号，再执行验收。

## 一次性配置 GitHub Secrets

仓库 → Settings → Secrets and variables → Actions → New repository secret。签名文件只放在 GitHub Secrets；不要提交 `.p12`、`.p8`、描述文件、密码或私钥到仓库，不要粘贴到 issue 或日志。

| Secret | 内容 | 何时需要 |
| --- | --- | --- |
| `IOS_DISTRIBUTION_P12_BASE64` | 带私钥的 Apple Distribution 证书 `.p12`，整体转成 base64 | export |
| `IOS_DISTRIBUTION_P12_PASSWORD` | 导出该 `.p12` 时设置的非空密码 | export |
| `IOS_APP_STORE_PROFILE_BASE64` | 对应精确 Bundle ID、团队和证书的 App Store Connect 分发 `.mobileprovision`，整体转成 base64 | export |
| `ASC_API_KEY_ID` | App Store Connect **团队 API 密钥**的 Key ID | upload |
| `ASC_API_ISSUER_ID` | 同一团队的 Issuer ID | upload |
| `ASC_API_PRIVATE_KEY_BASE64` | 对应 `AuthKey_….p8` 文件，整体转成 base64 | upload |

在 Mac 的 Keychain Access 导出分发证书及其私钥为 `.p12`；Apple 网站下载的 `.cer` 不包含私钥，不能代替 `.p12`。描述文件在 Apple Developer → Certificates, Identifiers & Profiles 创建，类型选 App Store Connect。API 密钥在 App Store Connect → Users and Access → Integrations 创建，授予允许上传构建的权限，并保留好只可下载一次的 `.p8`。这里使用需要 Issuer ID 的团队密钥。

在 Mac 上，可把文件的 base64 写入剪贴板，再直接粘贴至 GitHub Secret：

```sh
base64 -i /absolute/path/distribution.p12 | pbcopy
```

Windows PowerShell：

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes('C:\secure\distribution.p12')) | Set-Clipboard
```

同样处理 `.mobileprovision` 和 `.p8`。不要把转换结果写入仓库文件。建议限制可修改发布工作流和签名 secrets 的人员；如需组织内发布审批，可将签名步骤移入受保护的 GitHub Environment，并在该环境配置同名 secrets。

脚本在临时钥匙串导入证书，检查有效期、团队、精确 App ID、App Store 分发类型及证书是否属于描述文件，再执行 archive / export。正常结束、失败及工作流清理步骤都会移除临时钥匙串、描述文件和 API 私钥；使用 GitHub 托管的临时 runner。私钥不会包含在上传的构建产物中。

## 上传后

等待 App Store Connect 完成处理，在对应版本选择构建，补齐实机/模拟器截图、隐私政策与支持网址、App Privacy、年龄分级、出口合规、审核联系信息、必要的测试服务器/凭据、定价和可用地区，再提交审核。App Store 显示的图标来自构建中的 AppIcon。

上传成功仅表示 Apple 接收了构建；本工作流不会自动提交审核、更改定价或发布版本。App Review 通过且版本按所选方式发布后，应用才会上架。

官方依据（2026-09-28 核对）：[Apple SDK 最低要求](https://developer.apple.com/news/upcoming-requirements/?id=02032026a)、[Apple 上传构建指南](https://developer.apple.com/help/app-store-connect/manage-builds/upload-builds)、[GitHub macOS 26 runner](https://github.com/actions/runner-images/blob/main/images/macos/macos-26-arm64-Readme.md)。
