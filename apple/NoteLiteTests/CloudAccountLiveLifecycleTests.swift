import XCTest
import CryptoKit
@testable import NoteLite

/// Explicit CI acceptance, using synthetic data and the unchanged production TLS/Keychain client.
/// This is not a musician recording, physical MIDI test, or an application relaunch test.
final class CloudAccountLiveLifecycleTests: XCTestCase {
    private let origin = "https://124.221.211.156"

    @MainActor func testActualTrustedTLSKeychainSyncHistoryAndPermanentDeletion() async throws {
        guard ProcessInfo.processInfo.environment["NOTELITE_LIVE_ACCOUNT_ACCEPTANCE"] == "1" else {
            throw XCTSkip("Live account acceptance requires an explicit TestAction opt-in.")
        }
        let runID = UUID().uuidString.lowercased().replacingOccurrences(of: "-", with: "")
        let username = "syn_del_" + String(runID.prefix(24))
        let password = "Native-Acceptance-" + UUID().uuidString
        let stores = try (0..<3).map { try AcceptanceKeychainScope(origin: origin, runID: runID, index: $0) }
        var evidence: [String: Any] = [
            "schemaVersion": 1, "publicOrigin": origin, "syntheticDataOnly": true,
            "omrRequests": 0, "providerRequests": 0, "microphoneCaptured": false,
            "physicalMIDICaptured": false, "applicationRelaunchTested": false,
            "registrationAttempts": 0, "actualNativeRequests": 0, "completed": false,
            "credentialsLogged": false, "defaultSystemTLS": true, "privateFilesRead": false
        ]
        var registrationAttempted = false
        var confirmedDeletionCompleted = false
        var ownEmptyKeychainScopesConfirmed = false
        var registrations = 0
        var requests = 0
        defer {
            if ownEmptyKeychainScopesConfirmed {
                for store in stores { try? store.remove(origin: origin) }
            }
            evidence["registrationAttempts"] = registrations
            evidence["actualNativeRequests"] = requests
            if let data = try? JSONSerialization.data(withJSONObject: evidence, options: [.prettyPrinted, .sortedKeys]) {
                let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
                attachment.name = "NoteLite-actual-native-cloud-account-lifecycle"
                attachment.lifetime = .keepAlways
                add(attachment)
            }
        }
        for store in stores {
            try require(try store.read(origin: origin) == nil, "The isolated acceptance Keychain must start empty.")
        }
        ownEmptyKeychainScopesConfirmed = true
        let first = try CloudAccountClient(origin: origin, credentials: stores[0])
        let second = try CloudAccountClient(origin: origin, credentials: stores[1])
        func call(_ client: CloudAccountClient, _ path: String, _ method: String = "GET",
                  body: [String: Any]? = nil, etag: String? = nil, owner: String? = nil) async throws -> Any {
            requests += 1
            var input: [String: Any] = ["path": path, "method": method,
                                        "response": path.hasSuffix("/musicxml") ? "text" : "json"]
            if let body { input["body"] = body }
            if let etag { input["etag"] = etag }
            if let owner { input["expectedUserId"] = owner }
            return try await client.request(input)
        }
        let authentication: [String: Any] = ["username": username, "password": password,
                                             "deviceName": "Synthetic native CI acceptance"]
        let deletion: [String: Any] = ["password": password, "confirmation": "DELETE_ACCOUNT"]
        do {
            registrationAttempted = true; registrations += 1
            let identity = try object(await call(first, "/register", "POST", body: authentication))
            let userID = try identifier(identity["userId"])
            try require(identity["token"] == nil, "Credentials must not enter the public identity response.")
            let credential = try XCTUnwrap(try first.credential())
            try require(credential.userID == userID, "Registration must persist its actual identity.")
            let reloaded = try CloudAccountClient(origin: origin,
                credentials: AcceptanceKeychainScope(origin: origin, runID: runID, index: 0))
            let reloadedCredential = try XCTUnwrap(try reloaded.credential())
            try require(reloadedCredential.userID == userID && reloadedCredential.sessionID == credential.sessionID &&
                        reloadedCredential.token == credential.token, "A new client must read the same real Keychain entry.")
            let reloadedMe = try object(await call(reloaded, "/me"))
            try require(reloadedMe["userId"] as? String == userID, "Reloaded credentials must authenticate over actual HTTPS.")
            evidence["realKeychainWriteRead"] = true
            evidence["clientReinstantiationVerified"] = true
            evidence["actualTrustedTLSAuthenticated"] = true

            let otherIdentity = try object(await call(second, "/login", "POST", body: authentication))
            let otherCredential = try XCTUnwrap(try second.credential())
            try require(otherIdentity["userId"] as? String == userID && otherCredential.userID == userID &&
                        otherCredential.sessionID != credential.sessionID, "Two actual sessions must share one account.")
            let sessions = try object(await call(second, "/sessions"))
            try require((sessions["sessions"] as? [[String: Any]])?.count == 2, "Exactly two synthetic sessions should exist.")
            evidence["twoSessionsSameAccount"] = true

            let xml = Self.syntheticXML
            let sha = SHA256.hash(data: Data(xml.utf8)).map { String(format: "%02x", $0) }.joined()
            let score = try object(await call(first, "/scores", "POST", body: ["title": "Synthetic native cloud acceptance",
                "musicxml": xml, "requestId": UUID().uuidString.lowercased()], owner: userID))
            let scoreID = try identifier(score["id"])
            let scoreETag = try XCTUnwrap(score["etag"] as? String)
            try require(try await call(second, "/scores/\(scoreID)/musicxml", owner: userID) as? String == xml,
                        "A second actual native session must receive exact MusicXML bytes.")
            evidence["multiSessionMusicXMLSync"] = true

            let eventID = UUID().uuidString.lowercased()
            let ended = Date(), started = ended.addingTimeInterval(-2.2)
            let formatter = ISO8601DateFormatter(); formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            let original = Self.syntheticPerformance(eventID: eventID, sha: sha, wrongSecondNote: false)
            let saved = try object(await call(first, "/history", "POST", body: ["eventId": eventID,
                "sourceKind": "personal", "scoreId": scoreID, "scoreRevision": 1, "mode": "strict",
                "durationSeconds": 2.2, "startedAt": formatter.string(from: started),
                "endedAt": formatter.string(from: ended), "analysis": original], owner: userID))
            let savedEvent = try object(saved["event"])
            try require(savedEvent["scoreSha256"] as? String == sha && savedEvent["analysisVersion"] as? Int == 1 &&
                        savedEvent["snapshotValidatedByServer"] as? Bool == true, "History must bind version one to the exact score.")
            let versionOne = try object(await call(second, "/history/\(eventID)/analyses/1", owner: userID))
            let oneHash = try XCTUnwrap(versionOne["analysisHash"] as? String)
            let versionTwo = try object(await call(second, "/history/\(eventID)/analyses", "POST", body: [
                "requestId": UUID().uuidString.lowercased(), "parentVersion": 1, "sourceHash": sha,
                "analysis": Self.syntheticPerformance(eventID: eventID, sha: sha, wrongSecondNote: true)], owner: userID))
            try require(versionTwo["version"] as? Int == 2 && versionTwo["parentVersion"] as? Int == 1 &&
                        versionTwo["analysisHash"] as? String != oneHash, "Re-analysis must append a distinct immutable version.")
            let changedXML = xml.replacingOccurrences(of: "<work-title>Synthetic", with: "<work-title>Edited synthetic")
            _ = try await call(second, "/scores/\(scoreID)", "PUT", body: ["musicxml": changedXML], etag: scoreETag, owner: userID)
            try require(try await call(first, "/history/\(eventID)/musicxml", owner: userID) as? String == xml,
                        "Editing the personal score must not change a practiced score snapshot.")
            let unchanged = try object(await call(first, "/history/\(eventID)/analyses/1", owner: userID))
            try require(NSDictionary(dictionary: unchanged).isEqual(to: versionOne), "The first analysis version must remain byte-equivalent in JSON content.")
            let versions = try object(await call(first, "/history/\(eventID)/analyses", owner: userID))
            try require(versions["latestVersion"] as? Int == 2 && (versions["analyses"] as? [Any])?.count == 2,
                        "Both immutable analysis versions must remain readable on the other session.")
            evidence["syntheticMIDIEvents"] = true
            evidence["historySnapshotImmutable"] = true
            evidence["analysisVersionsImmutable"] = true

            let removed = try object(await call(first, "/account", "DELETE", body: deletion, owner: userID))
            confirmedDeletionCompleted = removed["deleted"] as? Bool == true && removed["status"] as? String == "completed"
            try require(removed["deleted"] as? Bool == true && removed["status"] as? String == "completed",
                        "An account with only synthetic score/history data must complete permanent deletion.")
            try require(try first.credential() == nil, "Accepted deletion must clear this native Keychain credential.")
            evidence["deletionClearsKeychain"] = true
            try await requireStatus(401) { try await call(second, "/me") }
            try stores[2].save(credential, origin: origin)
            let revoked = try CloudAccountClient(origin: origin, credentials: stores[2])
            try await requireStatus(401) { try await call(revoked, "/me") }
            evidence["bothOldSessionsRejected401"] = true

            registrations += 1; confirmedDeletionCompleted = false
            let newIdentity = try object(await call(first, "/register", "POST", body: authentication))
            let newUserID = try identifier(newIdentity["userId"])
            try require(newUserID != userID, "Re-registering the same synthetic username must create a new UUID.")
            let emptyScores = try object(await call(first, "/scores", owner: newUserID))
            let emptyHistory = try object(await call(first, "/history", owner: newUserID))
            try require((emptyScores["scores"] as? [Any])?.isEmpty == true && (emptyHistory["events"] as? [Any])?.isEmpty == true,
                        "Deleted scores and history must not resurrect in the replacement account.")
            try await requireStatus(404) { try await call(first, "/scores/\(scoreID)/musicxml", owner: newUserID) }
            try await requireStatus(404) { try await call(first, "/history/\(eventID)/analyses/1", owner: newUserID) }
            evidence["sameNameNewUUID"] = true
            evidence["deletedDataDoesNotResurrect"] = true
            let cleanup = try object(await call(first, "/account", "DELETE", body: deletion, owner: newUserID))
            try require(cleanup["deleted"] as? Bool == true && cleanup["status"] as? String == "completed",
                        "The replacement synthetic account must also be permanently removed.")
            evidence["syntheticAccountCleanupCompleted"] = true
            evidence["completed"] = true
        } catch {
            // A single bounded login can recover a write whose response was lost. Never creates another account.
            var cleaned = !registrationAttempted
            if registrationAttempted {
                do {
                    _ = try await call(first, "/login", "POST", body: authentication)
                    let result = try object(await call(first, "/account", "DELETE", body: deletion))
                    cleaned = result["deleted"] as? Bool == true && result["status"] as? String == "completed"
                } catch let cleanupError as CloudOMRError where cleanupError.status == 401 {
                    // A revoked identity proves access removal, not completion of remote cleanup.
                    cleaned = confirmedDeletionCompleted
                } catch { cleaned = false }
            }
            evidence["syntheticAccountCleanupCompleted"] = cleaned
            XCTAssertTrue(cleaned, "Synthetic account cleanup did not complete; retain the failed acceptance evidence.")
            throw error
        }
    }

