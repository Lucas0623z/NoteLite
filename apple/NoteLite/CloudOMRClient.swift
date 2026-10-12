import Foundation
import Security

/// The public gateway issues device credentials. The engine's administrator token never enters this app.
enum CloudDeviceTokenStore {
    private static let service = "com.notelite.figma.cloud-device-token"

    static func read(origin: String) throws -> String {
        var query = identity(origin)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return "" }
        guard status == errSecSuccess else { throw NoteLiteError.keychain(status) }
        guard let data = result as? Data, let value = String(data: data, encoding: .utf8) else {
            throw NoteLiteError.invalidResponse
        }
        return value
    }

    static func save(_ value: String, origin: String) throws {
        guard !value.isEmpty, value.count <= 4096,
              !value.unicodeScalars.contains(where: { CharacterSet.whitespacesAndNewlines.contains($0) }) else {
            throw NoteLiteError.invalidResponse
        }
        let identity = identity(origin)
        let values: [String: Any] = [
            kSecValueData as String: Data(value.utf8),
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        ]
        let status = SecItemUpdate(identity as CFDictionary, values as CFDictionary)
        if status == errSecItemNotFound {
            let item = identity.merging(values) { _, new in new }
            let status = SecItemAdd(item as CFDictionary, nil)
            guard status == errSecSuccess else { throw NoteLiteError.keychain(status) }
        } else if status != errSecSuccess { throw NoteLiteError.keychain(status) }
    }

    static func remove(origin: String) throws {
        let status = SecItemDelete(identity(origin) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw NoteLiteError.keychain(status) }
    }

    private static func identity(_ origin: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service, kSecAttrAccount as String: origin]
    }
}

struct CloudOMRError: LocalizedError {
    let code: String
    let message: String
    var status: Int? = nil
    var errorDescription: String? { message }

    var bridgeValue: [String: Any] {
        var value: [String: Any] = ["code": code, "message": message]
        if let status { value["status"] = status }
        return value
    }
}

private final class CloudTransferDelegate: NSObject, URLSessionTaskDelegate {
    let progress: @Sendable (Double) -> Void
    init(progress: @escaping @Sendable (Double) -> Void = { _ in }) { self.progress = progress }

    func urlSession(_ session: URLSession, task: URLSessionTask,
                    didSendBodyData bytesSent: Int64, totalBytesSent: Int64,
                    totalBytesExpectedToSend: Int64) {
        if totalBytesExpectedToSend > 0 { progress(min(1, Double(totalBytesSent) / Double(totalBytesExpectedToSend))) }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        // Never forward a device credential to a redirect destination.
        completionHandler(nil)
    }
}

final class CloudOMRClient {
    static let defaultOrigin = "https://124.221.211.156"
    static let maximumUploadBytes = 32 * 1024 * 1024
    private let configuration: ServerConfiguration
    private let token: String
    private let accountUserID: String?
    private let session: URLSession

    init(origin: String, token: String, accountToken: String? = nil, accountUserID: String? = nil,
         sessionConfiguration: URLSessionConfiguration = .ephemeral) throws {
        configuration = try ServerConfiguration(origin)
        // An expired account remains authoritative; never silently retry as a legacy device.
        self.token = accountToken ?? token
        self.accountUserID = accountUserID
        // Edits synchronously regenerate MIDI; the public proxy may wait 190 seconds.
        sessionConfiguration.timeoutIntervalForRequest = 240
        sessionConfiguration.timeoutIntervalForResource = 300
        sessionConfiguration.urlCache = nil
        sessionConfiguration.httpShouldSetCookies = false
        sessionConfiguration.httpCookieStorage = nil
        sessionConfiguration.httpCookieAcceptPolicy = .never
        sessionConfiguration.urlCredentialStorage = nil
        session = URLSession(configuration: sessionConfiguration)
    }

    deinit { session.invalidateAndCancel() }

    func health() async throws -> [String: Any] {
        try await json(method: "GET", path: ["api", "health"], authenticated: false)
    }

    func pair(code: String, deviceName: String) async throws -> [String: Any] {
        let code = code.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !code.isEmpty, code.count <= 1024, !code.contains("\n"), !code.contains("\r"),
              !deviceName.isEmpty, deviceName.count <= 120 else {
            throw CloudOMRError(code: "invalid_pairing", message: "请输入有效的设备配对码和设备名称。")
        }
        return try await json(method: "POST", path: ["api", "pair"],
                              body: ["code": code, "deviceName": deviceName, "mode": "native"], authenticated: false,
                              accepted: [201])
    }

