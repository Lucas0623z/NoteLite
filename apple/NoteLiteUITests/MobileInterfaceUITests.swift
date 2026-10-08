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
        let demo = app.webViews.staticTexts.matching(NSPredicate(format: "label == %@ OR value == %@", "demo.musicxml", "demo.musicxml")).firstMatch
        let start = app.webViews.buttons.matching(identifier: "开始练习 demo.musicxml").firstMatch
        // The real launch import publishes asynchronously and returns to the library when it finishes.
        // Finish that import before navigating so it cannot replace the first selected page.
        XCTAssertTrue(demo.waitForExistence(timeout: 30), "Real MusicXML importer must feed the new library")
        waitUntilVisible(start, message: "Imported MusicXML must be ready to practice before navigating")
        XCTAssertTrue(start.isEnabled)
        for tab in ["官方曲谱", "练习记录", "黑白键AI", "账号", "我的曲谱"] {
            let button = app.webViews.buttons.matching(identifier: tab).firstMatch
            XCTAssertTrue(button.waitForExistence(timeout: 10), "Missing navigation: \(tab)")
            XCTAssertTrue(button.isHittable, "Navigation must stay reachable above the home indicator")
            button.tap()
            let marker = pageMarker(tab, in: app)
            attachAfterRender(name: "Mobile-\(tab)", marker: marker, visibleControls: [button])
        }
        verifyImportMenu(app)
        XCTAssertTrue(demo.waitForExistence(timeout: 20))
        XCTAssertTrue(start.waitForExistence(timeout: 10))
        start.tap()
        let title = app.webViews.staticTexts.matching(NSPredicate(format: "label CONTAINS %@ OR value CONTAINS %@", "晨光练习曲", "晨光练习曲")).firstMatch
        XCTAssertTrue(title.waitForExistence(timeout: 40), "Imported MusicXML must reach the local renderer")
        assertPracticeControls(app)
        attachAfterRender(name: "Mobile-native-practice", marker: title)
        if UIDevice.current.userInterfaceIdiom == .pad {
            XCUIDevice.shared.orientation = .landscapeLeft
            let landscape = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in app.frame.width > app.frame.height }, object: app)
            XCTAssertEqual(XCTWaiter.wait(for: [landscape], timeout: 15), .completed)
            assertPracticeControls(app)
            attachAfterRender(name: "Mobile-native-practice-iPad-landscape", marker: title)
            XCUIDevice.shared.orientation = .portrait
        }
        app.buttons["practice-close"].firstMatch.tap()
        XCTAssertTrue(demo.waitForExistence(timeout: 15), "Closing practice must restore the redesigned library")
        XCTAssertTrue(app.webViews.buttons["我的曲谱"].firstMatch.isHittable)
        attachAfterRender(name: "Mobile-library-after-practice", marker: start)
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
        attachAfterRender(name: "Mobile-saved-second-part", marker: title)
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
    @MainActor private func pageMarker(_ tab: String, in app: XCUIApplication) -> XCUIElement {
        switch tab {
        case "官方曲谱": return app.webViews.buttons["选择阶段和部分"].firstMatch
        case "练习记录": return app.webViews.buttons["练琴日历"].firstMatch
        case "黑白键AI": return app.webViews.buttons["分析我的练琴记录"].firstMatch
        case "账号": return app.webViews.staticTexts.matching(NSPredicate(format: "label CONTAINS %@ OR value CONTAINS %@", "本机档案", "本机档案")).firstMatch
        default: return app.webViews.buttons["导入乐谱"].firstMatch
        }
    }
    @MainActor private func verifyImportMenu(_ app: XCUIApplication) {
        app.webViews.buttons["导入乐谱"].firstMatch.tap()
        let hero = app.webViews.buttons["上传文件、图片或拍照识谱，开启你的专属陪练"].firstMatch
        attachAfterRender(name: "Mobile-import-landing", marker: hero)
        hero.tap()
        for label in ["选择文件", "从相册选择", "拍照识谱", "载入示例曲谱", "取消"] {
            waitUntilVisible(app.webViews.buttons[label].firstMatch, message: "Missing import option: \(label)")
        }
        let cancel = app.webViews.buttons["取消"].firstMatch
        attachAfterRender(name: "Mobile-import-menu", marker: cancel)
        cancel.tap()
        let dismissed = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in !cancel.exists }, object: app)
        XCTAssertEqual(XCTWaiter.wait(for: [dismissed], timeout: 10), .completed, "Import menu must dismiss")
        let back = app.webViews.buttons["返回我的曲谱"].firstMatch
        waitUntilVisible(back, message: "Import landing must retain a way back to the library")
        back.tap()
        waitUntilVisible(pageMarker("我的曲谱", in: app), message: "Import landing must return to the library")
    }
    @MainActor private func waitUntilVisible(_ element: XCUIElement, message: String) {
        XCTAssertTrue(element.waitForExistence(timeout: 20), message)
        let visible = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in element.exists && element.isHittable }, object: element)
        XCTAssertEqual(XCTWaiter.wait(for: [visible], timeout: 20), .completed, message)
    }
    private struct RenderedScreen {
        let width: Int
        let height: Int
        let pixels: [UInt8]
    }
    @MainActor private func renderedScreen(_ screenshot: XCUIScreenshot) -> RenderedScreen? {
        guard let image = screenshot.image.cgImage, let colorSpace = CGColorSpace(name: CGColorSpace.sRGB) else { return nil }
        let scale = min(1, 768 / Double(max(image.width, image.height)))
        let width = max(1, Int((Double(image.width) * scale).rounded()))
        let height = max(1, Int((Double(image.height) * scale).rounded()))
        var pixels = [UInt8](repeating: 0, count: width * height * 4)
        let rendered = pixels.withUnsafeMutableBytes { bytes -> Bool in
            guard let context = CGContext(data: bytes.baseAddress, width: width, height: height,
                bitsPerComponent: 8, bytesPerRow: width * 4, space: colorSpace,
                bitmapInfo: CGBitmapInfo.byteOrder32Big.rawValue | CGImageAlphaInfo.premultipliedLast.rawValue) else { return false }
            context.interpolationQuality = .high
            let bounds = CGRect(x: 0, y: 0, width: CGFloat(width), height: CGFloat(height))
            context.setFillColor(red: 1, green: 1, blue: 1, alpha: 1)
            context.fill(bounds)
            context.draw(image, in: bounds)
            return true
        }
        return rendered ? RenderedScreen(width: width, height: height, pixels: pixels) : nil
    }
    private func sameRendering(_ previous: RenderedScreen, _ current: RenderedScreen) -> Bool {
        guard previous.width == current.width, previous.height == current.height else { return false }
        // Ignore at most 8/255 of channel noise, and at most 0.01% of visibly changed pixels.
        // A navigation transition or a missing image changes far more than this small allowance.
        let allowedChangedPixels = max(1, Int(Double(current.width * current.height) * 0.0001))
        var changedPixels = 0
        for offset in stride(from: 0, to: current.pixels.count, by: 4) {
            if (0..<3).contains(where: { abs(Int(previous.pixels[offset + $0]) - Int(current.pixels[offset + $0])) > 8 }) {
                changedPixels += 1
                if changedPixels > allowedChangedPixels { return false }
            }
        }
        return true
    }
    @MainActor private func attachAfterRender(name: String, marker: XCUIElement, visibleControls: [XCUIElement] = []) {
        waitUntilVisible(marker, message: "Selected screen must be visible before capturing \(name)")
        var previousScreen: RenderedScreen?
        var settledScreenshot: XCUIScreenshot?
        // DOM accessibility can update before WebKit finishes painting local images and navigation.
        // Compare consecutive decoded sRGB screen samples, without relying on PNG encoding bytes.
        let settled = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            guard marker.exists && marker.isHittable && visibleControls.allSatisfy({ $0.exists && $0.isHittable }) else {
                previousScreen = nil
                return false
            }
            let screenshot = XCUIScreen.main.screenshot()
            guard let screen = self.renderedScreen(screenshot) else {
                previousScreen = nil
                return false
            }
            let matchesPrevious = previousScreen.map { self.sameRendering($0, screen) } ?? false
            previousScreen = screen
            if matchesPrevious { settledScreenshot = screenshot }
            return matchesPrevious
        }, object: marker)
        XCTAssertEqual(XCTWaiter.wait(for: [settled], timeout: 20), .completed, "Screen must finish painting before capturing \(name)")
        guard let screenshot = settledScreenshot else { return }
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
#endif
