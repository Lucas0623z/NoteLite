import Foundation

// A task-specific delegate also blocks redirects: bearer credentials never follow a new URL.
private final class TransferDelegate: NSObject, URLSessionTaskDelegate {
    let progress: @Sendable (Double) -> Void

    init(progress: @escaping @Sendable (Double) -> Void = { _ in }) {
        self.progress = progress
    }

    func urlSession(_ session: URLSession, task: URLSessionTask,
                    didSendBodyData bytesSent: Int64, totalBytesSent: Int64,
                    totalBytesExpectedToSend: Int64) {
        guard totalBytesExpectedToSend > 0 else { return }
        progress(min(1, Double(totalBytesSent) / Double(totalBytesExpectedToSend)))
    }

    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

final class NoteLiteAPI {
    let configuration: ServerConfiguration
    private let token: String
    private let session: URLSession

    init(configuration: ServerConfiguration, token: String,
         sessionConfiguration: URLSessionConfiguration = .ephemeral) {
        self.configuration = configuration
        self.token = token
        sessionConfiguration.timeoutIntervalForRequest = 60
        sessionConfiguration.timeoutIntervalForResource = 300
        sessionConfiguration.urlCache = nil
        session = URLSession(configuration: sessionConfiguration)
    }

    deinit { session.invalidateAndCancel() }

    func checkHealth() async throws {
        let request = URLRequest(url: configuration.endpoint(["v1", "health"]))
        let (data, response) = try await session.data(for: request, delegate: TransferDelegate())
        try Self.validate(response, data: data, accepted: [200])
        struct Health: Decodable { let status: String }
        guard try JSONDecoder().decode(Health.self, from: data).status == "ok" else {
            throw NoteLiteError.invalidResponse
        }
    }

    func upload(file: URL, filename: String,
                progress: @escaping @Sendable (Double) -> Void) async throws -> RemoteJob {
        let size = try file.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard size > 0 else { throw NoteLiteError.invalidFile }
        guard size <= FileRules.maximumUploadBytes else { throw NoteLiteError.fileTooLarge }
        var components = URLComponents(url: configuration.endpoint(["v1", "jobs"]), resolvingAgainstBaseURL: false)!
        components.queryItems = [URLQueryItem(name: "filename", value: filename)]
        // Python's query parser treats a literal '+' as a space.
        components.percentEncodedQuery = components.percentEncodedQuery?.replacingOccurrences(of: "+", with: "%2B")
        var request = try authenticatedRequest(components.url!)
        request.httpMethod = "POST"
        request.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
        request.setValue(String(size), forHTTPHeaderField: "Content-Length")
        let (data, response) = try await session.upload(
            for: request, fromFile: file, delegate: TransferDelegate(progress: progress)
        )
        try Self.validate(response, data: data, accepted: [202])
        return try JSONDecoder().decode(RemoteJob.self, from: data)
    }

    func job(_ id: UUID) async throws -> RemoteJob {
        let request = try authenticatedRequest(configuration.endpoint(["v1", "jobs", id.uuidString.lowercased()]))
        let (data, response) = try await session.data(for: request, delegate: TransferDelegate())
        try Self.validate(response, data: data, accepted: [200])
        let job = try JSONDecoder().decode(RemoteJob.self, from: data)
        guard job.id == id else { throw NoteLiteError.invalidResponse }
        return job
    }

    func deleteJob(_ id: UUID) async throws {
        var request = try authenticatedRequest(configuration.endpoint(["v1", "jobs", id.uuidString.lowercased()]))
        request.httpMethod = "DELETE"
        let (data, response) = try await session.data(for: request, delegate: TransferDelegate())
        // A job already removed by the server needs no further cleanup.
        try Self.validate(response, data: data, accepted: [204, 404])
    }

    func download(_ artifact: JobArtifact, jobID: UUID, to destination: URL) async throws {
        try FileRules.validateFilename(artifact.name)
        // Construct from the original origin and validated name, never from a server-provided URL.
        let url = configuration.endpoint(["v1", "jobs", jobID.uuidString.lowercased(), "artifacts", artifact.name])
        let request = try authenticatedRequest(url)
        let (temporary, response) = try await session.download(for: request, delegate: TransferDelegate())
        defer { try? FileManager.default.removeItem(at: temporary) }
        try Self.validate(response, data: nil, accepted: [200])
        try Task.checkCancellation()
        if FileManager.default.fileExists(atPath: destination.path) {
            _ = try FileManager.default.replaceItemAt(destination, withItemAt: temporary)
        } else {
            try FileManager.default.moveItem(at: temporary, to: destination)
        }
    }

    private func authenticatedRequest(_ url: URL) throws -> URLRequest {
        guard !token.isEmpty, !token.contains("\r"), !token.contains("\n") else {
            throw NoteLiteError.missingToken
        }
        var request = URLRequest(url: url)
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        return request
    }

    static func validate(_ response: URLResponse, data: Data?, accepted: Set<Int>) throws {
        guard let response = response as? HTTPURLResponse else { throw NoteLiteError.invalidResponse }
        guard accepted.contains(response.statusCode) else {
            switch response.statusCode {
            case 401, 403: throw NoteLiteError.server("访问令牌无效或无权访问，请检查服务器设置。")
            case 404: throw NoteLiteError.server("服务器找不到此任务或文件；任务可能已过期，请重新识别。")
            case 409: throw NoteLiteError.server("任务仍在服务器运行，请等待完成后再清理或重新提交。")
            case 413: throw NoteLiteError.fileTooLarge
            case 300...399: throw NoteLiteError.server("服务器返回了重定向，请直接填写最终 HTTPS 地址。")
            default:
                struct ErrorResponse: Decodable { let error: String }
                let message = data.flatMap { try? JSONDecoder().decode(ErrorResponse.self, from: $0).error }
                throw NoteLiteError.server(message ?? "服务器请求失败（HTTP \(response.statusCode)）。")
            }
        }
    }
}
