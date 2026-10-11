import SwiftUI
import WebKit
import UniformTypeIdentifiers
import CoreFoundation
import QuickLook
import AVKit
import CryptoKit
#if os(iOS)
import UIKit
#else
import AppKit
#endif

/// The Figma page owns its layout and controls. No native navigation bars are added.
struct FigmaShellView: View {
    @StateObject private var controller = FigmaShellController()
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        Group {
            if let error = controller.errorMessage {
                VStack(spacing: 16) {
                    Text("无法打开界面").font(.title2)
                    Text(error).multilineTextAlignment(.center)
                    Button("重试") { controller.load() }
                }.padding(24).frame(maxWidth: .infinity, maxHeight: .infinity)
            } else { FigmaWebSurface(controller: controller) }
        }
        #if os(iOS)
        // The Figma page owns the iPhone/iPad safe-area insets itself.
        .ignoresSafeArea()
        #endif
        .alert("确认操作", isPresented: $controller.showingJavaScriptDialog) {
            if controller.requiresConfirmation {
                Button("取消", role: .cancel) { controller.finishJavaScriptDialog(false) }
            }
            Button("确定") { controller.finishJavaScriptDialog(true) }
        } message: { Text(controller.javaScriptDialogMessage) }
        .quickLookPreview($controller.previewURL)
        .onChange(of: controller.previewURL) { value in
            if value == nil { controller.clearPreview() }
        }
        .sheet(item: $controller.audioPreview, onDismiss: { controller.clearAudio() }) { preview in
            VStack(spacing: 16) {
                Text("课堂录音").font(.headline)
                VideoPlayer(player: preview.player).frame(minWidth: 280, minHeight: 150)
                Button("关闭") { controller.clearAudio() }
            }.padding(24).onAppear { preview.player.play() }
        }
        .onAppear { controller.load() }
        .onChange(of:scenePhase) { phase in if phase != .active { controller.interruptListening() } }
        .onDisappear { controller.interruptListening() }
    }

}

struct FigmaAccountAudioPreview: Identifiable {
    let id = UUID()
    let player: AVPlayer
}

@MainActor
final class FigmaShellController: NSObject, ObservableObject, WKScriptMessageHandler, WKNavigationDelegate, WKUIDelegate {
    @Published var errorMessage: String?
    @Published var importing = false
    @Published var exporting = false
    @Published var showingJavaScriptDialog = false
    @Published var javaScriptDialogMessage = ""
    @Published var requiresConfirmation = false
    @Published var previewURL: URL?
    @Published var audioPreview: FigmaAccountAudioPreview?
    private(set) var webView: WKWebView!
    private var requests: [String: Task<Void, Never>] = [:]
    private var importContinuation: CheckedContinuation<URL, Error>?
    private var exportContinuation: CheckedContinuation<String, Error>?
    private var importRequestID: String?
    private var exportRequestID: String?
    private var previewDirectory: URL?
    private var audioFile: CloudAccountAudioFile?
    private var accountClients: [String: CloudAccountClient] = [:]
    private let accountDigests = CloudAccountDigestStore()
    private let noteWise = NoteWiseSession()
    private let recordedTranscriber = NoteWisePolyphonicTranscriber()
    private var filePanel: FigmaNativeFilePanel?
    private var javaScriptDialogCompletion: ((Bool) -> Void)?
    private var loaded = false
    private static let originKey = "NoteLite.figma.cloudOrigin"

