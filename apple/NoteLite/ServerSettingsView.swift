import SwiftUI

struct ServerSettingsView: View {
    @EnvironmentObject private var library: LibraryStore
    @Environment(\.dismiss) private var dismiss
    @State private var address: String
    @State private var token = ""
    @State private var status: String?
    @State private var isChecking = false
    @State private var checkTask: Task<Void, Never>?

    init(address: String) { _address = State(initialValue: address) }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("https://scores.example.com", text: $address)
                        #if os(iOS)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        #endif
                        .autocorrectionDisabled()
                        .accessibilityLabel("HTTPS 服务器地址")
                    SecureField("访问令牌", text: $token)
                        #if os(iOS)
                        .textInputAutocapitalization(.never)
                        #endif
                        .autocorrectionDisabled()
                } header: {
                    Text(library.hasLocalEngine ? "服务器设置（兼容已有任务）" : "识谱服务器")
                } footer: {
                    if library.hasLocalEngine {
                        Text("新导入的 PDF 和图片在设备上识别，无需填写这里。服务器设置用于已有远端任务的兼容处理。")
                    }
                    Text("使用有效证书的 HTTPS 地址。访问令牌保存在这台设备的钥匙串中，并按服务器分别保存。")
                }

                Section {
                    Button {
                        checkTask?.cancel()
                        checkTask = Task { await checkConnection() }
                    } label: {
                        HStack {
                            Text("检查服务器连接")
                            Spacer()
                            if isChecking { ProgressView() }
                        }
                    }
                    .disabled(isChecking)
                    if let status { Text(status).font(.footnote).textSelection(.enabled) }
                } footer: {
                    Text("连接检查只验证服务可达；访问令牌会在实际服务器任务请求时验证。")
                }

                Section("识谱与本地曲谱") {
                    if library.hasLocalEngine {
                        Text("新导入的 PDF 和图片使用设备内的 Audiveris 引擎识别，原稿和结果保存在本机。填写服务器地址不会改变新任务的处理方式；本机识谱失败也不会自动上传。MusicXML 可直接导入练习。")
                        Text("识谱时请保持应用在前台。离开应用后会请求停止识谱，返回后可重新开始。")
                    } else {
                        Text("原稿和识谱结果保存在此设备。PDF 和图片通过你配置的服务器识谱；原稿只有在你点选“开始识别”时才上传。MusicXML 可直接导入练习。")
                    }
                    Text("已有服务器任务仍使用原服务器和令牌查询、下载及清理。进入后台时停止网络跟踪，回到前台后恢复未暂停的任务。未完成的上传需要手动重试。")
                    Text("更换服务器不迁移已有任务。重新识别已有远端任务时，会先清理旧任务，再按当前服务器设置重新上传原稿。")
                }

                Section("隐私与支持") {
                    NavigationLink {
                        PrivacyPolicyView()
                    } label: {
                        Label("隐私政策", systemImage: "hand.raised")
                    }
                    Link(destination: AppSupport.issuesURL) {
                        Label("支持与问题反馈", systemImage: "questionmark.circle")
                    }
                    Link("联系开发者", destination: AppSupport.emailURL)
                }
            }
            .navigationTitle("服务器设置")
            .noteLiteInlineTitle()
            .formStyle(.grouped)
            .tint(NoteLiteTheme.accent)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存") {
                        do {
                            try library.saveConfiguration(address: address, token: token)
                            library.resumePending()
                            dismiss()
                        } catch { status = error.localizedDescription }
                    }
                    .disabled(address.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || token.isEmpty)
                }
            }
            .task { token = library.storedToken() }
            .onChange(of: address) { value in
                checkTask?.cancel()
                status = nil
                // Do not accidentally carry one server's secret over when changing the origin.
                if let configuration = try? ServerConfiguration(value) {
                    token = (try? TokenStore.read(for: configuration)) ?? ""
                } else {
                    token = ""
                }
            }
            .onDisappear { checkTask?.cancel() }
        }
    }

    @MainActor
    private func checkConnection() async {
        isChecking = true
        status = nil
        defer { isChecking = false }
        do {
            let configuration = try ServerConfiguration(address)
            let api = NoteLiteAPI(configuration: configuration, token: "")
            try await api.checkHealth()
            try Task.checkCancellation()
            status = "服务器连接正常。"
        } catch {
            if !Task.isCancelled { status = error.localizedDescription }
        }
    }
}
