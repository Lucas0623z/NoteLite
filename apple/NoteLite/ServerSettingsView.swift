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
                    Text("NoteLite 识谱服务器")
                } footer: {
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
                    Text("连接检查只验证服务可达；访问令牌会在实际识谱请求时验证。")
                }

                Section("识谱与本地曲谱") {
                    Text("原稿和识谱结果保存在此设备。PDF 和图片通过 NoteLite 服务器识谱；原稿只有在你点选“开始识别”时才上传。MusicXML 可直接导入练习。")
                    Text("应用进入后台时停止网络跟踪，回到前台后自动恢复已有任务。未完成的上传需要手动重试。")
                    Text("更换服务器不迁移已有任务。已有任务仍使用原服务器的地址和令牌。")
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
