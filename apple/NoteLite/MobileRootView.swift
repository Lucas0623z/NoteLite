#if os(iOS)
import SwiftUI
import WebKit
import PhotosUI
import UniformTypeIdentifiers
import Combine
import AVFoundation

/// The designer's bundled interface shares native storage and the existing on-device practice engine.
struct MobileRootView: View {
    @EnvironmentObject private var library: LibraryStore
    @EnvironmentObject private var history: PracticeHistoryStore
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var controller = MobileWebController()
    @State private var importing = false
    @State private var photosOpen = false
    @State private var photoItems: [PhotosPickerItem] = []
    @State private var cameraOpen = false
    @State private var imageImporting = false
    @State private var settingsOpen = false
    @State private var privacyOpen = false
    @State private var sourcePreview: ScoreRecord?
    @State private var partSelection: ScoreRecord?
    @State private var practicing: PracticeSelection?
    @State private var reviewed: PracticeHistoryRecord?
    @State private var shareURL: MobileShareURL?
    @State private var renamedTitles = UserDefaults.standard.dictionary(forKey: "Yinban.scoreTitles") as? [String: String] ?? [:]

    var body: some View {
        Group {
            if let error = controller.errorMessage {
                VStack(spacing: 16) {
                    Text("无法打开界面").font(.title2.bold())
                    Text(error).multilineTextAlignment(.center).foregroundStyle(.secondary)
                    Button("重试") { controller.open() }.buttonStyle(.borderedProminent)
                }.padding(24).frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                MobileWebSurface(controller: controller).ignoresSafeArea()
            }
        }
        .preferredColorScheme(controller.isDark.map { $0 ? .dark : .light })
        .fileImporter(isPresented: $importing, allowedContentTypes: [.pdf, .png, .jpeg, .tiff, .xml,
            UTType(filenameExtension: "musicxml") ?? .xml,
            UTType(filenameExtension: "mxl") ?? .zip], allowsMultipleSelection: true) { result in
                switch result {
                case .success(let urls): Task { await library.importFiles(urls); synchronize() }
                case .failure(let error): library.errorMessage = error.localizedDescription
                }
        }
        .photosPicker(isPresented: $photosOpen, selection: $photoItems, maxSelectionCount: 8, matching: .images)
        .onChange(of: photoItems) { items in
            guard !items.isEmpty, !imageImporting else { return }
            imageImporting = true
            synchronize()
            Task {
                for item in items {
                    do {
                        guard let data = try await item.loadTransferable(type: Data.self), let image = UIImage(data: data) else {
                            throw NoteLiteError.invalidFile
                        }
                        await importImage(image)
                    } catch { library.errorMessage = "无法导入照片：\(error.localizedDescription)" }
                }
                photoItems = []
                imageImporting = false
                synchronize()
            }
        }
        .sheet(isPresented: $cameraOpen) {
            MobileCamera { image in
                cameraOpen = false
                if let image {
                    imageImporting = true
                    synchronize()
                    Task { await importImage(image); imageImporting = false; synchronize() }
                }
            }.ignoresSafeArea()
        }
        .sheet(isPresented: $settingsOpen, onDismiss: synchronize) { ServerSettingsView(address: library.serverAddress) }
        .sheet(isPresented: $privacyOpen) {
            NavigationStack {
                PrivacyPolicyView().toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { privacyOpen = false } } }
            }
        }
        .sheet(item: $sourcePreview) { record in
            NavigationStack {
                if let url = library.sourceURL(record) {
                    ScoreSourcePreview(url: url).navigationTitle(title(for: record)).noteLiteInlineTitle()
                        .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { sourcePreview = nil } } }
                }
            }
        }
        .sheet(item: $partSelection) { record in
            NavigationStack {
                List(library.practiceParts(record)) { part in
                    Button(part.title ?? "完整曲谱") {
                        partSelection = nil
                        // Wait for the part sheet to dismiss before presenting the practice cover.
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) {
                            practicing = PracticeSelection(score: record, part: part)
                        }
                    }.accessibilityIdentifier("mobile-practice-part")
                }
                .navigationTitle("选择练习部分").noteLiteInlineTitle()
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("取消") { partSelection = nil } } }
            }
        }
        .fullScreenCover(item: $practicing, onDismiss: synchronize) { selection in
            PracticeView(record: selection.score, part: selection.part, onDismiss: { practicing = nil })
        }
        .sheet(item: $reviewed) { record in
            NavigationStack {
                MobileHistoryReview(record: record) { beginPractice(record.scoreID, artifactName: record.artifactName) }
                    .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { reviewed = nil } } }
            }
        }
        .sheet(item: $shareURL) { value in MobileShareSheet(items: [value.url]) }
        .alert("无法完成操作", isPresented: Binding(get: { library.errorMessage != nil || history.errorMessage != nil },
            set: { if !$0 { library.errorMessage = nil; history.errorMessage = nil } })) {
                Button("好", role: .cancel) { library.errorMessage = nil; history.errorMessage = nil }
            } message: { Text(library.errorMessage ?? history.errorMessage ?? "") }
        .onReceive(library.objectWillChange) { _ in scheduleSynchronization() }
        .onReceive(history.objectWillChange) { _ in scheduleSynchronization() }
        .onChange(of: scenePhase) { phase in
            if phase == .active { library.resumePending(); synchronize() }
            if phase == .background { library.suspendForBackground() }
        }
        .onAppear {
            controller.onAction = handle
            controller.onReady = synchronize
            controller.open()
            library.resumePending()
        }
    }

    private func title(for record: ScoreRecord) -> String { renamedTitles[record.id.uuidString] ?? record.filename }

    private func scheduleSynchronization() {
        DispatchQueue.main.async { synchronize() }
    }

    private func synchronize() {
        let records: [[String: Any]] = library.records.map { record in
            var result: [String: Any] = ["id": record.id.uuidString, "title": title(for: record),
                "kind": (record.sourceName as NSString).pathExtension.lowercased(), "phase": record.phase.rawValue,
                "paused": record.paused, "canPractice": library.practiceURL(record) != nil,
                "partCount": library.practiceParts(record).count, "hasRemoteJob": record.job != nil]
            if let progress = library.uploadProgress[record.id] { result["progress"] = progress }
            if let error = record.lastError { result["error"] = error }
            return result
        }
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        var historyValues: [[String: Any]] = []
        if let data = try? encoder.encode(history.records), let values = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] {
            historyValues = values.map { value in
                var entry = value
                entry["recordID"] = entry.removeValue(forKey: "scoreID")
                entry["startedAt"] = entry.removeValue(forKey: "date")
                return entry
            }
        }
        controller.send(["records": records, "history": historyValues, "serverConfigured": library.isConfigured,
            "activeIDs": library.activeIDs.map(\.uuidString), "canImport": library.canImport && !imageImporting])
    }

    private func handle(_ body: [String: Any]) {
        guard let action = body["action"] as? String else { return }
        let id = (body["id"] as? String).flatMap(UUID.init(uuidString:))
        if ["importFiles", "importPhotos", "capturePhoto", "demo"].contains(action),
           !library.canImport || imageImporting {
            library.errorMessage = "正在导入曲谱，请稍候。"
            return
        }
        if !["ready", "theme", "preferences"].contains(action),
           (UserDefaults.standard.dictionary(forKey: "Yinban.practicePreferences")?["hapticEnabled"] as? Bool) != false {
            UISelectionFeedbackGenerator().selectionChanged()
        }
        switch action {
        case "ready": synchronize()
        case "importFiles": importing = true
        case "importPhotos": photosOpen = true
        case "capturePhoto":
            if AVCaptureDevice.authorizationStatus(for: .video) == .denied || AVCaptureDevice.authorizationStatus(for: .video) == .restricted {
                library.errorMessage = "相机权限未开启，请在系统设置中允许音伴使用相机，或从相册导入。"
            } else if UIImagePickerController.isSourceTypeAvailable(.camera) { cameraOpen = true }
            else { library.errorMessage = "这台设备没有可用相机，请从相册或文件导入。" }
        case "recognize":
            if let id, library.isConfigured || library.record(id)?.job != nil {
                library.start(id, newJob: body["newJob"] as? Bool ?? false)
            } else { settingsOpen = true }
        case "pause": if let id { library.pause(id) }
        case "cleanup": if let id { library.cleanServerJob(id) }
        case "delete": if let id { library.delete(id) }
        case "preview": if let id { sourcePreview = library.record(id) }
        case "practice": if let id { beginPractice(id) }
        case "serverSettings": settingsOpen = true
        case "privacy": privacyOpen = true
        case "feedback": UIApplication.shared.open(AppSupport.emailURL)
        case "demo":
            Task {
                if let existing = library.records.first(where: { $0.filename == "demo.musicxml" }) { beginPractice(existing.id); return }
                if let url = Bundle.main.url(forResource: "demo", withExtension: "musicxml", subdirectory: "practice"),
                   let newID = await library.importFiles([url]) { synchronize(); beginPractice(newID) }
            }
        case "rename":
            guard let id, library.record(id) != nil, let value = body["title"] as? String else { return }
            let cleaned = value.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !cleaned.isEmpty, cleaned.count <= 100 else {
                library.errorMessage = "曲谱名称需要包含 1–100 个字符。"; return
            }
            renamedTitles[id.uuidString] = cleaned
            UserDefaults.standard.set(renamedTitles, forKey: "Yinban.scoreTitles")
            synchronize()
        case "historyDetail": if let id { reviewed = history.records.first { $0.id == id } }
        case "deleteHistory": if let id { history.delete(id: id) }
        case "clearHistory": history.clear()
        case "exportData": exportData()
        case "theme": controller.isDark = body["isDark"] as? Bool
        case "preferences":
            var preferences = UserDefaults.standard.dictionary(forKey: "Yinban.practicePreferences") ?? [:]
            if let instrument = body["instrument"] as? String,
               ["auto", "piano", "strings", "winds", "guitar", "other"].contains(instrument) {
                preferences["instrument"] = instrument
            }
            for key in ["soundEnabled", "hapticEnabled", "encouragementEnabled"] {
                if let value = body[key] as? Bool { preferences[key] = value }
            }
            UserDefaults.standard.set(preferences, forKey: "Yinban.practicePreferences")
        default: break
        }
    }

    private func beginPractice(_ id: UUID, artifactName: String? = nil) {
        guard var record = library.record(id) else {
            practiceError("原练习曲谱已删除，请重新导入后再练。")
            return
        }
        let parts = library.practiceParts(record)
        guard !parts.isEmpty else { practiceError("请先完成识谱，再开始练习。"); return }
        if let artifactName, !parts.contains(where: { $0.artifactName == artifactName }) {
            practiceError("这次记录对应的乐谱部分已删除或更新，请从我的曲谱选择现有部分练习。")
            return
        }
        // A display rename never changes the original source or result filenames.
        if let custom = renamedTitles[id.uuidString] {
            record = ScoreRecord(id: record.id, filename: custom, sourceName: record.sourceName,
                importedAt: record.importedAt, phase: record.phase, job: record.job, serverURL: record.serverURL,
                recognitionLocation: record.recognitionLocation, downloadedArtifacts: record.downloadedArtifacts,
                lastError: record.lastError, paused: record.paused)
        }
        if let artifactName, let part = parts.first(where: { $0.artifactName == artifactName }) {
            reviewed = nil
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { practicing = PracticeSelection(score: record, part: part) }
        } else if parts.count == 1 {
            if reviewed != nil {
                reviewed = nil
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { practicing = PracticeSelection(score: record, part: parts[0]) }
            } else { practicing = PracticeSelection(score: record, part: parts[0]) }
        } else if reviewed != nil {
            reviewed = nil
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { partSelection = record }
        } else { partSelection = record }
    }

    private func practiceError(_ message: String) {
        if reviewed != nil {
            reviewed = nil
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { library.errorMessage = message }
        } else { library.errorMessage = message }
    }

    private func importImage(_ image: UIImage) async {
        guard let data = image.jpegData(compressionQuality: 0.94) else { library.errorMessage = "无法读取图片。"; return }
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("乐谱-\(UUID().uuidString).jpg")
        do {
            try data.write(to: url, options: [.atomic, .completeFileProtection])
            defer { try? FileManager.default.removeItem(at: url) }
            await library.importFiles([url])
        } catch { library.errorMessage = error.localizedDescription }
    }

    private func exportData() {
        do {
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            encoder.dateEncodingStrategy = .iso8601
            let data = try encoder.encode(MobileExport(library: library.records, history: history.records, titles: renamedTitles))
            let url = FileManager.default.temporaryDirectory.appendingPathComponent("音伴-本机练习数据.json")
            try data.write(to: url, options: [.atomic, .completeFileProtection])
            shareURL = MobileShareURL(url: url)
        } catch { library.errorMessage = "无法导出数据：\(error.localizedDescription)" }
    }
}

