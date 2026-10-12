import XCTest
@testable import NoteLite

final class CloudOMRTests: XCTestCase {
    override func tearDown() {
        CloudContractProtocol.responder = nil
        super.tearDown()
    }

    private func client(token: String = "device-test-credential") throws -> CloudOMRClient {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [CloudContractProtocol.self]
        return try CloudOMRClient(origin: "https://scores.example.com", token: token, sessionConfiguration: configuration)
    }

    func testHealthUsesGatewayAndDoesNotSendCredential() async throws {
        CloudContractProtocol.responder = { request in
            XCTAssertEqual(request.url?.path, "/api/health")
            XCTAssertNil(request.value(forHTTPHeaderField: "Authorization"))
            return (200, Data("{\"status\":\"ok\"}".utf8))
        }
        let result = try await client().health()
        XCTAssertEqual(result["status"] as? String, "ok")
    }

    func testPairRequestsNativeDeviceCredentialWithoutAdministratorToken() async throws {
        CloudContractProtocol.responder = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/pair")
            XCTAssertNil(request.value(forHTTPHeaderField: "Authorization"))
            let body = try! JSONSerialization.jsonObject(with: CloudContractProtocol.body(request)) as! [String: Any]
            XCTAssertEqual(body["mode"] as? String, "native")
            XCTAssertEqual(body["deviceName"] as? String, "My iPad")
            XCTAssertEqual(body["code"] as? String, "one-time-code")
            return (201, Data("{\"token\":\"new-device-token\",\"deviceId\":\"device-id\"}".utf8))
        }
        let result = try await client().pair(code: "one-time-code", deviceName: "My iPad")
        XCTAssertEqual(result["deviceId"] as? String, "device-id")
    }

    func testLogoutRevokesTheNativeSessionAtTheGateway() async throws {
        CloudContractProtocol.responder = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/session/logout")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer device-test-credential")
            return (200, Data("{\"authenticated\":false}".utf8))
        }
        try await client().logout()
    }

    func testJobListPreservesNewGatewayShapeAndUsesDeviceCredential() async throws {
        CloudContractProtocol.responder = { request in
            XCTAssertEqual(request.url?.path, "/api/jobs")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer device-test-credential")
            return (200, Data("{\"jobs\":[{\"id\":\"1096a6c1-32ce-4d06-a72f-e565700ecde2\",\"revision\":2,\"scores\":[],\"artifacts\":{}}]}".utf8))
        }
        let result = try await client().jobs() as! [String: Any]
        XCTAssertEqual((result["jobs"] as? [[String: Any]])?.count, 1)
    }

    func testNoteCorrectionSendsRevisionAndScoreToCurrentEndpoint() async throws {
        CloudContractProtocol.responder = { request in
            XCTAssertEqual(request.httpMethod, "PATCH")
            XCTAssertEqual(request.url?.path, "/api/jobs/1096a6c1-32ce-4d06-a72f-e565700ecde2/score/notes")
            XCTAssertEqual(URLComponents(url: request.url!, resolvingAgainstBaseURL: false)?.queryItems?.first?.value, "1")
            let body = try! JSONSerialization.jsonObject(with: CloudContractProtocol.body(request)) as! [String: Any]
            XCTAssertEqual(body["revision"] as? Int, 7)
            XCTAssertEqual(body["score"] as? Int, 1)
            XCTAssertEqual((body["edits"] as? [[String: Any]])?.first?["partId"] as? String, "P1")
            return (200, Data("{\"revision\":8}".utf8))
        }
        let result = try await client().patchNotes(jobID: "1096A6C1-32CE-4D06-A72F-E565700ECDE2", score: 1,
                                                 revision: 7, edits: [["partId": "P1", "measureIndex": 0, "noteIndex": 0, "duration": 6]])
        XCTAssertEqual(result["revision"] as? Int, 8)
    }

    func testFullScoreCorrectionUsesIfMatchAndRawXML() async throws {
        let xml = "<score-partwise version=\"4.0\"><part-list/></score-partwise>"
        CloudContractProtocol.responder = { request in
            XCTAssertEqual(request.httpMethod, "PUT")
            XCTAssertEqual(request.value(forHTTPHeaderField: "If-Match"), "\"3\"")
            XCTAssertEqual(String(data: CloudContractProtocol.body(request), encoding: .utf8), xml)
            return (200, Data("{\"revision\":4}".utf8))
        }
        let result = try await client().replaceScore(jobID: "1096a6c1-32ce-4d06-a72f-e565700ecde2", score: 0,
                                                   revision: 3, musicxml: xml)
        XCTAssertEqual(result["revision"] as? Int, 4)
    }

    func testExpiredRevisionIsReportedAsConflict() async throws {
        CloudContractProtocol.responder = { _ in (409, Data("{\"error\":\"谱面已经更新\"}".utf8)) }
        do {
            _ = try await client().patchNotes(jobID: "1096a6c1-32ce-4d06-a72f-e565700ecde2", score: 0,
                                             revision: 1, edits: [["delete": true]])
            XCTFail("A stale edit must not appear successful")
        } catch let error as CloudOMRError {
            XCTAssertEqual(error.status, 409)
            XCTAssertEqual(error.code, "revision_conflict")
        }
    }

    func testProxyFailureAndMalformedSuccessRequireRevisionRecheck() async throws {
        for response in [(504, Data("gateway timeout".utf8)), (502, Data()), (200, Data("{\"revision\":".utf8)),
                         (200, Data("[]".utf8)), (200, Data("{\"revision\":3}".utf8))] {
            CloudContractProtocol.responder = { _ in response }
            do {
                _ = try await client().replaceScore(jobID: "1096a6c1-32ce-4d06-a72f-e565700ecde2", score: 0,
                                                   revision: 3, musicxml: "<score-partwise/>")
                XCTFail("An uncertain write response must require a fresh revision")
            } catch let error as CloudOMRError {
                XCTAssertEqual(error.code, "write_status_unknown")
                XCTAssertNil(error.status, "The transport must not invent a server revision conflict")
            }
        }
    }

    func testRejectsUnsafeJobAndScoreBeforeNetworkRequest() async throws {
        CloudContractProtocol.responder = { _ in XCTFail("Invalid paths must not reach the network"); return (500, Data()) }
        for id in ["../secret", "", "/etc/passwd", "valid-id/extra"] {
            do { _ = try await client().job(id); XCTFail("Accepted \(id)") } catch {}
        }
        for score in [-1, 64, Int.max] {
            do { _ = try await client().notes(jobID: "1096a6c1-32ce-4d06-a72f-e565700ecde2", score: score); XCTFail("Accepted score \(score)") } catch {}
        }
    }

    func testUploadFormatAndLimitMatchNewService() throws {
        XCTAssertNoThrow(try CloudOMRClient.validateUpload(data: Data("%PDF-1.7".utf8), filename: "原谱.pdf"))
        XCTAssertNoThrow(try CloudOMRClient.validateUpload(data: Data("xml".utf8), filename: "score.musicxml"))
        for name in ["../score.pdf", "score.tiff", "script.html"] {
            XCTAssertThrowsError(try CloudOMRClient.validateUpload(data: Data([1]), filename: name))
        }
        XCTAssertThrowsError(try CloudOMRClient.validateUpload(data: Data(), filename: "score.pdf"))
        XCTAssertThrowsError(try CloudOMRClient.validateUpload(data: Data(count: CloudOMRClient.maximumUploadBytes + 1), filename: "score.pdf"))
    }

    func testNativeBridgeOriginRejectsRemoteAndCredentialURLs() {
        XCTAssertTrue(FigmaResourceHandler.isTrusted(URL(string: "notelite-ui://app/index.html")))
        for value in ["https://app/index.html", "file:///app/index.html", "notelite-ui://remote/index.html",
                      "notelite-ui://user@app/index.html", "notelite-ui://app:443/index.html"] {
            XCTAssertFalse(FigmaResourceHandler.isTrusted(URL(string: value)), value)
        }
    }

    func testBundledResourcesRejectTraversalAndEscapingSymlink() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let root = directory.appendingPathComponent("FigmaUI")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try Data("<html/>".utf8).write(to: root.appendingPathComponent("index.html"))
        try Data("private".utf8).write(to: directory.appendingPathComponent("private.txt"))
        try FileManager.default.createSymbolicLink(at: root.appendingPathComponent("escape.txt"),
                                                   withDestinationURL: directory.appendingPathComponent("private.txt"))
        XCTAssertEqual(try FigmaResourceHandler.resource(relativePath: "index.html", root: root).lastPathComponent, "index.html")
        for path in ["../private.txt", "escape.txt", "/index.html", "assets/../../private.txt", "..\\private.txt"] {
            XCTAssertThrowsError(try FigmaResourceHandler.resource(relativePath: path, root: root), path)
        }
    }
}

/// A transport substitute verifies Apple request contracts; it does not pretend to recognize music.
private final class CloudContractProtocol: URLProtocol {
    static var responder: ((URLRequest) -> (Int, Data))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    static func body(_ request: URLRequest) -> Data {
        if let body = request.httpBody { return body }
        guard let stream = request.httpBodyStream else { return Data() }
        stream.open()
        defer { stream.close() }
        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            if count <= 0 { break }
            data.append(contentsOf: buffer.prefix(count))
        }
        return data
    }
    override func startLoading() {
        guard let responder = Self.responder else { client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse)); return }
        let (status, data) = responder(request)
        let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: "HTTP/1.1",
                                       headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
