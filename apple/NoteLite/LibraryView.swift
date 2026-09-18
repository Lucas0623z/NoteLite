import SwiftUI
import UniformTypeIdentifiers
import QuickLook

struct LibraryView: View {
    @EnvironmentObject private var library: LibraryStore
    @Environment(\.scenePhase) private var scenePhase
    @State private var selection: UUID?
    @State private var importing = false
    @State private var showingSettings = false
    @State private var deleting: ScoreRecord?

    var body: some View {
        NavigationSplitView {
            List(selection: $selection) {
                if !library.isConfigured {
                    Section {
                        Button { showingSettings = true } label: {
                            Label("配置识谱服务器", systemImage: "network")
                        }
                        Text("可以先导入并预览乐谱。识谱需要连接你的 NoteLite 服务器。")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }
                Section("我的乐谱") {
                    ForEach(library.records) { record in
                        NavigationLink(value: record.id) {
                            HStack(spacing: 12) {
                                Image(systemName: record.sourceName.hasSuffix(".pdf") ? "doc.richtext" : "photo")
                                    .font(.title2)
                                    .foregroundStyle(.tint)
                                    .accessibilityHidden(true)
                                VStack(alignment: .leading, spacing: 5) {
                                    Text(record.filename).lineLimit(2)
                                    Text(record.paused ? "已暂停 · \(record.phase.title)" : record.phase.title)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            .padding(.vertical, 4)
                        }
                        .swipeActions {
                            Button("删除", role: .destructive) { deleting = record }
                        }
                        .contextMenu {
                            Button("删除本地乐谱", role: .destructive) { deleting = record }
                        }
                    }
                }
                if library.records.isEmpty {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("让纸上的音乐继续流动").font(.headline)
                        Text("导入 PDF 或乐谱图片，预览原稿，再识别并导出 MusicXML 和 MIDI。")
                            .foregroundStyle(.secondary)
                        Button("导入乐谱") { importing = true }
                            .buttonStyle(.borderedProminent)
                            .disabled(!library.canImport)
                    }
                    .padding(.vertical)
                }
            }
            .navigationTitle("NoteLite")
            .toolbar {
                ToolbarItemGroup(placement: .navigationBarTrailing) {
                    Button { showingSettings = true } label: {
                        Label("服务器设置", systemImage: "gearshape")
                    }
                    Button { importing = true } label: {
                        Label("导入乐谱", systemImage: "plus")
                    }
                    .keyboardShortcut("o")
                    .disabled(!library.canImport)
                }
            }
            .navigationSplitViewColumnWidth(min: 260, ideal: 320, max: 420)
        } detail: {
            if let selection, let record = library.record(selection) {
                ScoreDetailView(record: record)
            } else {
                VStack(spacing: 16) {
                    Image(systemName: "music.note.list")
                        .font(.system(size: 48))
                        .foregroundStyle(.tint)
                    Text("选择一份乐谱").font(.title2.bold())
                    Text("原稿与识谱结果都保存在这台设备上。")
                        .foregroundStyle(.secondary)
                    Button("导入乐谱") { importing = true }
                        .buttonStyle(.borderedProminent)
                        .disabled(!library.canImport)
                }
                .padding()
                .navigationTitle("乐谱")
            }
        }
        .fileImporter(isPresented: $importing,
                      allowedContentTypes: [.pdf, .png, .jpeg, .tiff],
                      allowsMultipleSelection: true) { result in
            switch result {
            case .success(let urls):
                Task {
                    if let importedID = await library.importFiles(urls) { selection = importedID }
                }
            case .failure(let error): library.errorMessage = error.localizedDescription
            }
        }
        .safeAreaInset(edge: .bottom) {
            if library.isImporting {
                HStack {
                    ProgressView()
                    Text("正在导入乐谱…")
                }
                .padding()
                .frame(maxWidth: .infinity)
                .background(.regularMaterial)
            }
        }
        .sheet(isPresented: $showingSettings) {
            ServerSettingsView(address: library.serverAddress)
        }
        .alert("无法完成操作", isPresented: Binding(
            get: { library.errorMessage != nil },
            set: { if !$0 { library.errorMessage = nil } }
        )) {
            Button("好", role: .cancel) { library.errorMessage = nil }
        } message: {
            Text(library.errorMessage ?? "")
        }
        .confirmationDialog("删除这份本地乐谱及下载结果？", isPresented: Binding(
            get: { deleting != nil }, set: { if !$0 { deleting = nil } }
        ), titleVisibility: .visible) {
            Button("删除本地文件", role: .destructive) {
                if let deleting {
                    if selection == deleting.id { selection = nil }
                    library.delete(deleting.id)
                }
                deleting = nil
            }
            Button("取消", role: .cancel) { deleting = nil }
        } message: {
            Text("已有服务器任务会先被清理；仍在运行或无法连接时保留本地记录，请稍后再试。")
        }
        .task { library.resumePending() }
        .onChange(of: scenePhase) { phase in
            if phase == .active { library.resumePending() }
            else if phase == .background { library.suspendForBackground() }
        }
    }
}

struct ScoreDetailView: View {
    @EnvironmentObject private var library: LibraryStore
    let record: ScoreRecord
    @State private var preview: PreviewFile?
    @State private var confirmingRestart = false
    @State private var confirmingCleanup = false

    private var active: Bool { library.activeIDs.contains(record.id) }

    var body: some View {
        List {
            Section("原始乐谱") {
                Label(record.filename, systemImage: "doc.richtext")
                    .font(.headline)
                    .textSelection(.enabled)
                Text(record.importedAt, style: .date).foregroundStyle(.secondary)
                if let url = library.sourceURL(record) {
                    Button { preview = PreviewFile(url: url) } label: {
                        Label("预览原稿", systemImage: "doc.text.magnifyingglass")
                    }
                    ShareLink(item: url) { Label("分享原稿", systemImage: "square.and.arrow.up") }
                }
            }

            Section("识谱") {
                HStack {
                    Text(record.paused ? "已暂停跟踪" : record.phase.title)
                    Spacer()
                    if active { ProgressView() }
                }
                if record.phase == .uploading {
                    ProgressView(value: library.uploadProgress[record.id] ?? 0)
                        .accessibilityLabel("上传进度")
                }
                if let error = record.lastError {
                    Text(error).foregroundStyle(.red).textSelection(.enabled)
                }
                if active {
                    Button(record.phase == .uploading ? "停止上传" : "暂停跟踪") {
                        library.pause(record.id)
                    }
                    Text("暂停跟踪不会取消服务器上的识谱。返回应用后可继续获取结果。")
                        .font(.footnote).foregroundStyle(.secondary)
                } else if record.phase != .ready {
                    Button {
                        library.start(record.id)
                    } label: {
                        Label(actionTitle, systemImage: "waveform.badge.magnifyingglass")
                    }
                    .disabled(!library.isConfigured && record.serverURL == nil)
                }
                if (record.job != nil || record.phase == .ready) && !active {
                    Button("重新提交识别") { confirmingRestart = true }
                        .disabled(!library.isConfigured)
                }
                if record.job != nil && !active {
                    Button("清理服务器任务", role: .destructive) { confirmingCleanup = true }
                }
                if let server = record.serverURL {
                    Text("任务服务器：\(server)")
                        .font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                }
            }

            if !record.downloadedArtifacts.isEmpty {
                Section("导出结果") {
                    ForEach(record.downloadedArtifacts, id: \.self) { name in
                        if let url = library.artifactURL(name, record: record) {
                            ShareLink(item: url) {
                                Label(name, systemImage: "square.and.arrow.up")
                            }
                        }
                    }
                    Text("点选结果，通过系统分享菜单存入“文件”或发送到其他音乐应用。MIDI 用于校对试听。")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }

            Section {
                Text("开始识别会将原稿上传到你配置的服务器。此版本支持原稿预览及 MusicXML / MIDI 导出；精细校谱请使用桌面版。")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }
        .navigationTitle(record.filename)
        .navigationBarTitleDisplayMode(.inline)
        .sheet(item: $preview) { item in
            NavigationStack {
                QuickLookPreview(url: item.url)
                    .ignoresSafeArea(edges: .bottom)
                    .toolbar {
                        ToolbarItem(placement: .confirmationAction) {
                            Button("完成") { preview = nil }
                        }
                    }
            }
        }
        .confirmationDialog("重新上传原稿并创建新的识谱任务？",
                            isPresented: $confirmingRestart, titleVisibility: .visible) {
            Button("重新识别") { library.start(record.id, newJob: true) }
            Button("取消", role: .cancel) {}
        } message: {
            Text("先清理原服务器上的旧任务，再使用当前服务器设置重新上传。服务器仍在运行旧任务时需要等待。")
        }
        .confirmationDialog("清理服务器上的原稿、任务和结果？",
                            isPresented: $confirmingCleanup, titleVisibility: .visible) {
            Button("清理服务器任务", role: .destructive) { library.cleanServerJob(record.id) }
            Button("取消", role: .cancel) {}
        } message: {
            Text("已导入的原稿和已下载的结果继续保留在这台设备。")
        }
    }

    private var actionTitle: String {
        if record.job?.state == .failed { return "重新识别" }
        if record.job != nil { return record.phase == .failed ? "重试获取结果" : "继续获取结果" }
        return record.phase == .failed ? "重新上传识别" : "开始识别"
    }
}

private struct PreviewFile: Identifiable {
    var id: URL { url }
    let url: URL
}

private struct QuickLookPreview: UIViewControllerRepresentable {
    let url: URL

    func makeCoordinator() -> Coordinator { Coordinator(url: url) }

    func makeUIViewController(context: Context) -> QLPreviewController {
        let controller = QLPreviewController()
        controller.dataSource = context.coordinator
        return controller
    }

    func updateUIViewController(_ controller: QLPreviewController, context: Context) {
        context.coordinator.url = url
        controller.reloadData()
    }

    final class Coordinator: NSObject, QLPreviewControllerDataSource {
        var url: URL
        init(url: URL) { self.url = url }

        func numberOfPreviewItems(in controller: QLPreviewController) -> Int { 1 }

        func previewController(_ controller: QLPreviewController, previewItemAt index: Int) -> QLPreviewItem {
            url as NSURL
        }
    }
}
