import XCTest
#if os(iOS)
import UIKit
#endif

final class NoteLiteUITests: XCTestCase {
    @MainActor
    func testImportedMusicXMLOpensBundledPracticeAndCaptureScreens() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["--uitesting-import-demo"]
        // The UI runner launches a separate process; pass the simulator runtime fix to it too.
        if let swiftPath = ProcessInfo.processInfo.environment["NOTELITE_SIM_SWIFT_PATH"],
           swiftPath.hasPrefix("/") {
            app.launchEnvironment["DYLD_FALLBACK_LIBRARY_PATH"] = swiftPath
        }
        app.launch()
        let score = app.descendants(matching: .any).matching(identifier: "score-row").firstMatch
        XCTAssertTrue(score.waitForExistence(timeout: 15), "Bundled MusicXML must enter the real library importer")
        attach(app, name: "Library")
        score.tap()
        let practice = app.buttons["practice-start"].firstMatch
        XCTAssertTrue(practice.waitForExistence(timeout: 10), "Imported structured scores need a practice entry")
        practice.tap()
        // WebKit exposes HTML text as `value` on macOS and `label` on iOS.
        let title = app.webViews.staticTexts.matching(NSPredicate(
            format: "label CONTAINS %@ OR value CONTAINS %@", "晨光练习曲", "晨光练习曲")).firstMatch
        XCTAssertTrue(title.waitForExistence(timeout: 30), "The native bridge must load MusicXML into the bundled renderer")
        assertPracticeControlsVisible(app)
        attach(app, name: "Practice")
        #if os(iOS)
        if UIDevice.current.userInterfaceIdiom == .pad {
            XCUIDevice.shared.orientation = .landscapeLeft
            let landscape = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
                app.frame.width > app.frame.height
            }, object: app)
            XCTAssertEqual(XCTWaiter.wait(for: [landscape], timeout: 10), .completed,
                           "The iPad practice screen must rotate before capture")
            waitForStableLandscapeLayout(app)
            assertPracticeControlsVisible(app)
            attach(app, name: "Practice-landscape")
            XCUIDevice.shared.orientation = .portrait
            let portrait = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
                app.frame.height > app.frame.width
            }, object: app)
            XCTAssertEqual(XCTWaiter.wait(for: [portrait], timeout: 10), .completed)
        }
        #endif
        let back = app.buttons.matching(identifier: "practice-close").firstMatch
        XCTAssertTrue(back.isHittable, "The return control must stay on screen")
        back.tap()
        let closed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: app.webViews.firstMatch)
        XCTAssertEqual(XCTWaiter.wait(for: [closed], timeout: 10), .completed,
                       "Returning must dismiss practice and release the bundled renderer")
    }

    @MainActor
    private func assertPracticeControlsVisible(_ app: XCUIApplication) {
        // matching(identifier:) also matches the AX title/value observed in the macOS snapshot.
        let start = app.webViews.buttons.matching(identifier: "开始练习").firstMatch
        let back = app.buttons.matching(identifier: "practice-close").firstMatch
        XCTAssertTrue(start.waitForExistence(timeout: 5))
        XCTAssertTrue(start.isHittable, "The bottom practice control must not be clipped")
        XCTAssertTrue(back.isHittable, "The native return control must not be clipped")
        #if os(macOS)
        let windowBottom = app.windows.firstMatch.frame.maxY
        XCTAssertLessThanOrEqual(start.frame.maxY, windowBottom + 1)
        XCTAssertLessThanOrEqual(back.frame.maxY, windowBottom + 1)
        #endif
    }

    #if os(iOS)
    @MainActor
    private func waitForStableLandscapeLayout(_ app: XCUIApplication) {
        var previousWindow = CGRect.null
        var previousWebView = CGRect.null
        var stableSamples = 0
        let settled = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            let window = app.windows.firstMatch.frame
            let webView = app.webViews.firstMatch.frame
            guard window.width > window.height, webView.width > webView.height,
                  window.contains(webView) else {
                stableSamples = 0
                return false
            }
            if window == previousWindow && webView == previousWebView {
                stableSamples += 1
            } else {
                previousWindow = window
                previousWebView = webView
                stableSamples = 0
            }
            return stableSamples >= 2
        }, object: app)
        XCTAssertEqual(XCTWaiter.wait(for: [settled], timeout: 10), .completed,
                       "The rotated window and score renderer must finish resizing before capture")
    }
    #endif

    @MainActor
    private func attach(_ app: XCUIApplication, name: String) {
        #if os(iOS)
        // Capture the whole display; app-frame cropping can be wrong after device rotation.
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        #else
        let attachment = XCTAttachment(screenshot: app.screenshot())
        #endif
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
