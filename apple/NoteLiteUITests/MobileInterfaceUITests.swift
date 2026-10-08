#if os(iOS)
import XCTest
import UIKit

/// Runs against the bundled designer UI and native importer/practice bridge on real Apple simulators.
final class MobileInterfaceUITests: XCTestCase {
    @MainActor
    func testAllMobileTabsAndImportedMusicXMLPractice() {
        continueAfterFailure = false
        executionTimeAllowance = 360
        XCUIDevice.shared.orientation = .portrait
        let app = launch(arguments: ["--uitesting-import-demo"])
        let mobile = app.webViews.matching(identifier: "yinban-mobile-interface").firstMatch
        XCTAssertTrue(mobile.waitForExistence(timeout: 30), "Bundled MobileUI must load without an external website")
        for tab in ["官方曲谱", "练习记录", "黑白键AI", "账号", "我的曲谱"] {
            let button = app.webViews.buttons.matching(identifier: tab).firstMatch
            XCTAssertTrue(button.waitForExistence(timeout: 10), "Missing navigation: \(tab)")
            XCTAssertTrue(button.isHittable, "Navigation must stay reachable above the home indicator")
            button.tap()
            attach(name: "Mobile-\(tab)")
        }
        let demo = app.webViews.staticTexts.matching(NSPredicate(format: "label == %@ OR value == %@", "demo.musicxml", "demo.musicxml")).firstMatch
        XCTAssertTrue(demo.waitForExistence(timeout: 20), "Real MusicXML importer must feed the new library")
        let start = app.webViews.buttons.matching(identifier: "开始练习 demo.musicxml").firstMatch
        XCTAssertTrue(start.waitForExistence(timeout: 10))
        start.tap()
        let title = app.webViews.staticTexts.matching(NSPredicate(format: "label CONTAINS %@ OR value CONTAINS %@", "晨光练习曲", "晨光练习曲")).firstMatch
        XCTAssertTrue(title.waitForExistence(timeout: 40), "Imported MusicXML must reach the local renderer")
        assertPracticeControls(app)
        attach(name: "Mobile-native-practice")
        if UIDevice.current.userInterfaceIdiom == .pad {
            XCUIDevice.shared.orientation = .landscapeLeft
            let landscape = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in app.frame.width > app.frame.height }, object: app)
            XCTAssertEqual(XCTWaiter.wait(for: [landscape], timeout: 15), .completed)
            assertPracticeControls(app)
            attach(name: "Mobile-native-practice-iPad-landscape")
            XCUIDevice.shared.orientation = .portrait
        }
        app.buttons["practice-close"].firstMatch.tap()
        XCTAssertTrue(demo.waitForExistence(timeout: 15), "Closing practice must restore the redesigned library")
        XCTAssertTrue(app.webViews.buttons["我的曲谱"].firstMatch.isHittable)
        attach(name: "Mobile-library-after-practice")
    }

    @MainActor
    func testSavedMultiPartResultsRemainPlayableAfterRelaunch() throws {
        continueAfterFailure = false
        executionTimeAllowance = 360
        let bundle = Bundle(for: Self.self)
        func fixture(_ name: String) throws -> Data {
            let url = try XCTUnwrap(bundle.url(forResource: name, withExtension: nil, subdirectory: "Fixtures"))
            return try Data(contentsOf: url)
        }
        let names = ["multipage.mvt1.mxl", "multipage.mvt1.mid", "multipage.mvt2.mxl", "multipage.mvt2.mid"]
        let payload: [String: Any] = ["source": try fixture("chula.png").base64EncodedString(),
            "artifacts": try names.map { ["name": $0, "data": try fixture($0).base64EncodedString()] }]
        let app = XCUIApplication()
        app.launchArguments = ["--uitesting-import-practice-parts"]
        app.launchEnvironment["NOTELITE_UI_PRACTICE_PARTS"] = String(data: try JSONSerialization.data(withJSONObject: payload), encoding: .utf8)
        configureEnvironment(app)
        app.launch()
        let libraryTab = app.webViews.buttons["我的曲谱"].firstMatch
        XCTAssertTrue(libraryTab.waitForExistence(timeout: 30))
        libraryTab.tap()
        let fixtureTitle = app.webViews.staticTexts.matching(NSPredicate(format: "label CONTAINS %@ OR value CONTAINS %@", "多部分练习样本", "多部分练习样本")).firstMatch
        XCTAssertTrue(fixtureTitle.waitForExistence(timeout: 20))
        app.terminate()
        app.launchArguments = []
        app.launchEnvironment.removeValue(forKey: "NOTELITE_UI_PRACTICE_PARTS")
        app.launch()
        XCTAssertTrue(libraryTab.waitForExistence(timeout: 30))
        libraryTab.tap()
        XCTAssertTrue(fixtureTitle.waitForExistence(timeout: 20), "Downloaded results must persist across launches")
        let start = app.webViews.buttons["开始练习 多部分练习样本.png"].firstMatch
        XCTAssertTrue(start.waitForExistence(timeout: 10))
        start.tap()
        let second = app.buttons.matching(NSPredicate(format: "identifier == %@ AND label == %@", "mobile-practice-part", "第 2 部分")).firstMatch
        XCTAssertTrue(second.waitForExistence(timeout: 10), "All saved MusicXML results need a part selector")
        second.tap()
        let title = app.webViews.staticTexts.matching(NSPredicate(format: "label == %@ OR value == %@", "37 - CHULA PAROARA", "37 - CHULA PAROARA")).firstMatch
        XCTAssertTrue(title.waitForExistence(timeout: 45))
        assertPracticeControls(app)
        attach(name: "Mobile-saved-second-part")
        app.buttons["practice-close"].firstMatch.tap()
        XCTAssertTrue(fixtureTitle.waitForExistence(timeout: 15))
    }

    @MainActor private func launch(arguments: [String]) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = arguments
        configureEnvironment(app)
        app.launch()
        return app
    }
    @MainActor private func configureEnvironment(_ app: XCUIApplication) {
        if let swiftPath = ProcessInfo.processInfo.environment["NOTELITE_SIM_SWIFT_PATH"], swiftPath.hasPrefix("/") {
            app.launchEnvironment["DYLD_FALLBACK_LIBRARY_PATH"] = swiftPath
        }
    }
    @MainActor private func assertPracticeControls(_ app: XCUIApplication) {
        let start = app.webViews.buttons["开始练习"].firstMatch
        let close = app.buttons["practice-close"].firstMatch
        XCTAssertTrue(start.waitForExistence(timeout: 10))
        XCTAssertTrue(start.isHittable, "Local practice controls must not be clipped")
        XCTAssertTrue(close.isHittable, "Native dismissal must remain reachable")
    }
    @MainActor private func attach(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
#endif
