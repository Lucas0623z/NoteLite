import SwiftUI
import UniformTypeIdentifiers

private enum LibrarySection: String, CaseIterable, Identifiable {
    case all = "全部曲谱", playable = "可以练习", pending = "待识别", history = "练习记录"
    var id: Self { self }
    var symbol: String {
        switch self {
        case .all: return "book"
        case .playable: return "play.circle"
        case .pending: return "doc.text.magnifyingglass"
        case .history: return "clock"
        }
    }
}

private enum LibrarySort: String, CaseIterable, Identifiable {
    case imported = "最近导入", practiced = "最近练习", title = "曲名"
    var id: Self { self }
}

struct LibraryView: View {
    @EnvironmentObject private var library: LibraryStore
    @EnvironmentObject private var history: PracticeHistoryStore
    @Environment(\.scenePhase) private var scenePhase
    #if os(iOS)
    @Environment(\.horizontalSizeClass) private var sizeClass
    #endif
    @State private var selection: UUID?
    @State private var section: LibrarySection? = .all
    @State private var sort: LibrarySort = .imported
    @State private var search = ""
    @State private var importing = false
    @State private var showingSettings = false
    @State private var deleting: ScoreRecord?
    @State private var phonePath: [UUID] = []

    private var compact: Bool {
        #if os(iOS)
        return sizeClass == .compact
        #else
        return false
        #endif
    }

    private var records: [ScoreRecord] {
        library.records.filter { record in
            let matchesSearch = search.isEmpty || record.filename.localizedStandardContains(search)
            let matchesSection: Bool
            switch section ?? .all {
            case .all: matchesSection = true
            case .playable: matchesSection = library.practiceURL(record) != nil
            case .pending: matchesSection = library.practiceURL(record) == nil
            case .history: matchesSection = history.latest(for: record.id) != nil
            }
            return matchesSearch && matchesSection
        }.sorted { first, second in
            switch sort {
            case .imported: return first.importedAt > second.importedAt
            case .practiced:
                return (history.latest(for: first.id)?.date ?? .distantPast) >
                    (history.latest(for: second.id)?.date ?? .distantPast)
            case .title: return first.filename.localizedStandardCompare(second.filename) == .orderedAscending
            }
        }
    }

    var body: some View {
        Group {
            if compact { phoneLibrary } else { splitLibrary }
        }
        .tint(NoteLiteTheme.accent)
        .fileImporter(isPresented: $importing,
                      allowedContentTypes: [.pdf, .png, .jpeg, .tiff, .xml,
                                            UTType(filenameExtension: "musicxml") ?? UTType(importedAs: "com.recordare.musicxml"),
                                            UTType(filenameExtension: "mxl") ?? UTType(importedAs: "com.recordare.musicxml.compressed")],
                      allowsMultipleSelection: true) { result in
            switch result {
            case .success(let urls):
                Task {
                    if let id = await library.importFiles(urls) {
                        section = .all
                        search = ""
                        selection = id
                        if compact { phonePath = [id] }
                    }
                }
            case .failure(let error): library.errorMessage = error.localizedDescription
            }
        }
        .safeAreaInset(edge: .bottom) {
            if library.isImporting {
                HStack(spacing: 10) {
                    ProgressView().controlSize(.small)
                    Text("正在导入曲谱…").font(.subheadline)
                }
                .padding(12).frame(maxWidth: .infinity).background(.regularMaterial)
            }
        }
        .sheet(isPresented: $showingSettings) {
            ServerSettingsView(address: library.serverAddress)
                #if os(macOS)
                .noteLiteSheetSize(idealWidth: 560, idealHeight: 590)
                #endif
        }
        .alert("无法完成操作", isPresented: Binding(
            get: { library.errorMessage != nil },
            set: { if !$0 { library.errorMessage = nil } }
        )) {
            Button("好", role: .cancel) { library.errorMessage = nil }
        } message: { Text(library.errorMessage ?? "") }
        .confirmationDialog("删除这份本地曲谱及下载结果？", isPresented: Binding(
            get: { deleting != nil }, set: { if !$0 { deleting = nil } }
        ), titleVisibility: .visible) {
            Button("删除本地文件", role: .destructive) {
                if let deleting { library.delete(deleting.id) }
                deleting = nil
            }
            Button("取消", role: .cancel) { deleting = nil }
        } message: {
            Text("已有服务器任务会先被清理；仍在运行或无法连接时保留本地记录，请稍后再试。")
        }
        .task { library.resumePending() }
        .onChange(of: library.records.map(\.id)) { ids in
            if let selection, !ids.contains(selection) { self.selection = nil }
            phonePath.removeAll { !ids.contains($0) }
        }
        .onChange(of: section) { value in
            // A fresh selection in the history-filtered list should open that score.
            if value == .history { selection = nil }
        }
        .onChange(of: scenePhase) { phase in
            if phase == .active { library.resumePending() }
            else if phase == .background { library.suspendForBackground() }
        }
    }

