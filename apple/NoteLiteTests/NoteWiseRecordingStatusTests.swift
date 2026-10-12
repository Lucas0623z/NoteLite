import XCTest
import AVFoundation
@testable import NoteLite

final class NoteWiseRecordingStatusTests: XCTestCase {
    private let origin = "https://124.221.211.156"
    private let owner = "e970e369-5860-40ad-89fa-604260ea97e1"
    private let other = "c7f7d28a-6698-49f6-9e6e-62a18c38dab0"

    private func directory() throws -> URL {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("notewise-status-" + UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false)
        addTeardownBlock { try? FileManager.default.removeItem(at: folder) }
        return folder
    }
    private func take(_ store: NoteWiseTakeStore, scope: String, kind: String = "microphone", audio: Bool = true) throws -> String {
        let id = UUID().uuidString.lowercased()
        try store.register(id, scope: scope, inputKind: kind)
        if audio { try Data("synthetic-local-audio".utf8).write(to: store.audioURL(id)) }
        return id
    }

    @MainActor func testLocalRecordingStatusSurvivesSessionRecreationButNotDeviceOrOwnerChange() throws {
        let folder = try directory(), store = NoteWiseTakeStore(directory: folder)
        let scope = origin + "|" + owner, id = try take(store, scope: scope)
        for _ in 0..<2 {
            let session = NoteWiseSession(recordingsDirectory: folder)
            let status = try session.recordingStatus(id.uppercased(), scope: scope)
            XCTAssertEqual(status["takeId"] as? String, id)
            XCTAssertEqual(status["available"] as? Bool, true)
            XCTAssertEqual(status["storage"] as? String, "device")
            XCTAssertNil(status["reason"])
            for foreign in [origin + "|" + other, origin + "|guest", "https://other.invalid|" + owner] {
                let unavailable = try session.recordingStatus(id, scope: foreign)
                XCTAssertEqual(unavailable["available"] as? Bool, false)
                XCTAssertEqual(unavailable["reason"] as? String, "not_on_this_device")
                XCTAssertNil(unavailable["scope"])
                XCTAssertNil(unavailable["path"])
                XCTAssertThrowsError(try session.recording(id, scope: foreign))
            }
        }
        let newDevice = NoteWiseSession(recordingsDirectory: try directory())
        let missing = try newDevice.recordingStatus(id, scope: scope)
        XCTAssertEqual(missing["available"] as? Bool, false)
        XCTAssertEqual(missing["reason"] as? String, "not_on_this_device")
    }

    @MainActor func testMissingAudioMIDIAndMalformedIdentifiersCannotBecomePlayableRecordings() throws {
        let folder = try directory(), store = NoteWiseTakeStore(directory: folder)
        let scope = origin + "|" + owner, session = NoteWiseSession(recordingsDirectory: folder)
        let absentAudio = try take(store, scope: scope, audio: false)
        let midi = try take(store, scope: scope, kind: "midi")
        let empty = try take(store, scope: scope)
        try Data().write(to: store.audioURL(empty))
        for id in [absentAudio, midi, empty, UUID().uuidString.lowercased()] {
            XCTAssertEqual(try session.recordingStatus(id, scope: scope)["available"] as? Bool, false)
        }
        for invalid in ["../another-owner.wav", "", "not-a-uuid"] {
            XCTAssertThrowsError(try session.recordingStatus(invalid, scope: scope))
        }
    }

    @MainActor func testPendingAccountDeletionBlocksStatusAndReadBeforeLocalPurgeFinishes() async throws {
        let folder = try directory(), store = NoteWiseTakeStore(directory: folder)
        let scope = origin + "|" + owner, id = try take(store, scope: scope)
        try store.schedulePurge(scope: scope)
        let session = NoteWiseSession(recordingsDirectory: folder)
        XCTAssertThrowsError(try session.recordingStatus(id, scope: scope)) {
            XCTAssertEqual(($0 as? CloudOMRError)?.status, 410)
        }
        XCTAssertThrowsError(try session.recording(id, scope: scope))
        try await session.resumePendingAccountDeletions()
        XCTAssertFalse(FileManager.default.fileExists(atPath: try store.audioURL(id).path))
        XCTAssertThrowsError(try session.recordingStatus(id, scope: scope))
    }

    @MainActor func testInProgressRecordingIsUnavailableWithoutRevealingAnotherOwnersCapture() async throws {
        let folder = try directory(), scope = origin + "|" + owner
        let session = NoteWiseSession(input: RecordingStatusTestCapture(), recordingsDirectory: folder)
        let id = UUID().uuidString.lowercased()
        _ = try await session.start(["takeId": id, "inputKind": "microphone", "tuning": 440.0, "instrument": "piano"], scope: scope)
        let pending = try session.recordingStatus(id, scope: scope)
        XCTAssertEqual(pending["available"] as? Bool, false)
        XCTAssertEqual(pending["reason"] as? String, "recording_in_progress")
        let foreign = try session.recordingStatus(id, scope: origin + "|" + other)
        XCTAssertEqual(foreign["available"] as? Bool, false)
        XCTAssertEqual(foreign["reason"] as? String, "not_on_this_device")
        _ = await session.stop()
    }

    @MainActor func testLocalAvailabilityNeverFollowsOwnershipOrAudioSymbolicLinks() throws {
        let folder = try directory(), store = NoteWiseTakeStore(directory: folder), scope = origin + "|" + owner
        let session = NoteWiseSession(recordingsDirectory: folder)
        let metadataID = try take(store, scope: scope)
        let metadata = folder.appendingPathComponent(metadataID + ".json")
        let moved = folder.appendingPathComponent("sidecar-target.json")
        try FileManager.default.moveItem(at: metadata, to: moved)
        try FileManager.default.createSymbolicLink(at: metadata, withDestinationURL: moved)
        XCTAssertEqual(try session.recordingStatus(metadataID, scope: scope)["available"] as? Bool, false)

        let audioID = try take(store, scope: scope), audio = try store.audioURL(audioID)
        let otherAudio = folder.appendingPathComponent("audio-target.wav")
        try FileManager.default.moveItem(at: audio, to: otherAudio)
        try FileManager.default.createSymbolicLink(at: audio, withDestinationURL: otherAudio)
        XCTAssertEqual(try session.recordingStatus(audioID, scope: scope)["available"] as? Bool, false)
        XCTAssertTrue(FileManager.default.fileExists(atPath: otherAudio.path))
    }
}

@MainActor private final class RecordingStatusTestCapture: NoteWiseCapturing {
    var onPCM: ((AVAudioPCMBuffer, AVAudioTime) -> Void)?
    var onMIDI: (([MIDIPerformanceEvent]) -> Void)?
    var onError: ((String) -> Void)?
    func start(_ mode: String) async throws {}
    func stop() {}
}
