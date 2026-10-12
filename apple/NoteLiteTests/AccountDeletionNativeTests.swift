import XCTest
import AVFoundation
@testable import NoteLite

final class AccountDeletionNativeTests: XCTestCase {
    private let origin = "https://example.com"
    private let owner = "11111111-1111-4111-8111-111111111111"
    private let other = "22222222-2222-4222-8222-222222222222"
    private let sessionID = "33333333-3333-4333-8333-333333333333"
    override func tearDown() { DeletionResponseProtocol.reply = nil; super.tearDown() }

    private func identity() -> CloudAccountCredential {
        CloudAccountCredential(token: "deletion-test-only-native-token", userID: owner, sessionID: sessionID)
    }
    private func accepted(deleted: Bool) -> [String: Any] {
        ["authenticated": false, "accountDeleted": true, "deletionRequested": true,
         "deleted": deleted, "status": deleted ? "completed" : "pending"]
    }
    private func request() -> [String: Any] {
        ["path": "/account", "method": "DELETE", "response": "json",
         "body": ["password": "long-test-password-only", "confirmation": "DELETE_ACCOUNT"]]
    }
    private func temporaryFolder() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("notewise-delete-test-" + UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url
    }
    private func recordedTake(_ store: NoteWiseTakeStore, scope: String) throws -> String {
        let id = UUID().uuidString.lowercased()
        try store.register(id, scope: scope, inputKind: "microphone")
        try Data("test-recording-file".utf8).write(to: store.audioURL(id))
        return id
    }

    @MainActor func testMalformedOrFailedDeletionDoesNotRemoveCredentialsOrRecordings() async throws {
        let folder = try temporaryFolder(), takes = NoteWiseTakeStore(directory: folder)
        let id = try recordedTake(takes, scope: origin + "|" + owner)
        let credentials = DeletionTestCredentials(); credentials.value = identity()
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [DeletionResponseProtocol.self]
        let client = try CloudAccountClient(origin: origin, credentials: credentials, sessionConfiguration: configuration)
        var malformed = accepted(deleted: false); malformed["status"] = "completed"
        var numeric = accepted(deleted: false); numeric["authenticated"] = 0; numeric["deleted"] = 0
        let replies: [(Int, Any)] = [(403, ["error": "wrong_password"]), (503, ["error": "unavailable"]),
                                    (200, ["authenticated": false]), (202, malformed),
                                    (200, numeric), (201, accepted(deleted: true))]
        for reply in replies {
            DeletionResponseProtocol.reply = reply
            do { _ = try await client.request(request()); XCTFail("Unconfirmed deletion was accepted") }
            catch { XCTAssertEqual(credentials.value, identity()) }
            XCTAssertEqual(credentials.removals, 0)
            XCTAssertTrue(FileManager.default.fileExists(atPath: try takes.audioURL(id).path))
            XCTAssertTrue(try takes.pendingPurges().isEmpty)
        }
        let invalidReplies: [Any] = [NSNull(), accepted(deleted: false).merging(["authenticated": true]) { _, new in new }, malformed, numeric]
        for value in invalidReplies {
            XCTAssertFalse(CloudAccountClient.isAcceptedDeletion(value))
        }
    }