    private var phoneLibrary: some View {
        TabView {
            NavigationStack(path: $phonePath) {
                scoreList.navigationDestination(for: UUID.self) { id in
                    if let record = library.record(id) { ScoreDetailView(record: record) }
                }
            }
            .tabItem { Label("曲谱", systemImage: "book") }
            NavigationStack { PracticeHistoryView() }
                .tabItem { Label("练习记录", systemImage: "clock") }
        }
    }

    private var splitLibrary: some View {
        NavigationSplitView {
            List(selection: $section) {
                Section("资料库") {
                    ForEach(LibrarySection.allCases) { item in
                        Label(item.rawValue, systemImage: item.symbol).padding(.vertical, 6).tag(item)
                    }
                }
            }
            .listStyle(.sidebar)
            .scrollContentBackground(.hidden)
            .background(NoteLiteTheme.sidebar)
            .navigationTitle("NoteLite")
            .navigationSplitViewColumnWidth(min: 180, ideal: 212, max: 250)
            .safeAreaInset(edge: .bottom) {
                VStack(alignment: .leading, spacing: 16) {
                    Text("\(library.records.count) 份曲谱 · 保存在此设备")
                        .font(.caption).foregroundStyle(NoteLiteTheme.secondary)
                    Button { showingSettings = true } label: { Label("设置", systemImage: "gearshape") }
                        .buttonStyle(.plain).frame(minHeight: 32)
                }
                .frame(maxWidth: .infinity, alignment: .leading).padding(20)
            }
        } content: {
            scoreList.navigationSplitViewColumnWidth(min: 280, ideal: 380, max: 500)
        } detail: {
            if section == .history { PracticeHistoryView() }
            else if let selection, let record = library.record(selection) { ScoreDetailView(record: record) }
            else { emptyDetail }
        }
        .navigationSplitViewStyle(.balanced)
    }

