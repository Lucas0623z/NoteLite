import XCTest
@testable import NoteLite

final class FigmaCloudRequestIdentityTests: XCTestCase {
    private let origin = "https://124.221.211.156"
    private let userA = "e970e369-5860-40ad-89fa-604260ea97e1"
    private let userB = "c7f7d28a-6698-49f6-9e6e-62a18c38dab0"

    private func identity(_ user: String, session: String = "27e089fb-40f3-4e85-95db-41ea94a8c0b4", token: String = "synthetic_account_token_for_test") -> CloudAccountCredential {
        CloudAccountCredential(token: token, userID: user, sessionID: session)
    }

    func testMissingAccountCannotUseLegacyPairingForAnAccountScoreRequest() {
        XCTAssertThrowsError(try FigmaCloudRequestIdentity(origin: origin, credential: nil, expectedUserID: userA)) {
            XCTAssertEqual(($0 as? CloudOMRError)?.status, 401)
            XCTAssertEqual(($0 as? CloudOMRError)?.code, "account_required")
        }
    }

    func testExpectedAccountMustMatchBeforeNativePickerOrNetworkStarts() throws {
        for expected in [nil, userB, "not-a-user"] as [String?] {
            XCTAssertThrowsError(try FigmaCloudRequestIdentity(origin: origin, credential: identity(userA), expectedUserID: expected)) {
                XCTAssertEqual(($0 as? CloudOMRError)?.status, 409)
                XCTAssertEqual(($0 as? CloudOMRError)?.code, "identity_changed")
            }
        }
        let captured = try FigmaCloudRequestIdentity(origin: origin, credential: identity(userA), expectedUserID: userA)
        XCTAssertEqual(captured.ownerScope, origin + "|" + userA)
        XCTAssertNoThrow(try captured.validate(origin: origin, credential: identity(userA)))
    }

    func testAccountSwitchOrLogoutWhileSelectingAFileCannotUploadUnderAnotherIdentity() throws {
        let captured = try FigmaCloudRequestIdentity(origin: origin, credential: identity(userA), expectedUserID: userA)
        for current in [identity(userB), nil] as [CloudAccountCredential?] {
            XCTAssertThrowsError(try captured.validate(origin: origin, credential: current)) {
                XCTAssertEqual(($0 as? CloudOMRError)?.status, 409)
            }
        }
        XCTAssertThrowsError(try captured.validate(origin: "https://another.invalid", credential: identity(userA)))
    }

    func testSameUserFreshSessionCannotReceiveAnEarlierPickerResult() throws {
        let captured = try FigmaCloudRequestIdentity(origin: origin, credential: identity(userA), expectedUserID: userA)
        XCTAssertThrowsError(try captured.validate(origin: origin,
            credential: identity(userA, session: "892a1e1f-fd54-4d94-8ce4-d686743d91ef")))
        XCTAssertThrowsError(try captured.validate(origin: origin,
            credential: identity(userA, token: "different_synthetic_token_for_test")))
    }

    func testGuestPracticeCannotBeginOrReceiveAResultAfterAnAccountLogsIn() throws {
        let guest = try FigmaPracticeRequestIdentity(origin: origin, credential: nil, expectedUserID: "guest", expectedSessionID: NSNull())
        XCTAssertEqual(guest.ownerScope, origin + "|guest")
        XCTAssertNoThrow(try guest.validate(origin: origin, credential: nil))
        XCTAssertThrowsError(try guest.validate(origin: origin, credential: identity(userA)))
        XCTAssertThrowsError(try FigmaPracticeRequestIdentity(origin: origin, credential: identity(userA), expectedUserID: "guest", expectedSessionID: NSNull()))
    }

