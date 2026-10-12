import XCTest
@testable import NoteLite

final class FigmaLegalInformationTests: XCTestCase {
    private let commit = String(repeating: "a", count: 40)
    private let trusted = URL(string: "notelite-ui://app/index.html")!

    private func fixture() throws -> URL {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        let legal = root.appendingPathComponent("Legal", isDirectory: true)
        try FileManager.default.createDirectory(at: legal, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        let offer: [String: Any] = ["schemaVersion": 1, "repository": "https://github.com/Lucas0623z/NoteLite",
            "sourceCommit": commit, "sourceArchiveURL": "https://github.com/Lucas0623z/NoteLite/archive/\(commit).tar.gz"]
        try JSONSerialization.data(withJSONObject: offer).write(to: legal.appendingPathComponent("SOURCE-OFFER.json"))
        try Data("synthetic license fixture".utf8).write(to: legal.appendingPathComponent("AGPL-3.0-LICENSE.txt"))
        try Data("synthetic public notice".utf8).write(to: legal.appendingPathComponent("AUDIVERISCORE-NOTICE.md"))
        return root
    }

    func testPublicReadRequiresTrustedMainFrameAndEmptyPayloadWithoutAccount() {
        XCTAssertTrue(FigmaLegalInformation.permitsRead(isMainFrame: true, frameURL: trusted, pageURL: trusted, payload: [:]))
        XCTAssertFalse(FigmaLegalInformation.permitsRead(isMainFrame: false, frameURL: trusted, pageURL: trusted, payload: [:]))
        for text in ["https://github.com/Lucas0623z/NoteLite", "file:///tmp/private.json", "blob:notelite-ui://app/x",
                     "notelite-ui://evil/index.html", "notelite-ui://user@app/index.html", "notelite-ui://app:80/index.html"] {
            let url = URL(string: text)
            XCTAssertFalse(FigmaLegalInformation.permitsRead(isMainFrame: true, frameURL: url, pageURL: trusted, payload: [:]))
            XCTAssertFalse(FigmaLegalInformation.permitsRead(isMainFrame: true, frameURL: trusted, pageURL: url, payload: [:]))
        }
        for key in ["path", "filename", "url", "expectedUserId", "token"] {
            XCTAssertFalse(FigmaLegalInformation.permitsRead(isMainFrame: true, frameURL: trusted, pageURL: trusted, payload: [key: "anything"]))
        }
    }

    func testBoundedFixedBundleReaderDoesNotReturnManifestOrPrivateData() throws {
        let root = try fixture()
        try Data("private sample".utf8).write(to: root.appendingPathComponent("account.json"))
        let value = try FigmaLegalInformation.read(resources: root)
        XCTAssertEqual(Set(value.keys), ["sourceCommit", "sourceArchiveURL", "researchURL", "license", "notice"])
        XCTAssertEqual(value["sourceCommit"] as? String, commit)
        XCTAssertFalse(String(describing: value).contains("private sample"))
        for payload in [["path": "../account.json"], ["url": "https://example.invalid/private"], ["filename": "account.json"]] {
            XCTAssertThrowsError(try FigmaLegalInformation.read(resources: root, payload: payload))
        }
    }

    func testMalformedForeignMissingOversizeAndLinkedResourcesAreRejected() throws {
        let root = try fixture(), legal = root.appendingPathComponent("Legal")
        let offer = legal.appendingPathComponent("SOURCE-OFFER.json"), original = try Data(contentsOf: offer)
        func changedField(_ key: String, _ value: String) throws -> Data {
            var document = try XCTUnwrap(try JSONSerialization.jsonObject(with: original) as? [String: Any])
            document[key] = value
            return try JSONSerialization.data(withJSONObject: document)
        }
        // Foundation may escape URL slashes. Mutate parsed fields, never the
        // serialized spelling of "/archive/", which can leave valid JSON intact.
        let malformed: [(String, Data)] = [
            ("missing fields", Data("{}".utf8)), ("array", Data("[]".utf8)), ("invalid UTF-8", Data([0xff])),
            ("oversize offer", Data(repeating: 65, count: 256 * 1024 + 1)),
            ("foreign repository", try changedField("repository", "https://github.com/foreign/NoteLite")),
            ("tree instead of archive", try changedField("sourceArchiveURL", "https://github.com/Lucas0623z/NoteLite/tree/\(commit).tar.gz"))]
        for (label, data) in malformed {
            XCTAssertNotEqual(data, original, "The \(label) fixture must actually differ from the valid offer")
            try data.write(to: offer)
            XCTAssertThrowsError(try FigmaLegalInformation.read(resources: root), label)
        }
        try original.write(to: offer)
        let notice = legal.appendingPathComponent("AUDIVERISCORE-NOTICE.md")
        try Data(repeating: 65, count: 16 * 1024 + 1).write(to: notice)
        XCTAssertThrowsError(try FigmaLegalInformation.read(resources: root))
        try FileManager.default.removeItem(at: notice)
        XCTAssertThrowsError(try FigmaLegalInformation.read(resources: root))
        let external = root.appendingPathComponent("private.txt")
        try Data("not a bundled public notice".utf8).write(to: external)
        try FileManager.default.createSymbolicLink(at: notice, withDestinationURL: external)
        XCTAssertThrowsError(try FigmaLegalInformation.read(resources: root))
    }

    func testEscapedAndUnescapedJSONSlashesKeepTheSameStrictMetadataValidation() throws {
        let root = try fixture(), offer = root.appendingPathComponent("Legal").appendingPathComponent("SOURCE-OFFER.json")
        let document = try XCTUnwrap(try JSONSerialization.jsonObject(with: Data(contentsOf: offer)) as? [String: Any])
        let encodings: [JSONSerialization.WritingOptions] = [[], [.withoutEscapingSlashes]]
        for options in encodings {
            let original = try JSONSerialization.data(withJSONObject: document, options: options)
            try original.write(to: offer)
            XCTAssertEqual(try FigmaLegalInformation.read(resources: root)["sourceCommit"] as? String, commit)
            for (field, replacement) in [("repository", "https://github.com/foreign/NoteLite"),
                                          ("sourceArchiveURL", "https://github.com/Lucas0623z/NoteLite/tree/\(commit).tar.gz")] {
                var malformed = document
                malformed[field] = replacement
                let data = try JSONSerialization.data(withJSONObject: malformed, options: options)
                XCTAssertNotEqual(data, original, field)
                let decoded = try XCTUnwrap(try JSONSerialization.jsonObject(with: data) as? [String: Any])
                XCTAssertEqual(decoded[field] as? String, replacement, "Mutation must target the decoded metadata")
                try data.write(to: offer)
                XCTAssertThrowsError(try FigmaLegalInformation.read(resources: root), field)
            }
        }
    }

    func testOnlyFixedResearchAndExactCommitSourceArchiveCanOpenExternally() {
        XCTAssertEqual(FigmaLegalInformation.researchURL, "https://github.com/Lucas0623z/NoteLite/blob/codex/notewise-fusion-research/docs/NOTEWISE_ENGINE_RESEARCH.md")
        XCTAssertTrue(FigmaLegalInformation.isPublicSourceLink(URL(string: FigmaLegalInformation.researchURL)))
        XCTAssertTrue(FigmaLegalInformation.isPublicSourceLink(URL(string: "https://github.com/Lucas0623z/NoteLite/archive/\(commit).tar.gz")))
        for text in ["http://github.com/Lucas0623z/NoteLite/archive/\(commit).tar.gz",
                     "https://github.com/Lucas0623z/NoteLite/blob/main/docs/NOTEWISE_ENGINE_RESEARCH.md",
                     "https://github.com/Lucas0623z/NoteLite/archive/main.tar.gz",
                     "https://github.com/foreign/NoteLite/archive/\(commit).tar.gz",
                     "https://user@github.com/Lucas0623z/NoteLite/archive/\(commit).tar.gz",
                     "https://github.com:443/Lucas0623z/NoteLite/archive/\(commit).tar.gz",
                     "https://github.com/Lucas0623z/NoteLite/archive/\(commit).tar.gz?url=private",
                     "https://github.com/Lucas0623z/NoteLite/archive/\(commit).tar.gz#fragment",
                     "file:///tmp/recordings/private.wav", "https://124.221.211.156"] {
            XCTAssertFalse(FigmaLegalInformation.isPublicSourceLink(URL(string: text)), text)
        }
    }

    func testActualInstalledAppHasReadableFullLicenseNoticeAndCommitSourceOffer() throws {
        let value = try FigmaLegalInformation.read(resources: Bundle.main.resourceURL)
        XCTAssertEqual((value["sourceCommit"] as? String)?.count, 40)
        XCTAssertTrue(FigmaLegalInformation.isPublicSourceLink(URL(string: value["sourceArchiveURL"] as! String)))
        XCTAssertTrue((value["license"] as? String)?.contains("GNU AFFERO GENERAL PUBLIC LICENSE") == true)
        XCTAssertGreaterThan((value["license"] as? String)?.utf8.count ?? 0, 30000)
        XCTAssertTrue((value["notice"] as? String)?.contains("b02fd4f8e31bf3dee1124bf4956e60fcca7f00a0") == true)
    }
}
