import Foundation

enum JobState: String, Codable {
    case queued, running, succeeded, failed
}

struct JobArtifact: Codable, Equatable {
    let name: String
    let path: String
}

struct RemoteJob: Codable, Equatable {
    let id: UUID
    let state: JobState
    let filename: String
    let error: String?
    let artifacts: [JobArtifact]
}

enum ScorePhase: String, Codable {
    case imported, uploading, queued, running, downloading, ready, failed

    var title: String {
        switch self {
        case .imported: return "待识别"
        case .uploading: return "正在上传"
        case .queued: return "等待服务器"
        case .running: return "正在识谱"
        case .downloading: return "正在下载"
        case .ready: return "识别完成"
        case .failed: return "需要重试"
        }
    }
}

struct ScoreRecord: Identifiable, Codable, Equatable {
    let id: UUID
    let filename: String
    let sourceName: String
    let importedAt: Date
    var phase: ScorePhase = .imported
    var job: RemoteJob?
    var serverURL: String?
    var downloadedArtifacts: [String] = []
    var lastError: String?
    var paused = false

    var isMusicXML: Bool { FileRules.musicXMLExtensions.contains((sourceName as NSString).pathExtension.lowercased()) }

    mutating func prepareForUpload(serverURL: String) {
        job = nil
        downloadedArtifacts = []
        phase = .uploading
        self.serverURL = serverURL
        lastError = nil
        paused = false
    }
}

struct ServerConfiguration: Equatable {
    let baseURL: URL

    init(_ input: String) throws {
        let value = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard var components = URLComponents(string: value),
              components.scheme?.lowercased() == "https",
              let host = components.host, !host.isEmpty,
              components.user == nil, components.password == nil,
              components.query == nil, components.fragment == nil,
              components.path.isEmpty || components.path == "/",
              components.port.map({ (1...65535).contains($0) }) ?? true else {
            throw NoteLiteError.invalidServer
        }
        components.scheme = "https"
        components.host = host.lowercased()
        components.path = ""
        if components.port == 443 { components.port = nil }
        guard let url = components.url else { throw NoteLiteError.invalidServer }
        baseURL = url
    }

    var key: String { baseURL.absoluteString }

    func endpoint(_ components: [String]) -> URL {
        components.reduce(baseURL) { $0.appendingPathComponent($1) }
    }
}

enum NoteLiteError: LocalizedError {
    case invalidServer
    case missingToken
    case invalidFile
    case fileTooLarge
    case unsafeArtifact
    case invalidResponse
    case server(String)
    case keychain(Int32)

    var errorDescription: String? {
        switch self {
        case .invalidServer:
            return "请输入 HTTPS 服务器地址，例如 https://scores.example.com，不要包含路径、用户名或查询参数。"
        case .missingToken: return "请先在服务器设置中保存访问令牌。"
        case .invalidFile: return "请导入 PDF、乐谱图片或 MusicXML（XML / MXL）文件。"
        case .fileTooLarge: return "单个文件不能超过 25 MiB。"
        case .unsafeArtifact: return "服务器返回了不安全的结果文件名。"
        case .invalidResponse: return "服务器返回的数据格式不正确。"
        case .server(let message): return message
        case .keychain(let status): return "无法访问安全存储（\(status)），请解锁设备后重试。"
        }
    }
}

enum FileRules {
    static let maximumUploadBytes = 25 * 1024 * 1024
    static let musicXMLExtensions: Set<String> = ["xml", "musicxml", "mxl"]
    static let supportedExtensions: Set<String> = Set(["pdf", "png", "jpg", "jpeg", "tif", "tiff"]).union(musicXMLExtensions)

    static func validateFilename(_ filename: String) throws {
        guard filename != ".", filename != "..", !filename.isEmpty,
              !filename.contains("/"), !filename.contains("\\"),
              !filename.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }) else {
            throw NoteLiteError.unsafeArtifact
        }
    }
}
