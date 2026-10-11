import Foundation
import Security
import CryptoKit
import CoreFoundation

struct CloudAccountCredential: Codable, Equatable {
    let token: String
    let userID: String
    let sessionID: String

    func validate() throws {
        guard token.range(of: "^[A-Za-z0-9_-]{16,4096}$", options: .regularExpression) != nil,
              UUID(uuidString: userID) != nil, UUID(uuidString: sessionID) != nil else {
            throw NoteLiteError.invalidResponse
        }
    }
}

protocol CloudAccountCredentialStore {
    func read(origin: String) throws -> CloudAccountCredential?
    func save(_ value: CloudAccountCredential, origin: String) throws
    func remove(origin: String) throws
}

/// Account identity is separate from the legacy device pairing, scoped to one HTTPS origin.
struct KeychainCloudAccountCredentials: CloudAccountCredentialStore {
    private func identity(_ origin: String) throws -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: "com.notelite.figma.cloud-account-token",
         kSecAttrAccount as String: try ServerConfiguration(origin).key]
    }

    func read(origin: String) throws -> CloudAccountCredential? {
        var query = try identity(origin)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess else { throw NoteLiteError.keychain(status) }
        guard let data = result as? Data, data.count <= 8192 else { throw NoteLiteError.invalidResponse }
        let value = try JSONDecoder().decode(CloudAccountCredential.self, from: data)
        try value.validate()
        return value
    }

    func save(_ value: CloudAccountCredential, origin: String) throws {
        try value.validate()
        let query = try identity(origin)
        let values: [String: Any] = [
            kSecValueData as String: try JSONEncoder().encode(value),
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        ]
        let status = SecItemUpdate(query as CFDictionary, values as CFDictionary)
        if status == errSecItemNotFound {
            let status = SecItemAdd(query.merging(values) { _, new in new } as CFDictionary, nil)
            guard status == errSecSuccess else { throw NoteLiteError.keychain(status) }
        } else if status != errSecSuccess { throw NoteLiteError.keychain(status) }
    }

    func remove(origin: String) throws {
        let status = SecItemDelete(try identity(origin) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw NoteLiteError.keychain(status) }
    }
}

private final class AccountTransferDelegate: NSObject, URLSessionDownloadDelegate {
    private let maximumBytes: Int64
    private let lock = NSLock()
    private var exceeded = false
    init(maximumBytes: Int) { self.maximumBytes = Int64(maximumBytes) }
    var oversized: Bool { lock.lock(); defer { lock.unlock() }; return exceeded }
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask,
                    didWriteData bytesWritten: Int64, totalBytesWritten: Int64, totalBytesExpectedToWrite: Int64) {
        if totalBytesWritten > maximumBytes || totalBytesExpectedToWrite > maximumBytes {
            lock.lock(); exceeded = true; lock.unlock()
            downloadTask.cancel()
        }
    }
    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {}
}

struct CloudAccountAudioFile {
    let directory: URL
    let url: URL
    let mime: String
    func remove() { try? FileManager.default.removeItem(at: directory) }
}

@MainActor
final class CloudAccountClient {
    static let maximumRecordingBytes = 100 * 1024 * 1024
    static let maximumChunkBytes = 1024 * 1024
    private let configuration: ServerConfiguration
    private let credentials: CloudAccountCredentialStore
    private let session: URLSession
    private var changingAuthentication = false

    init(origin: String, credentials: CloudAccountCredentialStore = KeychainCloudAccountCredentials(),
         sessionConfiguration: URLSessionConfiguration = .ephemeral) throws {
        configuration = try ServerConfiguration(origin)
        self.credentials = credentials
        sessionConfiguration.timeoutIntervalForRequest = 240
        sessionConfiguration.timeoutIntervalForResource = 300
        sessionConfiguration.urlCache = nil
        sessionConfiguration.httpCookieStorage = nil
        sessionConfiguration.httpShouldSetCookies = false
        sessionConfiguration.httpCookieAcceptPolicy = .never
        sessionConfiguration.urlCredentialStorage = nil
        session = URLSession(configuration: sessionConfiguration)
    }
    deinit { session.invalidateAndCancel() }