    override init() {
        super.init()
        let configuration = WKWebViewConfiguration()
        // Preserve UI preferences locally; device credentials remain exclusively in Keychain.
        configuration.websiteDataStore = .default()
        configuration.userContentController.add(WeakCloudMessageHandler(self), name: "noteLiteCloud")
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--uitesting-figma") {
            configuration.userContentController.add(WeakCloudMessageHandler(self), name: "noteLiteDiagnostics")
            configuration.userContentController.addUserScript(WKUserScript(source: """
                (() => {
                  const post = (text) => window.webkit.messageHandlers.noteLiteDiagnostics.postMessage(text);
                  const original = console.info.bind(console);
                  console.info = (...args) => {
                    original(...args);
                    if (typeof args[0] === 'string' && args[0].startsWith('[NoteLite dialog]')) post(args[0].slice(0, 500));
                  };
                  for (const type of ['pointerdown', 'click']) {
                    document.addEventListener(type, (event) => {
                      if (event.target?.closest?.('button')?.getAttribute('aria-label') === '导入曲谱') post('[NoteLite dialog] import ' + type + ' captured');
                    }, true);
                  }
                  window.addEventListener('error', () => post('[NoteLite dialog] JavaScript error observed'));
                  window.addEventListener('unhandledrejection', () => post('[NoteLite dialog] Promise rejection observed'));
                })();
                """, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        }
        #endif
        if let root = Bundle.main.resourceURL?.appendingPathComponent("FigmaUI", isDirectory: true) {
            configuration.setURLSchemeHandler(FigmaResourceHandler(root: root), forURLScheme: FigmaResourceHandler.scheme)
        }
        #if os(macOS)
        webView = FigmaMacWKWebView(frame: .zero, configuration: configuration)
        #else
        webView = WKWebView(frame: .zero, configuration: configuration)
        #endif
        webView.navigationDelegate = self
        webView.uiDelegate = self
        noteWise.event = { [weak self] value in self?.event(value) }
        #if DEBUG && os(iOS)
        FigmaUITestDiagnostics.installTouchObservation(on: webView)
        #endif
        #if os(iOS)
        webView.isOpaque = false
        webView.backgroundColor = .clear
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        FigmaOrientationPolicy.shared.onError = { [weak self] message in
            self?.event(["type": "orientationError", "message": message])
        }
        #endif
    }

    func load() {
        guard !loaded || errorMessage != nil else { return }
        guard let root = Bundle.main.resourceURL?.appendingPathComponent("FigmaUI", isDirectory: true),
              FileManager.default.fileExists(atPath: root.appendingPathComponent("index.html").path) else {
            errorMessage = "Figma 界面资源缺失，请重新安装应用。"
            return
        }
        errorMessage = nil
        loaded = true
        webView.load(URLRequest(url: URL(string: "notelite-ui://app/index.html")!))
    }

    func interruptListening() { noteWise.interruptIfConnected("应用已进入后台或离开页面，请准备好后继续练习。") }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        #if DEBUG
        if message.name == "noteLiteDiagnostics" {
            guard message.frameInfo.isMainFrame,
                  FigmaResourceHandler.isTrusted(message.frameInfo.request.url),
                  FigmaResourceHandler.isTrusted(webView.url),
                  let diagnostic = message.body as? String,
                  diagnostic.hasPrefix("[NoteLite dialog]") else { return }
            // The diagnostic protocol contains static event tags/booleans only,
            // never filenames, account details, score XML or device credentials.
            FigmaUITestDiagnostics.record(String(diagnostic.prefix(500)))
            return
        }
        #endif
        guard message.frameInfo.isMainFrame,
              FigmaResourceHandler.isTrusted(message.frameInfo.request.url),
              FigmaResourceHandler.isTrusted(webView.url),
              let body = message.body as? [String: Any],
              let requestID = body["requestId"] as? String, !requestID.isEmpty, requestID.count <= 128,
              let action = body["action"] as? String, action.count <= 80 else { return }
        let payload = body["payload"] as? [String: Any] ?? [:]
        if action == "request/cancel" {
            guard let target = payload["targetRequestId"] as? String, target != requestID, target.count <= 128 else { return }
            cancelRequest(target)
            resolve(requestID, result: ["cancelled": true])
            return
        }
        guard requests[requestID] == nil, requests.count < 16 else {
            resolve(requestID, error: CloudOMRError(code: "busy", message: "已有请求正在处理，请稍后重试。"))
            return
        }
        requests[requestID] = Task { [weak self] in
            guard let self else { return }
            defer { requests.removeValue(forKey: requestID) }
            do {
                let result = try await perform(action, payload: payload, requestID: requestID)
                if Task.isCancelled, action == "account/digest/start", let value = result as? [String: Any],
                   let id = value["digestId"] as? String, let scope = try? accountClient().identityScope() {
                    _ = try? accountDigests.cancel(id: id, scope: scope)
                }
                try Task.checkCancellation()
                resolve(requestID, result: result)
            } catch { resolve(requestID, error: error) }
        }
    }

