import XCTest
@testable import NoteLite

/// An in-memory credential store and HTTP transport exercise the native contract without production credentials.
final class CloudAccountTests: XCTestCase {
    private let origin = "https://example.com"
    private let userID = "11111111-1111-4111-8111-111111111111"
    private let sessionID = "22222222-2222-4222-8222-222222222222"
    private let recordID = "33333333-3333-4333-8333-333333333333"
    override func tearDown() { AccountContractProtocol.responder = nil; super.tearDown() }

    private func configuration() -> URLSessionConfiguration {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [AccountContractProtocol.self]
        return configuration
    }
    private func identity() -> CloudAccountCredential {
        CloudAccountCredential(token: "native-account-only", userID: userID, sessionID: sessionID)
    }
    private func json(_ value: Any) -> Data { try! JSONSerialization.data(withJSONObject: value) }

    @MainActor func testLoginForcesNativeAndDoesNotReturnCredential() async throws {
        let store = AccountMemoryCredentials()
        AccountContractProtocol.responder = { request in
            XCTAssertEqual(request.url?.absoluteString, "https://example.com/api/account/login")
            XCTAssertNil(request.value(forHTTPHeaderField: "Authorization"))
            let body = try! JSONSerialization.jsonObject(with: AccountContractProtocol.body(request)) as! [String: Any]
            XCTAssertEqual(body["mode"] as? String, "native")
            return (201, self.json(["authenticated": true, "kind": "native", "token": "native-account-only",
                                    "userId": self.userID, "sessionId": self.sessionID, "username": "musician",
                                    "deviceName": "test", "expiresAt": "2030-01-01", "unexpectedSecret": "discarded"]))
        }
        let client = try CloudAccountClient(origin: origin, credentials: store, sessionConfiguration: configuration())
        let reply = try await client.request(["path": "/login", "method": "POST", "response": "json",
                                             "body": ["username": "musician", "password": "a-long-test-password", "mode": "browser"]]) as! [String: Any]
        XCTAssertNil(reply["token"])
        XCTAssertNil(reply["unexpectedSecret"])
        XCTAssertEqual(reply["userId"] as? String, userID)
        XCTAssertEqual(try store.read(origin: origin), identity())
    }

    @MainActor func testMalformedAuthenticationNeverStoresCredential() async throws {
        let store = AccountMemoryCredentials()
        AccountContractProtocol.responder = { _ in (201, self.json(["authenticated": true, "kind": "browser", "token": "invalid"])) }
        let client = try CloudAccountClient(origin: origin, credentials: store, sessionConfiguration: configuration())
        do {
            _ = try await client.request(["path": "/register", "method": "POST", "response": "json", "body": ["username": "musician", "password": "a-long-test-password"]])
            XCTFail("Malformed authentication was accepted")
        } catch let error as CloudOMRError { XCTAssertEqual(error.code, "write_status_unknown") }
        XCTAssertNil(try store.read(origin: origin))
    }

    @MainActor func testUnauthenticatedMeNeverSendsLegacyCredential() async throws {
        AccountContractProtocol.responder = { _ in XCTFail("Unauthenticated request reached server"); return (200, Data("{}".utf8)) }
        let client = try CloudAccountClient(origin: origin, credentials: AccountMemoryCredentials(), sessionConfiguration: configuration())
        do { _ = try await client.request(["path": "/me", "method": "GET", "response": "json"]); XCTFail("Unauthenticated /me accepted") }
        catch let error as CloudOMRError { XCTAssertEqual(error.status, 401) }
    }

    @MainActor func testMeChecksStoredIdentityAndStripsUnexpectedToken() async throws {
        let store = AccountMemoryCredentials()
        try store.save(identity(), origin: origin)
        AccountContractProtocol.responder = { _ in
            (200, self.json(["authenticated": true, "kind": "native", "userId": self.userID,
                              "sessionId": self.sessionID, "username": "musician", "token": "must-not-enter-webview"]))
        }
        let client = try CloudAccountClient(origin: origin, credentials: store, sessionConfiguration: configuration())
        let result = try await client.request(["path": "/me", "method": "GET", "response": "json"]) as! [String: Any]
        XCTAssertNil(result["token"])
        AccountContractProtocol.responder = { _ in (200, self.json(["authenticated": true, "kind": "native", "userId": self.recordID, "sessionId": self.sessionID])) }
        do { _ = try await client.request(["path": "/me", "method": "GET", "response": "json"]); XCTFail("Foreign /me reply accepted") }
        catch { XCTAssertEqual(try store.read(origin: origin), identity()) }
    }

