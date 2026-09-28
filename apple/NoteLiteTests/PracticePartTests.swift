import XCTest
@testable import NoteLite

final class PracticePartTests: XCTestCase {
    private func temporaryDirectory() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url
    }

    private func xml(_ title: String, step: String) -> Data {
        Data("""
        <score-partwise version="4.0"><work><work-title>\(title)</work-title></work><part-list>
        <score-part id="P1"><part-name>Piano</part-name></score-part></part-list><part id="P1">
        <measure number="1"><attributes><divisions>1</divisions></attributes><note><pitch>
        <step>\(step)</step><octave>4</octave></pitch><duration>1</duration></note></measure></part></score-partwise>
        """.utf8)
    }

    @MainActor
    private func library() throws -> (LibraryStore, ScoreRecord, URL) {
        let root = try temporaryDirectory()
        let storage = try DocumentStorage(root: root.appendingPathComponent("library"))
        let original = root.appendingPathComponent("score.pdf")
        try Data("source fixture".utf8).write(to: original)
        var record = try storage.importFile(original)
        let artifacts = [EmbeddedArtifact(name: "score.mvt10.xml", data: xml("Ten", step: "G")),
                         EmbeddedArtifact(name: "score.mvt2.xml", data: xml("Two", step: "D")),
                         EmbeddedArtifact(name: "score.mvt1.xml", data: xml("One", step: "C")),
                         EmbeddedArtifact(name: "score.mid", data: Data("MThd".utf8))]
        try storage.installEmbeddedArtifacts(artifacts, for: record)
        record.downloadedArtifacts = artifacts.map(\.name) + ["zz-missing.xml"]
        record.phase = .ready
        try storage.save([record])
        return (LibraryStore(storageRoot: storage.root), record, root)
    }

    @MainActor
    func testEverySavedPartIsSelectableInNumericOrderWithoutChangingExports() async throws {
        let (store, record, _) = try library()
        let parts = store.practiceParts(record)
        XCTAssertEqual(parts.map(\.artifactName), ["score.mvt1.xml", "score.mvt2.xml", "score.mvt10.xml"])
        XCTAssertEqual(parts.map(\.title), ["第 1 部分", "第 2 部分", "第 3 部分"])
        XCTAssertEqual(try Data(contentsOf: parts[1].url), xml("Two", step: "D"))
        XCTAssertEqual(store.record(record.id)?.downloadedArtifacts, record.downloadedArtifacts)
        XCTAssertNotNil(store.artifactURL("score.mid", record: record))
        XCTAssertEqual(store.practicePart(record, artifactName: nil), parts.first)
        XCTAssertNil(store.practicePart(record, artifactName: "removed.xml"),
                     "History must not silently open a different surviving part")
        var legacy = record
        legacy.downloadedArtifacts = ["score.mvt2.xml", "score.mvt10.xml"]
        XCTAssertEqual(store.practicePart(legacy, artifactName: nil)?.artifactName, "score.mvt10.xml",
                       "Old history must retain the original lexical first-file behavior")
        legacy.downloadedArtifacts = ["missing.xml", "score.mvt2.xml"]
        XCTAssertNil(store.practicePart(legacy, artifactName: nil))
    }

    @MainActor
    func testSingleImportedMusicXMLKeepsOneDirectPracticeChoice() async throws {
        let root = try temporaryDirectory()
        let source = root.appendingPathComponent("one.musicxml")
        try xml("One", step: "C").write(to: source)
        let store = LibraryStore(storageRoot: root.appendingPathComponent("library"))
        let imported = await store.importFiles([source])
        let record = try XCTUnwrap(imported.flatMap(store.record))
        let part = try XCTUnwrap(store.practiceParts(record).first)
        XCTAssertEqual(store.practiceParts(record).count, 1)
        XCTAssertNil(part.title)
        XCTAssertNil(part.artifactName)
        XCTAssertEqual(part.url, store.sourceURL(record))
    }

    @MainActor
    func testRendererLoadsSelectedPartWhenScoreIdentityStaysTheSame() async throws {
        let (store, record, _) = try library()
        let parts = store.practiceParts(record)
        let controller = PracticeWebController()
        controller.open(score: record, url: parts[0].url, partID: parts[0].id)
        let firstIdentity = controller.source?.id
        controller.open(score: record, url: parts[1].url, partID: parts[1].id)
        XCTAssertNil(controller.errorMessage)
        XCTAssertNotEqual(controller.source?.id, firstIdentity)
        XCTAssertEqual(controller.source?.id, record.id.uuidString + "/" + parts[1].id)
        XCTAssertEqual(controller.source.flatMap { Data(base64Encoded: $0.data) }, xml("Two", step: "D"))
        controller.close()
    }

    @MainActor
    func testHistoryPersistsAndRestoresEachSelectedPart() async throws {
        let (store, score, root) = try library()
        let parts = store.practiceParts(score)
        let history = PracticeHistoryStore(root: root)
        history.save(report: ["title": "First", "errors": []], for: score, part: parts[0])
        history.save(report: ["title": "Second", "errors": []], for: score, part: parts[1])
        let restored = PracticeHistoryStore(root: root)
        XCTAssertNil(restored.errorMessage)
        XCTAssertEqual(restored.latest(for: score.id, part: parts[0])?.title, "First")
        let second = try XCTUnwrap(restored.latest(for: score.id, part: parts[1]))
        XCTAssertEqual(second.artifactName, "score.mvt2.xml")
        XCTAssertEqual(second.partTitle, "第 2 部分")
        XCTAssertEqual(store.practicePart(score, artifactName: second.artifactName), parts[1])
    }

    @MainActor
    func testLegacyPracticeHistoryWithoutPartMetadataStillLoads() async throws {
        let (store, score, root) = try library()
        let old = """
        [{"id":"A694E49D-64BF-40BA-B8D2-BE9E53D8F595","scoreID":"\(score.id)","title":"Old practice",
          "date":0,"durationSeconds":12,"completed":true,"measureCount":1,"errors":[]}]
        """
        try Data(old.utf8).write(to: root.appendingPathComponent("practice-history.json"))
        let history = PracticeHistoryStore(root: root)
        XCTAssertNil(history.errorMessage)
        let oldRecord = try XCTUnwrap(history.latest(for: score.id))
        XCTAssertNil(oldRecord.artifactName)
        XCTAssertNil(oldRecord.partTitle)
        XCTAssertEqual(store.practicePart(score, artifactName: oldRecord.artifactName), store.practiceParts(score).first)
    }
}
