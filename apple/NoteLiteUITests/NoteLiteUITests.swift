import XCTest
#if os(iOS)
import UIKit
#else
import AppKit
#endif

final class NoteLiteUITests: XCTestCase {
    @MainActor
    func testImportedMusicXMLOpensBundledPracticeAndCaptureScreens() {
        continueAfterFailure = false
        // Simulator launch, accessibility snapshots and both iPad rotations
        // exceeded 120 seconds in CI while every functional assertion passed.
        executionTimeAllowance = 300
        #if os(iOS)
        XCUIDevice.shared.orientation = .portrait
        #endif
        let app = XCUIApplication()
        app.launchArguments = ["--uitesting-import-demo"]
        // The UI runner launches a separate process; pass the simulator runtime fix to it too.
        if let swiftPath = ProcessInfo.processInfo.environment["NOTELITE_SIM_SWIFT_PATH"],
           swiftPath.hasPrefix("/") {
            app.launchEnvironment["DYLD_FALLBACK_LIBRARY_PATH"] = swiftPath
        }
        app.launch()
        let score = app.descendants(matching: .any).matching(identifier: "score-row")
            .matching(NSPredicate(format: "label CONTAINS %@ OR value CONTAINS %@", "demo", "demo")).firstMatch
        XCTAssertTrue(score.waitForExistence(timeout: 15), "Bundled MusicXML must enter the real library importer")
        attach(app, name: "Library")
        score.tap()
        let practice = app.buttons["practice-start"].firstMatch
        XCTAssertTrue(practice.waitForExistence(timeout: 10), "Imported structured scores need a practice entry")
        attach(app, name: "Score-details")
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
            waitForStablePracticeLayout(app, landscape: true)
            assertPracticeControlsVisible(app)
            attach(app, name: "Practice-landscape")
            XCUIDevice.shared.orientation = .portrait
            let portrait = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
                app.frame.height > app.frame.width
            }, object: app)
            XCTAssertEqual(XCTWaiter.wait(for: [portrait], timeout: 10), .completed)
            waitForStablePracticeLayout(app, landscape: false)
        }
        #endif
        let back = app.buttons.matching(identifier: "practice-close").firstMatch
        XCTAssertTrue(back.isHittable, "The return control must stay on screen")
        back.tap()
        let closed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: app.webViews.firstMatch)
        XCTAssertEqual(XCTWaiter.wait(for: [closed], timeout: 10), .completed,
                       "Returning must dismiss practice and release the bundled renderer")
        XCTAssertTrue(app.buttons["practice-start"].firstMatch.waitForExistence(timeout: 5),
                      "Returning must restore the score details")
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
        // The practice sheet is taller than the library window underneath it.
        // Compare controls with the native presentation that actually owns them.
        let sheets = app.sheets.containing(.button, identifier: "practice-close")
        let sheet = sheets.firstMatch
        let screen = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screen.name = "Practice-native-presentation-actual-screen"
        screen.lifetime = .keepAlways
        add(screen)
        let hierarchy = XCTAttachment(string: app.debugDescription)
        hierarchy.name = "Practice-native-presentation-actual-hierarchy"
        hierarchy.lifetime = .keepAlways
        add(hierarchy)
        XCTAssertTrue(sheet.waitForExistence(timeout: 5),
                      "The practice controls must belong to the actual native sheet")
        XCTAssertEqual(sheets.count, 1, "Only one active sheet may own the practice controls")
        let renderer = sheet.webViews.firstMatch
        XCTAssertTrue(renderer.exists, "The native sheet must contain the real practice renderer")
        let frame = sheet.frame
        XCTAssertGreaterThan(frame.width, 0)
        XCTAssertGreaterThan(frame.height, 0)
        let bounds = frame.insetBy(dx: -1, dy: -1)
        XCTAssertTrue(bounds.contains(renderer.frame), "The full renderer must fit inside its native sheet")
        XCTAssertTrue(bounds.contains(start.frame), "The whole start control must fit inside its native sheet")
        XCTAssertTrue(bounds.contains(back.frame), "The whole return control must fit inside its native sheet")
        // XCTest accessibility rectangles use a top-left global origin, while
        // AppKit display rectangles use the primary display's bottom-left origin.
        guard let primaryTop = NSScreen.screens.first?.frame.maxY else {
            XCTFail("A real display is required to verify the complete practice sheet")
            return
        }
        let screenFrame = CGRect(x: frame.minX, y: primaryTop - frame.maxY,
                                 width: frame.width, height: frame.height)
        XCTAssertTrue(NSScreen.screens.contains { display in
            display.visibleFrame.insetBy(dx: -1, dy: -1).contains(screenFrame)
        }, "The full native practice sheet must remain above the Dock and inside a visible display")
        #endif
    }

    #if os(iOS)
    @MainActor
    private func waitForStablePracticeLayout(_ app: XCUIApplication, landscape: Bool) {
        var previousWindow = CGRect.null
        var previousWebView = CGRect.null
        var stableSamples = 0
        let settled = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            let window = app.windows.firstMatch.frame
            let webView = app.webViews.firstMatch.frame
            guard (window.width > window.height) == landscape,
                  (webView.width > webView.height) == landscape,
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
        // One CI accessibility query took 9.16 seconds after rotation. Allow
        // three stable samples while keeping orientation and containment checks.
        XCTAssertEqual(XCTWaiter.wait(for: [settled], timeout: 30), .completed,
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