    private func require(_ condition: Bool, _ message: String) throws {
        guard condition else { XCTFail(message); throw AcceptanceFailure.checkFailed }
    }
    private func object(_ value: Any?) throws -> [String: Any] { try XCTUnwrap(value as? [String: Any]) }
    private func identifier(_ value: Any?) throws -> String {
        let result = try XCTUnwrap(value as? String)
        try require(UUID(uuidString: result) != nil, "A native account identifier must be a UUID.")
        return result.lowercased()
    }
    @MainActor private func requireStatus(_ status: Int, operation: () async throws -> Any) async throws {
        do { _ = try await operation(); XCTFail("A forbidden or deleted resource unexpectedly succeeded."); throw AcceptanceFailure.checkFailed }
        catch let error as CloudOMRError { try require(error.status == status, "The actual server must reject with the expected HTTP status.") }
    }

    private static let syntheticXML = """
    <?xml version="1.0" encoding="UTF-8"?>
    <score-partwise version="4.0"><work><work-title>Synthetic native cloud acceptance</work-title></work><part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list><part id="P1"><measure number="1"><attributes><divisions>1</divisions><key><fifths>0</fifths></key><time><beats>2</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes><direction><sound tempo="60"/></direction><note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice><type>quarter</type><staff>1</staff></note><note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice><type>quarter</type><staff>1</staff></note></measure></part></score-partwise>
    """