    func credential() throws -> CloudAccountCredential? { try credentials.read(origin: configuration.key) }
    func identityScope() throws -> String {
        guard let identity = try credential() else { throw Self.unauthenticated() }
        return configuration.key + "|" + identity.userID + "|" + identity.sessionID
    }

    /// The bridge accepts a small API vocabulary, never a URL, arbitrary header or internal endpoint.
    static func route(path: String, method: String) throws -> (path: [String], query: [URLQueryItem]) {
        guard ["GET", "POST", "PUT", "DELETE"].contains(method), path.count <= 1024,
              path.hasPrefix("/"), !path.hasPrefix("//"), !path.contains("\\"), !path.contains("#"),
              let components = URLComponents(string: path), components.scheme == nil, components.host == nil,
              !components.percentEncodedPath.contains("%") else { throw Self.invalidRequest() }
        var p = components.path.split(separator: "/", omittingEmptySubsequences: false).dropFirst().map(String.init)
        guard !p.isEmpty, p.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }) else { throw Self.invalidRequest() }
        func uuid(_ index: Int) -> Bool {
            p.indices.contains(index) && p[index].range(of: "^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", options: .regularExpression) != nil
        }
        var allowed = false
        switch p.count {
        case 1:
            let verbs: [String: Set<String>] = ["health": ["GET"], "register": ["POST"], "login": ["POST"],
                "me": ["GET"], "logout": ["POST"], "account": ["DELETE"], "sessions": ["GET"], "catalog": ["GET"],
                "scores": ["GET", "POST"], "history": ["GET", "POST"], "courses": ["GET", "POST"], "uploads": ["POST"],
                "practice-analysis": ["POST"]]
            allowed = verbs[p[0]]?.contains(method) == true
        case 2:
            if p[0] == "course-codes" { allowed = method == "POST" && ["preview", "join"].contains(p[1]) }
            else if uuid(1) {
                switch p[0] {
                case "sessions": allowed = method == "DELETE"
                case "scores": allowed = ["GET", "PUT"].contains(method)
                case "courses", "submissions": allowed = method == "GET"
                case "uploads": allowed = ["GET", "PUT"].contains(method)
                default: break
                }
            }
        case 3:
            if p[0] == "catalog" {
                allowed = method == "GET" && p[2] == "musicxml" && p[1].range(of: "^[A-Za-z0-9_-]{1,80}$", options: .regularExpression) != nil
            } else if uuid(1) {
                switch p[0] {
                case "scores": allowed = p[2] == "musicxml" && method == "GET"
                case "history": allowed = (p[2] == "musicxml" && method == "GET") || (p[2] == "analyses" && ["GET","POST"].contains(method))
                case "submissions": allowed = ["musicxml", "audio"].contains(p[2]) && method == "GET"
                case "uploads": allowed = p[2] == "complete" && method == "POST"
                case "assignments": allowed = p[2] == "submissions" && ["GET", "POST"].contains(method)
                case "courses":
                    allowed = (p[2] == "roster" && method == "GET") ||
                        (["scores", "codes"].contains(p[2]) && method == "POST") ||
                        (p[2] == "assignments" && ["GET", "POST"].contains(method)) ||
                        (p[2] == "membership" && method == "DELETE")
                default: break
                }
            }
        case 4:
            allowed = (p[0] == "courses" && uuid(1) && p[2] == "codes" &&
                p[3].range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil && method == "DELETE") ||
                (p[0] == "history" && uuid(1) && p[2] == "analyses" &&
                    p[3].range(of:"^[1-9][0-9]{0,8}$",options:.regularExpression) != nil && method == "GET")
        default: break
        }
        guard allowed else { throw Self.invalidRequest() }
        for index in p.indices where uuid(index) { p[index] = p[index].lowercased() }
        let query = components.queryItems ?? []
        guard query.isEmpty || (p == ["history"] && method == "GET") else { throw Self.invalidRequest() }
        var seen = Set<String>()
        for item in query {
            guard seen.insert(item.name).inserted, let value = item.value else { throw Self.invalidRequest() }
            if item.name == "limit" {
                guard value.range(of: "^[0-9]{1,3}$", options: .regularExpression) != nil,
                      let limit = Int(value), (1...200).contains(limit) else { throw Self.invalidRequest() }
            } else if item.name == "cursor" {
                let pair = value.split(separator: ":", maxSplits: 1).map(String.init)
                guard pair.count == 2, let timestamp = Double(pair[0]), timestamp.isFinite, timestamp >= 0,
                      UUID(uuidString: pair[1]) != nil else { throw Self.invalidRequest() }
            } else { throw Self.invalidRequest() }
        }
        return (["api", "account"] + p, query)
    }

    /// This URL is supplied exclusively by the native take registry, never a WebView path.
    func uploadNativeRecording(_ file:URL,assignmentID:String) async throws -> String {
        guard UUID(uuidString:assignmentID) != nil, let userID=try credential()?.userID else { throw Self.unauthenticated() }
        let scope=try identityScope(), size=try file.resourceValues(forKeys:[.fileSizeKey]).fileSize ?? 0
        guard size>0, size<=Self.maximumRecordingBytes else { throw Self.invalidRequest() }
        let reader=try FileHandle(forReadingFrom:file); defer { try? reader.close() }
        var hash=SHA256()
        while let data=try reader.read(upToCount:Self.maximumChunkBytes), !data.isEmpty { hash.update(data:data) }
        let digest=hash.finalize().map { String(format:"%02x",$0) }.joined()
        let response=try await request(["path":"/uploads","method":"POST","response":"json","expectedUserId":userID,
            "body":["assignmentId":assignmentID,"size":size,"mime":"audio/wav","sha256":digest]]) as? [String:Any]
        guard let id=response?["uploadId"] as? String, UUID(uuidString:id) != nil else { throw NoteLiteError.invalidResponse }
        var offset=try Self.integer(response?["offset"],maximum:size)
        try reader.seek(toOffset:UInt64(offset))
        while offset<size {
            try Task.checkCancellation(); guard try identityScope()==scope else { throw Self.unauthenticated() }
            guard let data=try reader.read(upToCount:min(Self.maximumChunkBytes,size-offset)), !data.isEmpty else { throw NoteLiteError.invalidResponse }
            _ = try await request(["path":"/uploads/\(id)","method":"PUT","response":"json","expectedUserId":userID,
                "base64":data.base64EncodedString(),"uploadOffset":offset])
            offset += data.count
        }
        _ = try await request(["path":"/uploads/\(id)/complete","method":"POST","response":"json","expectedUserId":userID,"body":[String:Any]()])
        return id
    }

    func request(_ input: [String: Any]) async throws -> Any {
        try ReleaseFeatures.requireAllowedRequest("account/request", payload: input)
        let keys: Set<String> = ["path", "method", "body", "etag", "response", "base64", "uploadOffset", "expectedUserId"]
        guard Set(input.keys).isSubset(of: keys), let path = input["path"] as? String,
              let method = input["method"] as? String, let representation = input["response"] as? String,
              ["json", "text", "base64"].contains(representation) else { throw Self.invalidRequest() }
        let route = try Self.route(path: path, method: method)
        guard route.path.last != "audio" else {
            throw CloudOMRError(code: "native_audio_preview_required", message: "请使用播放录音功能打开这段录音。")
        }
        let auth = path == "/register" || path == "/login"
        let logout = path == "/logout"
        let deleting = path == "/account" && method == "DELETE"
        guard !changingAuthentication else { throw CloudOMRError(code: "busy", message: "正在更新登录状态，请稍后重试。") }
        if auth || logout || deleting { changingAuthentication = true }
        defer { if auth || logout || deleting { changingAuthentication = false } }
        let identity = try credential()
        let isPublic = auth || path == "/health"
        if !isPublic && identity == nil { throw Self.unauthenticated() }
        try Self.checkExpectedUser(input["expectedUserId"], identity: identity)
        // Binary audio is intentionally presented by the native player, not copied through WebView.
        if representation == "base64" {
            throw CloudOMRError(code: "native_audio_preview_required", message: "请使用播放录音功能打开这段录音。")
        }
        guard (representation == "text") == (route.path.last == "musicxml") else { throw Self.invalidRequest() }
        var request = try makeRequest(route, method: method, identity: isPublic ? nil : identity)
        request.setValue(representation == "text" ? "application/vnd.recordare.musicxml+xml" : "application/json", forHTTPHeaderField: "Accept")
        if let expected = input["expectedUserId"] as? String { request.setValue(expected.lowercased(), forHTTPHeaderField: "X-NoteLite-Expected-User") }
        if let base64 = input["base64"] {
            guard route.path.count == 4, route.path[2] == "uploads", method == "PUT", input["body"] == nil,
                  let encoded = base64 as? String, encoded.count <= ((Self.maximumChunkBytes + 2) / 3) * 4,
                  let data = Data(base64Encoded: encoded), !data.isEmpty, data.count <= Self.maximumChunkBytes else { throw Self.invalidRequest() }
            let offset = try Self.integer(input["uploadOffset"], maximum: Self.maximumRecordingBytes)
            guard offset + data.count <= Self.maximumRecordingBytes else { throw Self.invalidRequest() }
            request.httpBody = data
            request.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
            request.setValue(String(offset), forHTTPHeaderField: "Upload-Offset")
        } else {
            guard input["uploadOffset"] == nil else { throw Self.invalidRequest() }
            if let body = input["body"] {
                guard method != "GET", JSONSerialization.isValidJSONObject(body) else { throw Self.invalidRequest() }
                var value = body
                if auth {
                    guard var object = body as? [String: Any], Set(object.keys).isSubset(of: ["username", "password", "mode", "deviceName"]) else { throw Self.invalidRequest() }
                    object["mode"] = "native"
                    value = object
                }
                if deleting {
                    guard let object = body as? [String: Any], Set(object.keys) == ["password", "confirmation"],
                          let password = object["password"] as? String, (15...256).contains(password.unicodeScalars.count),
                          password.utf8.count <= 1024, object["confirmation"] as? String == "DELETE_ACCOUNT" else { throw Self.invalidRequest() }
                }
                let data = try JSONSerialization.data(withJSONObject: value)
                guard data.count <= (auth || deleting ? 4096 : 24 * 1024 * 1024) else { throw Self.invalidRequest() }
                request.httpBody = data
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            } else if auth || deleting { throw Self.invalidRequest() }
        }
        if let etag = input["etag"] {
            guard let etag = etag as? String, route.path.count == 4, route.path[2] == "scores", method == "PUT",
                  etag.range(of: "^\"" + NSRegularExpression.escapedPattern(for: route.path[3]) + ":[1-9][0-9]{0,12}\"$", options: .regularExpression) != nil else { throw Self.invalidRequest() }
            request.setValue(etag, forHTTPHeaderField: "If-Match")
        }
        do {
            let (data, response) = try await session.data(for: request, delegate: AccountTransferDelegate(maximumBytes: 16 * 1024 * 1024))
            try Task.checkCancellation()
            if logout, (response as? HTTPURLResponse)?.statusCode == 401 {
                try removeIfCurrent(identity)
                return ["authenticated": false]
            }
            try Self.validate(response, data: data, accepted: auth ? [201] : deleting ? [200, 202] : method == "POST" ? [200, 201] : [200])
            guard data.count <= (representation == "text" ? 10 * 1024 * 1024 : 16 * 1024 * 1024) else { throw NoteLiteError.invalidResponse }
            try checkStillCurrent(identity)
            if representation == "text" {
                guard let text = String(data: data, encoding: .utf8), !text.isEmpty else { throw NoteLiteError.invalidResponse }
                return text
            }
            let result = try JSONSerialization.jsonObject(with: data)
            if auth {
                guard let object = result as? [String: Any], object["authenticated"] as? Bool == true,
                      object["kind"] as? String == "native", let token = object["token"] as? String,
                      let userID = object["userId"] as? String, let sessionID = object["sessionId"] as? String else { throw NoteLiteError.invalidResponse }
                let value = CloudAccountCredential(token: token, userID: userID.lowercased(), sessionID: sessionID.lowercased())
                try value.validate()
                try credentials.save(value, origin: configuration.key)
                return Self.publicIdentity(object)
            }
            if path == "/me" {
                guard let object = result as? [String: Any], object["authenticated"] as? Bool == true,
                      object["kind"] as? String == "native", (object["userId"] as? String)?.lowercased() == identity?.userID,
                      (object["sessionId"] as? String)?.lowercased() == identity?.sessionID else { throw NoteLiteError.invalidResponse }
                return Self.publicIdentity(object)
            }
            if deleting {
                guard Self.isAcceptedDeletion(result) else { throw NoteLiteError.invalidResponse }
                try removeIfCurrent(identity)
            }
            if logout || (method == "DELETE" && route.path == ["api", "account", "sessions", identity?.sessionID ?? ""]) { try removeIfCurrent(identity) }
            return result
        } catch {
            if method != "GET", Self.uncertainWrite(error) {
                throw CloudOMRError(code: "write_status_unknown", message: "提交结果尚未确认。请刷新最新状态后再操作。")
            }
            throw error
        }
    }

    private static func strictJSONBoolean(_ value: Any?) -> Bool? {
        guard let number = value as? NSNumber, CFGetTypeID(number) == CFBooleanGetTypeID() else { return nil }
        return number.boolValue
    }

    static func isAcceptedDeletion(_ result: Any) -> Bool {
        guard let value = result as? [String: Any], Self.strictJSONBoolean(value["authenticated"]) == false,
              Self.strictJSONBoolean(value["accountDeleted"]) == true, Self.strictJSONBoolean(value["deletionRequested"]) == true,
              let deleted = Self.strictJSONBoolean(value["deleted"]), value["status"] as? String == (deleted ? "completed" : "pending") else { return false }
        return true
    }

    func downloadAudio(submissionID: String, expectedUserID: Any? = nil) async throws -> CloudAccountAudioFile {
        let route = try Self.route(path: "/submissions/\(submissionID)/audio", method: "GET")
        guard let identity = try credential(), !changingAuthentication else { throw Self.unauthenticated() }
        try Self.checkExpectedUser(expectedUserID, identity: identity)
        var request = try makeRequest(route, method: "GET", identity: identity)
        request.setValue("audio/wav, audio/mpeg, audio/ogg, audio/mp4", forHTTPHeaderField: "Accept")
        request.setValue(identity.userID, forHTTPHeaderField: "X-NoteLite-Expected-User")
        let delegate = AccountTransferDelegate(maximumBytes: Self.maximumRecordingBytes)
        let temporary: URL
        let response: URLResponse
        do { (temporary, response) = try await session.download(for: request, delegate: delegate) }
        catch {
            if delegate.oversized { throw CloudOMRError(code: "file_too_large", message: "录音不能超过 100 MiB。") }
            throw error
        }
        defer { try? FileManager.default.removeItem(at: temporary) }
        try Self.validate(response, data: nil, accepted: [200])
        try Task.checkCancellation()
        try checkStillCurrent(identity)
        let size = try temporary.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        let handle = try FileHandle(forReadingFrom: temporary)
        defer { try? handle.close() }
        let header = try handle.read(upToCount: 16) ?? Data()
        let mime = response.mimeType?.lowercased() ?? ""
        let ext = try Self.audioExtension(mime: mime, header: header, size: size)
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("notelite-recording-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        let url = directory.appendingPathComponent("recording.\(ext)")
        do {
            try await Task.detached(priority: .userInitiated) { try FileManager.default.copyItem(at: temporary, to: url) }.value
            try Task.checkCancellation()
            try checkStillCurrent(identity)
        }
        catch { try? FileManager.default.removeItem(at: directory); throw error }
        return CloudAccountAudioFile(directory: directory, url: url, mime: mime)
    }

    static func audioExtension(mime: String, header: Data, size: Int) throws -> String {
        guard size > 0, size <= maximumRecordingBytes else { throw CloudOMRError(code: "file_too_large", message: "录音为空或超过 100 MiB。") }
        let bytes = [UInt8](header)
        switch mime {
        case "audio/wav":
            if bytes.count >= 12, String(bytes: bytes[0..<4], encoding: .ascii) == "RIFF", String(bytes: bytes[8..<12], encoding: .ascii) == "WAVE" { return "wav" }
        case "audio/mpeg":
            if bytes.count >= 3, String(bytes: bytes[0..<3], encoding: .ascii) == "ID3" { return "mp3" }
            if bytes.count >= 2, bytes[0] == 0xff, bytes[1] & 0xe0 == 0xe0 { return "mp3" }
        case "audio/ogg": if bytes.count >= 4, String(bytes: bytes[0..<4], encoding: .ascii) == "OggS" { return "ogg" }
        case "audio/mp4": if bytes.count >= 8, String(bytes: bytes[4..<8], encoding: .ascii) == "ftyp" { return "m4a" }
        default: break
        }
        throw CloudOMRError(code: "invalid_audio", message: "服务器返回的录音格式不正确。")
    }

    private func makeRequest(_ route: (path: [String], query: [URLQueryItem]), method: String, identity: CloudAccountCredential?) throws -> URLRequest {
        var components = URLComponents(url: configuration.endpoint(route.path), resolvingAgainstBaseURL: false)!
        if !route.query.isEmpty { components.queryItems = route.query }
        guard let url = components.url else { throw Self.invalidRequest() }
        var request = URLRequest(url: url)
        request.httpMethod = method
        if let identity { request.setValue("Bearer \(identity.token)", forHTTPHeaderField: "Authorization") }
        return request
    }
    private func checkStillCurrent(_ captured: CloudAccountCredential?) throws {
        guard try credential() == captured else { throw CloudOMRError(code: "identity_changed", message: "账号已切换，请重新打开当前内容。", status: 409) }
    }
    private func removeIfCurrent(_ captured: CloudAccountCredential?) throws {
        try checkStillCurrent(captured)
        try credentials.remove(origin: configuration.key)
    }
    private static func checkExpectedUser(_ value: Any?, identity: CloudAccountCredential?) throws {
        guard let value else { return }
        if value is NSNull { return }
        guard let expected = value as? String, UUID(uuidString: expected) != nil,
              expected.lowercased() == identity?.userID.lowercased() else {
            throw CloudOMRError(code: "identity_changed", message: "账号已切换，请刷新后再操作。", status: 409)
        }
    }
    private static func validate(_ response: URLResponse, data: Data?, accepted: Set<Int>) throws {
        do { try CloudOMRClient.validate(response, data: data, accepted: accepted) }
        catch let error as CloudOMRError where error.status == 401 {
            throw CloudOMRError(code: "unauthorized", message: "登录已失效，请重新登录。", status: 401)
        }
    }
    private static func uncertainWrite(_ error: Error) -> Bool {
        if let error = error as? CloudOMRError { return error.status.map { $0 >= 500 || $0 == 408 } ?? false }
        return true
    }
    private static func publicIdentity(_ object: [String: Any]) -> [String: Any] {
        var result: [String: Any] = [:]
        for key in ["authenticated", "kind", "userId", "username", "sessionId", "deviceName", "expiresAt"] { result[key] = object[key] }
        return result
    }
    static func integer(_ value: Any?, maximum: Int) throws -> Int {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue.isFinite, number.doubleValue.rounded() == number.doubleValue,
              number.doubleValue >= 0, number.doubleValue <= Double(maximum) else { throw invalidRequest() }
        return number.intValue
    }
    static func invalidRequest() -> CloudOMRError { CloudOMRError(code: "invalid_request", message: "账号请求参数无效。") }
    static func unauthenticated() -> CloudOMRError { CloudOMRError(code: "unauthorized", message: "请先登录账号。", status: 401) }
}

