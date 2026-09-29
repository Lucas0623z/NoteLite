import XCTest
#if os(iOS)
import UIKit
#endif

/// Documentation-only capture suite. A mock-data watermark is included by the opt-in app route.
final class UICatalogUITests: XCTestCase {
    @MainActor
    func testCatalogMainPages() {
        captureScenes(["empty", "library", "detail-new", "detail-running", "detail-failed", "detail-ready"])
    }

    @MainActor
    func testCatalogNavigationAndOverlays() {
        captureScenes(["part-picker", "source-preview", "settings", "privacy", "history"])
    }

    @MainActor
    func testCatalogRemainingPages() {
        captureScenes(["review", "error-alert"])
    }

    @MainActor
    private func captureScenes(_ scenes: [String]) {
        continueAfterFailure = false
        executionTimeAllowance = 900
        #if os(iOS)
        XCUIDevice.shared.orientation = .portrait
        #endif
        for scene in scenes {
            let app = XCUIApplication()
            app.launchArguments = ["--ui-catalog"]
            app.launchEnvironment["NOTELITE_UI_CATALOG_SCENE"] = scene
            app.launchEnvironment["TZ"] = "UTC"
            if let swiftPath = ProcessInfo.processInfo.environment["NOTELITE_SIM_SWIFT_PATH"], swiftPath.hasPrefix("/") {
                app.launchEnvironment["DYLD_FALLBACK_LIBRARY_PATH"] = swiftPath
            }
            app.launch()
            XCTAssertTrue(app.staticTexts["catalog-ready"].firstMatch.waitForExistence(timeout: 20), scene)
            if scene == "review" {
                let row = app.descendants(matching: .any).matching(identifier: "catalog-history-row").firstMatch
                if row.waitForExistence(timeout: 10) { row.tap() }
            }
            waitForScene(scene, app: app)
            // The screenshot includes the real scroll view. Bring controls into the viewport
            // for feedback/result scenes instead of capturing only their large PDF preview.
            if ["detail-running", "detail-failed", "detail-ready"].contains(scene) {
                #if os(iOS)
                if UIDevice.current.userInterfaceIdiom == .phone { app.swipeUp() }
                #endif
            }
            attach(app, scene: scene, variant: "portrait")
            #if os(iOS)
            if scene == "library", UIDevice.current.userInterfaceIdiom == .pad {
                XCUIDevice.shared.orientation = .landscapeLeft
                let rotated = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
                    app.frame.width > app.frame.height
                }, object: app)
                XCTAssertEqual(XCTWaiter.wait(for: [rotated], timeout: 15), .completed)
                attach(app, scene: scene, variant: "landscape")
                XCUIDevice.shared.orientation = .portrait
            }
            #endif
            app.terminate()
        }
    }

    @MainActor
    private func waitForScene(_ scene: String, app: XCUIApplication) {
        let element: XCUIElement
        switch scene {
        case "empty": element = app.staticTexts["导入第一份曲谱"].firstMatch
        case "library": element = app.descendants(matching: .any).matching(identifier: "score-row").firstMatch
        case "detail-new", "detail-failed": element = app.buttons["recognition-start"].firstMatch
        case "detail-running":
            #if os(macOS)
            element = app.buttons["暂停跟踪"].firstMatch
            #else
            element = app.buttons["停止识谱"].firstMatch
            #endif
        case "detail-ready": element = app.buttons["practice-start"].firstMatch
        case "part-picker": element = app.buttons.matching(NSPredicate(format: "label == %@ OR identifier == %@", "第 1 部分", "practice-part-练习曲.mvt1.musicxml")).firstMatch
        case "source-preview": element = app.buttons["完成"].firstMatch
        case "settings": element = app.buttons["检查服务器连接"].firstMatch
        case "privacy": element = app.descendants(matching: .any).matching(identifier: "catalog-privacy-content").firstMatch
        case "history": element = app.descendants(matching: .any).matching(identifier: "catalog-history-content").firstMatch
        case "review": element = app.descendants(matching: .any).matching(identifier: "catalog-review-content").firstMatch
        case "error-alert": element = app.alerts.firstMatch
        default: XCTFail("Unknown scene: \(scene)"); return
        }
        // AX containers differ between OS releases. A named attachment is a capture candidate;
        // visual review, not the existence of a section header, determines final catalog inclusion.
        _ = element.waitForExistence(timeout: 5)
        // Allow sheet/stack animation and PDF rendering to settle after AX content appears.
        Thread.sleep(forTimeInterval: 1)
    }

    @MainActor
    private func attach(_ app: XCUIApplication, scene: String, variant: String) {
        #if os(iOS)
        let family = UIDevice.current.userInterfaceIdiom == .pad ? "iPad" : "iPhone"
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        #else
        let family = "macOS"
        let attachment = XCTAttachment(screenshot: app.screenshot())
        #endif
        attachment.name = "MOCK-\(family)-\(scene)-\(variant)"
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
