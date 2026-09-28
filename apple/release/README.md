# 音伴 App Store 构建与上传

商店名称：**音伴-你的音乐搭子**。默认 Bundle ID：`com.lucas0623z.yinban`。工程名和 scheme 保留 `NoteLite`，不影响商店展示名称。

## 工作流

在 GitHub → Actions → **iOS App Store release** → Run workflow 运行。工作流文件需要先进入默认分支，手动运行入口才会出现；相关拉取请求会自动执行无签名校验。

| 设置 | 用途 |
| --- | --- |
| `mode: verify`（默认） | 构建真正的 iOS 设备 archive，检查版本、Bundle ID 和 SDK；无需 Apple 密钥。产物未签名，不能安装或上传。 |
| `mode: export` | 使用下面的签名密钥生成 App Store IPA 和 archive。 |
| `upload: false`（默认） | 只导出产物。 |
| `upload: true` | 必须选择 `export`；先调用 Apple 验证，再上传 App Store Connect。上传后仍需等待处理和 App Review。 |
| `bundle_id` / `team_id` | 必须与 Apple Developer 注册的 App ID、描述文件及 App Store Connect 记录一致。导出时必填 Team ID。 |
| `version` / `build_number` | 默认版本 `1.0.0`；空构建号使用工作流 run number。已上传的版本/构建号组合不能重复；重跑旧任务时请改用新的构建号。 |

工作流使用 GitHub 的 `macos-26` runner，选择已安装的最高稳定 Xcode，并在构建前后验证 Xcode 26 / iOS SDK 26 最低要求。产物在 Actions 中保留 7 天，正式版本请下载保存。`verify` 包含网页练习模块测试及无签名设备构建；真机交互、麦克风、MIDI 和服务器识谱仍须验收，已有 Apple clients 工作流继续负责模拟器测试。

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
