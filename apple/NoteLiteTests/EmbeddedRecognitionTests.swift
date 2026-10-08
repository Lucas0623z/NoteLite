import XCTest
@testable import NoteLite

final class EmbeddedRecognitionTests: XCTestCase {
    func testCancellationBeforeWorkerEntryIsRetained() {
        let ticket = EmbeddedRecognitionService.Ticket()
        ticket.cancel()
        XCTAssertThrowsError(try ticket.checkCancellation()) { error in
            XCTAssertTrue(error is CancellationError)
        }
        XCTAssertThrowsError(try ticket.checkCancellation())
    }

    func testLateCancellationCannotAffectTheFollowingRequest() throws {
        let old = EmbeddedRecognitionService.Ticket()
        try old.checkCancellation()
        let next = EmbeddedRecognitionService.Ticket()
        old.cancel()
        XCTAssertThrowsError(try old.checkCancellation())
        try next.checkCancellation()
        old.cancel()
        try next.checkCancellation()
    }

    private func temporaryDirectory() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url
    }

    func testOldLibraryManifestStillDecodesWithoutRecognitionLocation() throws {
        let json = """
        [{"id":"1096a6c1-32ce-4d06-a72f-e565700ecde2","filename":"score.png","sourceName":"source.png",
          "importedAt":0,"phase":"imported","downloadedArtifacts":[],"paused":false}]
        """
        let records = try JSONDecoder().decode([ScoreRecord].self, from: Data(json.utf8))
        XCTAssertNil(records.first?.recognitionLocation)
    }

    func testEmbeddedExportsRejectEscapedFilesAndMissingMidi() throws {
        let root = try temporaryDirectory()
        let job = root.appendingPathComponent("job")
        try FileManager.default.createDirectory(at: job, withIntermediateDirectories: true)
        let outside = root.appendingPathComponent("outside.mxl")
        let midi = job.appendingPathComponent("score.mid")
        try Data([1]).write(to: outside)
        try Data([2]).write(to: midi)
        let escaped = EmbeddedRecognitionService.Report(status: "SUCCESS", outputDirectory: job.path,
                                                         musicXML: [outside.path], midi: [midi.path], errors: [])
        XCTAssertThrowsError(try EmbeddedRecognitionService.readArtifacts(escaped, inside: job))
        let missing = EmbeddedRecognitionService.Report(status: "SUCCESS", outputDirectory: job.path,
                                                         musicXML: [outside.path], midi: [], errors: [])
        XCTAssertThrowsError(try EmbeddedRecognitionService.readArtifacts(missing, inside: job))
    }

    func testFailedArtifactInstallationKeepsPreviousResults() throws {
        let root = try temporaryDirectory()
        let storage = try DocumentStorage(root: root)
        let record = ScoreRecord(id: UUID(), filename: "score.png", sourceName: "source.png", importedAt: Date())
        try storage.installEmbeddedArtifacts(Self.artifacts, for: record)
        let previous = try Data(contentsOf: storage.artifactURL(name: "score.mxl", for: record))
        let malformed = [EmbeddedArtifact(name: "../escape.mxl", data: Data([0])),
                         EmbeddedArtifact(name: "score.mid", data: Data([0]))]
        XCTAssertThrowsError(try storage.installEmbeddedArtifacts(malformed, for: record))
        XCTAssertEqual(try Data(contentsOf: storage.artifactURL(name: "score.mxl", for: record)), previous)
    }

    @MainActor
    func testLibraryUsesAvailableEmbeddedEngineWithoutServerConfiguration() async throws {
        let root = try temporaryDirectory()
        let source = root.appendingPathComponent("scan.png")
        try Data([1, 2, 3]).write(to: source)
        let suite = "EmbeddedRecognitionTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let engine = StubEngine()
        let library = LibraryStore(defaults: defaults, storageRoot: root.appendingPathComponent("library"),
                                   localRecognizer: engine)
        XCTAssertFalse(library.isConfigured)
        #if os(iOS)
        XCTAssertFalse(library.hasLocalEngine, "Mobile must use cloud OMR even when the legacy engine is linked")
        XCTAssertFalse(library.canRecognize)
        let imported = await library.importFiles([source])
        let id = try XCTUnwrap(imported)
        library.start(id)
        XCTAssertNotNil(library.errorMessage)
        let calls = await engine.calls
        XCTAssertEqual(calls, 0)
        #else
        XCTAssertTrue(library.canRecognize)
        let imported = await library.importFiles([source])
        let id = try XCTUnwrap(imported)
        library.start(id)
        for _ in 0..<300 where library.activeIDs.contains(id) {
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        let record = try XCTUnwrap(library.record(id))
        XCTAssertEqual(record.phase, .ready, record.lastError ?? "")
        XCTAssertEqual(record.recognitionLocation, .device)
        XCTAssertNil(record.job)
        XCTAssertNil(record.serverURL)
        XCTAssertEqual(record.downloadedArtifacts.sorted(), ["score.mid", "score.mxl"])
        XCTAssertNotNil(library.practiceURL(record))
        let calls = await engine.calls
        XCTAssertEqual(calls, 1)
        let restored = LibraryStore(defaults: defaults, storageRoot: root.appendingPathComponent("library"),
                                   localRecognizer: engine)
        XCTAssertEqual(restored.record(id)?.phase, .ready)
        #endif
    }

    func testInterruptedLocalRecognitionRetainsOldResultMetadata() {
        var record = ScoreRecord(id: UUID(), filename: "score.png", sourceName: "source.png", importedAt: Date())
        record.downloadedArtifacts = ["old.mxl", "old.mid"]
        record.prepareForLocalRecognition()
        XCTAssertEqual(record.phase, .running)
        XCTAssertEqual(record.downloadedArtifacts, ["old.mxl", "old.mid"])
        XCTAssertNil(record.job)
        XCTAssertNil(record.serverURL)
    }

    // These test orchestration and persistence. Real recognition is separately
    // required by EmbeddedOMRProbe and its MusicXML/MIDI semantic comparison.
    private static let artifacts = [EmbeddedArtifact(name: "score.mxl", data: Data([80, 75, 3, 4])),
                                    EmbeddedArtifact(name: "score.mid", data: Data("MThd".utf8))]
    private actor StubEngine: EmbeddedRecognizing {
        nonisolated let isAvailable = true
        private(set) var calls = 0
        func recognize(source: URL) async throws -> [EmbeddedArtifact] {
            XCTAssertTrue(FileManager.default.fileExists(atPath: source.path))
            calls += 1
            return EmbeddedRecognitionTests.artifacts
        }
    }
}
