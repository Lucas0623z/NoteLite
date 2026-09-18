import XCTest
@testable import NoteLite

final class NoteLiteTests: XCTestCase {
    func testServerOriginNormalization() throws {
        let configuration = try ServerConfiguration("  HTTPS://Scores.Example.com:443/  ")
        XCTAssertEqual(configuration.key, "https://scores.example.com")
        XCTAssertEqual(configuration.endpoint(["v1", "health"]).absoluteString,
                       "https://scores.example.com/v1/health")
        XCTAssertEqual(try ServerConfiguration("https://localhost:9443").baseURL.port, 9443)
    }

    func testRejectsPlaintextAndAmbiguousServerAddresses() {
        for input in ["http://localhost:8765", "file:///tmp/score", "https://",
                      "https://token@example.com", "https://example.com/api",
                      "https://example.com?token=secret", "https://example.com#fragment",
                      "https://example.com:65536"] {
            XCTAssertThrowsError(try ServerConfiguration(input), "Accepted \(input)")
        }
    }

    func testDecodesBridgeJobAndMusicArtifacts() throws {
        let data = Data("""
        {"id":"1096a6c1-32ce-4d06-a72f-e565700ecde2","state":"succeeded",
        "filename":"乐谱.pdf","error":null,"artifacts":[
        {"name":"01-score.mid","path":"/v1/jobs/1096a6c1-32ce-4d06-a72f-e565700ecde2/artifacts/01-score.mid"},
        {"name":"02-score.mxl","path":"/v1/jobs/1096a6c1-32ce-4d06-a72f-e565700ecde2/artifacts/02-score.mxl"}]}
        """.utf8)
        let job = try JSONDecoder().decode(RemoteJob.self, from: data)
        XCTAssertEqual(job.state, .succeeded)
        XCTAssertEqual(job.filename, "乐谱.pdf")
        XCTAssertNil(job.error)
        XCTAssertEqual(job.artifacts.map(\.name), ["01-score.mid", "02-score.mxl"])
    }

    func testArtifactFilenamesCannotEscapeOwnedDirectory() throws {
        for name in ["../secret", "..", ".", "/etc/passwd", "..\\secret", "bad\nname", ""] {
            XCTAssertThrowsError(try FileRules.validateFilename(name), "Accepted \(name)")
        }
        XCTAssertNoThrow(try FileRules.validateFilename("01-score.mxl"))
    }

    func testNewUploadAfterRemoteCleanupInvalidatesOldResultCache() {
        var record = ScoreRecord(id: UUID(), filename: "score.pdf", sourceName: "source.pdf", importedAt: Date())
        // A downloaded score whose remote job has already been cleaned still has local results.
        record.phase = .ready
        record.downloadedArtifacts = ["01-score.mid", "02-score.mxl"]
        XCTAssertNil(record.job)
        record.prepareForUpload(serverURL: "https://new.example.com")
        XCTAssertEqual(record.phase, .uploading)
        XCTAssertTrue(record.downloadedArtifacts.isEmpty,
                      "Same-named results from a new recognition must be downloaded again")
        XCTAssertEqual(record.serverURL, "https://new.example.com")
    }

    func testImportsOwnedCopyAndPersistsPendingRemoteJob() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let storage = try DocumentStorage(root: root.appendingPathComponent("library"))
        let source = root.appendingPathComponent("乐谱.pdf")
        let bytes = Data("%PDF-1.4\nowned-source-test".utf8)
        try bytes.write(to: source)
        var record = try storage.importFile(source)
        try FileManager.default.removeItem(at: source)
        XCTAssertEqual(try Data(contentsOf: storage.sourceURL(for: record)), bytes)
        record.job = RemoteJob(id: UUID(), state: .running, filename: record.filename,
                               error: nil, artifacts: [])
        record.phase = .running
        record.serverURL = "https://scores.example.com"
        try storage.save([record])
        XCTAssertEqual(try DocumentStorage(root: storage.root).load(), [record])
        XCTAssertThrowsError(try storage.artifactURL(name: "../outside", for: record))
    }

    func testCorruptManifestIsReportedWithoutOverwritingData() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let storage = try DocumentStorage(root: root)
        let manifest = root.appendingPathComponent("library.json")
        let bytes = Data("broken manifest".utf8)
        try bytes.write(to: manifest)
        XCTAssertThrowsError(try storage.load())
        XCTAssertEqual(try Data(contentsOf: manifest), bytes)
    }

    func testOversizeImportLeavesNoOwnedFile() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let storage = try DocumentStorage(root: root.appendingPathComponent("library"))
        let source = root.appendingPathComponent("too-large.pdf")
        try Data("%PDF-1.4".utf8).write(to: source)
        let handle = try FileHandle(forWritingTo: source)
        try handle.truncate(atOffset: UInt64(FileRules.maximumUploadBytes + 1))
        try handle.close()
        XCTAssertThrowsError(try storage.importFile(source))
        XCTAssertTrue(try FileManager.default.contentsOfDirectory(atPath: storage.root.path).isEmpty)
    }

    func testHTTPAuthAndRedirectFailuresAreNotSuccess() throws {
        let url = try XCTUnwrap(URL(string: "https://scores.example.com/v1/jobs"))
        for status in [301, 302, 401, 403, 409, 413, 500] {
            let response = try XCTUnwrap(HTTPURLResponse(url: url, statusCode: status,
                                                       httpVersion: nil, headerFields: nil))
            XCTAssertThrowsError(try NoteLiteAPI.validate(response, data: nil, accepted: [200]))
        }
        let deleted = try XCTUnwrap(HTTPURLResponse(url: url, statusCode: 204,
                                                   httpVersion: nil, headerFields: nil))
        XCTAssertNoThrow(try NoteLiteAPI.validate(deleted, data: nil, accepted: [204, 404]))
    }
}