    private var origin: String {
        UserDefaults.standard.string(forKey: Self.originKey) ?? CloudOMRClient.defaultOrigin
    }

    private func configuration() throws -> [String: Any] {
        let account = try accountClient().credential()
        let hasCredentials: Bool
        if account != nil { hasCredentials = true }
        else { hasCredentials = !(try CloudDeviceTokenStore.read(origin: origin)).isEmpty }
        return ["baseURL": origin, "hasCredentials": hasCredentials,
         "hasAccountCredentials": account != nil,
         "platform": platform, "native": true, "listeningEnabled": true]
    }

    private var platform: String {
        #if os(macOS)
        return "macos"
        #else
        return UIDevice.current.userInterfaceIdiom == .pad ? "ipad" : "iphone"
        #endif
    }

    private func client(authenticated: Bool = true) throws -> CloudOMRClient {
        let account = authenticated ? try accountClient().credential() : nil
        return try CloudOMRClient(origin: origin, token: authenticated && account == nil ? CloudDeviceTokenStore.read(origin: origin) : "",
                                  accountToken: account?.token, accountUserID: account?.userID)
    }

    private func accountClient() throws -> CloudAccountClient {
        let key = try ServerConfiguration(origin).key
        if let existing = accountClients[key] { return existing }
        let value = try CloudAccountClient(origin: key)
        accountClients[key] = value
        return value
    }