    @MainActor func testCurrentSessionRevocationClearsAccountOnly() async throws {
        let store = AccountMemoryCredentials()
        try store.save(identity(), origin: origin)
        AccountContractProtocol.responder = { request in
            XCTAssertEqual(request.httpMethod, "DELETE")
            return (200, self.json(["revoked": true]))
        }
        let client = try CloudAccountClient(origin: origin, credentials: store, sessionConfiguration: configuration())
        _ = try await client.request(["path": "/sessions/\(recordID)", "method": "DELETE", "response": "json"])
        XCTAssertEqual(try store.read(origin: origin), identity())
        _ = try await client.request(["path": "/sessions/\(sessionID.uppercased())", "method": "DELETE", "response": "json"])
        XCTAssertNil(try store.read(origin: origin))
    }

    @MainActor func testWriteProxyFailureAndMalformedSuccessRemainUnconfirmed() async throws {
        let store = AccountMemoryCredentials()
        try store.save(identity(), origin: origin)
        let client = try CloudAccountClient(origin: origin, credentials: store, sessionConfiguration: configuration())
        for status in [504, 200] {
            AccountContractProtocol.responder = { _ in (status, Data("broken-json".utf8)) }
            do { _ = try await client.request(["path": "/scores", "method": "POST", "response": "json", "body": ["title": "test", "musicxml": "<score-partwise/>"]]); XCTFail("Unconfirmed write accepted") }
            catch let error as CloudOMRError { XCTAssertEqual(error.code, "write_status_unknown") }
        }
        XCTAssertEqual(try store.read(origin: origin), identity())
    }

    @MainActor func testExpiredAccountIsRetainedAndNeverRetriesLegacyDevice() async throws {
        let store = AccountMemoryCredentials()
        try store.save(identity(), origin: origin)
        var requests = 0
        AccountContractProtocol.responder = { request in
            requests += 1
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer native-account-only")
            return (401, self.json(["error": "expired"]))
        }
        let account = try CloudAccountClient(origin: origin, credentials: store, sessionConfiguration: configuration())
        do { _ = try await account.request(["path": "/me", "method": "GET", "response": "json"]); XCTFail("Expired account accepted") }
        catch let error as CloudOMRError { XCTAssertEqual(error.status, 401) }
        XCTAssertEqual(try store.read(origin: origin), identity())
        let omr = try CloudOMRClient(origin: origin, token: "legacy-device", accountToken: identity().token, sessionConfiguration: configuration())
        do { _ = try await omr.jobs(); XCTFail("Expired account fell back") }
        catch let error as CloudOMRError { XCTAssertEqual(error.status, 401) }
        XCTAssertEqual(requests, 2)
    }

    @MainActor func testExplicitLogoutAcceptsAlreadyExpiredAndOnlyRemovesAccountOrigin() async throws {
        let store = AccountMemoryCredentials()
        try store.save(identity(), origin: origin)
        try store.save(identity(), origin: "https://another.example")
        AccountContractProtocol.responder = { _ in (401, self.json(["error": "expired"])) }
        let client = try CloudAccountClient(origin: origin, credentials: store, sessionConfiguration: configuration())
        let result = try await client.request(["path": "/logout", "method": "POST", "response": "json"]) as! [String: Any]
        XCTAssertEqual(result["authenticated"] as? Bool, false)
        XCTAssertNil(try store.read(origin: origin))
        XCTAssertEqual(try store.read(origin: "https://another.example"), identity())
    }

    @MainActor func testFailedLogoutRetainsCredential() async throws {
        let store = AccountMemoryCredentials()
        try store.save(identity(), origin: origin)
        AccountContractProtocol.responder = { _ in (503, Data()) }
        let client = try CloudAccountClient(origin: origin, credentials: store, sessionConfiguration: configuration())
        do { _ = try await client.request(["path": "/logout", "method": "POST", "response": "json"]); XCTFail("Unconfirmed logout accepted") }
        catch let error as CloudOMRError { XCTAssertEqual(error.code, "write_status_unknown") }
        XCTAssertEqual(try store.read(origin: origin), identity())
    }