    @MainActor func testAcceptedPendingDeletionRemovesOnlyOriginalAccountAndItsDigests() async throws {
        let folder = try temporaryFolder(), takes = NoteWiseTakeStore(directory: folder)
        let scope = origin + "|" + owner
        let ownerTake = try recordedTake(takes, scope: scope)
        let guestTake = try recordedTake(takes, scope: origin + "|guest")
        let otherTake = try recordedTake(takes, scope: origin + "|" + other)
        let foreignOriginTake = try recordedTake(takes, scope: "https://another.example|" + owner)
        let credentials = DeletionTestCredentials(); credentials.value = identity()
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [DeletionResponseProtocol.self]
        DeletionResponseProtocol.reply = (202, accepted(deleted: false))
        let client = try CloudAccountClient(origin: origin, credentials: credentials, sessionConfiguration: configuration)
        let oldIdentity = try XCTUnwrap(client.credential())
        let reply = try await client.request(request())
        XCTAssertTrue(CloudAccountClient.isAcceptedDeletion(reply))
        XCTAssertNil(credentials.value); XCTAssertEqual(credentials.removals, 1)
        let digests = CloudAccountDigestStore()
        for suffix in ["|" + sessionID, "|44444444-4444-4444-8444-444444444444"] {
            _ = try digests.start(size: 1, scope: scope + suffix)
        }
        let survivingDigest = try digests.start(size: 1, scope: origin + "|" + other + "|session")["digestId"] as! String
        digests.clear(accountScope: origin + "|" + oldIdentity.userID)
        XCTAssertEqual(digests.count, 1)
        _ = try digests.cancel(id: survivingDigest, scope: origin + "|" + other + "|session")
        let capture = DeletionTestCapture()
        let session = NoteWiseSession(input: capture, recordingsDirectory: folder)
        let removed = try await session.deleteRecordings(accountScope: scope)
        XCTAssertEqual(removed, 1)
        XCTAssertFalse(FileManager.default.fileExists(atPath: try takes.audioURL(ownerTake).path))
        for id in [guestTake, otherTake, foreignOriginTake] {
            XCTAssertTrue(FileManager.default.fileExists(atPath: try takes.audioURL(id).path))
        }
        XCTAssertTrue(try takes.pendingPurges().isEmpty)
        do { _ = try session.recording(ownerTake, scope: scope); XCTFail("Deleted account recording was readable") }
        catch let error as CloudOMRError { XCTAssertEqual(error.code, "account_deleted") }
        credentials.value = identity()
        DeletionResponseProtocol.reply = (200, accepted(deleted: true))
        let completed = try await client.request(request())
        XCTAssertTrue(CloudAccountClient.isAcceptedDeletion(completed))
        XCTAssertNil(credentials.value); XCTAssertEqual(credentials.removals, 2)
    }

