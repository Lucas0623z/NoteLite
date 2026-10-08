import Foundation
#if canImport(FoundationXML)
import FoundationXML
#endif
import zlib

// A task-specific delegate also blocks redirects: bearer credentials never follow a new URL.
private final class TransferDelegate: NSObject, URLSessionTaskDelegate, URLSessionDownloadDelegate {
    let progress: @Sendable (Double) -> Void
    let maximumDownloadBytes: Int?

    init(progress: @escaping @Sendable (Double) -> Void = { _ in }, maximumDownloadBytes: Int? = nil) {
        self.progress = progress
        self.maximumDownloadBytes = maximumDownloadBytes
    }

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask,
                    didWriteData bytesWritten: Int64, totalBytesWritten: Int64,
                    totalBytesExpectedToWrite: Int64) {
        if let maximumDownloadBytes,
           totalBytesWritten > Int64(maximumDownloadBytes) || totalBytesExpectedToWrite > Int64(maximumDownloadBytes) {
            downloadTask.cancel()
        }
    }

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {}

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

    func download(_ artifact: JobArtifact, jobID: UUID, to destination: URL,
                  maximumBytes: Int = CloudResultValidation.maximumJobBytes) async throws {
        try FileRules.validateFilename(artifact.name)
        guard maximumBytes > 0 else { throw NoteLiteError.server("识谱结果超过允许的大小。") }
        // Construct from the original origin and validated name, never from a server-provided URL.
        let url = configuration.endpoint(["v1", "jobs", jobID.uuidString.lowercased(), "artifacts", artifact.name])
        let request = try authenticatedRequest(url)
        let limit = FileRules.musicXMLExtensions.contains((artifact.name as NSString).pathExtension.lowercased())
            ? min(maximumBytes, CloudResultValidation.maximumPracticeBytes) : maximumBytes
        let (temporary, response) = try await session.download(for: request, delegate: TransferDelegate(maximumDownloadBytes: limit))
        defer { try? FileManager.default.removeItem(at: temporary) }
        try Self.validate(response, data: nil, accepted: [200])
        try Task.checkCancellation()
        let size = try temporary.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        let encoded = (response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Encoding")
        guard size > 0, size <= limit,
              encoded != nil || response.expectedContentLength < 0 || response.expectedContentLength == Int64(size) else {
            throw NoteLiteError.server("识谱结果为空、下载不完整或超过允许的大小。")
        }
        // Validate using the intended name before replacing an existing, usable result.
        _ = try CloudResultValidation.validateArtifact(at: temporary, named: artifact.name)
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

/// Same limits and supported score root as the bundled practice renderer.
/// ZIP entries are inspected in memory; no server-controlled paths are extracted.
enum CloudResultValidation {
    static let maximumPracticeBytes = 15 * 1024 * 1024
    static let maximumExpandedBytes = 30 * 1024 * 1024
    static let maximumJobBytes = 32 * 1024 * 1024

    static func validateManifest(_ artifacts: [JobArtifact]) throws {
        guard !artifacts.isEmpty, artifacts.count <= 128 else { throw invalid("结果文件列表为空或过多。") }
        var names = Set<String>()
        for artifact in artifacts {
            try FileRules.validateFilename(artifact.name)
            guard names.insert(artifact.name.lowercased()).inserted else { throw invalid("结果文件名重复。") }
        }
        guard artifacts.contains(where: {
            FileRules.musicXMLExtensions.contains(($0.name as NSString).pathExtension.lowercased())
        }) else { throw invalid("服务器没有提供可练习的 MusicXML 乐谱。") }
    }

    @discardableResult
    static func validateArtifact(at url: URL, named name: String? = nil) throws -> Int {
        let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard size > 0, size <= maximumJobBytes else { throw invalid("结果文件为空或超过 32 MiB。") }
        let ext = ((name ?? url.lastPathComponent) as NSString).pathExtension.lowercased()
        if FileRules.musicXMLExtensions.contains(ext) { try validateMusicXML(at: url) }
        return size
    }

    static func validateMusicXML(at url: URL) throws {
        let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard size > 0, size <= maximumPracticeBytes else { throw invalid("可练习的乐谱文件必须在 15 MiB 以内。") }
        try validateMusicXML(Data(contentsOf: url, options: .mappedIfSafe))
    }

    static func validateMusicXML(_ data: Data) throws {
        guard !data.isEmpty, data.count <= maximumPracticeBytes else { throw invalid("可练习的乐谱文件必须在 15 MiB 以内。") }
        let xml: Data
        if data.prefix(4) == Data([0x50, 0x4b, 0x03, 0x04]) {
            let archive = try ScoreZIP(data)
            guard archive.entries["META-INF/container.xml"] != nil else {
                throw invalid("压缩乐谱缺少 MusicXML container.xml。")
            }
            let container = XMLInspection()
            try container.read(archive.read("META-INF/container.xml"))
            guard container.root == "container", let path = container.rootFiles.first,
                  ["xml", "musicxml"].contains((path as NSString).pathExtension.lowercased()) else {
                throw invalid("压缩乐谱没有有效的 MusicXML 根文件。")
            }
            xml = try archive.read(path)
        } else { xml = data }
        let inspection = XMLInspection()
        try inspection.read(xml)
        guard inspection.root == "score-partwise", inspection.hasPart, inspection.hasMeasure,
              inspection.hasNote else { throw invalid("结果不是可练习的 MusicXML 乐谱，或没有音符和休止符。") }
    }

    private static func invalid(_ message: String) -> NoteLiteError { .server(message) }

    private final class XMLInspection: NSObject, XMLParserDelegate {
        var root: String?
        var hasPart = false
        var hasMeasure = false
        var hasNote = false
        var rootFiles: [String] = []
        private var rejected = false
        private var path: [String] = []
        func read(_ data: Data) throws {
            guard !data.isEmpty, data.count <= maximumExpandedBytes else { throw invalid("解压后的乐谱过大或为空。") }
            let parser = XMLParser(data: data)
            parser.delegate = self
            parser.shouldResolveExternalEntities = false
            parser.externalEntityResolvingPolicy = .never
            guard parser.parse(), !rejected else { throw invalid("乐谱 XML 格式损坏或包含不支持的实体声明。") }
        }
        func parser(_ parser: XMLParser, didStartElement elementName: String,
                    namespaceURI: String?, qualifiedName qName: String?, attributes: [String: String]) {
            if path.isEmpty { root = elementName }
            path.append(elementName)
            if path == ["score-partwise", "part"] { hasPart = true }
            if path == ["score-partwise", "part", "measure"] { hasMeasure = true }
            if path == ["score-partwise", "part", "measure", "note"] { hasNote = true }
            if path == ["container", "rootfiles", "rootfile"], let file = attributes["full-path"] { rootFiles.append(file) }
        }
        func parser(_ parser: XMLParser, didEndElement elementName: String, namespaceURI: String?, qualifiedName qName: String?) {
            if !path.isEmpty { path.removeLast() }
        }
        func parser(_ parser: XMLParser, foundInternalEntityDeclarationWithName name: String, value: String?) {
            rejected = true; parser.abortParsing()
        }
        func parser(_ parser: XMLParser, foundExternalEntityDeclarationWithName name: String, publicID: String?, systemID: String?) {
            rejected = true; parser.abortParsing()
        }
    }

    private struct ScoreZIP {
        struct Entry { let method: Int; let size: Int; let packed: Int; let offset: Int; let crc: UInt32 }
        let bytes: Data
        var entries: [String: Entry] = [:]
        var orderedNames: [String] = []
        init(_ data: Data) throws {
            bytes = data
            guard data.count >= 22 else { throw invalid("压缩乐谱格式损坏。") }
            func u16(_ offset: Int) -> Int { Int(data[offset]) | Int(data[offset + 1]) << 8 }
            func u32(_ offset: Int) -> Int { u16(offset) | u16(offset + 2) << 16 }
            let lower = max(0, data.count - 65557)
            guard let end = stride(from: data.count - 22, through: lower, by: -1).first(where: {
                u32($0) == 0x06054b50 && $0 + 22 + u16($0 + 20) == data.count
            }), u16(end + 4) == 0, u16(end + 6) == 0,
                  u16(end + 8) == u16(end + 10), (1...128).contains(u16(end + 10)) else {
                throw invalid("压缩乐谱缺少完整目录，或使用了不支持的格式。")
            }
            var cursor = u32(end + 16)
            let directoryEnd = cursor + u32(end + 12)
            guard cursor >= 0, directoryEnd == end else { throw invalid("压缩乐谱目录无效。") }
            var expanded = 0
            for _ in 0..<u16(end + 10) {
                guard cursor <= end - 46, u32(cursor) == 0x02014b50 else { throw invalid("压缩乐谱目录损坏。") }
                let flags = u16(cursor + 8), method = u16(cursor + 10)
                let packed = u32(cursor + 20), size = u32(cursor + 24)
                let nameBytes = u16(cursor + 28), extra = u16(cursor + 30), comment = u16(cursor + 32)
                let next = cursor + 46 + nameBytes + extra + comment
                guard next <= end, flags & 1 == 0, [0, 8].contains(method), u16(cursor + 34) == 0,
                      (u32(cursor + 38) >> 16) & 0xf000 != 0xa000,
                      let name = String(data: data.subdata(in: cursor + 46..<cursor + 46 + nameBytes), encoding: .utf8),
                      !name.isEmpty, !name.hasPrefix("/"), !name.contains("\\"), !name.contains(":"),
                      !name.split(separator: "/", omittingEmptySubsequences: false).contains(".."),
                      !name.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }),
                      entries[name] == nil,
                      !orderedNames.contains(where: { $0.lowercased() == name.lowercased() }),
                      size <= maximumExpandedBytes - expanded else { throw invalid("压缩乐谱包含不安全条目或解压后超过 30 MiB。") }
                expanded += size
                let offset = u32(cursor + 42)
                guard offset <= u32(end + 16) - 30, u32(offset) == 0x04034b50,
                      u16(offset + 6) == flags, u16(offset + 8) == method else { throw invalid("压缩乐谱文件头无效。") }
                let localNameSize = u16(offset + 26)
                let start = offset + 30 + localNameSize + u16(offset + 28)
                guard start <= u32(end + 16), packed <= u32(end + 16) - start,
                      data.subdata(in: offset + 30..<offset + 30 + localNameSize) == Data(name.utf8) else {
                    throw invalid("压缩乐谱文件不完整。")
                }
                entries[name] = Entry(method: method, size: size, packed: packed, offset: start, crc: UInt32(u32(cursor + 16)))
                orderedNames.append(name)
                cursor = next
            }
            guard cursor == directoryEnd else { throw invalid("压缩乐谱目录长度不正确。") }
        }
        func read(_ name: String) throws -> Data {
            guard let entry = entries[name], entry.size > 0 else { throw invalid("压缩乐谱缺少所声明的根文件。") }
            let input = bytes.subdata(in: entry.offset..<entry.offset + entry.packed)
            let result: Data
            if entry.method == 0 {
                guard entry.packed == entry.size else { throw invalid("压缩乐谱文件大小不正确。") }
                result = input
            } else {
                var stream = z_stream()
                guard inflateInit2_(&stream, -MAX_WBITS, ZLIB_VERSION, Int32(MemoryLayout<z_stream>.size)) == Z_OK else {
                    throw invalid("无法解压乐谱。")
                }
                defer { inflateEnd(&stream) }
                var output = Data(count: entry.size + 1)
                let status = input.withUnsafeBytes { source in
                    output.withUnsafeMutableBytes { destination -> Int32 in
                        stream.next_in = UnsafeMutablePointer<Bytef>(mutating: source.bindMemory(to: Bytef.self).baseAddress)
                        stream.avail_in = uInt(entry.packed)
                        stream.next_out = destination.bindMemory(to: Bytef.self).baseAddress
                        stream.avail_out = uInt(entry.size + 1)
                        return inflate(&stream, Z_FINISH)
                    }
                }
                guard status == Z_STREAM_END, Int(stream.total_out) == entry.size, Int(stream.total_in) == entry.packed else {
                    throw invalid("压缩乐谱数据损坏或解压大小不正确。")
                }
                output.removeLast()
                result = output
            }
            let checksum = result.withUnsafeBytes { crc32(0, $0.bindMemory(to: Bytef.self).baseAddress, uInt(result.count)) }
            guard UInt32(checksum) == entry.crc else { throw invalid("压缩乐谱校验失败，文件可能损坏。") }
            return result
        }
    }
}
