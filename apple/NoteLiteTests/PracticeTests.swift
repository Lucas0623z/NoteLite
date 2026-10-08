import XCTest
@testable import NoteLite

final class PracticeTests: XCTestCase {
    func testMicrophoneWindowsOverlapAndKeepCaptureEndTimes() {
        let frames = MicrophoneFrames()
        let rate = 48000.0
        let input = (0..<8192).map { Float($0) }
        let windows = frames.append(input, sampleRate: rate, startTime: 100)
        XCTAssertEqual(windows.count, 5)
        for (index, frame) in windows.enumerated() {
            XCTAssertEqual(frame.samples.count, 4096)
            XCTAssertEqual(frame.samples.first, Float(index * 1024))
            XCTAssertEqual(frame.samples.last, Float(index * 1024 + 4095))
            XCTAssertEqual(frame.endTime, 100 + Double(index * 1024 + 4096) / rate, accuracy: 1e-9)
        }
        let next = frames.append((8192..<9216).map { Float($0) }, sampleRate: rate,
                                 startTime: 100 + 8192 / rate)
        XCTAssertEqual(next.count, 1)
        XCTAssertEqual(next.first?.samples.first, 5120)
        XCTAssertEqual(next.first?.endTime ?? 0, 100 + 9216 / rate, accuracy: 1e-9)
    }

    func testMicrophoneDoesNotJoinDifferentRatesOrMissingAudio() {
        let frames = MicrophoneFrames()
        XCTAssertTrue(frames.append(Array(repeating: 1, count: 2048), sampleRate: 48000,
                                    startTime: 10).isEmpty)
        // A missing interval must not contribute the preceding half-window.
        XCTAssertTrue(frames.append(Array(repeating: 2, count: 2048), sampleRate: 48000,
                                    startTime: 11).isEmpty)
        let changed = frames.append(Array(repeating: 3, count: 4096), sampleRate: 44100,
                                    startTime: 12)
        XCTAssertEqual(changed.count, 1)
        XCTAssertEqual(Set(changed[0].samples), [3])
        XCTAssertEqual(changed[0].endTime, 12 + 4096 / 44100.0, accuracy: 1e-9)
    }

    func testMIDIRunningStatusSurvivesSplitPacketsAndRealtimeBytes() {
        var parser = MIDINoteParser()
        XCTAssertEqual(parser.consume([0x92, 60]), [])
        XCTAssertEqual(parser.consume([0xF8, 100, 64, 0xFE]), [60])
        XCTAssertEqual(parser.consume([90, 67, 127]), [64, 67])
        // Velocity-zero Note On and real Note Off both mean release, not an attack.
        XCTAssertEqual(parser.consume([60, 0, 0x82, 64, 90, 67, 0]), [])
    }

    func testMIDISystemMessagesCancelRunningStatusWithoutCreatingNotes() {
        var parser = MIDINoteParser()
        XCTAssertEqual(parser.consume([0x90, 60, 90]), [60])
        XCTAssertEqual(parser.consume([0xF0, 0x7D, 60, 100]), [])
        XCTAssertEqual(parser.consume([0xF8, 64, 100, 0xF7, 67, 100]), [])
        XCTAssertEqual(parser.consume([0x90, 72, 0xF8, 80]), [72])
        // Song Position Pointer clears a previous channel message's running status.
        XCTAssertEqual(parser.consume([0xF2, 1, 2, 76, 90]), [])
        XCTAssertEqual(parser.consume([0x91, 76, 90]), [76])
    }

    func testMIDIChannelMessagesAndInterruptedNotesDoNotMisalignTheStream() {
        var parser = MIDINoteParser()
        // Program Change / Channel Pressure use one data byte; CC and pitch bend use two.
        XCTAssertEqual(parser.consume([0xC0, 10, 20, 0xD0, 70, 0xB0, 64, 127, 0xE0, 0, 64]), [])
        XCTAssertEqual(parser.consume([0x90, 60, 0x91, 65, 100, 69, 100]), [65, 69])
    }

