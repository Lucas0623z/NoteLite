import Foundation

struct EmbeddedArtifact: Sendable {
    let name: String
    let data: Data
}

protocol EmbeddedRecognizing: Sendable {
    var isAvailable: Bool { get }
    func recognize(source: URL) async throws -> [EmbeddedArtifact]
}

enum EmbeddedRecognitionError: LocalizedError {
    case unavailable, missingResources, invalidResult, failed(String)

    var errorDescription: String? {
        switch self {
        case .unavailable: return "当前构建尚未包含本地识谱引擎。"
        case .missingResources: return "应用内的识谱资源不完整，请重新安装完整版本。"
        case .invalidResult: return "本地识谱未生成有效的 MusicXML 和 MIDI 文件。"
        case .failed(let message): return "本地识谱失败：\(message)"
        }
    }
}

/// The same static JVM bridge used by the full iOS acceptance probe.
/// A single serial queue owns engine calls; Swift cancellation never kills a JVM thread.
final class EmbeddedRecognitionService: EmbeddedRecognizing, @unchecked Sendable {
    static let shared = EmbeddedRecognitionService()
    private let queue = DispatchQueue(label: "com.notelite.embedded-recognition", qos: .userInitiated)

    var isAvailable: Bool {
        #if EMBEDDED_OMR_RUNTIME
        return true
        #else
        return false
        #endif
    }

    func recognize(source: URL) async throws -> [EmbeddedArtifact] {
        #if EMBEDDED_OMR_RUNTIME
        let ticket = Ticket()
        return try await withTaskCancellationHandler {
            try Task.checkCancellation()
            return try await withCheckedThrowingContinuation { continuation in
                queue.async {
                    let finished = DispatchSemaphore(value: 0)
                    let worker = Thread {
                        defer { finished.signal() }
                        do {
                            try ticket.begin()
                            defer { ticket.finish() }
                            let artifacts = try self.run(source: source, cancellationCheck: ticket.checkCancellation)
                            try ticket.checkCancellation()
                            continuation.resume(returning: artifacts)
                        } catch {
                            continuation.resume(throwing: error)
                        }
                    }
                    // Zero interprets on native frames; dispatch worker stacks
                    // are too small for the complete recognition pipeline.
                    worker.name = "NoteLite embedded OMR"
                    worker.stackSize = 8 * 1024 * 1024
                    worker.qualityOfService = .userInitiated
                    worker.start()
                    finished.wait()
                }
            }
        } onCancel: {
            ticket.cancel()
        }
        #else
        throw EmbeddedRecognitionError.unavailable
        #endif
    }

    #if EMBEDDED_OMR_RUNTIME
    private func run(source: URL, cancellationCheck: () throws -> Void) throws -> [EmbeddedArtifact] {
        guard let resources = Bundle.main.url(forResource: "OMRResources", withExtension: nil),
              FileManager.default.fileExists(atPath: resources.appendingPathComponent("runtime/lib/modules").path)
        else { throw EmbeddedRecognitionError.missingResources }
        let files = FileManager.default
        let support = try files.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                    appropriateFor: nil, create: true)
        let sandbox = support.appendingPathComponent("NoteLiteEmbeddedEngine", isDirectory: true)
        let imported = sandbox.appendingPathComponent("inputs", isDirectory: true)
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try files.createDirectory(at: imported, withIntermediateDirectories: true)
        var safeToRemoveJobFiles = true
        defer { if safeToRemoveJobFiles { try? files.removeItem(at: imported) } }
        let prepared = try EmbeddedOMRInputPreparer.prepare(source: source, in: imported,
                                                            cancellationCheck: cancellationCheck)
        try cancellationCheck()
        // A timed-out worker may still own these files. Only a definitive
        // finished-job status permits removing them while this JVM is alive.
        safeToRemoveJobFiles = false
        let json = try EmbeddedJVM.recognize(resourceRoot: resources.path, sandbox: sandbox.path, input: prepared.url.path)
        let report = try JSONDecoder().decode(Report.self, from: Data(json.utf8))
        safeToRemoveJobFiles = ["SUCCESS", "FAILED", "CANCELLED"].contains(report.status)
        let output = URL(fileURLWithPath: report.outputDirectory).resolvingSymlinksInPath().standardizedFileURL
        let jobs = sandbox.appendingPathComponent("jobs", isDirectory: true).resolvingSymlinksInPath().standardizedFileURL
        guard Self.isDescendant(output, of: jobs) else { throw EmbeddedRecognitionError.invalidResult }
        defer { if safeToRemoveJobFiles { try? files.removeItem(at: output) } }
        if report.status == "CANCELLED" { throw CancellationError() }
        guard report.status == "SUCCESS" else {
            throw EmbeddedRecognitionError.failed(report.errors.joined(separator: "\n"))
        }
        return try Self.readArtifacts(report, inside: output)
    }

    private final class Ticket: @unchecked Sendable {
        private let lock = NSLock()
        private var cancelled = false
        private var running = false
        func begin() throws {
            lock.lock(); defer { lock.unlock() }
            if cancelled { throw CancellationError() }
            running = true
        }
        func finish() {
            lock.lock(); defer { lock.unlock() }
            running = false
        }
        func checkCancellation() throws {
            lock.lock(); defer { lock.unlock() }
            if cancelled { throw CancellationError() }
        }
        func cancel() {
            lock.lock(); defer { lock.unlock() }
            cancelled = true
            // Keep the lock until the bridge observes this job's cancellation.
            // The serial worker cannot finish and start another job in between.
            if running { EmbeddedJVM.cancelCurrentRecognition() }
        }
    }
    #endif

    struct Report: Decodable {
        let status: String
        let outputDirectory: String
        let musicXML: [String]
        let midi: [String]
        let errors: [String]
    }

    static func isDescendant(_ child: URL, of parent: URL) -> Bool {
        child.path.hasPrefix(parent.path + "/")
    }

    static func readArtifacts(_ report: Report, inside output: URL) throws -> [EmbeddedArtifact] {
        guard report.status == "SUCCESS", !report.musicXML.isEmpty, !report.midi.isEmpty else {
            throw EmbeddedRecognitionError.invalidResult
        }
        let root = output.resolvingSymlinksInPath().standardizedFileURL
        var names = Set<String>()
        var total = 0
        return try (report.musicXML + report.midi).enumerated().map { index, path in
            let url = URL(fileURLWithPath: path).resolvingSymlinksInPath().standardizedFileURL
            guard isDescendant(url, of: root) else { throw EmbeddedRecognitionError.invalidResult }
            let allowed = index < report.musicXML.count ? FileRules.musicXMLExtensions : Set(["mid"])
            guard allowed.contains(url.pathExtension.lowercased()) else { throw EmbeddedRecognitionError.invalidResult }
            let name = url.lastPathComponent
            try FileRules.validateFilename(name)
            guard names.insert(name.lowercased()).inserted else { throw EmbeddedRecognitionError.invalidResult }
            let values = try url.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
            guard values.isRegularFile == true, let size = values.fileSize, size > 0,
                  size <= 32 * 1024 * 1024 - total else { throw EmbeddedRecognitionError.invalidResult }
            total += size
            return EmbeddedArtifact(name: name, data: try Data(contentsOf: url))
        }
    }
}
