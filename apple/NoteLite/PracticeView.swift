import SwiftUI
import WebKit

/// SwiftUI owns navigation and storage; the bundled renderer/matcher is shared with desktop NoteLite.
struct PracticeView: View {
    @EnvironmentObject private var history: PracticeHistoryStore
    @Environment(\.scenePhase) private var scenePhase
    let record: ScoreRecord
    let part: PracticePart
    let onDismiss: () -> Void
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
            .navigationTitle(part.title.map { record.displayTitle + " · " + $0 } ?? record.filename)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button { controller.close(completion: onDismiss) } label: {
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
        controller.onReport = { report in history.save(report: report, for: record, part: part) }
        controller.onClose = onDismiss
        controller.open(score: record, url: part.url, partID: part.id)
    }
}

@MainActor
final class PracticeWebController: NSObject, ObservableObject, WKScriptMessageHandler, WKNavigationDelegate {
    @Published var errorMessage: String?
    private(set) var webView: WKWebView!
    var onReport: (([String: Any]) -> Void)?
    var onClose: (() -> Void)?
    private let input = NativePracticeInput()
    private(set) var source: (data: String, title: String, id: String)?
    private var inputTask: Task<Void, Never>?
    private var documentID: String?
    private var forwardingAudio = false
    private var pendingAudio: [MicrophoneFrame] = []
    private var audioClockOffset: Double?
    private var audioGeneration = UUID()
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
        input.onAudio = { [weak self] frames in self?.enqueueAudio(frames) }
        input.onError = { [weak self] error in
            self?.resetAudioPipeline()
            self?.call("window.NoteLiteNative?.inputError(error)", arguments: ["error": error])
        }
    }

    func open(score: ScoreRecord, url: URL?, partID: String = "source") {
        let identity = score.id.uuidString + "/" + partID
        guard documentID != identity || errorMessage != nil else { return }
        inputTask?.cancel()
        input.stop()
        resetAudioPipeline()
        isClosing = false
        closeFinished = false
        closeCompletions.removeAll()
        errorMessage = nil
        guard let url else { errorMessage = "此乐谱还没有可用的 MusicXML。请先完成识谱，或直接导入 MusicXML 文件。"; return }
        guard let page = Bundle.main.url(forResource: "index", withExtension: "html", subdirectory: "practice") else {
            errorMessage = "练习资源缺失，请重新安装应用。"; return
        }
        do {
            let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
            guard size > 0, size <= 15 * 1024 * 1024 else {
                throw NoteLiteError.server("陪练乐谱需要小于 15 MB，请拆分后导入。")
            }
            let data = try Data(contentsOf: url)
            source = (data.base64EncodedString(), score.filename, identity)
            documentID = identity
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
                call("await window.NoteLiteNative.loadScore(data, title, id); window.NoteLiteNative.applyPreferences(preferences)",
                    arguments: ["data": source.data, "title": source.title, "id": source.id,
                        "preferences": UserDefaults.standard.dictionary(forKey: "Yinban.practicePreferences") ?? [:]], reportErrors: true)
            }
        case "startInput":
            guard !isClosing else { return }
            guard let mode = body["input"] as? String, let requestID = body["requestId"] else { return }
            inputTask?.cancel()
            resetAudioPipeline()
            inputTask = Task { [weak self] in
                guard let self else { return }
                do {
                    try Task.checkCancellation()
                    if mode == "microphone" { try await synchronizeAudioClock() }
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
        case "stopInput": inputTask?.cancel(); input.stop(); resetAudioPipeline()
        case "report":
            if let report = body["report"] as? [String: Any] { onReport?(report) }
        case "close": close { [weak self] in self?.onClose?() }
        default: break
        }
    }

    func suspend() {
        inputTask?.cancel()
        input.stop()
        resetAudioPipeline()
        call("window.NoteLiteNative?.suspend?.()")
    }

    func close(completion: (() -> Void)? = nil) {
        inputTask?.cancel()
        input.stop()
        resetAudioPipeline()
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

    private func resetAudioPipeline() {
        audioGeneration = UUID()
        pendingAudio.removeAll(keepingCapacity: true)
        audioClockOffset = nil
        forwardingAudio = false
    }

    func readJavaScriptAudioClock() async throws -> Double {
        // The async overload uses contentWorld:, whereas the callback overload uses a second in:.
        let result: Any? = try await webView.callAsyncJavaScript("return performance.now()", arguments: [:], in: nil, contentWorld: .page)
        guard let milliseconds = result as? Double, milliseconds.isFinite else {
            throw NoteLiteError.server("无法准备声音处理时钟，请重新开始练习。")
        }
        return milliseconds
    }

    private func synchronizeAudioClock() async throws {
        let generation = audioGeneration
        var best: (roundTrip: Double, offset: Double)?
        for _ in 0..<3 {
            let before = PracticeAudioClock.now
            let milliseconds = try await readJavaScriptAudioClock()
            let after = PracticeAudioClock.now
            try Task.checkCancellation()
            guard generation == audioGeneration else { throw CancellationError() }
            let roundTrip = after - before
            if best == nil || roundTrip < best!.roundTrip {
                best = (roundTrip, milliseconds - (before + after) * 500)
            }
        }
        // Audio timestamps and performance.now() are both monotonic but have
        // different origins. Prefer the shortest round trip to reduce scheduling
        // error, and reject a stalled page rather than publish an inaccurate clock.
        guard let best, best.roundTrip <= 0.100 else {
            throw NoteLiteError.server("声音处理准备超时，请稍后重新开始练习。")
        }
        audioClockOffset = best.offset
    }

    private func enqueueAudio(_ frames: [MicrophoneFrame]) {
        guard !isClosing, audioClockOffset != nil else { return }
        pendingAudio.append(contentsOf: frames)
        guard pendingAudio.count <= 16 else { audioBackpressureFailed(); return }
        forwardPendingAudio()
    }

    private func forwardPendingAudio() {
        guard !forwardingAudio, !pendingAudio.isEmpty, let offset = audioClockOffset else { return }
        guard PracticeAudioClock.now - pendingAudio[0].endTime <= 0.150 else {
            audioBackpressureFailed(); return
        }
        // One JS call carries overlap windows in order, so a busy call cannot
        // silently discard the remaining windows from the same audio tap.
        let frames = Array(pendingAudio.prefix(4))
        pendingAudio.removeFirst(frames.count)
        let payload = frames.map { frame -> [String: Any] in
            ["samples": frame.samples, "sampleRate": frame.sampleRate,
             "endTime": frame.endTime * 1000 + offset]
        }
        let generation = audioGeneration
        forwardingAudio = true
        webView.callAsyncJavaScript("for (const frame of frames) window.NoteLiteNative?.audioFrame(frame.samples, frame.sampleRate, frame.endTime)",
            arguments: ["frames": payload], in: nil, in: .page) { [weak self] result in
                guard let self, self.audioGeneration == generation else { return }
                self.forwardingAudio = false
                if case .failure = result { self.audioBackpressureFailed(); return }
                self.forwardPendingAudio()
            }
    }

    private func audioBackpressureFailed() {
        inputTask?.cancel()
        input.stop()
        resetAudioPipeline()
        call("window.NoteLiteNative?.inputError(error)",
             arguments: ["error": "声音处理暂时跟不上，练习已暂停。准备好后请继续练习。"])
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
        resetAudioPipeline()
        errorMessage = error.localizedDescription
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        inputTask?.cancel()
        input.stop()
        resetAudioPipeline()
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
