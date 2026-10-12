import XCTest
import AVFoundation
@testable import NoteLite

final class NoteWiseStopTailTests: XCTestCase {
    private let origin = "https://124.221.211.156"
    private func temporaryFolder() throws -> URL {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("notewise-tail-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        return folder
    }
    private func tone() throws -> AVAudioPCMBuffer {
        let format = try XCTUnwrap(AVAudioFormat(commonFormat: .pcmFormatFloat32,
            sampleRate: 44100, channels: 1, interleaved: false))
        let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 22050))
        buffer.frameLength = buffer.frameCapacity
        let values = try XCTUnwrap(buffer.floatChannelData?[0])
        for index in 0..<Int(buffer.frameLength) { values[index] = Float(.2 * sin(2 * Double.pi * 440 * Double(index) / 44100)) }
        return buffer
    }
    private func payload(_ id: String, kind: String = "microphone") -> [String: Any] {
        ["takeId":id,"inputKind":kind,"tuning":440.0,"instrument":"piano"]
    }

    @MainActor func testActualPCMOrdinaryStopDeliversOrderedFinalReleaseBeforeReturning() async throws {
        let folder = try temporaryFolder()
        defer { try? FileManager.default.removeItem(at: folder) }
        let capture = StopTailTestCapture(), session = NoteWiseSession(input: capture, recordingsDirectory: folder)
        let id = UUID().uuidString.lowercased(), scope = origin + "|guest"
        var messages: [[String: Any]] = []
        session.event = { messages.append($0) }
        _ = try await session.start(payload(id), scope: scope)
        capture.onPCM?(try tone(), AVAudioTime(sampleTime: 0, atRate: 44100))
        // No yield: the writer must process actual queued PCM and its final C
        // event before this stop returns, not rely on MainActor task ordering.
        let result = await session.stop()
        XCTAssertEqual(result["available"] as? Bool, true)
        XCTAssertEqual(result["sampleCount"] as? UInt64, 22050)
        let events = messages.compactMap { $0["event"] as? [String: Any] }
        let ons = events.filter { $0["type"] as? String == "on" }
        let offs = events.filter { $0["type"] as? String == "off" }
        XCTAssertEqual(ons.count, 1); XCTAssertEqual(offs.count, 1)
        XCTAssertEqual(ons.first?["eventId"] as? String, offs.first?["eventId"] as? String)
        XCTAssertEqual(offs.first?["reason"] as? String, "stop")
        XCTAssertEqual(offs.first?["releaseReliable"] as? Bool, false)
        XCTAssertEqual(events.last?["type"] as? String, "off")
        XCTAssertEqual(messages.compactMap { $0["sequence"] as? Int }, (0..<messages.count).map { $0 + 1 })
        XCTAssertTrue(messages.allSatisfy { $0["takeId"] as? String == id })
        let file = try session.recording(id, scope: scope)
        XCTAssertEqual(try AVAudioFile(forReading: file).length, 22050)
    }

    @MainActor func testActualPCMAbortDiscardsOldTailAndStaleStopPreservesNewGuestTake() async throws {
        try await detachedTailRace(deleteAccount: false)
    }
    @MainActor func testActualPCMAccountDeletionDiscardsOldTailAndStaleStopPreservesNewGuestTake() async throws {
        try await detachedTailRace(deleteAccount: true)
    }

    @MainActor private func detachedTailRace(deleteAccount: Bool) async throws {
        let folder = try temporaryFolder()
        defer { try? FileManager.default.removeItem(at: folder) }
        let queue = DispatchQueue(label: "notewise-tail-controlled-real-pcm")
        queue.suspend()
        var suspended = true
        defer { if suspended { queue.resume() } }
        let capture = StopTailTestCapture()
        let session = NoteWiseSession(input: capture, recordingsDirectory: folder, processingQueue: queue)
        let ownedScope = origin + "|" + UUID().uuidString.lowercased()
        let oldID = UUID().uuidString.lowercased(), guestID = UUID().uuidString.lowercased()
        var messages: [[String: Any]] = []
        session.event = { messages.append($0) }
        _ = try await session.start(payload(oldID), scope: ownedScope)
        let copiedPCM = try XCTUnwrap(capture.onPCM), buffer = try tone()
        copiedPCM(buffer, AVAudioTime(sampleTime: 0, atRate: 44100))
        let stopping = expectation(description: "Ordinary stop entered while native PCM queue is blocked")
        capture.stopped = stopping
        let oldStop = Task { await session.stop() }
        await fulfillment(of: [stopping], timeout: 2)
        let detaching = expectation(description: "Old owner detached before native queue drain")
        capture.stopped = detaching
        let detached = Task {
            if deleteAccount { _ = try await session.deleteRecordings(accountScope: ownedScope) }
            else { _ = await session.abort() }
        }
        await fulfillment(of: [detaching], timeout: 2)
        _ = try await session.start(payload(guestID, kind: "midi"), scope: origin + "|guest")
        XCTAssertTrue(capture.active)
        queue.resume(); suspended = false
        try await detached.value
        _ = await oldStop.value
        try session.checkActive(guestID, scope: origin + "|guest")
        XCTAssertTrue(capture.active, "An old suspended stop cannot stop the new owner's native input")
        XCTAssertTrue(messages.isEmpty, "The old native PCM tail cannot be delivered to the new owner")
        copiedPCM(buffer, AVAudioTime(sampleTime: 22050, atRate: 44100))
        await withCheckedContinuation { continuation in queue.async { continuation.resume() } }
        try session.checkActive(guestID, scope: origin + "|guest")
        XCTAssertTrue(messages.isEmpty, "An AVAudioEngine callback retained before detach cannot leak later")
        if deleteAccount {
            XCTAssertFalse(FileManager.default.fileExists(atPath: folder.appendingPathComponent(oldID + ".wav").path))
            XCTAssertFalse(FileManager.default.fileExists(atPath: folder.appendingPathComponent(oldID + ".json").path))
        } else {
            XCTAssertEqual(try AVAudioFile(forReading: session.recording(oldID, scope: ownedScope)).length, 22050)
        }
        _ = await session.stop()
    }
}

@MainActor private final class StopTailTestCapture: NoteWiseCapturing {
    var onPCM: ((AVAudioPCMBuffer, AVAudioTime) -> Void)?
    var onMIDI: (([MIDIPerformanceEvent]) -> Void)?
    var onError: ((String) -> Void)?
    var active = false
    var stopped: XCTestExpectation?
    func start(_ mode: String) async throws { active = true }
    func stop() { active = false; stopped?.fulfill(); stopped = nil }
}
