import XCTest

/// Exercises the actual on-device raster/algorithm slice without a server URL.
/// Successful preprocessing is deliberately distinct from score recognition.
final class LocalOMRUITests: XCTestCase {
    @MainActor
    func testLocalPreprocessingWithoutServer() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launch()
        try skipLegacySelectorsForRedesignedMobileUI(app)
        let entry = app.descendants(matching: .any).matching(identifier: "local-omr-open").firstMatch
        if !entry.exists {
            // The library toolbar exposes debug actions in its menu.
            let menu = app.descendants(matching: .any).matching(identifier: "library-menu").firstMatch
            XCTAssertTrue(menu.waitForExistence(timeout: 10))
            menu.tap()
        }
        XCTAssertTrue(entry.waitForExistence(timeout: 10))
        entry.tap()
        XCTAssertTrue(app.staticTexts["local-omr-incomplete"].waitForExistence(timeout: 5))
        app.buttons["local-omr-demo"].tap()
        let run = app.buttons["local-omr-run"].firstMatch
        XCTAssertTrue(run.waitForExistence(timeout: 10))
        let enabled = XCTNSPredicateExpectation(predicate: NSPredicate(format: "enabled == true"), object: run)
        XCTAssertEqual(XCTWaiter.wait(for: [enabled], timeout: 10), .completed)
        run.tap()
        XCTAssertTrue(app.staticTexts["local-omr-result"].waitForExistence(timeout: 30))
        #if os(iOS)
        let shot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        #else
        let shot = XCTAttachment(screenshot: app.screenshot())
        #endif
        shot.name = "Audiveris-local-preprocessing"
        shot.lifetime = .keepAlways
        add(shot)
    }
}