    func sessionInfo() async throws -> [String: Any] { try await json(method: "GET", path: ["api", "session"]) }
    func logout() async throws { _ = try await json(method: "POST", path: ["api", "session", "logout"]) }
    func jobs() async throws -> Any { try await jsonValue(method: "GET", path: ["api", "jobs"]) }
    func job(_ id: String) async throws -> [String: Any] { try await json(method: "GET", path: jobPath(id)) }

    func upload(data: Data, filename: String,
                progress: @escaping @Sendable (Double) -> Void = { _ in }) async throws -> [String: Any] {
        try Self.validateUpload(data: data, filename: filename)
        var request = try request(method: "POST", path: ["api", "jobs"],
                                  query: [URLQueryItem(name: "filename", value: filename)])
        request.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
        request.setValue(String(data.count), forHTTPHeaderField: "Content-Length")
        let (responseData, response) = try await session.upload(for: request, from: data,
                                                               delegate: CloudTransferDelegate(progress: progress))
        try Self.validate(response, data: responseData, accepted: [202])
        return try Self.object(responseData)
    }

    func musicxml(jobID: String, score: Int) async throws -> String {
        let data = try await file(jobID: jobID, score: score, kind: "musicxml")
        guard let xml = String(data: data, encoding: .utf8), data.count <= 10 * 1024 * 1024 else {
            throw CloudOMRError(code: "invalid_score", message: "服务器返回了无效或过大的 MusicXML。")
        }
        return xml
    }

    func notes(jobID: String, score: Int) async throws -> [String: Any] {
        try await json(method: "GET", path: jobPath(jobID) + ["score", "notes"], query: scoreQuery(score))
    }

    func patchNotes(jobID: String, score: Int, revision: Int, edits: [[String: Any]]) async throws -> [String: Any] {
        guard revision > 0, edits.count <= 200, !edits.isEmpty else {
            throw CloudOMRError(code: "invalid_edit", message: "音符修改或修订号无效。")
        }
        do {
            let result = try await json(method: "PATCH", path: jobPath(jobID) + ["score", "notes"], query: scoreQuery(score),
                                        body: ["revision": revision, "score": score, "edits": edits])
            return try Self.writeResult(result, previousRevision: revision)
        } catch { throw Self.writeError(error) }
    }

    func replaceScore(jobID: String, score: Int, revision: Int, musicxml: String) async throws -> [String: Any] {
        let data = Data(musicxml.utf8)
        guard revision > 0, !data.isEmpty, data.count <= 10 * 1024 * 1024 else {
            throw CloudOMRError(code: "invalid_edit", message: "MusicXML 或修订号无效。")
        }
        var request = try request(method: "PUT", path: jobPath(jobID) + ["score"], query: scoreQuery(score))
        request.setValue("application/vnd.recordare.musicxml+xml", forHTTPHeaderField: "Content-Type")
        request.setValue("\"\(revision)\"", forHTTPHeaderField: "If-Match")
        request.httpBody = data
        do {
            let (result, response) = try await session.data(for: request, delegate: CloudTransferDelegate())
            try Self.validate(response, data: result, accepted: [200])
            return try Self.writeResult(Self.object(result), previousRevision: revision)
        } catch { throw Self.writeError(error) }
    }

    func file(jobID: String, score: Int, kind: String) async throws -> Data {
        var path = try jobPath(jobID)
        var query: [URLQueryItem] = []
        switch kind {
        case "musicxml", "midi": path += ["score", kind]; query = try scoreQuery(score)
        case "original": path += ["original"]
        case "omr": path += ["project", "omr"]
        case "log": path += ["log"]
        default: throw CloudOMRError(code: "invalid_file", message: "不支持的结果文件类型。")
        }
        let request = try request(method: "GET", path: path, query: query)
        let (temporary, response) = try await session.download(for: request, delegate: CloudTransferDelegate())
        defer { try? FileManager.default.removeItem(at: temporary) }
        try Self.validate(response, data: nil, accepted: [200])
        let size = try temporary.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard size > 0, size <= 64 * 1024 * 1024 else {
            throw CloudOMRError(code: "file_too_large", message: "结果文件为空或超过 64 MiB。")
        }
        return try Data(contentsOf: temporary)
    }

    static func validateUpload(data: Data, filename: String) throws {
        try FileRules.validateFilename(filename)
        let ext = (filename as NSString).pathExtension.lowercased()
        guard ["pdf", "png", "jpg", "jpeg", "xml", "musicxml", "mxl"].contains(ext), !data.isEmpty else {
            throw CloudOMRError(code: "invalid_file", message: "请选择 PDF、PNG、JPEG、MusicXML 或 MXL 文件。")
        }
        guard data.count <= maximumUploadBytes else {
            throw CloudOMRError(code: "file_too_large", message: "乐谱文件不能超过 32 MiB。")
        }
    }