    func testMusicXMLImportIsImmediatelyReadyAndKeepsAnOwnedCopy() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let storage = try DocumentStorage(root: root.appendingPathComponent("library"))
        let xml = Data("""
        <?xml version="1.0"?><score-partwise version="4.0"><part-list>
        <score-part id="P1"><part-name>Flute</part-name></score-part></part-list>
        <part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
        <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
        </measure></part></score-partwise>
        """.utf8)
        var records: [ScoreRecord] = []
        for ext in ["xml", "musicxml", "MUSICXML"] {
            let source = root.appendingPathComponent("score.\(ext)")
            try xml.write(to: source)
            let record = try storage.importFile(source)
            try FileManager.default.removeItem(at: source)
            XCTAssertTrue(record.isMusicXML)
            XCTAssertEqual(record.phase, .ready)
            XCTAssertNil(record.job)
            XCTAssertNil(record.serverURL)
            XCTAssertEqual(try Data(contentsOf: storage.sourceURL(for: record)), xml)
            records.append(record)
        }
        try storage.save(records)
        XCTAssertEqual(try DocumentStorage(root: storage.root).load(), records)
    }

    @MainActor
    func testHistoryRoundTripPreservesScoreIdentityAndPrintedMeasureLabels() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let score = ScoreRecord(id: UUID(), filename: "Flute.musicxml", sourceName: "source.musicxml", importedAt: Date())
        // Decode JSON so Foundation's NSNumber/NSNull representation matches WKScriptMessage.
        let report = try XCTUnwrap(JSONSerialization.jsonObject(with: Data("""
        {"title":"Minuet","durationSeconds":18.5,"completed":false,"measureCount":4,"errors":[
          {"kind":"wrong","index":0,"measure":2,"mi":1,"beat":1,"expected":[60],"played":61},
          {"kind":"missing","index":1,"measure":"2a","mi":2,"beat":1.5,"expected":[64,67]},
          {"kind":"intonation","index":2,"measure":null,"mi":3,"beat":2,"played":69,"cents":-42}
        ]}
        """.utf8)) as? [String: Any])
        let history = PracticeHistoryStore(root: root)
        history.save(report: report, for: score)
        XCTAssertNil(history.errorMessage)
        let saved = try XCTUnwrap(history.latest(for: score.id))
        XCTAssertEqual(saved.scoreID, score.id)
        XCTAssertEqual(saved.title, "Minuet")
        XCTAssertEqual(saved.durationSeconds, 18.5)
        XCTAssertFalse(saved.completed)
        XCTAssertEqual(saved.measureCount, 4)
        XCTAssertEqual(saved.errors.map(\.measure), ["2", "2a", "—"])
        XCTAssertEqual(saved.errors[1].expected, [64, 67])
        XCTAssertNil(saved.errors[1].played)
        XCTAssertEqual(saved.errors[2].cents, -42)
        let restored = PracticeHistoryStore(root: root)
        XCTAssertNil(restored.errorMessage)
        XCTAssertEqual(restored.records.count, 1)
        XCTAssertEqual(restored.records.first?.id, saved.id)
        XCTAssertEqual(restored.latest(for: score.id)?.errors.map(\.measure), ["2", "2a", "—"])
    }

    @MainActor
    func testHistoryRoundTripRetainsMetricsAndNumericResultMeasures() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let score = ScoreRecord(id: UUID(), filename: "Flute.musicxml", sourceName: "source.musicxml", importedAt: Date())
        let report = try XCTUnwrap(JSONSerialization.jsonObject(with: Data("""
        {"title":"Minuet","durationSeconds":18.5,"completed":true,"measureCount":2,
         "firstTryCorrect":1,"total":2,"input":"microphone","mode":"tempo","bpm":96,
         "scope":{"part":"P1","from":2,"to":3},"errors":[],"results":[
          {"index":0,"measure":2,"beat":1,"correct":1,"expected":1,"status":"correct"},
          {"index":1,"measure":"2a","beat":1.5,"correct":1,"expected":1,"status":"corrected"}]}
        """.utf8)) as? [String: Any])
        let history = PracticeHistoryStore(root: root)
        history.save(report: report, for: score)
        XCTAssertNil(history.errorMessage)
        let saved = try XCTUnwrap(PracticeHistoryStore(root: root).records.first)
        XCTAssertEqual(saved.firstTryCorrect, 1)
        XCTAssertEqual(saved.total, 2)
        XCTAssertEqual(saved.results?.map(\.measure), ["2", "2a"])
        XCTAssertEqual(saved.results?.map(\.status), ["correct", "corrected"])
        XCTAssertEqual(saved.input, "microphone")
        XCTAssertEqual(saved.mode, "tempo")
        XCTAssertEqual(saved.bpm, 96)
        XCTAssertEqual(saved.scope, PracticeScope(part: "P1", from: 2, to: 3))
    }

    @MainActor
    func testLegacyHistoryLoadsWithUnknownMetricsInsteadOfInventedAccuracy() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let scoreID = UUID(), recordID = UUID()
        let legacy: [[String: Any]] = [["id": recordID.uuidString, "scoreID": scoreID.uuidString,
            "title": "Old practice", "date": 100, "durationSeconds": 12,
            "completed": true, "measureCount": 3, "errors": []]]
        try JSONSerialization.data(withJSONObject: legacy).write(to: root.appendingPathComponent("practice-history.json"))
        let store = PracticeHistoryStore(root: root)
        XCTAssertNil(store.errorMessage)
        let record = try XCTUnwrap(store.records.first)
        XCTAssertEqual(record.id, recordID)
        XCTAssertEqual(record.scoreID, scoreID)
        XCTAssertNil(record.firstTryCorrect)
        XCTAssertNil(record.total)
        XCTAssertNil(record.results)
        XCTAssertNil(record.input)
        XCTAssertNil(record.scope)
    }

    @MainActor
    func testInvalidMetricsCannotReplaceSavedHistory() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let score = ScoreRecord(id: UUID(), filename: "score.xml", sourceName: "source.xml", importedAt: Date())
        let store = PracticeHistoryStore(root: root)
        store.save(report: ["errors": [], "firstTryCorrect": 1, "total": 2], for: score)
        let file = root.appendingPathComponent("practice-history.json")
        let original = try Data(contentsOf: file)
        store.save(report: ["errors": [], "firstTryCorrect": 3, "total": 2], for: score)
        XCTAssertNotNil(store.errorMessage)
        XCTAssertEqual(store.records.count, 1)
        XCTAssertEqual(try Data(contentsOf: file), original)
    }

    @MainActor
    func testHistoryDeleteAndClearPersistAndKeepMemoryOnWriteFailure() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let score = ScoreRecord(id: UUID(), filename: "score.xml", sourceName: "source.xml", importedAt: Date())
        let store = PracticeHistoryStore(root: root)
        store.save(report: ["errors": []], for: score)
        store.save(report: ["errors": []], for: score)
        let removed = try XCTUnwrap(store.records.first?.id)
        store.delete(id: removed)
        XCTAssertNil(store.errorMessage)
        XCTAssertEqual(PracticeHistoryStore(root: root).records.count, 1)
        let retained = try XCTUnwrap(store.records.first?.id)
        // Deterministically make the parent path a file; no permission assumptions.
        try FileManager.default.removeItem(at: root)
        try Data("not a directory".utf8).write(to: root)
        store.delete(id: retained)
        XCTAssertNotNil(store.errorMessage)
        XCTAssertEqual(store.records.map(\.id), [retained])
        store.clear()
        XCTAssertNotNil(store.errorMessage)
        XCTAssertEqual(store.records.map(\.id), [retained])
        try FileManager.default.removeItem(at: root)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        store.clear()
        XCTAssertNil(store.errorMessage)
        XCTAssertTrue(store.records.isEmpty)
        XCTAssertTrue(PracticeHistoryStore(root: root).records.isEmpty)
    }

    @MainActor
    func testMalformedHistoryReportCannotOverwritePreviouslySavedPractice() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let score = ScoreRecord(id: UUID(), filename: "score.xml", sourceName: "source.xml", importedAt: Date())
        let history = PracticeHistoryStore(root: root)
        history.save(report: ["completed": true, "durationSeconds": 12.0, "measureCount": 1, "errors": []], for: score)
        let file = root.appendingPathComponent("practice-history.json")
        let original = try Data(contentsOf: file)
        history.save(report: ["errors": [["kind": "wrong", "measure": "1"]]], for: score)
        XCTAssertNotNil(history.errorMessage)
        XCTAssertEqual(history.records.count, 1)
        XCTAssertEqual(try Data(contentsOf: file), original)
    }

    @MainActor
    func testCorruptHistoryIsReportedWithoutSilentlyReplacingTheFile() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let file = root.appendingPathComponent("practice-history.json")
        let original = Data("broken practice history".utf8)
        try original.write(to: file)
        let history = PracticeHistoryStore(root: root)
        XCTAssertNotNil(history.errorMessage)
        let score = ScoreRecord(id: UUID(), filename: "score.xml", sourceName: "source.xml", importedAt: Date())
        history.save(report: ["errors": []], for: score)
        XCTAssertTrue(history.records.isEmpty)
        XCTAssertEqual(try Data(contentsOf: file), original)
    }
}
