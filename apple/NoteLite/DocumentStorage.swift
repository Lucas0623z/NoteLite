import Foundation

/// Files in Application Support are owned by the app, so Files-provider bookmarks are unnecessary.
/// Immutable paths and FileManager are safe across threads; each import owns a unique UUID directory.
final class DocumentStorage: @unchecked Sendable {
    let root: URL
    private let fileManager: FileManager

    init(root: URL? = nil, fileManager: FileManager = .default) throws {
        self.fileManager = fileManager
        if let root {
            self.root = root
        } else {
            self.root = try fileManager.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                            appropriateFor: nil, create: true)
                .appendingPathComponent("NoteLite", isDirectory: true)
        }
        try fileManager.createDirectory(at: self.root, withIntermediateDirectories: true)
    }

    func load() throws -> [ScoreRecord] {
        let manifest = root.appendingPathComponent("library.json")
        guard fileManager.fileExists(atPath: manifest.path) else { return [] }
        let records = try JSONDecoder().decode([ScoreRecord].self, from: Data(contentsOf: manifest))
        guard Set(records.map(\.id)).count == records.count else { throw NoteLiteError.invalidResponse }
        for record in records {
            try FileRules.validateFilename(record.sourceName)
            for name in record.downloadedArtifacts { try FileRules.validateFilename(name) }
        }
        return records
    }

    func save(_ records: [ScoreRecord]) throws {
        let data = try JSONEncoder().encode(records)
        try data.write(to: root.appendingPathComponent("library.json"), options: [.atomic, .completeFileProtection])
    }

    func importFile(_ url: URL) throws -> ScoreRecord {
        let ext = url.pathExtension.lowercased()
        guard FileRules.supportedExtensions.contains(ext) else { throw NoteLiteError.invalidFile }
        try FileRules.validateFilename(url.lastPathComponent)
        let record = ScoreRecord(id: UUID(), filename: url.lastPathComponent,
                                 sourceName: "source.\(ext)", importedAt: Date())
        let folder = directory(for: record.id)
        try fileManager.createDirectory(at: folder, withIntermediateDirectories: true)
        do {
            let hasAccess = url.startAccessingSecurityScopedResource()
            defer { if hasAccess { url.stopAccessingSecurityScopedResource() } }
            var coordinationError: NSError?
            var copyError: Error?
            let coordinator = NSFileCoordinator(filePresenter: nil)
            coordinator.coordinate(readingItemAt: url, options: .withoutChanges,
                                   error: &coordinationError) { readableURL in
                do {
                    let size = try readableURL.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
                    guard size > 0 else { throw NoteLiteError.invalidFile }
                    guard size <= FileRules.maximumUploadBytes else { throw NoteLiteError.fileTooLarge }
                    try fileManager.copyItem(at: readableURL, to: sourceURL(for: record))
                } catch { copyError = error }
            }
            if let error = coordinationError { throw error }
            if let error = copyError { throw error }
            return record
        } catch {
            try? fileManager.removeItem(at: folder)
            throw error
        }
    }

    func sourceURL(for record: ScoreRecord) -> URL {
        directory(for: record.id).appendingPathComponent(record.sourceName)
    }

    func artifactURL(name: String, for record: ScoreRecord) throws -> URL {
        try FileRules.validateFilename(name)
        let folder = directory(for: record.id).appendingPathComponent("results", isDirectory: true)
        try fileManager.createDirectory(at: folder, withIntermediateDirectories: true)
        return folder.appendingPathComponent(name)
    }

    func remove(_ record: ScoreRecord) throws {
        let folder = directory(for: record.id)
        if fileManager.fileExists(atPath: folder.path) { try fileManager.removeItem(at: folder) }
    }

    private func directory(for id: UUID) -> URL {
        root.appendingPathComponent(id.uuidString, isDirectory: true)
    }
}
