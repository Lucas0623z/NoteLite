import SwiftUI
import WebKit

/// SwiftUI owns navigation and storage; the bundled renderer/matcher is shared with desktop NoteLite.
struct PracticeView: View {
    @EnvironmentObject private var library: LibraryStore
    @EnvironmentObject private var history: PracticeHistoryStore
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    let record: ScoreRecord
    @StateObject private var controller = PracticeWebController()

    var body: some View {
        NavigationStack {
            Group {
                if let error = controller.errorMessage {
                    VStack(spacing: 16) {
                        Image(systemName: "exclamationmark.circle").font(.largeTitle).foregroundStyle(.secondary)
                        Text("无法打开练习").font(.title2.weight(.medium))
                        Text(error).foregroundStyle(.secondary).multilineTextAlignment(.center)
                        Button("重试") { prepare() }.buttonStyle(.borderedProminent)
                    }.frame(maxWidth: .infinity, maxHeight: .infinity).padding(24)
                } else {
                    PracticeWebSurface(controller: controller)
                }
            }
            .background(NoteLiteTheme.window)
            .navigationTitle(record.filename)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button { controller.close { dismiss() } } label: {
                        Label("曲谱", systemImage: "chevron.left")
                    }
                    .accessibilityIdentifier("practice-close")
                }
            }
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
        }
        .onAppear { prepare() }
        .onDisappear { controller.close() }
        .onChange(of: scenePhase) { phase in
            // Permission dialogs temporarily make the scene inactive; do not cancel the user's answer.
            if phase == .background { controller.suspend() }
        }
    }

    private func prepare() {
        controller.onReport = { report in history.save(report: report, for: record) }
        controller.onClose = { dismiss() }
        controller.open(score: record, url: library.practiceURL(record))
    }
}

@MainActor
final class PracticeWebController: NSObject, ObservableObject, WKScriptMessageHandler, WKNavigationDelegate {
    @Published var errorMessage: String?
    private(set) var webView: WKWebView!
    var onReport: (([String: Any]) -> Void)?
    var onClose: (() -> Void)?
    private let input = NativePracticeInput()
    private var source: (data: String, title: String, id: String)?
    private var inputTask: Task<Void, Never>?
    private var documentID: UUID?
    private var forwardingAudio = false
    private var pageURL: URL?
    private var isClosing = false
    private var closeFinished = false
    private var closeCompletions: [() -> Void] = []

    override init() {
        super.init()
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.userContentController.add(WeakPracticeMessageHandler(self), name: "noteLite")
        #if os(iOS)
        configuration.allowsInlineMediaPlayback = true
        configuration.mediaTypesRequiringUserActionForPlayback = []
        #endif
        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        #if os(iOS)
        webView.isOpaque = false
        webView.backgroundColor = .clear
        #endif
        input.onNotes = { [weak self] notes in
            self?.call("for (const note of notes) window.NoteLiteNative?.noteOn(note)", arguments: ["notes": notes])
        }
        input.onAudio = { [weak self] samples, sampleRate in
            guard let self, !self.forwardingAudio else { return }
            self.forwardingAudio = true
            self.webView.callAsyncJavaScript("window.NoteLiteNative?.audioFrame(samples, sampleRate)",
                arguments: ["samples": samples, "sampleRate": sampleRate], in: nil, in: .page) { [weak self] _ in
                    self?.forwardingAudio = false
                }
        }
        input.onError = { [weak self] error in
            self?.call("window.NoteLiteNative?.inputError(error)", arguments: ["error": error])
        }
    }

