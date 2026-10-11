import XCTest
#if os(iOS)
import UIKit
#else
import AppKit
#endif

/// Runs the shipped Figma controls and the native orientation bridge with the
/// explicitly labelled offline example. Cloud recognition is verified separately.
final class FigmaShellUITests: XCTestCase {
    #if os(macOS)
    @MainActor
    func testMacFigmaLandscapeAndPortraitContentWindows() throws {
        continueAfterFailure = false
        executionTimeAllowance = 180
        let app = XCUIApplication()
        for size in [CGSize(width: 1440, height: 900), CGSize(width: 900, height: 1440)] {
            app.launchArguments = ["--uitesting-figma", "--uitesting-window-size=\(Int(size.width))x\(Int(size.height))"]
            app.launch()
            XCTAssertTrue(button("我的曲谱", in: app).waitForExistence(timeout: 45),
                          "The real bundled product must load at each native Mac window size")
            let web = app.webViews.firstMatch
            let actualSize = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
                abs(web.frame.width - size.width) <= 1 && abs(web.frame.height - size.height) <= 1
            }, object: web)
            let resizeResult = XCTWaiter.wait(for: [actualSize], timeout: 15)
            let window = app.windows.firstMatch.frame
            let displays = NSScreen.screens.map { screen -> [String: Any] in
                ["frame": rectValue(screen.frame), "visibleFrame": rectValue(screen.visibleFrame),
                 "scale": screen.backingScaleFactor]
            }
            let canFitOnDisplay = NSScreen.screens.contains { screen in
                window.width <= screen.visibleFrame.width && window.height <= screen.visibleFrame.height
            }
            let metrics: [String: Any] = [
                "requestedContent": ["width": size.width, "height": size.height],
                "actualWindow": rectValue(window), "actualWebView": rectValue(web.frame),
                "windowDecorationHeight": window.height - web.frame.height,
                "displayCanContainWholeWindow": canFitOnDisplay, "displays": displays,
                "screenshotLimitation": canFitOnDisplay ? "Actual native window capture" : "Actual native capture; runner display cannot contain the full tall window"
            ]
            let data = try JSONSerialization.data(withJSONObject: metrics, options: [.prettyPrinted, .sortedKeys])
            let attachment = XCTAttachment(string: String(decoding: data, as: UTF8.self))
            attachment.name = "Figma-mac-\(Int(size.width))x\(Int(size.height))-window-metrics"
            attachment.lifetime = .keepAlways
            add(attachment)
            capture(app, name: "Figma-mac-\(Int(size.width))x\(Int(size.height))-actual-window")
            XCTAssertEqual(resizeResult, .completed,
                           "Requested native content dimensions must actually reach WKWebView")
            XCTAssertEqual(window.width, web.frame.width, accuracy: 1)
            XCTAssertGreaterThanOrEqual(window.height, web.frame.height,
                                        "Window decoration may add height but must not shrink page content")
            XCTAssertTrue(app.navigationBars.allElementsBoundByIndex.isEmpty)
            app.terminate()
        }
    }

    private func rectValue(_ rect: CGRect) -> [String: CGFloat] {
        ["x": rect.minX, "y": rect.minY, "width": rect.width, "height": rect.height]
    }
    #endif

    @MainActor
    func testBundledFigmaInterfaceAndScoreOrientationRestore() throws {
        continueAfterFailure = false
        executionTimeAllowance = 300
        #if os(iOS)
        XCUIDevice.shared.orientation = .portrait
        #endif
        let app = XCUIApplication()
        app.launchArguments = ["--uitesting-figma"]
        #if os(macOS)
        let exportDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("NoteLite-Figma-export-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: exportDirectory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: exportDirectory) }
        app.launchEnvironment["NOTELITE_UI_EXPORT_DIRECTORY"] = exportDirectory.path
        #endif
        app.launch()
        let libraryTab = button("我的曲谱", in: app)
        XCTAssertTrue(libraryTab.waitForExistence(timeout: 45), "Bundled Figma JavaScript and local fonts must load in WKWebView")
        XCTAssertTrue(app.navigationBars.allElementsBoundByIndex.isEmpty, "Native navigation bars must not alter the Figma viewport")
        capture(app, name: "Figma-library-portrait")
        libraryTab.tap()
        let importButton = button("导入曲谱", in: app)
        let sample = button("载入示例曲谱", in: app)
        if !sample.waitForExistence(timeout: 3) {
            XCTAssertTrue(importButton.waitForExistence(timeout: 10))
            importButton.tap()
        }
        let sampleAvailable = sample.waitForExistence(timeout: 10)
        capture(app, name: "Figma-import-panel-after-tap")
        if !sampleAvailable {
            let hierarchy = XCTAttachment(string: app.debugDescription)
            hierarchy.name = "Figma-import-panel-missing-actual-hierarchy"
            hierarchy.lifetime = .keepAlways
            add(hierarchy)
        }
        XCTAssertTrue(sampleAvailable, "The local example must remain available without cloud credentials")
        sample.tap()
        let viewScore = button("查看曲谱", in: app)
        XCTAssertTrue(viewScore.waitForExistence(timeout: 15))
        viewScore.tap()
        let close = button("‹ 我的曲谱", in: app)
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
            let englishCancel = app.buttons.matching(identifier: "Cancel").firstMatch
            let cancel = englishCancel.waitForExistence(timeout: 2) ? englishCancel : app.buttons.matching(identifier: "取消").firstMatch
            XCTAssertTrue(cancel.waitForExistence(timeout: 20), "The production export must open a native save window")
            cancel.tap()
            let released = XCTNSPredicateExpectation(predicate: NSPredicate(format: "enabled == true"), object: download)
            XCTAssertEqual(XCTWaiter.wait(for: [released], timeout: 10), .completed,
                           "Cancel must release the pending export and permit another export")
        }
        #if os(macOS)
        // Save on the third attempt, after the real two cancellations above.
        // This verifies bytes on disk, rather than only a success message.
        download.tap()
        let save = app.buttons.matching(identifier: "Save").firstMatch
        XCTAssertTrue(save.waitForExistence(timeout: 20))
        save.tap()
        XCTAssertTrue(text("文件已导出。", in: app).waitForExistence(timeout: 15))
        let exports = try FileManager.default.contentsOfDirectory(at: exportDirectory, includingPropertiesForKeys: nil)
        XCTAssertEqual(exports.count, 1)
        let output = try XCTUnwrap(exports.first)
        XCTAssertEqual(output.pathExtension, "musicxml")
        let bytes = try Data(contentsOf: output)
        let document = try XMLDocument(data: bytes)
        XCTAssertEqual(try document.nodes(forXPath: "/score-partwise/part/measure/note").count, 4)
        XCTAssertEqual(try document.nodes(forXPath: "/score-partwise/part/measure/note/pitch/step").compactMap(\.stringValue), ["C", "D", "E", "F"])
        XCTAssertEqual(try document.nodes(forXPath: "/score-partwise/part/measure/note/pitch/octave").compactMap(\.stringValue), ["4", "4", "4", "4"])
        let exported = XCTAttachment(data: bytes, uniformTypeIdentifier: "public.xml")
        exported.name = "Figma-actual-saved-MusicXML-after-cancellation"
        exported.lifetime = .keepAlways
        add(exported)
        #endif

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
        // Some SVG static text exposes NSNumber as its AXValue on macOS.
        // Read actual string values before matching; a BEGINSWITH expression
        // over every value otherwise throws on OSMD's numeric annotations.
        let loaded = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            app.webViews.staticTexts.allElementsBoundByIndex.contains { element in
                element.label.hasPrefix("MusicXML 已载入") ||
                (element.value as? String)?.hasPrefix("MusicXML 已载入") == true
            }
        }, object: app)
        XCTAssertEqual(XCTWaiter.wait(for: [loaded], timeout: 10), .completed)
        XCTAssertTrue(text("4 个音符 / 休止符", in: app).exists)
        for (index, pitch) in ["C4", "D4", "E4", "F4"].enumerated() {
            let note = app.webViews.buttons.matching(identifier: "第 1 小节 · \(pitch) #\(index + 1)").firstMatch
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
        // WebKit on macOS reports text buttons as AXTitle while aria-label
        // buttons have AXDescription. XCTest name matching handles both.
        app.webViews.buttons.matching(identifier: label).firstMatch
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
