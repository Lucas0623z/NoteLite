import SwiftUI

enum AppSupport {
    static let issuesURL = URL(string: "https://github.com/Lucas0623z/NoteLite/issues")!
    static let emailURL = URL(string: "mailto:Lucas.z0623@outlook.com")!
}

struct PrivacyPolicyView: View {
    @EnvironmentObject private var library: LibraryStore

    var body: some View {
        List {
            Section {
                Text("音伴-你的音乐搭子")
                    .font(.headline)
                Text("隐私政策 · 更新日期：2026 年 9 月 28 日")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                Text(library.hasLocalEngine
                     ? "本版本在设备上识别新导入的 PDF 和图片，无需配置服务器。开发者不运营识谱服务器；以前创建的服务器任务仍保留相应的网络功能。"
                     : "本版本通过你自行配置的服务器识别 PDF 和图片，MusicXML 可直接在本机练习。开发者不运营识谱服务器；请在上传前了解所选运营者的隐私和保留政策。")
            }

            Section("保存在设备上的内容") {
                Text("导入的乐谱副本、生成或下载的结果、曲谱列表和任务信息保存在应用存储中。已填写的服务器地址保存在应用设置中；访问令牌按服务器分别保存在此设备的系统钥匙串中。")
                Text("练习记录包含曲谱名称、时间、时长和错音等结果，保存在本机，最多保留最近 500 次。应用不提供账户或自有云同步。系统备份及你选用的文件服务由相应服务提供方管理。")
            }

            if library.hasLocalEngine {
                Section("本机识谱") {
                    Text("识谱使用随应用附带的 Audiveris 引擎及资源，在此设备上处理原稿并生成 MusicXML 和 MIDI。新任务不会因填写了服务器地址而改为上传，也不会在本机识谱失败后自动上传。")
                    Text("引擎可能在应用存储中保存配置、临时文件、运行日志和错误信息，用于本机处理与排错，不会自动发送给开发者。完成的任务会尝试清理工作文件；中断、超时或异常时可能留下部分文件。")
                }
            }

            Section("麦克风与 MIDI") {
                Text("选择麦克风输入时，应用会请求系统权限。声音在设备上实时分析音高，不保存录音，也不发送到识谱服务器。MIDI 音符也在本机处理。结束练习或应用进入后台时会停止输入。")
                Text("你可以在系统设置中撤销麦克风权限，也可以使用已连接的 MIDI 乐器练习。")
            }

            Section(library.hasLocalEngine ? "旧服务器任务与连接检查" : "服务器识谱时发送的内容") {
                Text(library.hasLocalEngine
                     ? "已有服务器任务的查询、下载和清理会访问原服务器，并发送任务标识与访问令牌。重新识别已有远端任务时，会先清理旧任务，再按当前服务器设置重新上传原稿和文件名。服务器可看到 IP 地址等网络连接信息。"
                     : "点选“开始识别”或重新上传时，PDF 或图片原稿及文件名会通过 HTTPS 发给你配置的服务器。认证请求还会发送访问令牌；查询、下载和清理请求会发送任务标识。服务器可看到 IP 地址等网络连接信息。")
                Text("原稿可能包含姓名、批注或图片元数据，应用不会在上传前自动去除这些内容。仅导入文件不会启动识谱上传；MusicXML 可直接在本机练习。")
                Text("检查连接会访问所填服务器的健康检查接口，不发送原稿或访问令牌。已有任务在回到前台后可能继续查询和下载，仍使用原来的服务器。暂停跟踪不会取消服务器正在执行的识谱。")
            }

            Section("保留与删除") {
                Text("删除曲谱会移除该曲谱的本地副本和结果。如果曲谱关联已有服务器任务，会先请求清理服务器任务；任务仍在运行、网络不可用或清理失败时，本地记录会保留并显示错误。也可单独清理服务器任务并保留已下载结果。")
                if library.hasLocalEngine {
                    Text("删除曲谱不会同时清空独立保存的引擎配置、日志或异常遗留的工作文件。当前版本没有单独清空这些引擎数据的按钮。")
                }
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
