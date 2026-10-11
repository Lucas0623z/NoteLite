import XCTest
#if os(iOS)
import UIKit
#endif

/// Runs the shipped Figma controls and the native orientation bridge with the
/// explicitly labelled offline example. Cloud recognition is verified separately.
final class FigmaShellUITests: XCTestCase {
    @MainActor
    func testBundledFigmaInterfaceAndScoreOrientationRestore() {
        continueAfterFailure = false
        executionTimeAllowance = 300
        #if os(iOS)
        XCUIDevice.shared.orientation = .portrait
        #endif
        let app = XCUIApplication()
        app.launchArguments = ["--uitesting-figma"]
        app.launch()
        let libraryTab = app.webViews.buttons.matching(NSPredicate(format: "label == %@ OR value == %@", "我的曲谱", "我的曲谱")).firstMatch
        XCTAssertTrue(libraryTab.waitForExistence(timeout: 45), "Bundled Figma JavaScript and local fonts must load in WKWebView")
        XCTAssertTrue(app.navigationBars.allElementsBoundByIndex.isEmpty, "Native navigation bars must not alter the Figma viewport")
        capture(app, name: "Figma-library-portrait")
        libraryTab.tap()
        let importButton = app.webViews.buttons.matching(NSPredicate(format: "label == %@ OR value == %@", "导入曲谱", "导入曲谱")).firstMatch
        let sample = app.webViews.buttons.matching(NSPredicate(format: "label == %@ OR value == %@", "载入示例曲谱", "载入示例曲谱")).firstMatch
        if !sample.waitForExistence(timeout: 3) {
            XCTAssertTrue(importButton.waitForExistence(timeout: 10))
            importButton.tap()
        }
        XCTAssertTrue(sample.waitForExistence(timeout: 10), "The local example must remain available without cloud credentials")
        sample.tap()
        let viewScore = app.webViews.buttons.matching(NSPredicate(format: "label == %@ OR value == %@", "查看曲谱", "查看曲谱")).firstMatch
        XCTAssertTrue(viewScore.waitForExistence(timeout: 15))
        viewScore.tap()
        let close = app.webViews.buttons.matching(NSPredicate(format: "label == %@ OR value == %@", "‹ 我的曲谱", "‹ 我的曲谱")).firstMatch
        XCTAssertTrue(close.waitForExistence(timeout: 30))
        assertScoreRendered(app)
        #if os(iOS)
        let landscape = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            app.frame.width > app.frame.height
        }, object: app)
        XCTAssertEqual(XCTWaiter.wait(for: [landscape], timeout: 20), .completed,
                       "Opening the production score view must request actual device landscape")
        XCTAssertTrue(close.isHittable)
        capture(app, name: "Figma-score-native-landscape")
        #else
        XCTAssertTrue(close.isHittable)
        capture(app, name: "Figma-score-mac-window")
        #endif
        close.tap()
        XCTAssertTrue(viewScore.waitForExistence(timeout: 10), "Closing restores the saved library cards")
        #if os(iOS)
        let portrait = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            app.frame.height > app.frame.width
        }, object: app)
        XCTAssertEqual(XCTWaiter.wait(for: [portrait], timeout: 20), .completed,
                       "Closing the score view must restore the original interface direction")
        capture(app, name: "Figma-library-restored-portrait")
        #endif

        // Relaunch through the real production entry: the card and its XML must
        // come from IndexedDB, rather than only the previous React state.
        app.terminate()
        app.launch()
        XCTAssertTrue(libraryTab.waitForExistence(timeout: 45))
        libraryTab.tap()
        XCTAssertTrue(viewScore.waitForExistence(timeout: 15), "The example must persist across application relaunch")
        viewScore.tap()
        assertScoreRendered(app)
        assertLandscape(app)

        // Cancel is a real native picker path. Reopening immediately proves the
        // previous export released its continuation without waiting for JS timeout.
        let download = button("下载当前曲谱", in: app)
        for _ in 0..<2 {
            XCTAssertTrue(download.waitForExistence(timeout: 10))
            download.tap()
            let cancel = app.buttons.matching(NSPredicate(format: "label == %@ OR label == %@", "Cancel", "取消")).firstMatch
            XCTAssertTrue(cancel.waitForExistence(timeout: 20), "The production export must open a native save window")
            cancel.tap()
            let released = XCTNSPredicateExpectation(predicate: NSPredicate(format: "enabled == true"), object: download)
            XCTAssertEqual(XCTWaiter.wait(for: [released], timeout: 10), .completed,
                           "Cancel must release the pending export and permit another export")
        }

        let startPractice = button("开始练习", in: app)
        XCTAssertTrue(startPractice.waitForExistence(timeout: 10))
        startPractice.tap()
        XCTAssertTrue(text("练琴时刻", in: app).waitForExistence(timeout: 10))
        XCTAssertTrue(text("自由练习计时 · 不含演奏评分", in: app).exists)
        XCTAssertTrue(text("演奏设备 · 尚未连接", in: app).exists,
                      "The reviewed UI must not claim an audio engine is connected")
        capture(app, name: "Figma-practice-awaiting-audio")
        let returnToEditing = button("返回曲谱校对", in: app)
        XCTAssertTrue(returnToEditing.waitForExistence(timeout: 10))
        returnToEditing.tap()
        XCTAssertTrue(text("曲谱预览与校对", in: app).waitForExistence(timeout: 10))
        assertScoreRendered(app)
        close.tap()
        XCTAssertTrue(viewScore.waitForExistence(timeout: 10))
        #if os(iOS)
        let restored = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            app.frame.height > app.frame.width
        }, object: app)
        XCTAssertEqual(XCTWaiter.wait(for: [restored], timeout: 20), .completed)
        #endif
    }

    @MainActor
    private func assertScoreRendered(_ app: XCUIApplication) {
        let rendered = app.webViews.descendants(matching: .any)
            .matching(NSPredicate(format: "label == %@ OR value == %@", "MusicXML 谱面", "MusicXML 谱面")).firstMatch
        XCTAssertTrue(rendered.waitForExistence(timeout: 60),
                      "The actual OSMD dynamic module must load and render the MusicXML SVG")
        let loaded = app.webViews.staticTexts
            .matching(NSPredicate(format: "label BEGINSWITH %@ OR value BEGINSWITH %@", "MusicXML 已载入", "MusicXML 已载入")).firstMatch
        XCTAssertTrue(loaded.waitForExistence(timeout: 10))
        XCTAssertTrue(text("4 个音符 / 休止符", in: app).exists)
        for pitch in ["C4", "D4", "E4", "F4"] {
            let note = app.webViews.buttons.matching(NSPredicate(format: "label CONTAINS %@ OR value CONTAINS %@", "小节 · \(pitch)", "小节 · \(pitch)")).firstMatch
            XCTAssertTrue(note.exists, "The XML must provide an actual \(pitch) note for editing")
        }
    }

    @MainActor
    private func assertLandscape(_ app: XCUIApplication) {
        #if os(iOS)
        let landscape = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            app.frame.width > app.frame.height
        }, object: app)
        XCTAssertEqual(XCTWaiter.wait(for: [landscape], timeout: 20), .completed)
        #endif
    }

    @MainActor
    private func button(_ label: String, in app: XCUIApplication) -> XCUIElement {
        app.webViews.buttons.matching(NSPredicate(format: "label == %@ OR value == %@", label, label)).firstMatch
    }

    @MainActor
    private func text(_ label: String, in app: XCUIApplication) -> XCUIElement {
        app.webViews.staticTexts.matching(NSPredicate(format: "label == %@ OR value == %@", label, label)).firstMatch
    }

    @MainActor
    private func capture(_ app: XCUIApplication, name: String) {
        #if os(iOS)
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        #else
        let attachment = XCTAttachment(screenshot: app.screenshot())
        #endif
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