    func open(score: ScoreRecord, url: URL?) {
        guard documentID != score.id || errorMessage != nil else { return }
        inputTask?.cancel()
        input.stop()
        forwardingAudio = false
        isClosing = false
        closeFinished = false
        closeCompletions.removeAll()
        errorMessage = nil
        guard let url else { errorMessage = "此乐谱还没有可用的 MusicXML。请先完成识谱，或直接导入 MusicXML 文件。"; return }
        guard let page = Bundle.main.url(forResource: "index", withExtension: "html", subdirectory: "practice") else {
            errorMessage = "练习资源未打包，请重新构建 NoteLite。"; return
        }
        do {
            let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
            guard size > 0, size <= 15 * 1024 * 1024 else {
                throw NoteLiteError.server("陪练乐谱需要小于 15 MB，请拆分后导入。")
            }
            let data = try Data(contentsOf: url)
            source = (data.base64EncodedString(), score.filename, score.id.uuidString)
            documentID = score.id
            pageURL = page.standardizedFileURL
            webView.loadFileURL(page, allowingReadAccessTo: page.deletingLastPathComponent())
        } catch { errorMessage = error.localizedDescription }
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, let pageURL,
              message.frameInfo.request.url?.standardizedFileURL == pageURL,
              let body = message.body as? [String: Any], let type = body["type"] as? String else { return }
        switch type {
        case "ready":
            if let source {
                call("await window.NoteLiteNative.loadScore(data, title, id)",
                    arguments: ["data": source.data, "title": source.title, "id": source.id], reportErrors: true)
            }
        case "startInput":
            guard !isClosing else { return }
            guard let mode = body["input"] as? String, let requestID = body["requestId"] else { return }
            inputTask?.cancel()
            inputTask = Task { [weak self] in
                guard let self else { return }
                do {
                    try Task.checkCancellation()
                    try await input.start(mode)
                    try Task.checkCancellation()
                    call("window.NoteLiteNative.inputResult(requestId, null)", arguments: ["requestId": requestID])
                } catch {
                    if !Task.isCancelled {
                        call("window.NoteLiteNative.inputResult(requestId, error)",
                            arguments: ["requestId": requestID, "error": error.localizedDescription])
                    }
                }
            }
        case "stopInput": inputTask?.cancel(); input.stop()
        case "report":
            if let report = body["report"] as? [String: Any] { onReport?(report) }
        case "close": close { [weak self] in self?.onClose?() }
        default: break
        }
    }

    func suspend() {
        inputTask?.cancel()
        input.stop()
        call("window.NoteLiteNative?.suspend?.()")
    }

    func close(completion: (() -> Void)? = nil) {
        inputTask?.cancel()
        input.stop()
        if closeFinished { completion?(); return }
        if let completion { closeCompletions.append(completion) }
        guard !isClosing else { return }
        isClosing = true
        // Keep the controller alive until JavaScript posts its final report, then dismiss.
        webView.callAsyncJavaScript("window.NoteLiteNative?.finish?.()", arguments: [:], in: nil, in: .page) { [self] _ in
            closeFinished = true
            forwardingAudio = false
            let callbacks = closeCompletions
            closeCompletions.removeAll()
            callbacks.forEach { $0() }
        }
    }

    private func call(_ code: String, arguments: [String: Any] = [:], reportErrors: Bool = false) {
        webView.callAsyncJavaScript(code, arguments: arguments, in: nil, in: .page) { [weak self] result in
            if reportErrors, case .failure(let error) = result { self?.errorMessage = error.localizedDescription }
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        // Never grant the native input bridge to a remote page or an arbitrary imported document.
        let allowed = pageURL != nil && navigationAction.request.url?.standardizedFileURL == pageURL
        decisionHandler(allowed ? .allow : .cancel)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        navigationFailed(error)
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        navigationFailed(error)
    }

    private func navigationFailed(_ error: Error) {
        guard (error as NSError).code != NSURLErrorCancelled else { return }
        inputTask?.cancel()
        input.stop()
        forwardingAudio = false
        errorMessage = error.localizedDescription
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        inputTask?.cancel()
        input.stop()
        forwardingAudio = false
        errorMessage = "练习页面已停止，请重新打开；此前保存的记录仍在本机。"
    }
}

private final class WeakPracticeMessageHandler: NSObject, WKScriptMessageHandler {
    weak var target: PracticeWebController?
    init(_ target: PracticeWebController) { self.target = target }
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.userContentController(userContentController, didReceive: message)
    }
}

#if os(macOS)
private struct PracticeWebSurface: NSViewRepresentable {
    @ObservedObject var controller: PracticeWebController
    func makeNSView(context: Context) -> WKWebView { controller.webView }
    func updateNSView(_ view: WKWebView, context: Context) {}
}
#else
private struct PracticeWebSurface: UIViewRepresentable {
    @ObservedObject var controller: PracticeWebController
    func makeUIView(context: Context) -> WKWebView { controller.webView }
    func updateUIView(_ view: WKWebView, context: Context) {}
}
#endif
