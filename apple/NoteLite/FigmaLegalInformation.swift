import Foundation

/// Public installed notices only. This is not a general file or network reader.
enum FigmaLegalInformation {
    static let action = "legal/information"
    static let researchURL = "https://github.com/Lucas0623z/NoteLite/blob/codex/notewise-fusion-research/docs/NOTEWISE_ENGINE_RESEARCH.md"
    private static let repository = "https://github.com/Lucas0623z/NoteLite"

    static func permitsRead(isMainFrame: Bool, frameURL: URL?, pageURL: URL?, payload: [String: Any]) -> Bool {
        isMainFrame && FigmaResourceHandler.isTrusted(frameURL) && FigmaResourceHandler.isTrusted(pageURL) && payload.isEmpty
    }

    /// Only user-clicked public repository links may leave the local WKWebView.
    /// No URL supplied to the bridge is fetched or used as a resource path.
    static func isPublicSourceLink(_ url: URL?) -> Bool {
        guard let url, url.scheme == "https", url.host == "github.com", url.user == nil,
              url.password == nil, url.port == nil, url.query == nil, url.fragment == nil else { return false }
        if url.absoluteString == researchURL { return true }
        let prefix = repository + "/archive/", suffix = ".tar.gz"
        let value = url.absoluteString
        guard value.hasPrefix(prefix), value.hasSuffix(suffix) else { return false }
        let commit = String(value.dropFirst(prefix.count).dropLast(suffix.count))
        return exactCommit(commit) && value == prefix + commit + suffix
    }

    static func read(resources: URL?, payload: [String: Any] = [:]) throws -> [String: Any] {
        guard payload.isEmpty, let resources, resources.isFileURL else { throw unavailable() }
        do {
            let root = resources.standardizedFileURL.resolvingSymlinksInPath()
            let legal = root.appendingPathComponent("Legal", isDirectory: true)
            guard legal.resolvingSymlinksInPath().path == legal.path else { throw unavailable() }
            let offer = try readFixed("SOURCE-OFFER.json", maximum: 256 * 1024, root: legal)
            guard let encoded = offer.data(using: .utf8),
                  let document = try JSONSerialization.jsonObject(with: encoded) as? [String: Any],
                  document["schemaVersion"] as? Int == 1,
                  document["repository"] as? String == repository,
                  let commit = document["sourceCommit"] as? String, exactCommit(commit),
                  let archive = document["sourceArchiveURL"] as? String,
                  archive == repository + "/archive/" + commit + ".tar.gz",
                  isPublicSourceLink(URL(string: archive)) else { throw unavailable() }
            // Return a fixed small set of public strings, not the whole source
            // manifest or any arbitrary metadata/document supplied by a caller.
            return ["sourceCommit": commit, "sourceArchiveURL": archive, "researchURL": researchURL,
                    "license": try readFixed("AGPL-3.0-LICENSE.txt", maximum: 64 * 1024, root: legal),
                    "notice": try readFixed("AUDIVERISCORE-NOTICE.md", maximum: 16 * 1024, root: legal)]
        } catch { throw unavailable() }
    }

    private static func exactCommit(_ value: String) -> Bool {
        value.utf8.count == 40 && value.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) }
    }

    private static func readFixed(_ name: String, maximum: Int, root: URL) throws -> String {
        let file = root.appendingPathComponent(name)
        guard file.standardizedFileURL.path == file.path, file.resolvingSymlinksInPath().path == file.path else { throw unavailable() }
        let metadata = try file.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
        guard metadata.isRegularFile == true, let bytes = metadata.fileSize, bytes > 0, bytes <= maximum else { throw unavailable() }
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        guard let data = try handle.read(upToCount: maximum + 1), !data.isEmpty,
              data.count <= maximum, let text = String(data: data, encoding: .utf8) else { throw unavailable() }
        return text
    }

    private static func unavailable() -> CloudOMRError {
        CloudOMRError(code: "legal_information_unavailable", message: "此安装包的软件许可资料不可读取，请查看公开研究说明。")
    }
}
