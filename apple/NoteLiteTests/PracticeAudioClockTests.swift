import XCTest
import WebKit
@testable import NoteLite

final class PracticeAudioClockTests: XCTestCase {
    @MainActor
    func testAudioClockReadsFiniteMonotonicValuesFromWebKit() async throws {
        let controller = PracticeWebController()
        let loaded = expectation(description: "Local clock verification page finished loading")
        let observer = ClockPageObserver(loaded: loaded)
        controller.webView.navigationDelegate = observer
        defer {
            controller.webView.stopLoading()
            controller.webView.navigationDelegate = controller
        }
        controller.webView.loadHTMLString("<!doctype html><html><body>Local clock verification</body></html>", baseURL: nil)
        await fulfillment(of: [loaded], timeout: 15)
        if let error = observer.error { throw error }

        // Use the same entry point as microphone clock synchronization, without requesting microphone access.
        let first = try await controller.readJavaScriptAudioClock()
        let second = try await controller.readJavaScriptAudioClock()
        XCTAssertTrue(first.isFinite)
        XCTAssertGreaterThanOrEqual(first, 0)
        XCTAssertTrue(second.isFinite)
        XCTAssertGreaterThanOrEqual(second, first)
    }
}

@MainActor
private final class ClockPageObserver: NSObject, WKNavigationDelegate {
    let loaded: XCTestExpectation
    private(set) var error: Error?
    private var finished = false

    init(loaded: XCTestExpectation) {
        self.loaded = loaded
        super.init()
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { finish() }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { finish(error) }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { finish(error) }

    private func finish(_ error: Error? = nil) {
        guard !finished else { return }
        finished = true
        self.error = error
        loaded.fulfill()
    }
}