private struct MobileExport: Encodable {
    let library: [ScoreRecord]
    let history: [PracticeHistoryRecord]
    let titles: [String: String]
}
private struct MobileShareURL: Identifiable { let id = UUID(); let url: URL }

@MainActor final class MobileWebController: NSObject, ObservableObject, WKNavigationDelegate, WKScriptMessageHandler {
    @Published var errorMessage: String?
    @Published var isDark: Bool?
    private(set) var webView: WKWebView!
    var onAction: (([String: Any]) -> Void)?
    var onReady: (() -> Void)?
    private var pageURL: URL?
    private var ready = false
    private var pending: [String: Any]?

    override init() {
        super.init()
        let configuration = WKWebViewConfiguration()
        configuration.userContentController.add(WeakMobileHandler(self), name: "yinban")
        configuration.allowsInlineMediaPlayback = true
        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.isOpaque = false
        webView.backgroundColor = .systemBackground
        webView.scrollView.backgroundColor = .systemBackground
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.scrollView.bounces = false
        webView.accessibilityIdentifier = "yinban-mobile-interface"
    }

    func open() {
        if pageURL != nil, errorMessage == nil { return }
        ready = false
        errorMessage = nil
        guard let url = Bundle.main.url(forResource: "index", withExtension: "html", subdirectory: "MobileUI") else {
            errorMessage = "界面资源缺失，请重新构建或安装应用。"; return
        }
        pageURL = url.standardizedFileURL
        webView.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent())
    }

    func send(_ state: [String: Any]) {
        pending = state
        guard ready else { return }
        webView.callAsyncJavaScript("window.dispatchEvent(new CustomEvent('yinban-state', {detail: state}))",
            arguments: ["state": state], in: nil, in: .page) { _ in }
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, message.frameInfo.request.url?.standardizedFileURL == pageURL,
              let body = message.body as? [String: Any], let action = body["action"] as? String else { return }
        if action == "ready" { ready = true; if let pending { send(pending) }; onReady?() }
        else { onAction?(body) }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard navigationAction.targetFrame?.isMainFrame != false else { decisionHandler(.cancel); return }
        decisionHandler(navigationAction.request.url?.standardizedFileURL == pageURL ? .allow : .cancel)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        errorMessage = error.localizedDescription
    }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        pageURL = nil; open()
    }
}

