import XCTest
#if os(iOS)
import UIKit
#endif

final class NoteLiteUITests: XCTestCase {
    @MainActor
    func testImportedMusicXMLOpensBundledPracticeAndCaptureScreens() {
        let app = XCUIApplication()
        app.launchArguments = ["--uitesting-import-demo"]
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
            assertPracticeControlsVisible(app)
            attach(app, name: "Practice-landscape")
            XCUIDevice.shared.orientation = .portrait
            let portrait = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
                app.frame.height > app.frame.width
            }, object: app)
            XCTAssertEqual(XCTWaiter.wait(for: [portrait], timeout: 10), .completed)
        }
        #endif
        let back = app.buttons.matching(identifier: "曲谱").firstMatch
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
        let back = app.buttons.matching(identifier: "曲谱").firstMatch
        XCTAssertTrue(start.waitForExistence(timeout: 5))
        XCTAssertTrue(start.isHittable, "The bottom practice control must not be clipped")
        XCTAssertTrue(back.isHittable, "The native return control must not be clipped")
        #if os(macOS)
        let windowBottom = app.windows.firstMatch.frame.maxY
        XCTAssertLessThanOrEqual(start.frame.maxY, windowBottom + 1)
        XCTAssertLessThanOrEqual(back.frame.maxY, windowBottom + 1)
        #endif
    }

    @MainActor
    private func attach(_ app: XCUIApplication, name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