/// Incremental SHA-256 keeps only one ≤1 MiB chunk in memory and never crosses an account/session scope.
@MainActor
final class CloudAccountDigestStore {
    private struct Context {
        let scope: String
        let size: Int
        var offset = 0
        var hash = SHA256()
        var touched = Date()
    }
    private var contexts: [UUID: Context] = [:]
    func clear() { contexts.removeAll() }
    func clear(accountScope: String) {
        guard !accountScope.isEmpty else { return }
        contexts = contexts.filter { $0.value.scope != accountScope && !$0.value.scope.hasPrefix(accountScope + "|") }
    }
    var count: Int { contexts.count }
    func start(size: Any?, scope: String) throws -> [String: Any] {
        contexts = contexts.filter { Date().timeIntervalSince($0.value.touched) < 300 }
        let size = try CloudAccountClient.integer(size, maximum: CloudAccountClient.maximumRecordingBytes)
        guard size > 0, !scope.isEmpty, contexts.count < 4 else { throw CloudAccountClient.invalidRequest() }
        let id = UUID()
        contexts[id] = Context(scope: scope, size: size)
        return ["digestId": id.uuidString.lowercased()]
    }
    func update(id: String, base64: String, offset: Any?, scope: String) throws -> [String: Any] {
        let (key, existing) = try context(id, scope: scope)
        guard base64.count <= ((CloudAccountClient.maximumChunkBytes + 2) / 3) * 4,
              let data = Data(base64Encoded: base64), !data.isEmpty, data.count <= CloudAccountClient.maximumChunkBytes,
              try CloudAccountClient.integer(offset, maximum: existing.size) == existing.offset,
              existing.offset + data.count <= existing.size else { throw CloudAccountClient.invalidRequest() }
        var value = existing
        value.hash.update(data: data)
        value.offset += data.count
        value.touched = Date()
        contexts[key] = value
        return ["offset": value.offset]
    }
    func finish(id: String, scope: String) throws -> [String: Any] {
        let (key, value) = try context(id, scope: scope)
        guard value.offset == value.size else { throw CloudAccountClient.invalidRequest() }
        contexts.removeValue(forKey: key)
        return ["sha256": value.hash.finalize().map { String(format: "%02x", $0) }.joined()]
    }
    func cancel(id: String, scope: String) throws -> [String: Any] {
        let (key, _) = try context(id, scope: scope)
        contexts.removeValue(forKey: key)
        return ["cancelled": true]
    }
    private func context(_ id: String, scope: String) throws -> (UUID, Context) {
        guard let key = UUID(uuidString: id), let value = contexts[key], value.scope == scope,
              Date().timeIntervalSince(value.touched) < 300 else {
            throw CloudOMRError(code: "not_found", message: "录音校验已失效，请重新选择录音。", status: 404)
        }
        return (key, value)
    }
}