    /// Two explicit synthetic MIDI opportunities exercise transport/versioning, not physical performance.
    private static func syntheticPerformance(eventID: String, sha: String, wrongSecondNote: Bool) -> [String: Any] {
        let attempt = eventID + ":1"
        var expected: [[String: Any]] = [], actual: [[String: Any]] = [], opportunities: [[String: Any]] = []
        for (index, midi) in [60, 62].enumerated() {
            let source = "P1:0:\(index)", occurrence = source + "@1", actualID = "midi-\(index + 1)"
            let wrong = wrongSecondNote && index == 1
            expected.append(["partId": "P1", "measureIndex": 0, "noteIndex": index, "sourceNoteId": source,
                "occurrenceId": occurrence, "occurrenceOrdinal": 1, "midi": midi, "writtenMidi": midi,
                "step": index == 0 ? "C" : "D", "alter": 0, "octave": 4, "transpose": 0, "voice": "1", "staff": "1",
                "startMs": index * 1000, "durationMs": 1000, "onsetBeat": index, "durationBeat": 1])
            for kind in ["on", "off"] {
                var event: [String: Any] = ["eventId": actualID, "type": kind, "midi": wrong ? midi + 1 : midi,
                    "timeMs": (index + (kind == "off" ? 1 : 0)) * 1000 + 150, "confidence": 1,
                    "timingConfidence": 1, "centsEvidence": "none"]
                if kind == "off" { event["releaseReliable"] = true }
                actual.append(event)
            }
            opportunities.append(["opportunityId": "\(attempt):\(occurrence):\(midi)", "attemptId": attempt,
                "occurrenceId": occurrence, "sourceNoteIds": [source], "expectedMidi": midi, "entered": true,
                "terminal": true, "completed": true, "evaluated": true, "outcome": wrong ? "wrong" : "correct",
                "actualEventIds": [actualID], "partId": "P1", "measureIndex": 0, "noteIndex": index,
                "voice": "1", "staff": "1", "onsetBeat": index, "durationBeat": 1, "firstTryCorrect": !wrong,
                "dimensions": ["pitch": ["eligible": true, "outcome": wrong ? "wrong" : "correct"],
                    "onset": ["eligible": true, "outcome": "correct", "error": 0],
                    "duration": ["eligible": true, "outcome": "correct", "error": 0],
                    "intonation": ["eligible": false, "outcome": "unavailable", "reason": "MIDI has no continuous intonation evidence"]]])
        }
        return ["schemaVersion": 2, "contract": "notewise-history-1", "status": "analysed", "source": "client-reported",
            "verifiedByServer": false, "takeId": eventID, "eventId": eventID, "sourceScoreSha256": sha, "scoreRevision": 1,
            "inputKind": "midi", "detectorVersion": "midi-stream-2", "matcherVersion": "online-occurrence-2",
            "judgeRulesVersion": "active-feedback-2", "normalizerVersion": "musicxml-repeat-tie-2", "mode": "strict", "bpm": 60, "tuning": 440,
            "captureClock": ["source": "host-monotonic", "unit": "ms", "timingCalibrated": false, "phaseAnchor": "midi-1"],
            "capabilities": ["pitch": true, "onset": true, "duration": true, "intonation": false, "polyphony": true, "recording": false],
            "attempts": [["attemptId": attempt, "startMs": 0, "endMs": 2200, "interrupted": false]],
            "expected": expected, "actualEvents": actual, "opportunities": opportunities, "errors": [], "uncertainty": [],
            "coverageByDimension": [
                "pitch": ["eligible": 2, "evaluated": 2, "failed": wrongSecondNote ? 1 : 0, "pending": 0],
                "onset": ["eligible": 2, "evaluated": 2, "failed": 0, "pending": 0],
                "duration": ["eligible": 2, "evaluated": 2, "failed": 0, "pending": 0],
                "intonation": ["eligible": 0, "evaluated": 0, "failed": 0, "pending": 0]],
            "completed": true, "terminal": true, "performanceDurationMs": 2200]
    }
}

private enum AcceptanceFailure: Error { case checkFailed, incorrectStorageOrigin }

/// Test-only origin mapping isolates entries while executing the real product Keychain implementation.
/// The .invalid hostname is only a Keychain account label; it is never a network destination.
private struct AcceptanceKeychainScope: CloudAccountCredentialStore {
    let expectedOrigin: String
    let storageOrigin: String
    init(origin: String, runID: String, index: Int) throws {
        expectedOrigin = try ServerConfiguration(origin).key
        storageOrigin = try ServerConfiguration("https://syn-del-\(runID)-\(index).invalid").key
    }
    private func validate(_ origin: String) throws {
        guard try ServerConfiguration(origin).key == expectedOrigin else { throw AcceptanceFailure.incorrectStorageOrigin }
    }
    func read(origin: String) throws -> CloudAccountCredential? {
        try validate(origin); return try KeychainCloudAccountCredentials().read(origin: storageOrigin)
    }
    func save(_ value: CloudAccountCredential, origin: String) throws {
        try validate(origin); try KeychainCloudAccountCredentials().save(value, origin: storageOrigin)
    }
    func remove(origin: String) throws {
        try validate(origin); try KeychainCloudAccountCredentials().remove(origin: storageOrigin)
    }
}