    private static func writeError(_ error: Error) -> Error {
        if let value = error as? CloudOMRError {
            // Explicit rejection has a known outcome. A proxy/server failure or
            // malformed success body can arrive after the server committed a revision.
            if value.status == nil || (value.status! < 500 && value.status! != 408) { return value }
        }
        return CloudOMRError(code: "write_status_unknown", message: "保存结果尚未确认。请重新载入最新版本，确认是否已保存后再修改。")
    }

    private static func writeResult(_ result: [String: Any], previousRevision: Int) throws -> [String: Any] {
        guard let revision = result["revision"] as? Int, revision > previousRevision else {
            throw NoteLiteError.invalidResponse
        }
        return result
    }

    private func jobPath(_ id: String) throws -> [String] {
        guard let uuid = UUID(uuidString: id) else {
            throw CloudOMRError(code: "invalid_job", message: "识谱任务编号无效。")
        }
        return ["api", "jobs", uuid.uuidString.lowercased()]
    }

    private func scoreQuery(_ score: Int) throws -> [URLQueryItem] {
        guard (0..<64).contains(score) else { throw CloudOMRError(code: "invalid_score", message: "乐章编号无效。") }
        return [URLQueryItem(name: "score", value: String(score))]
    }

    private func request(method: String, path: [String], query: [URLQueryItem] = [], authenticated: Bool = true) throws -> URLRequest {
        var components = URLComponents(url: configuration.endpoint(path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty {
            components.queryItems = query
            components.percentEncodedQuery = components.percentEncodedQuery?.replacingOccurrences(of: "+", with: "%2B")
        }
        guard let url = components.url else { throw NoteLiteError.invalidServer }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if authenticated {
            guard !token.isEmpty, !token.contains("\r"), !token.contains("\n") else {
                throw CloudOMRError(code: "pairing_required", message: "请先使用设备配对码连接识谱服务。")
            }
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            if let accountUserID {
                guard UUID(uuidString: accountUserID) != nil else { throw NoteLiteError.invalidResponse }
                request.setValue(accountUserID.lowercased(), forHTTPHeaderField: "X-NoteLite-Expected-User")
            }
        }
        return request
    }

    private func json(method: String, path: [String], query: [URLQueryItem] = [],
                      body: [String: Any]? = nil, authenticated: Bool = true,
                      accepted: Set<Int> = [200]) async throws -> [String: Any] {
        guard let value = try await jsonValue(method: method, path: path, query: query, body: body,
                                             authenticated: authenticated, accepted: accepted) as? [String: Any] else {
            throw NoteLiteError.invalidResponse
        }
        return value
    }

    private func jsonValue(method: String, path: [String], query: [URLQueryItem] = [],
                           body: [String: Any]? = nil, authenticated: Bool = true,
                           accepted: Set<Int> = [200]) async throws -> Any {
        var request = try request(method: method, path: path, query: query, authenticated: authenticated)
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await session.data(for: request, delegate: CloudTransferDelegate())
        try Self.validate(response, data: data, accepted: accepted)
        guard data.count <= 16 * 1024 * 1024 else { throw NoteLiteError.invalidResponse }
        return try JSONSerialization.jsonObject(with: data)
    }

    private static func object(_ data: Data) throws -> [String: Any] {
        guard data.count <= 16 * 1024 * 1024,
              let value = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw NoteLiteError.invalidResponse
        }
        return value
    }

    static func validate(_ response: URLResponse, data: Data?, accepted: Set<Int>) throws {
        guard let response = response as? HTTPURLResponse else { throw NoteLiteError.invalidResponse }
        guard accepted.contains(response.statusCode) else {
            let status = response.statusCode
            let error = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            let fallback: String
            let code: String
            switch status {
            case 401, 403: code = "unauthorized"; fallback = "设备配对已失效或没有访问权限，请重新配对。"
            case 404: code = "not_found"; fallback = "找不到此任务或结果文件。"
            case 409: code = "revision_conflict"; fallback = "谱面已更新或正在处理，请刷新后再保存。"
            case 413: code = "file_too_large"; fallback = "文件超过服务器允许的大小。"
            case 300...399: code = "redirect_blocked"; fallback = "服务器地址发生重定向，请使用最终 HTTPS 地址。"
            default: code = "server_error"; fallback = "识谱服务请求失败（HTTP \(status)）。"
            }
            let message = (error?["error"] as? String) ?? fallback
            throw CloudOMRError(code: code, message: message, status: status)
        }
    }
}