    @MainActor func testForeignIdentityIsRejectedBeforeNetwork() async throws {
        let store = AccountMemoryCredentials()
        try store.save(identity(), origin: origin)
        AccountContractProtocol.responder = { _ in XCTFail("Foreign identity reached server"); return (200, Data("{}".utf8)) }
        let client = try CloudAccountClient(origin: origin, credentials: store, sessionConfiguration: configuration())
        do { _ = try await client.request(["path": "/scores", "method": "GET", "response": "json", "expectedUserId": recordID]); XCTFail("Foreign identity accepted") }
        catch let error as CloudOMRError { XCTAssertEqual(error.status, 409) }
    }

    @MainActor func testXMLWriteSendsExactETagAndExpectedUser() async throws {
        let store = AccountMemoryCredentials()
        try store.save(identity(), origin: origin)
        let etag = "\"\(recordID):1\""
        AccountContractProtocol.responder = { request in
            XCTAssertEqual(request.value(forHTTPHeaderField: "If-Match"), etag)
            XCTAssertEqual(request.value(forHTTPHeaderField: "X-NoteLite-Expected-User"), self.userID)
            return (200, self.json(["id": self.recordID, "revision": 2]))
        }
        let client = try CloudAccountClient(origin: origin, credentials: store, sessionConfiguration: configuration())
        _ = try await client.request(["path": "/scores/\(recordID)", "method": "PUT", "response": "json", "etag": etag,
                                      "expectedUserId": userID, "body": ["musicxml": "<score-partwise/>"]])
    }

    @MainActor func testBinaryChunkUsesBoundedBodyAndUploadOffset() async throws {
        let store = AccountMemoryCredentials()
        try store.save(identity(), origin: origin)
        let data = Data(repeating: 7, count: 1024 * 1024)
        AccountContractProtocol.responder = { request in
            XCTAssertEqual(request.value(forHTTPHeaderField: "Upload-Offset"), "1048576")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Content-Type"), "application/octet-stream")
            XCTAssertEqual(AccountContractProtocol.body(request), data)
            return (200, self.json(["offset": 2097152]))
        }
        let client = try CloudAccountClient(origin: origin, credentials: store, sessionConfiguration: configuration())
        _ = try await client.request(["path": "/uploads/\(recordID)", "method": "PUT", "response": "json", "base64": data.base64EncodedString(), "uploadOffset": 1048576])
        do {
            _ = try await client.request(["path": "/uploads/\(recordID)", "method": "PUT", "response": "json", "base64": Data(repeating: 7, count: 1048577).base64EncodedString(), "uploadOffset": 0])
            XCTFail("Oversized chunk accepted")
        } catch let error as CloudOMRError { XCTAssertEqual(error.code, "invalid_request") }
    }

    @MainActor func testRouteAllowlistRejectsURLInternalHeadersAndTraversal() async throws {
        for path in ["https://evil.example/me", "//evil.example/me", "/../me", "/api/account/me", "/internal/account/resolve", "/me%2f..", "/me#token", "/me?token=secret", "/courses/\(recordID)/codes/../roster"] {
            XCTAssertThrowsError(try CloudAccountClient.route(path: path, method: "GET"), path)
        }
        XCTAssertNoThrow(try CloudAccountClient.route(path: "/practice-analysis", method: "POST"))
        let classroomCodeID = String(repeating: "a", count: 64)
        XCTAssertNoThrow(try CloudAccountClient.route(path: "/courses/\(recordID)/codes/\(classroomCodeID)", method: "DELETE"))
        XCTAssertThrowsError(try CloudAccountClient.route(path: "/courses/\(recordID)/codes/\(recordID)", method: "DELETE"))
        XCTAssertThrowsError(try CloudAccountClient.route(path: "/courses/\(recordID)/codes/\(String(repeating: "g", count: 64))", method: "DELETE"))
        XCTAssertNoThrow(try CloudAccountClient.route(path: "/history?limit=200&cursor=1234%3A\(recordID)", method: "GET"))
        for path in ["/history?limit=201", "/history?limit=1&limit=2", "/history?cursor=nan%3A\(recordID)", "/history?admin=1"] {
            XCTAssertThrowsError(try CloudAccountClient.route(path: path, method: "GET"), path)
        }
        let client = try CloudAccountClient(origin: origin, credentials: AccountMemoryCredentials(), sessionConfiguration: configuration())
        do { _ = try await client.request(["path": "/health", "method": "GET", "response": "json", "headers": ["Authorization": "secret"]]); XCTFail("Arbitrary header accepted") }
        catch let error as CloudOMRError { XCTAssertEqual(error.code, "invalid_request") }
    }

