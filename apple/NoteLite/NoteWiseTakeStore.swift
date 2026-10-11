import Foundation

/// Each recording has a native ownership sidecar. Account deletion never follows
/// user supplied paths, recursively deletes a folder, or deletes another account.
struct NoteWiseTakeStore: Sendable {
    private static let diskLock = NSRecursiveLock()
    private let directory: URL?
    init(directory: URL? = nil) { self.directory = directory }

    func root() throws -> URL {
        let result: URL
        if let directory { result = directory }
        else {
            result = try FileManager.default.url(for: .applicationSupportDirectory,
                in: .userDomainMask, appropriateFor: nil, create: true)
                .appendingPathComponent("NoteLite/NoteWiseTakes", isDirectory: true)
        }
        try FileManager.default.createDirectory(at: result, withIntermediateDirectories: true)
        return result
    }
    func identifier(_ raw: String) throws -> String {
        guard let id = UUID(uuidString: raw) else { throw NoteLiteError.invalidResponse }
        return id.uuidString.lowercased()
    }
    func audioURL(_ raw: String) throws -> URL { try root().appendingPathComponent(identifier(raw) + ".wav") }

    func register(_ raw: String, scope: String, inputKind: String) throws {
        Self.diskLock.lock(); defer { Self.diskLock.unlock() }
        let id = try identifier(raw), root = try self.root()
        guard !scope.isEmpty, ["midi", "microphone"].contains(inputKind),
              !FileManager.default.fileExists(atPath: root.appendingPathComponent(id + ".json").path),
              !FileManager.default.fileExists(atPath: root.appendingPathComponent(id + ".wav").path) else {
            throw NoteLiteError.invalidResponse
        }
        let value: [String: Any] = ["takeId": id, "scope": scope, "inputKind": inputKind,
                                   "createdAt": ISO8601DateFormatter().string(from: Date())]
        try JSONSerialization.data(withJSONObject: value).write(to: root.appendingPathComponent(id + ".json"), options: .atomic)
    }
    func recording(_ raw: String, scope: String) throws -> URL {
        let id = try identifier(raw), root = try self.root()
        let value = try sidecar(root.appendingPathComponent(id + ".json"))
        guard value?["takeId"] as? String == id, value?["scope"] as? String == scope,
              value?["inputKind"] as? String == "microphone" else { throw NoteLiteError.invalidResponse }
        let url = root.appendingPathComponent(id + ".wav")
        let properties = try url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey])
        guard properties.isRegularFile == true, properties.isSymbolicLink != true else { throw NoteLiteError.invalidResponse }
        return url
    }

    private func marker() throws -> URL { try root().appendingPathComponent(".account-purges.json") }
    func checkAccountScope(_ scope: String) throws {
        guard let separator = scope.lastIndex(of: "|"), separator != scope.startIndex,
              UUID(uuidString: String(scope[scope.index(after: separator)...])) != nil else {
            throw NoteLiteError.invalidResponse
        }
    }
    func pendingPurges() throws -> Set<String> {
        Self.diskLock.lock(); defer { Self.diskLock.unlock() }
        let url = try marker()
        guard FileManager.default.fileExists(atPath: url.path) else { return [] }
        let data = try Data(contentsOf: url)
        guard data.count <= 1024 * 1024, let values = try JSONSerialization.jsonObject(with: data) as? [String] else { throw NoteLiteError.invalidResponse }
        for scope in values { try checkAccountScope(scope) }
        return Set(values)
    }
    /// Persist before awaiting capture/refinement shutdown so a force-quit can
    /// complete the accepted account deletion at the next application launch.
    func schedulePurge(scope: String) throws {
        Self.diskLock.lock(); defer { Self.diskLock.unlock() }
        try checkAccountScope(scope)
        var pending = try pendingPurges(); pending.insert(scope)
        try JSONSerialization.data(withJSONObject: pending.sorted()).write(to: marker(), options: .atomic)
    }
    @discardableResult
    func purge(scope: String) throws -> Int {
        Self.diskLock.lock(); defer { Self.diskLock.unlock() }
        try checkAccountScope(scope)
        let root = try self.root()
        let entries = try FileManager.default.contentsOfDirectory(at: root,
            includingPropertiesForKeys: [.isRegularFileKey, .isSymbolicLinkKey], options: [.skipsHiddenFiles])
        var removed = 0
        for url in entries where url.pathExtension == "json" {
            guard let id = UUID(uuidString: url.deletingPathExtension().lastPathComponent)?.uuidString.lowercased(),
                  url.lastPathComponent == id + ".json", let value = try sidecar(url),
                  value["takeId"] as? String == id, value["scope"] as? String == scope,
                  ["microphone", "midi"].contains(value["inputKind"] as? String ?? "") else { continue }
            let audio = root.appendingPathComponent(id + ".wav")
            // Removing this fixed sibling also removes a symbolic link itself;
            // its target is never opened or traversed.
            if FileManager.default.fileExists(atPath: audio.path) { try FileManager.default.removeItem(at: audio) }
            try FileManager.default.removeItem(at: url)
            removed += 1
        }
        var pending = try pendingPurges(); pending.remove(scope)
        if pending.isEmpty {
            let url = try marker()
            if FileManager.default.fileExists(atPath: url.path) { try FileManager.default.removeItem(at: url) }
        } else { try JSONSerialization.data(withJSONObject: pending.sorted()).write(to: marker(), options: .atomic) }
        return removed
    }
    private func sidecar(_ url: URL) throws -> [String: Any]? {
        let properties = try url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
        guard properties.isRegularFile == true, properties.isSymbolicLink != true,
              (properties.fileSize ?? Int.max) <= 64 * 1024 else { return nil }
        return try? JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any]
    }
}
