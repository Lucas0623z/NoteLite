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
    func testMacFigmaLandscapeContentWindow() throws {
        try assertMacWindow(CGSize(width: 1440, height: 900))
    }

    @MainActor
    func testMacFigmaPortraitContentWindow() throws {
        try assertMacWindow(CGSize(width: 900, height: 1440))
    }

    @MainActor
    private func assertMacWindow(_ size: CGSize) throws {
        continueAfterFailure = false
        executionTimeAllowance = 180
        let app = XCUIApplication()
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
        let requestedCanFit = NSScreen.screens.contains { screen in
            size.width <= screen.visibleFrame.width &&
            size.height + window.height - web.frame.height <= screen.visibleFrame.height
        }
        let metrics: [String: Any] = [
            "requestedContent": ["width": size.width, "height": size.height],
            "actualWindow": rectValue(window), "actualWebView": rectValue(web.frame),
            "windowDecorationHeight": window.height - web.frame.height,
            "displayCanContainWholeWindow": canFitOnDisplay, "displays": displays,
            "displayCanContainRequestedWindow": requestedCanFit,
            "screenshotLimitation": requestedCanFit && canFitOnDisplay ? "Actual native window capture" : "Actual native capture; runner display cannot contain the requested full window"
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

    private func rectValue(_ rect: CGRect) -> [String: CGFloat] {
        ["x": rect.minX, "y": rect.minY, "width": rect.width, "height": rect.height]
    }
    #endif

    @MainActor
    func testBundledFigmaScorePersistenceNativeFilePanelsAndPractice() throws {
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
        ensureSampleInLibrary(app)
        let viewScore = button("查看曲谱", in: app)
        XCTAssertTrue(viewScore.waitForExistence(timeout: 15))
        viewScore.tap()
        let close = button("‹ 我的曲谱", in: app)
        XCTAssertTrue(close.waitForExistence(timeout: 30))
        assertScoreRendered(app)
        assertNoteSelection(app)
        XCTAssertTrue(close.isHittable)
        capture(app, name: "Figma-score-actual-current-window")
        close.tap()
        XCTAssertTrue(viewScore.waitForExistence(timeout: 10), "Closing restores the saved library cards")

        // Relaunch through the real production entry: the card and its XML must
        // come from IndexedDB, rather than only the previous React state.
        app.terminate()
        app.launch()
        XCTAssertTrue(libraryTab.waitForExistence(timeout: 45))
        libraryTab.tap()
        XCTAssertTrue(viewScore.waitForExistence(timeout: 15), "The example must persist across application relaunch")
        viewScore.tap()
        assertScoreRendered(app)

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
    }

    #if os(iOS)
    /// Keep system geometry acceptance separate from the real persistence and
    /// file-panel flow. A windowed iPad can reject public orientation requests;
    /// that is still a strict failure here, rather than hiding other results.
    @MainActor
    func testNativeScoreAndPracticeDirectionRestore() throws {
        continueAfterFailure = false
        executionTimeAllowance = 240
        XCUIDevice.shared.orientation = .portrait
        let app = XCUIApplication()
        app.launchArguments = ["--uitesting-figma"]
        app.launch()
        let libraryTab = button("我的曲谱", in: app)
        XCTAssertTrue(libraryTab.waitForExistence(timeout: 45))
        libraryTab.tap()
        ensureSampleInLibrary(app)
        let viewScore = button("查看曲谱", in: app)
        XCTAssertTrue(viewScore.waitForExistence(timeout: 15))
        viewScore.tap()
        assertScoreRendered(app)
        assertDirection(app, landscape: true, name: "Figma-score-automatic-landscape")
        let close = button("‹ 我的曲谱", in: app)
        XCTAssertTrue(close.waitForExistence(timeout: 10))
        close.tap()
        XCTAssertTrue(viewScore.waitForExistence(timeout: 10))
        assertDirection(app, landscape: false, name: "Figma-library-score-restored-portrait")

        let practice = button("开始练习", in: app)
        XCTAssertTrue(practice.waitForExistence(timeout: 10))
        practice.tap()
        XCTAssertTrue(text("练琴时刻", in: app).waitForExistence(timeout: 20))
        assertDirection(app, landscape: true, name: "Figma-practice-automatic-landscape")
        close.tap()
        XCTAssertTrue(viewScore.waitForExistence(timeout: 10))
        assertDirection(app, landscape: false, name: "Figma-library-practice-restored-portrait")
    }
    #endif

    @MainActor
    private func ensureSampleInLibrary(_ app: XCUIApplication) {
        // Reuse a production IndexedDB card when another independent test has
        // already created it. The first empty-library run still taps the real
        // import image and the original offline sample action.
        if button("查看曲谱", in: app).waitForExistence(timeout: 3) { return }
        let importButton = button("导入曲谱", in: app)
        let sample = button("载入示例曲谱", in: app)
        if !sample.waitForExistence(timeout: 3) {
            XCTAssertTrue(importButton.waitForExistence(timeout: 10))
            importButton.tap()
        }
        let available = sample.waitForExistence(timeout: 10)
        capture(app, name: "Figma-import-panel-after-tap")
        if !available { attachHierarchy(app, name: "Figma-import-panel-missing-actual-hierarchy") }
        XCTAssertTrue(available, "The local example must remain available without cloud credentials")
        sample.tap()
    }

    @MainActor
    private func assertScoreRendered(_ app: XCUIApplication) {
        let rendered = app.webViews.descendants(matching: .any)
            .matching(NSPredicate(format: "label == %@ OR value == %@", "MusicXML 谱面", "MusicXML 谱面")).firstMatch
        XCTAssertTrue(rendered.waitForExistence(timeout: 60),
                      "The actual OSMD dynamic module must load and render the MusicXML SVG")
        // Compare the complete status directly. Indexed traversal can become
        // stale while WebKit updates an OSMD tree after returning from practice;
        // substring predicates over AXValue also throw on numeric SVG values.
        let loaded = text("MusicXML 已载入 · 可从右侧选择音符校对", in: app)
        let loadedExists = loaded.waitForExistence(timeout: 20)
        if !loadedExists {
            let hierarchy = XCTAttachment(string: app.debugDescription)
            hierarchy.name = "Figma-MusicXML-status-missing-actual-hierarchy"
            hierarchy.lifetime = .keepAlways
            add(hierarchy)
            capture(app, name: "Figma-MusicXML-status-actual-view")
        }
        XCTAssertTrue(loadedExists, "The score must finish real MusicXML layout")
        XCTAssertTrue(text("4 个音符 / 休止符", in: app).exists)
        let scoreHierarchy = XCTAttachment(string: app.debugDescription)
        scoreHierarchy.name = "Figma-rendered-score-actual-hierarchy"
        scoreHierarchy.lifetime = .keepAlways
        add(scoreHierarchy)
        let controls = noteControls(app)
        let names = Set(controls.flatMap { element in
            [element.label, element.identifier, element.value as? String ?? ""].map(normalizedName)
        })
        for (index, pitch) in ["C4", "D4", "E4", "F4"].enumerated() {
            let expected = normalizedName("第 1 小节 · \(pitch) #\(index + 1)")
            // Actual macOS AX exposes these as CheckBox; iOS AX exposes Switch.
            // Match the same complete note name/index, allowing only whitespace
            // differences between AXTitle and aria-label. Read strings before
            // matching so numeric OSMD values cannot crash the harness.
            let present = names.contains(expected)
            if !present {
                let hierarchy = XCTAttachment(string: app.debugDescription)
                hierarchy.name = "Figma-note-\(pitch)-missing-actual-hierarchy"
                hierarchy.lifetime = .keepAlways
                add(hierarchy)
                capture(app, name: "Figma-note-\(pitch)-actual-view")
            }
            XCTAssertTrue(present, "The XML must provide an actual \(pitch) note for editing")
        }
    }

    @MainActor
    private func noteControls(_ app: XCUIApplication) -> [XCUIElement] {
        app.webViews.buttons.allElementsBoundByIndex + app.webViews.checkBoxes.allElementsBoundByIndex +
            app.webViews.toggles.allElementsBoundByIndex + app.webViews.switches.allElementsBoundByIndex
    }

    @MainActor
    private func note(_ label: String, in app: XCUIApplication) -> XCUIElement? {
        let expected = normalizedName(label)
        return noteControls(app).first { element in
            [element.label, element.identifier, element.value as? String ?? ""].map(normalizedName).contains(expected)
        }
    }

    @MainActor
    private func assertNoteSelection(_ app: XCUIApplication) {
        guard let second = note("第 1 小节 · D4 #2", in: app) else {
            XCTFail("The actual D4 editing control must exist")
            return
        }
        makeHittable(second, in: app)
        XCTAssertTrue(second.isHittable, "The real D4 control must be reachable by a user gesture")
        second.tap()
        assertSelectedPitch("D", control: "第 1 小节 · D4 #2", in: app)
        XCTAssertFalse(button("保存校对", in: app).isEnabled,
                       "Switching to an unchanged note must not carry another note's draft")
        attachHierarchy(app, name: "Figma-actual-D4-selected-with-D-field")
        guard let first = note("第 1 小节 · C4 #1", in: app) else {
            XCTFail("The original C4 editing control must remain available")
            return
        }
        makeHittable(first, in: app)
        first.tap()
        assertSelectedPitch("C", control: "第 1 小节 · C4 #1", in: app)
        XCTAssertFalse(button("保存校对", in: app).isEnabled)
        // Return to the header with ordinary scrolling, preserving all layout
        // and content. No JavaScript clicks or injected test controls are used.
        makeHittable(button("‹ 我的曲谱", in: app), in: app, upward: false)
    }

    @MainActor
    private func assertSelectedPitch(_ pitch: String, control label: String, in app: XCUIApplication) {
        let changed = XCTNSPredicateExpectation(predicate: NSPredicate { [weak self] _, _ in
            guard let self, let selected = note(label, in: app) else { return false }
            let active = (selected.value as? String) == "1" || (selected.value as? NSNumber)?.boolValue == true
            let fields = app.webViews.descendants(matching: .any).matching(identifier: "音名").allElementsBoundByIndex
            return active && fields.contains { ($0.value as? String) == pitch }
        }, object: app)
        let result = XCTWaiter.wait(for: [changed], timeout: 10)
        if result != .completed { attachHierarchy(app, name: "Figma-note-selection-\(pitch)-actual-hierarchy") }
        XCTAssertEqual(result, .completed, "A real note tap must update both its selected state and the pitch field")
    }

    @MainActor
    private func makeHittable(_ element: XCUIElement, in app: XCUIApplication, upward: Bool = true) {
        #if os(iOS)
        for _ in 0..<5 where !element.isHittable {
            if upward { app.webViews.firstMatch.swipeUp() }
            else { app.webViews.firstMatch.swipeDown() }
        }
        #endif
    }

    @MainActor
    private func attachHierarchy(_ app: XCUIApplication, name: String) {
        let attachment = XCTAttachment(string: app.debugDescription)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func normalizedName(_ value: String) -> String {
        value.components(separatedBy: .whitespacesAndNewlines).joined()
    }

    @MainActor
    private func assertDirection(_ app: XCUIApplication, landscape: Bool, name: String) {
        #if os(iOS)
        let direction = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            landscape ? app.frame.width > app.frame.height : app.frame.height > app.frame.width
        }, object: app)
        let result = XCTWaiter.wait(for: [direction], timeout: 20)
        capture(app, name: name)
        if result != .completed { attachHierarchy(app, name: "\(name)-actual-hierarchy") }
        XCTAssertEqual(result, .completed,
                       "The app must actually \(landscape ? "enter landscape" : "restore portrait") via the public system geometry request")
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