    @MainActor func testDeletingActiveCaptureWaitsForReaderAndPreservesNewGuestCapture() async throws {
        let folder = try temporaryFolder(), takes = NoteWiseTakeStore(directory: folder)
        let capture = DeletionTestCapture(), session = NoteWiseSession(input: capture, recordingsDirectory: folder)
        let scope = origin + "|" + owner, id = UUID().uuidString.lowercased()
        _ = try await session.start(["takeId": id, "inputKind": "microphone", "tuning": 440.0, "instrument": "piano"], scope: scope)
        let format = try XCTUnwrap(AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 44100, channels: 1, interleaved: false))
        let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 4096))
        buffer.frameLength = 4096
        for index in 0..<4096 { buffer.floatChannelData![0][index] = Float(sin(2 * Double.pi * 440 * Double(index) / 44100)) * 0.1 }
        let stalePCM = try XCTUnwrap(capture.onPCM)
        stalePCM(buffer, AVAudioTime(sampleTime: 0, atRate: 44100))

        let reading = expectation(description: "Native reader entered"), detached = expectation(description: "Owned capture detached")
        let barrier = DeletionReaderBarrier(started: reading)
        let reader = Task { await barrier.wait() }
        defer { barrier.finish() }
        await fulfillment(of: [reading], timeout: 2)
        capture.stopped = detached
        reader.cancel()
        let cleanup = Task { try await session.deleteRecordings(accountScope: scope, waitingFor: [reader]) }
        await fulfillment(of: [detached], timeout: 2)
        XCTAssertFalse(capture.active)
        XCTAssertEqual(try takes.pendingPurges(), [scope])
        let guestID = UUID().uuidString.lowercased()
        _ = try await session.start(["takeId": guestID, "inputKind": "midi", "tuning": 440.0], scope: origin + "|guest")
        XCTAssertTrue(capture.active)
        barrier.finish()
        let removed = try await cleanup.value
        XCTAssertEqual(removed, 1)
        try session.checkActive(guestID, scope: origin + "|guest")
        XCTAssertTrue(capture.active)
        XCTAssertFalse(FileManager.default.fileExists(atPath: try takes.audioURL(id).path))
        // An audio callback already copied by AVAudioEngine may arrive late.
        stalePCM(buffer, AVAudioTime(sampleTime: 4096, atRate: 44100))
        try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertFalse(FileManager.default.fileExists(atPath: try takes.audioURL(id).path))
        _ = await session.stop()
        XCTAssertTrue(FileManager.default.fileExists(atPath: folder.appendingPathComponent(guestID + ".json").path))
    }

    @MainActor func testPendingDeletionResumesAfterRelaunchAndOrdinaryStopKeepsRecordings() async throws {
        let folder = try temporaryFolder(), takes = NoteWiseTakeStore(directory: folder)
        let scope = origin + "|" + owner, id = try recordedTake(takes, scope: scope)
        let guest = try recordedTake(takes, scope: origin + "|guest")
        try takes.schedulePurge(scope: scope)
        let session = NoteWiseSession(input: DeletionTestCapture(), recordingsDirectory: folder)
        try await session.resumePendingAccountDeletions()
        XCTAssertFalse(FileManager.default.fileExists(atPath: try takes.audioURL(id).path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: try takes.audioURL(guest).path))
        let otherTake = try recordedTake(takes, scope: origin + "|" + other)
        _ = await session.stop()
        XCTAssertTrue(FileManager.default.fileExists(atPath: try takes.audioURL(otherTake).path))
        XCTAssertThrowsError(try takes.schedulePurge(scope: origin + "|guest"))
        do { _ = try await session.deleteRecordings(accountScope: origin + "|guest"); XCTFail("Guest purge was accepted") }
        catch { XCTAssertTrue(FileManager.default.fileExists(atPath: try takes.audioURL(guest).path)) }
        let guestID = UUID().uuidString.lowercased()
        _ = try await session.start(["takeId": guestID, "inputKind": "midi", "tuning": 440.0], scope: origin + "|guest")
        _ = await session.stop()
    }
}

private final class DeletionTestCredentials: CloudAccountCredentialStore {
    var value: CloudAccountCredential?
    var removals = 0
    func read(origin: String) throws -> CloudAccountCredential? { value }
    func save(_ value: CloudAccountCredential, origin: String) throws { self.value = value }
    func remove(origin: String) throws { value = nil; removals += 1 }
}

private final class DeletionResponseProtocol: URLProtocol {
    static var reply: (Int, Any)?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        guard let (status, value) = Self.reply, let url = request.url,
              let response = HTTPURLResponse(url: url, statusCode: status, httpVersion: "HTTP/1.1", headerFields: ["Content-Type": "application/json"]),
              let data = try? JSONSerialization.data(withJSONObject: value) else {
            client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse)); return
        }
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

@MainActor private final class DeletionTestCapture: NoteWiseCapturing {
    var onPCM: ((AVAudioPCMBuffer, AVAudioTime) -> Void)?
    var onMIDI: (([MIDIPerformanceEvent]) -> Void)?
    var onError: ((String) -> Void)?
    var active = false
    var stopped: XCTestExpectation?
    func start(_ mode: String) async throws { active = true }
    func stop() { active = false; stopped?.fulfill(); stopped = nil }
}

@MainActor private final class DeletionReaderBarrier {
    private let started: XCTestExpectation
    private var continuation: CheckedContinuation<Void, Never>?
    init(started: XCTestExpectation) { self.started = started }
    func wait() async {
        await withCheckedContinuation { continuation in self.continuation = continuation; started.fulfill() }
    }
    func finish() { continuation?.resume(); continuation = nil }
}