    func testOwnedPracticeAndDataExportRequireBothOriginalAccountAndOriginalSession() throws {
        let original = identity(userA)
        let request = try FigmaPracticeRequestIdentity(origin: origin, credential: original,
            expectedUserID: userA, expectedSessionID: original.sessionID)
        XCTAssertEqual(request.ownerScope, origin + "|" + userA)
        XCTAssertNoThrow(try request.validate(origin: origin, credential: original))
        for changed in [nil, identity(userB), identity(userA, session: "892a1e1f-fd54-4d94-8ce4-d686743d91ef"), identity(userA, token: "another_synthetic_session_token")] as [CloudAccountCredential?] {
            XCTAssertThrowsError(try request.validate(origin: origin, credential: changed)) {
                XCTAssertEqual(($0 as? CloudOMRError)?.status, 409)
            }
        }
        XCTAssertThrowsError(try request.validate(origin: "https://another.invalid", credential: original))
        for session in [nil, NSNull(), "not-a-session", "892a1e1f-fd54-4d94-8ce4-d686743d91ef"] as [Any?] {
            XCTAssertThrowsError(try FigmaPracticeRequestIdentity(origin: origin, credential: original, expectedUserID: userA, expectedSessionID: session))
        }
        XCTAssertThrowsError(try FigmaPracticeRequestIdentity(origin: origin, credential: original, expectedUserID: userB, expectedSessionID: original.sessionID))
        XCTAssertThrowsError(try FigmaPracticeRequestIdentity(origin: origin, credential: nil, expectedUserID: userA, expectedSessionID: original.sessionID))
    }

    @MainActor func testPermanentDeletionResumesImportAndExportContinuationsBeforeDrainingTasks() async throws {
        let controller = FigmaShellController()
        for exporting in [false, true] {
            let scope = origin + "|" + UUID().uuidString.lowercased()
            let id = UUID().uuidString
            var pending: Task<Void, Never>!
            var cancelled = false
            await withCheckedContinuation { (ready: CheckedContinuation<Void, Never>) in
                pending = Task { @MainActor in
                    do {
                        if exporting {
                            let _: String = try await withCheckedThrowingContinuation { continuation in
                                controller.installDeletionTestRequest(id, scope: scope, task: pending, exporting: continuation)
                                ready.resume()
                            }
                        } else {
                            let _: URL = try await withCheckedThrowingContinuation { continuation in
                                controller.installDeletionTestRequest(id, scope: scope, task: pending, importing: continuation)
                                ready.resume()
                            }
                        }
                        XCTFail("A deleted account's pending file request completed successfully")
                    } catch is CancellationError { cancelled = true }
                    catch { XCTFail("Unexpected pending-file error: \(error)") }
                }
            }
            // Calls the production purge and cancelRequest paths. With only
            // Task.cancel(), this await never finishes because the picker is suspended.
            try await controller.purgeDeletionTestScope(scope)
            XCTAssertTrue(pending.isCancelled)
            XCTAssertTrue(cancelled)
            XCTAssertFalse(controller.importing)
            XCTAssertFalse(controller.exporting)
        }
    }

    @MainActor func testPermanentDeletionRemovesOnlyTheDeletedAccountsPresentedOriginal() async throws {
        let controller = FigmaShellController()
        let deletedScope = origin + "|" + UUID().uuidString.lowercased()
        let otherScope = origin + "|" + UUID().uuidString.lowercased()
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        let file = directory.appendingPathComponent("synthetic-original.pdf")
        defer { controller.previewURL = nil; controller.clearPreview(); try? FileManager.default.removeItem(at: directory) }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        try Data("synthetic-original".utf8).write(to: file)
        controller.installDeletionTestPreview(directory: directory, file: file, scope: otherScope)
        try await controller.purgeDeletionTestScope(deletedScope)
        XCTAssertEqual(controller.previewURL, file)
        XCTAssertTrue(FileManager.default.fileExists(atPath: file.path))

        controller.installDeletionTestPreview(directory: directory, file: file, scope: deletedScope)
        try await controller.purgeDeletionTestScope(deletedScope)
        XCTAssertNil(controller.previewURL)
        XCTAssertFalse(FileManager.default.fileExists(atPath: directory.path))
    }
}