    private func perform(_ action: String, payload: [String: Any], requestID: String) async throws -> Any {
        switch action {
        case "notewise/score-digest":
            let xml = try string(payload, "musicxml")
            guard xml.utf8.count <= 10 * 1024 * 1024 else { throw NoteLiteError.invalidResponse }
            return ["sha256": SHA256.hash(data: Data(xml.utf8)).map { String(format: "%02x", $0) }.joined()]
        case "notewise/start":
            let scope = try accountClient().credential()?.userID ?? "guest"
            return try await noteWise.start(payload, scope: origin + "|" + scope)
        case "notewise/pause":
            try noteWise.checkActive(try string(payload, "takeId"), scope: origin + "|" + (accountClient().credential()?.userID ?? "guest"))
            noteWise.pause()
            return ["paused": true]
        case "notewise/stop":
            try noteWise.checkActive(try string(payload, "takeId"), scope: origin + "|" + (accountClient().credential()?.userID ?? "guest"))
            return await noteWise.stop()
        case "notewise/recording/play":
            guard audioPreview == nil, previewURL == nil, filePanel == nil else { throw CloudOMRError(code:"busy", message:"请先关闭当前播放器或文件窗口。") }
            let scope = try accountClient().credential()?.userID ?? "guest"
            let url = try noteWise.recording(string(payload, "takeId"), scope: origin + "|" + scope)
            audioPreview = FigmaAccountAudioPreview(player: AVPlayer(url:url))
            return ["previewOpened":true]
        case "notewise/refine":
            let capturedOrigin=origin
            let scope = try accountClient().credential()?.userID ?? "guest"
            let url = try noteWise.recording(string(payload,"takeId"),scope:origin+"|"+scope)
            guard let tuning=payload["tuning"] as? Double,tuning.isFinite,(400...480).contains(tuning) else { throw NoteLiteError.invalidResponse }
            let result=try await recordedTranscriber.transcribe(recordingURL:url,tuning:tuning).dictionary
            guard capturedOrigin==origin,(try accountClient().credential()?.userID ?? "guest")==scope else { throw CloudOMRError(code:"identity_changed",message:"账户已更新，请重新读取录音。",status:409) }
            return result
        case "notewise/recording/submit":
            let account=try accountClient(), scope=try account.identityScope(), user=try account.credential()!.userID
            guard try string(payload,"takeId").lowercased()==string(payload,"eventId").lowercased() else { throw NoteLiteError.invalidResponse }
            let file=try noteWise.recording(string(payload,"takeId"),scope:origin+"|"+user)
            let uploadID=try await account.uploadNativeRecording(file,assignmentID:string(payload,"assignmentId"))
            guard try account.identityScope()==scope else { throw CloudOMRError(code:"identity_changed",message:"账户已更改，请重新提交。",status:409) }
            var submission:[String:Any]=["eventId":try string(payload,"eventId"),"uploadId":uploadID]
            if payload["analysisVersion"] != nil { let version=try integer(payload,"analysisVersion");guard version>0 else{throw NoteLiteError.invalidResponse};submission["analysisVersion"]=version }
            return try await account.request(["path":"/assignments/\(try string(payload,"assignmentId"))/submissions","method":"POST","response":"json","expectedUserId":user,"body":submission])
        case "configuration/get": return try configuration()
        case "configuration/set":
            let value = try ServerConfiguration(string(payload, "baseURL")).key
            for (id, task) in requests where id != requestID { task.cancel() }
            accountDigests.clear()
            _ = await noteWise.stop()
            clearAudio()
            accountClients.removeAll()
            UserDefaults.standard.set(value, forKey: Self.originKey)
            return try configuration()
        case "account/request":
            let capturedOrigin = origin
            let account = try accountClient()
            let result = try await account.request(payload)
            guard origin == capturedOrigin else {
                throw CloudOMRError(code: "identity_changed", message: "服务地址已更改，请重新打开当前内容。", status: 409)
            }
            if ["/login", "/register", "/logout"].contains(payload["path"] as? String ?? "") ||
                ((payload["method"] as? String) == "DELETE" && (payload["path"] as? String)?.hasPrefix("/sessions/") == true) {
                accountDigests.clear()
                _ = await noteWise.stop()
                clearAudio()
            }
            return result
        case "account/digest/start":
            return try accountDigests.start(size: payload["size"], scope: accountClient().identityScope())
        case "account/digest/update":
            return try accountDigests.update(id: string(payload, "digestId"), base64: string(payload, "base64"),
                                             offset: payload["offset"], scope: accountClient().identityScope())
        case "account/digest/finish":
            return try accountDigests.finish(id: string(payload, "digestId"), scope: accountClient().identityScope())
        case "account/digest/cancel":
            return try accountDigests.cancel(id: string(payload, "digestId"), scope: accountClient().identityScope())
        case "account/audio/view":
            guard audioPreview == nil, previewURL == nil, filePanel == nil else {
                throw CloudOMRError(code: "busy", message: "请先关闭当前播放或文件窗口。")
            }
            let capturedOrigin = origin
            let account = try accountClient()
            let scope = try account.identityScope()
            let file = try await account.downloadAudio(submissionID: string(payload, "submissionId"), expectedUserID: payload["expectedUserId"])
            do {
                let playable = try await AVURLAsset(url: file.url).load(.isPlayable)
                try Task.checkCancellation()
                guard try account.identityScope() == scope else {
                    throw CloudOMRError(code: "identity_changed", message: "账号已切换，请重新打开录音。", status: 409)
                }
                guard origin == capturedOrigin, audioPreview == nil, previewURL == nil, filePanel == nil else {
                    throw CloudOMRError(code: "busy", message: "播放状态已更新，请重新打开录音。")
                }
                guard playable else { throw CloudOMRError(code: "unsupported_audio", message: "当前设备不能播放这种录音格式。") }
                audioFile = file
                audioPreview = FigmaAccountAudioPreview(player: AVPlayer(url: file.url))
                return ["previewOpened": true]
            } catch { file.remove(); throw error }
        case "device/pair":
            let pairingOrigin = origin
            let pairingClient = try CloudOMRClient(origin: pairingOrigin, token: "")
            var result = try await pairingClient.pair(code: string(payload, "code"), deviceName: string(payload, "deviceName"))
            guard let token = result.removeValue(forKey: "token") as? String, !token.isEmpty else {
                throw NoteLiteError.invalidResponse
            }
            try CloudDeviceTokenStore.save(token, origin: pairingOrigin)
            result["hasCredentials"] = true
            return result
        case "device/unpair":
            let logoutOrigin = origin
            let logoutClient = try CloudOMRClient(origin: logoutOrigin, token: CloudDeviceTokenStore.read(origin: logoutOrigin))
            do { try await logoutClient.logout() }
            catch let error as CloudOMRError where error.status == 401 { /* Already revoked or expired. */ }
            try CloudDeviceTokenStore.remove(origin: logoutOrigin)
            return try configuration()
        case "session": return try await client().sessionInfo()
        case "health": return try await client(authenticated: false).health()
        case "jobs/list": return try await client().jobs()
        case "jobs/get": return try await client().job(string(payload, "jobId"))
        case "jobs/upload":
            let base64 = try string(payload, "base64")
            guard base64.count <= 45 * 1024 * 1024, let data = Data(base64Encoded: base64) else {
                throw CloudOMRError(code: "invalid_file", message: "上传文件内容无效或过大。")
            }
            return try await upload(data, filename: string(payload, "filename"), requestID: requestID)
        case "jobs/import":
            guard importContinuation == nil, exportContinuation == nil, filePanel == nil, previewURL == nil, audioPreview == nil else {
                throw CloudOMRError(code: "busy", message: "请先关闭当前文件窗口。")
            }
            // Pairing must be completed before asking the user for a score file.
            _ = try client()
            guard (try configuration())["hasCredentials"] as? Bool == true else {
                throw CloudOMRError(code: "pairing_required", message: "请先连接识谱服务。")
            }
            let selected = try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<URL, Error>) in
                importRequestID = requestID
                importContinuation = continuation
                importing = true
                do {
                    filePanel = try FigmaNativeFilePanel.open(in: webView) { [weak self] in self?.importSelected($0) }
                } catch { importSelected(.failure(error)) }
            }
            let scoped = selected.startAccessingSecurityScopedResource()
            defer { if scoped { selected.stopAccessingSecurityScopedResource() } }
            let data = try await Task.detached(priority: .userInitiated) {
                let size = try selected.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
                guard size > 0, size <= CloudOMRClient.maximumUploadBytes else {
                    throw CloudOMRError(code: "file_too_large", message: "乐谱文件不能超过 32 MiB。")
                }
                return try Data(contentsOf: selected)
            }.value
            return try await upload(data, filename: selected.lastPathComponent, requestID: requestID)
        case "score/get":
            return try await client().musicxml(jobID: string(payload, "jobId"), score: integer(payload, "score", default: 0))
        case "notes/get":
            return try await client().notes(jobID: string(payload, "jobId"), score: integer(payload, "score", default: 0))
        case "notes/patch":
            guard let edits = payload["edits"] as? [[String: Any]] else { throw NoteLiteError.invalidResponse }
            return try await client().patchNotes(jobID: string(payload, "jobId"), score: integer(payload, "score", default: 0),
                                                revision: integer(payload, "revision"), edits: edits)
        case "score/put":
            return try await client().replaceScore(jobID: string(payload, "jobId"), score: integer(payload, "score", default: 0),
                                                   revision: integer(payload, "revision"), musicxml: string(payload, "musicxml"))
        case "files/get":
            let kind = try string(payload, "kind")
            let data = try await client().file(jobID: string(payload, "jobId"), score: integer(payload, "score", default: 0), kind: kind)
            guard data.count <= 16 * 1024 * 1024 else {
                throw CloudOMRError(code: "file_too_large", message: "请使用导出功能保存这个结果文件。")
            }
            return ["base64": data.base64EncodedString(), "kind": kind]
        case "files/export":
            guard exportContinuation == nil else { throw CloudOMRError(code: "busy", message: "结果保存窗口已经打开。") }
            let kind = try string(payload, "kind")
            let score = try integer(payload, "score", default: 0)
            let data = try await client().file(jobID: string(payload, "jobId"), score: score, kind: kind)
            guard exportContinuation == nil else { throw CloudOMRError(code: "busy", message: "结果保存窗口已经打开。") }
            let ext = kind == "midi" ? "mid" : kind == "musicxml" ? "musicxml" : kind == "log" ? "txt" : kind == "omr" ? "omr" : "bin"
            return try await saveFile(data, filename: (payload["filename"] as? String) ?? "score-\(score + 1).\(ext)", requestID: requestID)
        case "files/save":
            let base64 = try string(payload, "base64")
            guard base64.count <= 24 * 1024 * 1024, let data = Data(base64Encoded: base64),
                  !data.isEmpty, data.count <= 16 * 1024 * 1024 else {
                throw CloudOMRError(code: "file_too_large", message: "本机导出文件为空或超过 16 MiB。")
            }
            return try await saveFile(data, filename: string(payload, "filename"), requestID: requestID)
        case "files/view":
            guard previewURL == nil, filePanel == nil, audioPreview == nil else { throw CloudOMRError(code: "busy", message: "请先关闭当前文件窗口。") }
            guard try string(payload, "kind") == "original" else { throw NoteLiteError.invalidResponse }
            let filename = try string(payload, "filename")
            try FileRules.validateFilename(filename)
            guard ["pdf", "png", "jpg", "jpeg"].contains((filename as NSString).pathExtension.lowercased()) else {
                throw CloudOMRError(code: "invalid_file", message: "原稿预览支持 PDF、PNG 与 JPEG。")
            }
            let data = try await client().file(jobID: string(payload, "jobId"), score: integer(payload, "score", default: 0), kind: "original")
            guard data.count <= CloudOMRClient.maximumUploadBytes else {
                throw CloudOMRError(code: "file_too_large", message: "原稿预览不能超过 32 MiB。")
            }
            guard previewURL == nil, filePanel == nil else { throw CloudOMRError(code: "busy", message: "请先关闭当前文件窗口。") }
            let directory = FileManager.default.temporaryDirectory.appendingPathComponent("notelite-preview-\(UUID().uuidString)", isDirectory: true)
            let fileURL = directory.appendingPathComponent(filename)
            try await Task.detached(priority: .userInitiated) {
                try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
                do { try data.write(to: fileURL, options: .atomic) }
                catch { try? FileManager.default.removeItem(at: directory); throw error }
            }.value
            if Task.isCancelled { try? FileManager.default.removeItem(at: directory); throw CancellationError() }
            guard previewURL == nil, filePanel == nil, audioPreview == nil else {
                try? FileManager.default.removeItem(at: directory)
                throw CloudOMRError(code: "busy", message: "请先关闭当前文件窗口。")
            }
            clearPreview()
            previewDirectory = directory
            previewURL = fileURL
            return ["presented": true]
        case "orientation/set":
            let mode = try string(payload, "mode")
            #if os(iOS)
            return try FigmaOrientationPolicy.shared.set(mode, window: webView.window)
            #else
            guard mode == "landscape" || mode == "restore" else { throw NoteLiteError.invalidResponse }
            return ["mode": mode, "requested": false, "platform": "macos"]
            #endif
        default: throw CloudOMRError(code: "unsupported_action", message: "此版本未提供这个功能。")
        }
    }

    private func upload(_ data: Data, filename: String, requestID: String) async throws -> [String: Any] {
        try await client().upload(data: data, filename: filename) { [weak self] progress in
            Task { @MainActor [weak self] in
                self?.event(["type": "uploadProgress", "requestId": requestID, "progress": progress])
            }
        }
    }

    private func saveFile(_ data: Data, filename: String, requestID: String) async throws -> [String: Any] {
        guard exportContinuation == nil, importContinuation == nil, filePanel == nil, previewURL == nil, audioPreview == nil else {
            throw CloudOMRError(code: "busy", message: "请先关闭当前文件窗口。")
        }
        try FileRules.validateFilename(filename)
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("notelite-export-\(UUID().uuidString)", isDirectory: true)
        let fileURL = directory.appendingPathComponent(filename)
        try await Task.detached(priority: .userInitiated) {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
            do { try data.write(to: fileURL, options: .atomic) }
            catch { try? FileManager.default.removeItem(at: directory); throw error }
        }.value
        defer { try? FileManager.default.removeItem(at: directory) }
        try Task.checkCancellation()
        guard exportContinuation == nil, importContinuation == nil, filePanel == nil, previewURL == nil, audioPreview == nil else {
            throw CloudOMRError(code: "busy", message: "文件选择窗口已经打开。")
        }
        let savedName = try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<String, Error>) in
            exportRequestID = requestID
            exportContinuation = continuation
            exporting = true
            do {
                filePanel = try FigmaNativeFilePanel.save(fileURL, in: webView) { [weak self] result in
                    self?.exportFinished(result.flatMap { urls in
                        guard let first = urls.first else { return .failure(CancellationError()) }
                        return .success(first)
                    })
                }
            } catch { exportFinished(.failure(error)) }
        }
        return ["saved": true, "filename": savedName]
    }

    func importSelected(_ result: Result<[URL], Error>) {
        let continuation = importContinuation
        importContinuation = nil
        importRequestID = nil
        importing = false
        filePanel = nil
        switch result {
        case .success(let urls):
            if let first = urls.first { continuation?.resume(returning: first) }
            else { continuation?.resume(throwing: CancellationError()) }
        case .failure(let error): continuation?.resume(throwing: error)
        }
    }

    func exportFinished(_ result: Result<URL, Error>) {
        let continuation = exportContinuation
        exportContinuation = nil
        exportRequestID = nil
        exporting = false
        filePanel = nil
        switch result {
        case .success(let url): continuation?.resume(returning: url.lastPathComponent)
        case .failure(let error): continuation?.resume(throwing: error)
        }
    }

    func clearPreview() {
        if let previewDirectory { try? FileManager.default.removeItem(at: previewDirectory) }
        previewDirectory = nil
    }

    func clearAudio() {
        audioPreview?.player.pause()
        audioPreview = nil
        audioFile?.remove()
        audioFile = nil
    }

    private func cancelRequest(_ requestID: String) {
        requests[requestID]?.cancel()
        if importRequestID == requestID || exportRequestID == requestID {
            filePanel?.cancel()
            filePanel = nil
        }
        if importRequestID == requestID {
            importRequestID = nil
            let continuation = importContinuation
            importContinuation = nil
            importing = false
            continuation?.resume(throwing: CancellationError())
        }
        if exportRequestID == requestID {
            exportRequestID = nil
            let continuation = exportContinuation
            exportContinuation = nil
            exporting = false
            continuation?.resume(throwing: CancellationError())
        }
    }

    private func string(_ value: [String: Any], _ key: String) throws -> String {
        guard let result = value[key] as? String, !result.isEmpty else {
            throw CloudOMRError(code: "invalid_request", message: "缺少有效的 \(key) 参数。")
        }
        return result
    }

    private func integer(_ value: [String: Any], _ key: String, default fallback: Int? = nil) throws -> Int {
        if value[key] == nil, let fallback { return fallback }
        guard let result = value[key] as? NSNumber, CFGetTypeID(result) != CFBooleanGetTypeID(),
              result.doubleValue.isFinite, result.doubleValue.rounded() == result.doubleValue,
              result.doubleValue >= 0, result.doubleValue <= Double(Int32.max) else {
            throw CloudOMRError(code: "invalid_request", message: "\(key) 参数必须是非负整数。")
        }
        return result.intValue
    }

    private func resolve(_ requestID: String, result: Any) {
        callback("window.NoteLiteCloudNative?.resolve(requestId, envelope)",
                 arguments: ["requestId": requestID, "envelope": ["ok": true, "result": result]])
    }

    private func resolve(_ requestID: String, error: Error) {
        let value: [String: Any]
        if let error = error as? CloudOMRError { value = error.bridgeValue }
        else if error is CancellationError || (error as NSError).code == NSUserCancelledError ||
                    ((error as NSError).domain == NSURLErrorDomain && (error as NSError).code == NSURLErrorCancelled) {
            value = ["code": "cancelled", "message": "操作已取消。"]
        } else { value = ["code": "request_failed", "message": error.localizedDescription] }
        callback("window.NoteLiteCloudNative?.resolve(requestId, envelope)",
                 arguments: ["requestId": requestID, "envelope": ["ok": false, "error": value]])
    }

    private func event(_ value: [String: Any]) {
        callback("window.NoteLiteCloudNative?.event(value)", arguments: ["value": value])
    }

    private func callback(_ script: String, arguments: [String: Any]) {
        guard FigmaResourceHandler.isTrusted(webView.url) else { return }
        webView.callAsyncJavaScript(script, arguments: arguments, in: nil, in: .page) { _ in }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        // A local original PDF can be displayed in a blob iframe. It never gets
        // the main-frame-only native bridge, and blob top-level navigation is denied.
        let localBlobFrame = navigationAction.request.url?.scheme == "blob" &&
            navigationAction.targetFrame?.isMainFrame == false &&
            FigmaResourceHandler.isTrusted(navigationAction.sourceFrame.request.url) &&
            FigmaResourceHandler.isTrusted(webView.url)
        decisionHandler(FigmaResourceHandler.isTrusted(navigationAction.request.url) || localBlobFrame ? .allow : .cancel)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        event(["type": "nativeReady", "platform": platform, "listeningEnabled": true])
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        guard frame.isMainFrame, FigmaResourceHandler.isTrusted(frame.request.url),
              javaScriptDialogCompletion == nil else { completionHandler(false); return }
        javaScriptDialogMessage = message
        requiresConfirmation = true
        javaScriptDialogCompletion = completionHandler
        showingJavaScriptDialog = true
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        guard frame.isMainFrame, FigmaResourceHandler.isTrusted(frame.request.url),
              javaScriptDialogCompletion == nil else { completionHandler(); return }
        javaScriptDialogMessage = message
        requiresConfirmation = false
        javaScriptDialogCompletion = { _ in completionHandler() }
        showingJavaScriptDialog = true
    }

    func finishJavaScriptDialog(_ accepted: Bool) {
        let completion = javaScriptDialogCompletion
        javaScriptDialogCompletion = nil
        showingJavaScriptDialog = false
        completion?(accepted)
    }

    #if os(macOS)
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        guard frame.isMainFrame, FigmaResourceHandler.isTrusted(frame.request.url) else {
            completionHandler(nil)
            return
        }
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = parameters.allowsDirectories
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        let complete: (NSApplication.ModalResponse) -> Void = { result in
            completionHandler(result == .OK ? panel.urls : nil)
        }
        if let window = webView.window { panel.beginSheetModal(for: window, completionHandler: complete) }
        else { panel.begin(completionHandler: complete) }
    }
    #endif

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if (error as NSError).code != NSURLErrorCancelled { errorMessage = error.localizedDescription }
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        Task { _ = await noteWise.stop() }
        requests.values.forEach { $0.cancel() }
        filePanel?.cancel(); filePanel = nil
        importContinuation?.resume(throwing: CancellationError()); importContinuation = nil
        exportContinuation?.resume(throwing: CancellationError()); exportContinuation = nil
        importRequestID = nil; exportRequestID = nil
        importing = false; exporting = false
        previewURL = nil; clearPreview()
        finishJavaScriptDialog(false)
        errorMessage = "界面已停止，请重试。云端任务仍可在重新打开后获取。"
    }
}

private final class WeakCloudMessageHandler: NSObject, WKScriptMessageHandler {
    weak var controller: FigmaShellController?
    init(_ controller: FigmaShellController) { self.controller = controller }
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        controller?.userContentController(userContentController, didReceive: message)
    }
}

#if os(macOS)
private struct FigmaWebSurface: NSViewRepresentable {
    @ObservedObject var controller: FigmaShellController
    func makeNSView(context: Context) -> WKWebView { controller.webView }
    func updateNSView(_ view: WKWebView, context: Context) {}
}
#else
private struct FigmaWebSurface: UIViewRepresentable {
    @ObservedObject var controller: FigmaShellController
    func makeUIView(context: Context) -> WKWebView { controller.webView }
    func updateUIView(_ view: WKWebView, context: Context) {}
}
#endif
