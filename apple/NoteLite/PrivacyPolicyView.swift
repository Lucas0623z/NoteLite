import SwiftUI

enum AppSupport {
    static let issuesURL = URL(string: "https://github.com/Lucas0623z/NoteLite/issues")!
    static let emailURL = URL(string: "mailto:Lucas.z0623@outlook.com")!
}

struct PrivacyPolicyView: View {
    var body: some View {
        List {
            Section {
                Text("音伴-你的音乐搭子")
                    .font(.headline)
                Text("隐私政策 · 更新日期：2026 年 9 月 28 日")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                Text("本政策适用于音伴的 Apple 客户端。开发者不运营识谱服务器；识谱使用你自行配置的服务器。请在上传前了解该服务器运营者的隐私和保留政策。")
            }

            Section("保存在设备上的内容") {
                Text("导入的乐谱副本、下载结果、曲谱列表和任务信息保存在应用存储中。服务器地址保存在应用设置中；访问令牌按服务器分别保存在此设备的系统钥匙串中。")
                Text("练习记录包含曲谱名称、时间、时长和错音等结果，保存在本机，最多保留最近 500 次。应用不提供账户或自有云同步。系统备份及你选用的文件服务由相应服务提供方管理。")
            }

            Section("麦克风与 MIDI") {
                Text("选择麦克风输入时，应用会请求系统权限。声音在设备上实时分析音高，不保存录音，也不发送到识谱服务器。MIDI 音符也在本机处理。结束练习或应用进入后台时会停止输入。")
                Text("你可以在系统设置中撤销麦克风权限，也可以使用已连接的 MIDI 乐器练习。")
            }

            Section("识谱时发送的内容") {
                Text("点选“开始识别”或重新上传时，PDF 或图片原稿及文件名会通过 HTTPS 发给你配置的服务器。认证请求还会发送访问令牌；查询、下载和清理请求会发送任务标识。服务器可看到网络连接信息，例如 IP 地址。")
                Text("原稿可能包含姓名、批注或图片元数据，应用不会在上传前自动去除这些内容。仅导入文件不会启动识谱上传；MusicXML 可直接在本机练习。")
                Text("检查连接会访问所填服务器的健康检查接口，不发送原稿或访问令牌。已有任务在回到前台后可能继续查询和下载，仍使用原来的服务器。暂停跟踪不会取消服务器正在执行的识谱。")
            }

            Section("保留与删除") {
                Text("可在曲谱详情中清理服务器任务并保留已下载结果。删除本地曲谱时，已有服务器任务会先被清理；任务仍在运行、网络不可用或清理失败时，本地记录会保留并显示错误。")
                Text("本仓库的桥接服务默认保留原稿、结果、任务状态和引擎日志，直到清理完成，没有自动到期删除。其他服务器的保留时间、日志和备份由运营者决定；需要进一步删除时请联系该运营者。上传中断后，服务器可能仍保留已接收的文件。")
                Text("删除曲谱不会同时删除练习历史。当前版本没有单独清空历史或删除钥匙串令牌的按钮；需要停用令牌时，请让服务器运营者撤销或更换令牌。删除设备上的应用数据不会自动清理服务器、系统备份或已分享的副本。")
            }

            Section("分享与第三方服务") {
                Text("仅当你使用系统分享功能时，所选文件会交给你选择的应用或服务。支持链接在外部浏览器或邮件应用打开，其数据处理遵循对应服务的政策。")
                Text("客户端没有广告、行为分析或跨应用追踪功能，不出售用户数据。自选识谱服务器由其运营者管理，客户端开发者不会因提供此应用而自动获得该服务器上的内容。")
            }

            Section("联系与政策更新") {
                Text("开发维护：Yuexuan Zhang（Lucas0623z）。如需询问隐私或报告问题，可通过以下方式联系。请勿在公开问题中提交访问令牌、私人乐谱或其他敏感信息。")
                Link("隐私联系：Lucas.z0623@outlook.com", destination: AppSupport.emailURL)
                Link("支持与问题反馈", destination: AppSupport.issuesURL)
                Text("数据处理方式改变时，我们会更新本政策及日期。")
                    .foregroundStyle(.secondary)
            }
        }
        .textSelection(.enabled)
        .navigationTitle("隐私政策")
        .noteLiteInlineTitle()
        .tint(NoteLiteTheme.accent)
    }
}