    @MainActor func testDigestSequenceHashesExactChunksAndDeletesContext() throws {
        let digests = CloudAccountDigestStore()
        let id = try digests.start(size: 3, scope: "owner/session")["digestId"] as! String
        XCTAssertThrowsError(try digests.finish(id: id, scope: "owner/session"))
        _ = try digests.update(id: id, base64: Data("a".utf8).base64EncodedString(), offset: 0, scope: "owner/session")
        XCTAssertThrowsError(try digests.update(id: id, base64: Data("b".utf8).base64EncodedString(), offset: 0, scope: "owner/session"))
        XCTAssertThrowsError(try digests.update(id: id, base64: Data("bc".utf8).base64EncodedString(), offset: 1, scope: "another/session"))
        _ = try digests.update(id: id, base64: Data("bc".utf8).base64EncodedString(), offset: 1, scope: "owner/session")
        XCTAssertEqual(try digests.finish(id: id, scope: "owner/session")["sha256"] as? String, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        XCTAssertEqual(digests.count, 0)
        XCTAssertThrowsError(try digests.finish(id: id, scope: "owner/session"))
    }

    @MainActor func testDigestBoundsCancellationAndClear() throws {
        let digests = CloudAccountDigestStore()
        XCTAssertThrowsError(try digests.start(size: false, scope: "s"))
        XCTAssertThrowsError(try digests.start(size: 104857601, scope: "s"))
        var ids: [String] = []
        for _ in 0..<4 { ids.append(try digests.start(size: 104857600, scope: "s")["digestId"] as! String) }
        XCTAssertThrowsError(try digests.start(size: 1, scope: "s"))
        XCTAssertThrowsError(try digests.cancel(id: "bad-id", scope: "s"))
        _ = try digests.cancel(id: ids[0], scope: "s")
        XCTAssertEqual(digests.count, 3)
        digests.clear()
        XCTAssertEqual(digests.count, 0)
    }

    @MainActor func testAudioContainerValidationAllowsFull100MiBButRejectsMismatchedFiles() throws {
        XCTAssertEqual(try CloudAccountClient.audioExtension(mime: "audio/wav", header: Data("RIFF0000WAVEfmt ".utf8), size: 104857600), "wav")
        XCTAssertEqual(try CloudAccountClient.audioExtension(mime: "audio/mpeg", header: Data("ID3test".utf8), size: 30), "mp3")
        XCTAssertEqual(try CloudAccountClient.audioExtension(mime: "audio/mp4", header: Data([0, 0, 0, 20] + Array("ftyp".utf8)), size: 30), "m4a")
        XCTAssertThrowsError(try CloudAccountClient.audioExtension(mime: "audio/wav", header: Data("<html>error".utf8), size: 20))
        XCTAssertThrowsError(try CloudAccountClient.audioExtension(mime: "application/json", header: Data("ID3test".utf8), size: 30))
        XCTAssertThrowsError(try CloudAccountClient.audioExtension(mime: "audio/wav", header: Data("RIFF0000WAVEfmt ".utf8), size: 104857601))
    }
}

private final class AccountMemoryCredentials: CloudAccountCredentialStore {
    private var values: [String: CloudAccountCredential] = [:]
    func read(origin: String) throws -> CloudAccountCredential? { values[try ServerConfiguration(origin).key] }
    func save(_ value: CloudAccountCredential, origin: String) throws { try value.validate(); values[try ServerConfiguration(origin).key] = value }
    func remove(origin: String) throws { values.removeValue(forKey: try ServerConfiguration(origin).key) }
}

private final class AccountContractProtocol: URLProtocol {
    static var responder: ((URLRequest) -> (Int, Data))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    static func body(_ request: URLRequest) -> Data {
        if let body = request.httpBody { return body }
        guard let stream = request.httpBodyStream else { return Data() }
        stream.open(); defer { stream.close() }
        var data = Data()
        var bytes = [UInt8](repeating: 0, count: 4096)
        while stream.hasBytesAvailable {
            let count = stream.read(&bytes, maxLength: bytes.count)
            if count <= 0 { break }
            data.append(contentsOf: bytes.prefix(count))
        }
        return data
    }
    override func startLoading() {
        guard let responder = Self.responder else { client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse)); return }
        let (status, data) = responder(request)
        let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: "HTTP/1.1", headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