private final class WeakMobileHandler: NSObject, WKScriptMessageHandler {
    weak var owner: MobileWebController?
    init(_ owner: MobileWebController) { self.owner = owner }
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        owner?.userContentController(userContentController, didReceive: message)
    }
}

private struct MobileWebSurface: UIViewRepresentable {
    @ObservedObject var controller: MobileWebController
    func makeUIView(context: Context) -> WKWebView { controller.webView }
    func updateUIView(_ uiView: WKWebView, context: Context) {}
}

private struct MobileHistoryReview: View {
    let record: PracticeHistoryRecord
    let onPractice: () -> Void
    var body: some View {
        List {
            Section {
                Text(record.title).font(.headline)
                Text(record.date, style: .date)
                Text("\(Int(record.durationSeconds)) 秒 · \(record.measureCount) 小节")
                if !record.completed { Text("本次练习未完成，未演奏部分未评分。").foregroundStyle(.secondary) }
            }
            Section("需要再练的地方") {
                if record.errors.isEmpty { Text("本次未记录错音。").foregroundStyle(.secondary) }
                ForEach(Array(record.errors.enumerated()), id: \.offset) { _, issue in
                    VStack(alignment: .leading, spacing: 5) {
                        Text("第 \(issue.measure) 小节 · \(issue.label)").font(.headline)
                        Text(issue.detail).foregroundStyle(.secondary)
                    }
                }
            }
            Section { Button("再练一次", action: onPractice) }
        }.navigationTitle("练习回顾").noteLiteInlineTitle()
    }
}

private struct MobileCamera: UIViewControllerRepresentable {
    let completion: (UIImage?) -> Void
    func makeCoordinator() -> Coordinator { Coordinator(completion) }
    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = .camera
        picker.delegate = context.coordinator
        return picker
    }
    func updateUIViewController(_ controller: UIImagePickerController, context: Context) {}
    final class Coordinator: NSObject, UINavigationControllerDelegate, UIImagePickerControllerDelegate {
        let completion: (UIImage?) -> Void
        init(_ completion: @escaping (UIImage?) -> Void) { self.completion = completion }
        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) { completion(nil) }
        func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            completion(info[.originalImage] as? UIImage)
        }
    }
}
private struct MobileShareSheet: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController { UIActivityViewController(activityItems: items, applicationActivities: nil) }
    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}
#endif
