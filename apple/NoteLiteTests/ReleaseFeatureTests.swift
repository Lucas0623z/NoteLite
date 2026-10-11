import XCTest
@testable import NoteLite

final class ReleaseFeatureTests: XCTestCase {
    func testPurchasesCannotInvokeTransactionOrEntitlementMutation() throws {
        XCTAssertFalse(ReleaseFeatures.inAppPurchases)
        var transactionCalled = false
        XCTAssertThrowsError(try ReleaseFeatures.performPurchase { transactionCalled = true; return true }) { error in
            XCTAssertEqual((error as? CloudOMRError)?.code, "purchase_unavailable")
            XCTAssertEqual(error.localizedDescription, "测试期未开放")
        }
        XCTAssertFalse(transactionCalled)
    }

    func testFinancialBridgeActionsBlockedWhileClassroomAndPracticeRemainAllowed() throws {
        for action in ["iap/purchase", "store/checkout", "membership/restore", "coins/topup"] {
            XCTAssertThrowsError(try ReleaseFeatures.requireAllowedRequest(action))
        }
        XCTAssertThrowsError(try ReleaseFeatures.requireAllowedRequest("account/request", payload: ["path": "/api/account/subscriptions?plan=pro"]))
        for action in ["notewise/start", "notewise/refine", "jobs/create", "notes/patch"] {
            XCTAssertNoThrow(try ReleaseFeatures.requireAllowedRequest(action))
        }
        for path in ["/register", "/history?limit=200", "/courses/11111111-1111-4111-8111-111111111111/membership"] {
            XCTAssertNoThrow(try ReleaseFeatures.requireAllowedRequest("account/request", payload: ["path": path]))
        }
    }

    @MainActor func testNativeAccountPurchaseStopsBeforeCredentialReadOrHTTP() async throws {
        let credentials = PurchaseGateCredentials()
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [PurchaseGateURLProtocol.self]
        PurchaseGateURLProtocol.requests = 0
        let client = try CloudAccountClient(origin: "https://example.com", credentials: credentials, sessionConfiguration: configuration)
        for path in ["/billing/checkout", "/membership", "/coins/purchase", "/store/restore"] {
            do {
                _ = try await client.request(["path": path, "method": "POST", "response": "json"])
                XCTFail("A paid request must not start")
            } catch let error as CloudOMRError { XCTAssertEqual(error.code, "purchase_unavailable") }
        }
        XCTAssertEqual(credentials.reads, 0)
        XCTAssertEqual(PurchaseGateURLProtocol.requests, 0)
    }
}

private final class PurchaseGateCredentials: CloudAccountCredentialStore {
    var reads = 0
    func read(origin: String) throws -> CloudAccountCredential? { reads += 1; return nil }
    func save(_ value: CloudAccountCredential, origin: String) throws { XCTFail("Paid request must not change credentials") }
    func remove(origin: String) throws { XCTFail("Paid request must not remove credentials") }
}

private final class PurchaseGateURLProtocol: URLProtocol {
    static var requests = 0
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() { Self.requests += 1; client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse)) }
    override func stopLoading() {}
}