    private var scoreList: some View {
        VStack(spacing: 0) {
            if compact {
                Picker("曲谱筛选", selection: $section) {
                    ForEach([LibrarySection.all, .playable, .pending]) { item in
                        Text(item.rawValue).tag(Optional(item))
                    }
                }
                .pickerStyle(.segmented).padding(.horizontal, 20).padding(.vertical, 12)
            }
            if records.isEmpty { emptyList }
            else {
                List(selection: $selection) {
                    ForEach(records) { record in
                        NavigationLink(value: record.id) { ScoreLibraryRow(record: record) }
                            .accessibilityIdentifier("score-row")
                            .listRowInsets(EdgeInsets(top: 12, leading: 20, bottom: 12, trailing: 20))
                            .listRowBackground(NoteLiteTheme.surface)
                            .swipeActions {
                                Button("删除", role: .destructive) { deleting = record }
                            }
                            .contextMenu {
                                if let url = library.sourceURL(record) {
                                    ShareLink(item: url) { Label("分享原稿", systemImage: "square.and.arrow.up") }
                                }
                                Button("删除本地曲谱", role: .destructive) { deleting = record }
                            }
                    }
                }
                .listStyle(.plain).scrollContentBackground(.hidden)
            }
            if !library.records.isEmpty {
                Text("\(records.count) 份曲谱 · 保存在此设备")
                    .font(.caption).foregroundStyle(NoteLiteTheme.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading).padding(20)
            }
        }
        .background(NoteLiteTheme.surface)
        .navigationTitle("曲谱")
        .searchable(text: $search, prompt: "搜索曲谱")
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                Menu {
                    Picker("排列方式", selection: $sort) {
                        ForEach(LibrarySort.allCases) { item in Text(item.rawValue).tag(item) }
                    }
                    if compact {
                        Divider()
                        Button("服务器设置") { showingSettings = true }
                    }
                } label: { Label("排列与设置", systemImage: "line.3.horizontal.decrease") }
                Button { importing = true } label: { Label("导入乐谱", systemImage: "plus") }
                    .keyboardShortcut("o").disabled(!library.canImport)
            }
        }
        .onChange(of: selection) { value in
            if value != nil, section == .history { section = .all }
        }
    }

    private var emptyList: some View {
        VStack(spacing: 16) {
            Spacer()
            Image(systemName: library.records.isEmpty ? "book" : "magnifyingglass")
                .font(.system(size: 36, weight: .light)).foregroundStyle(NoteLiteTheme.secondary)
            Text(library.records.isEmpty ? "导入第一份曲谱" : "没有找到曲谱")
                .font(.title3.weight(.medium))
            Text(library.records.isEmpty ? "支持 PDF、乐谱图片和 MusicXML。" : "试试其他关键词或筛选条件。")
                .font(.subheadline).foregroundStyle(NoteLiteTheme.secondary).multilineTextAlignment(.center)
            if library.records.isEmpty {
                Button("导入乐谱") { importing = true }
                    .buttonStyle(.borderedProminent).controlSize(.large).disabled(!library.canImport)
            } else {
                Button("显示全部曲谱") { search = ""; section = .all }
            }
            Spacer()
        }
        .padding(24).frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var emptyDetail: some View {
        VStack(spacing: 14) {
            Image(systemName: "doc.text.magnifyingglass")
                .font(.system(size: 38, weight: .light)).foregroundStyle(NoteLiteTheme.secondary)
            Text("选择一份曲谱").font(.title2.weight(.medium))
            Text("预览原稿，或开始一次练习。").foregroundStyle(NoteLiteTheme.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity).background(NoteLiteTheme.window)
    }
}

private struct ScoreLibraryRow: View {
    @EnvironmentObject private var library: LibraryStore
    @EnvironmentObject private var history: PracticeHistoryStore
    let record: ScoreRecord
    var body: some View {
        HStack(spacing: 16) {
            ScoreThumbnail(url: library.sourceURL(record))
            VStack(alignment: .leading, spacing: 6) {
                Text(record.displayTitle).font(.body.weight(.medium))
                    .foregroundStyle(NoteLiteTheme.ink).lineLimit(2)
                Text(record.fileTypeLabel + " · " + status)
                    .font(.caption).lineLimit(1)
                    .foregroundStyle(record.lastError == nil ? NoteLiteTheme.secondary : NoteLiteTheme.wrong)
                if let practice = history.latest(for: record.id) {
                    Text("练习于 \(practice.date.formatted(date: .abbreviated, time: .shortened))")
                        .font(.caption).foregroundStyle(NoteLiteTheme.secondary).lineLimit(1)
                } else {
                    Text("导入于 \(record.importedAt.formatted(date: .abbreviated, time: .omitted))")
                        .font(.caption).foregroundStyle(NoteLiteTheme.secondary)
                }
            }
            if library.activeIDs.contains(record.id) { ProgressView().controlSize(.small) }
        }
        .padding(.vertical, 2).frame(minHeight: 68)
    }
    private var status: String {
        if library.practiceURL(record) != nil { return "可以练习" }
        return record.paused ? "已暂停 · \(record.phase.title)" : record.phase.title
    }
}

struct ScoreDetailView: View {
    @EnvironmentObject private var library: LibraryStore
    @EnvironmentObject private var history: PracticeHistoryStore
    let record: ScoreRecord
    @State private var practicing = false
    @State private var showingOriginal = false
    @State private var showingSettings = false
    @State private var confirmingRestart = false
    @State private var confirmingCleanup = false
    private var active: Bool { library.activeIDs.contains(record.id) }
    private var canPractice: Bool { library.practiceURL(record) != nil }

    var body: some View {
        GeometryReader { geometry in
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    if let url = library.sourceURL(record) {
                        ScoreSourcePreview(url: url)
                            .frame(height: max(280, min(geometry.size.height * 0.55, 560)))
                            .overlay(Rectangle().stroke(NoteLiteTheme.line, lineWidth: 0.5))
                    }
                    practiceSummary
                    if !record.isMusicXML {
                        Divider()
                        recognitionControls
                    }
                    if !record.downloadedArtifacts.isEmpty {
                        Divider()
                        artifactLinks
                    }
                    HStack {
                        Text("导入于 \(record.importedAt.formatted(date: .abbreviated, time: .shortened))")
                            .font(.caption).foregroundStyle(NoteLiteTheme.secondary)
                        Spacer()
                        if let url = library.sourceURL(record) {
                            ShareLink(item: url) { Label("分享原稿", systemImage: "square.and.arrow.up") }.font(.caption)
                        }
                    }
                }
                .padding(24).frame(maxWidth: 900).frame(maxWidth: .infinity)
            }
            .background(NoteLiteTheme.window)
        }
        .navigationTitle(record.displayTitle).noteLiteInlineTitle()
        .toolbar {
            if library.sourceURL(record) != nil {
                Button { showingOriginal = true } label: {
                    Label("放大原稿", systemImage: "arrow.up.left.and.arrow.down.right")
                }
            }
        }
        #if os(iOS)
        .fullScreenCover(isPresented: $practicing) { PracticeView(record: record) }
        #else
        .sheet(isPresented: $practicing) {
            PracticeView(record: record).noteLiteSheetSize(idealWidth: 1440, idealHeight: 900)
        }
        #endif
        .sheet(isPresented: $showingOriginal) {
            NavigationStack {
                if let url = library.sourceURL(record) {
                    ScoreSourcePreview(url: url)
                        .navigationTitle(record.displayTitle).noteLiteInlineTitle()
                        .toolbar {
                            ToolbarItem(placement: .confirmationAction) { Button("完成") { showingOriginal = false } }
                        }
                }
            }
            #if os(macOS)
            .noteLiteSheetSize(idealWidth: 900, idealHeight: 900)
            #endif
        }
        .sheet(isPresented: $showingSettings) {
            ServerSettingsView(address: library.serverAddress)
                #if os(macOS)
                .noteLiteSheetSize(idealWidth: 560, idealHeight: 590)
                #endif
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
        } message: { Text("已导入的原稿和已下载的结果继续保留在这台设备。") }
    }

    private var practiceSummary: some View {
        VStack(alignment: .leading, spacing: 14) {
            if let latest = history.latest(for: record.id) {
                Text("最近练习 · \(latest.date.formatted(date: .abbreviated, time: .shortened))").font(.headline)
                Text("\(latest.errorCount) 处需要留意").font(.subheadline).foregroundStyle(NoteLiteTheme.secondary)
            } else {
                Text(canPractice ? "曲谱已就绪" : "原稿已保存在此设备").font(.headline)
            }
            if canPractice {
                Button { practicing = true } label: {
                    Label(history.latest(for: record.id) == nil ? "开始练习" : "继续练习", systemImage: "play")
                        .frame(minHeight: 24)
                }
                .buttonStyle(.borderedProminent).controlSize(.large)
                .accessibilityIdentifier("practice-start")
                Text("乐器根据谱面信息判断，可在练习前更改。")
                    .font(.caption).foregroundStyle(NoteLiteTheme.secondary)
            } else {
                Text("识别为 MusicXML 后，即可看谱练习；也可以直接导入 MusicXML。")
                    .font(.subheadline).foregroundStyle(NoteLiteTheme.secondary)
            }
        }
    }

    private var recognitionControls: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("识谱与转换").font(.headline)
                Spacer()
                if active { ProgressView().controlSize(.small) }
                Text(record.paused ? "已暂停跟踪" : record.phase.title)
                    .font(.caption).foregroundStyle(NoteLiteTheme.secondary)
            }
            if record.phase == .uploading {
                ProgressView(value: library.uploadProgress[record.id] ?? 0).accessibilityLabel("上传进度")
            }
            if let error = record.lastError {
                Text(error).font(.subheadline).foregroundStyle(NoteLiteTheme.wrong).textSelection(.enabled)
            }
            if active {
                Button(record.phase == .uploading ? "停止上传" : "暂停跟踪") { library.pause(record.id) }
                Text("暂停跟踪不会取消服务器识谱，之后可以继续获取结果。")
                    .font(.caption).foregroundStyle(NoteLiteTheme.secondary)
            } else if record.phase != .ready {
                VStack(alignment: .leading, spacing: 12) {
                    Button(actionTitle) { library.start(record.id) }
                        .buttonStyle(.bordered).disabled(!library.isConfigured && record.serverURL == nil)
                    if !library.isConfigured { Button("连接识谱服务器") { showingSettings = true } }
                }
            }
            if (record.job != nil || record.phase == .ready) && !active {
                Menu("更多识谱操作") {
                    Button("重新提交识别") { confirmingRestart = true }.disabled(!library.isConfigured)
                    if record.job != nil {
                        Button("清理服务器任务", role: .destructive) { confirmingCleanup = true }
                    }
                }
            }
            if !canPractice {
                Text("点选开始识别时，原稿将上传到你配置的 NoteLite 服务器。")
                    .font(.caption).foregroundStyle(NoteLiteTheme.secondary)
            }
            if let server = record.serverURL {
                Text("任务服务器：\(server)").font(.caption)
                    .foregroundStyle(NoteLiteTheme.secondary).textSelection(.enabled)
            }
        }
    }

    private var artifactLinks: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("导出结果").font(.headline)
            ForEach(record.downloadedArtifacts, id: \.self) { name in
                if let url = library.artifactURL(name, record: record) {
                    ShareLink(item: url) { Label(name, systemImage: "square.and.arrow.up").lineLimit(2) }
                }
            }
            Text("通过系统分享菜单保存，或发送到其他音乐应用。")
                .font(.caption).foregroundStyle(NoteLiteTheme.secondary)
        }
    }

    private var actionTitle: String {
        if record.job?.state == .failed { return "重新识别" }
        if record.job != nil { return record.phase == .failed ? "重试获取结果" : "继续获取结果" }
        return record.phase == .failed ? "重新上传识别" : "开始识别"
    }
}

extension ScoreRecord {
    var displayTitle: String { URL(fileURLWithPath: filename).deletingPathExtension().lastPathComponent }
    var fileTypeLabel: String { URL(fileURLWithPath: sourceName).pathExtension.uppercased() }
}
