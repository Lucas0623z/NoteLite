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
        // XCTest/AX uses a top-left global origin; AppKit screen rectangles
        // use the primary screen's bottom-left origin. Convert the actual
        // window once, rather than comparing different coordinate spaces.
        let primaryTop = try XCTUnwrap(NSScreen.screens.first).frame.maxY
        let cocoaWindow = CGRect(x: window.minX, y: primaryTop - window.maxY,
                                 width: window.width, height: window.height)
        let wholeWindowIsVisible = NSScreen.screens.contains { screen in
            screen.visibleFrame.insetBy(dx: -1, dy: -1).contains(cocoaWindow)
        }
        let metrics: [String: Any] = [
            "requestedContent": ["width": size.width, "height": size.height],
            "actualWindow": rectValue(window), "actualWebView": rectValue(web.frame),
            "actualWindowInAppKitScreenCoordinates": rectValue(cocoaWindow),
            "windowDecorationHeight": window.height - web.frame.height,
            "displayCanContainWholeWindow": canFitOnDisplay, "displays": displays,
            "displayCanContainRequestedWindow": requestedCanFit,
            "actualWindowEntirelyInsideVisibleDisplay": wholeWindowIsVisible,
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
        XCTAssertTrue(requestedCanFit && canFitOnDisplay,
                      "The native test display must actually contain the entire requested content and window decoration")
        XCTAssertTrue(wholeWindowIsVisible,
                      "The actual full native window must be inside a visible NSScreen, without off-screen content")
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
        var app = XCUIApplication()
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
        var viewScore = button("查看曲谱", in: app)
        XCTAssertTrue(viewScore.waitForExistence(timeout: 15))
        viewScore.tap()
        var close = button("‹ 我的曲谱", in: app)
        XCTAssertTrue(close.waitForExistence(timeout: 30))
        assertScoreRendered(app)
        assertNoteSelection(app)
        close = button("‹ 我的曲谱", in: app)
        makeReturnNavigationHittable(close, in: app)
        _ = try waitForNativeInteractionGeometry("‹ 我的曲谱", in: app,
                                                 checkpoint: "Figma-core-before-first-close")
        XCTAssertTrue(close.isHittable)
        capture(app, name: "Figma-score-actual-current-window")
        close.tap()
        let returnedToLibrary = button("查看曲谱", in: app).waitForExistence(timeout: 10)
        if !returnedToLibrary {
            attachHierarchy(app, name: "Figma-core-first-close-library-missing")
            capture(app, name: "Figma-core-first-close-library-missing")
        }
        XCTAssertTrue(returnedToLibrary, "Closing restores the saved library cards")

        // Relaunch through the real production entry: the card and its XML must
        // come from IndexedDB, rather than only the previous React state.
        app = try relaunchFromLibrary(app, checkpoint: "Figma-core-persistence-relaunch")
        // Do not retain element proxies rooted in the terminated process.
        viewScore = button("查看曲谱", in: app)
        close = button("‹ 我的曲谱", in: app)
        assertScoreRendered(app)

        // Cancel is a real native picker path. Reopening immediately proves the
        // previous export released its continuation without waiting for JS timeout.
        let download = button("下载当前曲谱", in: app)
        for attempt in 1...2 {
            XCTAssertTrue(download.waitForExistence(timeout: 10))
            download.tap()
            let englishCancel = app.buttons.matching(identifier: "Cancel").firstMatch
            let chineseCancel = app.buttons.matching(identifier: "取消").firstMatch
            // iPhone's system document browser can finish opening after two
            // seconds. Continue checking both actual labels throughout the
            // wait instead of choosing a locale before its controls exist.
            let opened = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
                englishCancel.exists || chineseCancel.exists
            }, object: app)
            let openResult = XCTWaiter.wait(for: [opened], timeout: 30)
            if openResult != .completed { attachHierarchy(app, name: "Figma-native-export-window-missing") }
            XCTAssertEqual(openResult, .completed, "The production export must open a native save window")
            let cancel = englishCancel.exists ? englishCancel : chineseCancel
            capture(app, name: "Figma-native-export-window-\(attempt)")
            cancel.tap()
            let released = XCTNSPredicateExpectation(predicate: NSPredicate(format: "enabled == true"), object: download)
            XCTAssertEqual(XCTWaiter.wait(for: [released], timeout: 10), .completed,
                           "Cancel must release the pending export and permit another export")
            XCTAssertTrue(text("操作已取消。", in: app).waitForExistence(timeout: 10))
            capture(app, name: "Figma-native-export-cancel-\(attempt)")
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
        let waitingPointer = text("演奏指针 · 等待连接 MIDI 或麦克风跟谱", in: app)
        // On the real phone capture this description is below the viewport.
        // Read it through ordinary scrolling before checking the whole text.
        makeInteractionHittable(waitingPointer, in: app)
        let waitingPointerExists = waitingPointer.waitForExistence(timeout: 10)
        if !waitingPointerExists {
            attachHierarchy(app, name: "Figma-waiting-pointer-text-missing-actual-hierarchy")
            capture(app, name: "Figma-waiting-pointer-text-missing-actual-view")
        }
        XCTAssertTrue(waitingPointerExists,
                      "The reviewed UI must not claim an audio engine is connected")
        capture(app, name: "Figma-practice-awaiting-audio")
        let returnToEditing = button("返回曲谱校对", in: app)
        XCTAssertTrue(returnToEditing.waitForExistence(timeout: 10))
        makeReturnNavigationHittable(returnToEditing, in: app)
        XCTAssertTrue(returnToEditing.isHittable)
        returnToEditing.tap()
        XCTAssertTrue(text("曲谱预览与校对", in: app).waitForExistence(timeout: 10))
        #if os(macOS)
        assertScoreRendered(app, expectedFeedback: "文件已导出。")
        #else
        assertScoreRendered(app, expectedFeedback: "操作已取消。")
        #endif
        close.tap()
        XCTAssertTrue(viewScore.waitForExistence(timeout: 10))
    }

    /// Exercise edits through the shipped WebKit controls and then relaunch.
    /// This case is independent of whether iPadOS accepts the orientation request.
    @MainActor
    func testNewInteractionsLocalPitchTempoPersistenceAndExport() throws {
        continueAfterFailure = false
        executionTimeAllowance = 300
        #if os(iOS)
        XCUIDevice.shared.orientation = .portrait
        #endif
        var app = XCUIApplication()
        app.launchArguments = ["--uitesting-figma"]
        #if os(macOS)
        let exportDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("NoteLite-Figma-edited-export-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: exportDirectory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: exportDirectory) }
        app.launchEnvironment["NOTELITE_UI_EXPORT_DIRECTORY"] = exportDirectory.path
        #endif
        app.launch()
        let libraryTab = button("我的曲谱", in: app)
        XCTAssertTrue(libraryTab.waitForExistence(timeout: 45))
        libraryTab.tap()
        ensureSampleInLibrary(app)
        let viewScore = button("查看曲谱", in: app)
        XCTAssertTrue(viewScore.waitForExistence(timeout: 15))
        XCTAssertEqual(app.webViews.buttons.matching(identifier: "查看曲谱").count, 1,
                       "This offline fixture must identify one actual saved score across relaunch")
        viewScore.tap()
        assertScoreRendered(app)

        let first = try XCTUnwrap(note("第 1 小节 · C4 #1", in: app))
        makeInteractionHittable(first, in: app)
        XCTAssertTrue(first.isHittable)
        first.tap()
        assertSelectedPitch("C", control: "第 1 小节 · C4 #1", in: app)
        try selectHTMLValue("5", named: "八度", in: app)
        let savePitch = button("保存校对", in: app)
        makeInteractionHittable(savePitch, in: app)
        XCTAssertTrue(savePitch.isEnabled)
        XCTAssertTrue(savePitch.isHittable)
        savePitch.tap()
        let savedPitch = XCTNSPredicateExpectation(predicate: NSPredicate { [weak self] _, _ in
            self?.note("第 1 小节 · C5 #1", in: app)?.exists == true
        }, object: app)
        let pitchResult = XCTWaiter.wait(for: [savedPitch], timeout: 20)
        if pitchResult != .completed { attachHierarchy(app, name: "Figma-new-interactions-C5-save-missing") }
        XCTAssertEqual(pitchResult, .completed,
                       "Only a committed local edit may change the original C4 note to C5")
        assertScoreRendered(app, expectedFeedback: "校对已保存到本机。",
                            expectedPitches: ["C5", "D4", "E4", "F4"])
        capture(app, name: "Figma-new-interactions-C5-after-real-save")
        attachHierarchy(app, name: "Figma-new-interactions-C5-after-real-save-hierarchy")

        // A fresh app reads the edited Blob from IndexedDB; React state alone
        // cannot satisfy the C5 assertion after this relaunch.
        app = try relaunchLocalScore(app, checkpoint: "Figma-C5-persistence-relaunch")
        assertScoreRendered(app, expectedPitches: ["C5", "D4", "E4", "F4"])
        capture(app, name: "Figma-new-interactions-C5-after-relaunch")
        openScoreMetadata(app)
        let tempo = app.webViews.textFields.matching(identifier: "谱面速度").firstMatch
        XCTAssertTrue(tempo.waitForExistence(timeout: 10))
        makeInteractionHittable(tempo, in: app)
        XCTAssertTrue(tempo.isHittable)
        let originalTempo = tempo.value as? String ?? ""
        XCTAssertTrue(originalTempo.isEmpty || originalTempo == "原谱未提供时可填写",
                      "The original production example has no tempo; enter a new numeric marking")
        tempo.tap()
        tempo.typeText("96")
        assertFieldValue("96", field: tempo, in: app, name: "Figma-new-interactions-tempo-draft")
        capture(app, name: "Figma-new-interactions-tempo96-after-real-input")
        attachHierarchy(app, name: "Figma-new-interactions-tempo96-after-real-input-hierarchy")
        guard dismissIOSKeyboardIfPresent(app) else { return }
        let saveTempo = button("保存速度", in: app)
        makeInteractionHittable(saveTempo, in: app)
        XCTAssertTrue(saveTempo.isEnabled)
        XCTAssertTrue(saveTempo.isHittable)
        saveTempo.tap()
        let tempoSaved = text("曲谱信息已保存到本机。", in: app).waitForExistence(timeout: 20)
        if !tempoSaved {
            attachHierarchy(app, name: "Figma-new-interactions-tempo-save-confirmation-missing")
            capture(app, name: "Figma-new-interactions-tempo-save-confirmation-missing")
        }
        XCTAssertTrue(tempoSaved,
                      "The real tempo save must complete before the app is closed and relaunched")
        guard tempoSaved else { return }
        assertScoreRendered(app, expectedFeedback: "曲谱信息已保存到本机。",
                            expectedPitches: ["C5", "D4", "E4", "F4"])

        app = try relaunchLocalScore(app, checkpoint: "Figma-tempo96-persistence-relaunch")
        assertScoreRendered(app, expectedPitches: ["C5", "D4", "E4", "F4"])
        openScoreMetadata(app)
        let persistedTempo = app.webViews.textFields.matching(identifier: "谱面速度").firstMatch
        XCTAssertTrue(persistedTempo.waitForExistence(timeout: 10))
        makeInteractionHittable(persistedTempo, in: app)
        assertFieldValue("96", field: persistedTempo, in: app,
                         name: "Figma-new-interactions-tempo96-after-relaunch")
        capture(app, name: "Figma-new-interactions-tempo96-after-relaunch")
        attachHierarchy(app, name: "Figma-new-interactions-tempo96-after-relaunch-hierarchy")

        #if os(macOS)
        let download = button("下载当前曲谱", in: app)
        makeInteractionHittable(download, in: app, upward: false)
        XCTAssertTrue(download.isHittable)
        download.tap()
        let save = app.buttons.matching(identifier: "Save").firstMatch
        XCTAssertTrue(save.waitForExistence(timeout: 20))
        capture(app, name: "Figma-new-interactions-native-save-window")
        save.tap()
        XCTAssertTrue(text("文件已导出。", in: app).waitForExistence(timeout: 15))
        let exports = try FileManager.default.contentsOfDirectory(at: exportDirectory, includingPropertiesForKeys: nil)
        XCTAssertEqual(exports.count, 1)
        let output = try XCTUnwrap(exports.first)
        XCTAssertEqual(output.pathExtension, "musicxml")
        let bytes = try Data(contentsOf: output)
        let document = try XMLDocument(data: bytes)
        let prefix = "/score-partwise/part/measure"
        XCTAssertEqual(try document.nodes(forXPath: "\(prefix)/note/pitch/step").compactMap(\.stringValue), ["C", "D", "E", "F"])
        XCTAssertEqual(try document.nodes(forXPath: "\(prefix)/note/pitch/octave").compactMap(\.stringValue), ["5", "4", "4", "4"])
        XCTAssertEqual(try document.nodes(forXPath: "\(prefix)/note/duration").compactMap(\.stringValue), ["1", "1", "1", "1"])
        XCTAssertEqual(try document.nodes(forXPath: "\(prefix)/direction/direction-type/metronome/beat-unit").compactMap(\.stringValue), ["quarter"])
        XCTAssertEqual(try document.nodes(forXPath: "\(prefix)/direction/direction-type/metronome/per-minute").compactMap(\.stringValue), ["96"])
        XCTAssertEqual(try document.nodes(forXPath: "\(prefix)/direction/sound/@tempo").compactMap(\.stringValue), ["96"])
        let attachment = XCTAttachment(data: bytes, uniformTypeIdentifier: "public.xml")
        attachment.name = "Figma-new-interactions-actual-saved-C5-tempo96-MusicXML"
        attachment.lifetime = .keepAlways
        add(attachment)
        #endif
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
    private func assertScoreRendered(_ app: XCUIApplication,
                                     expectedFeedback: String = "MusicXML 已载入 · 可从右侧选择音符校对",
                                     expectedPitches: [String] = ["C4", "D4", "E4", "F4"]) {
        let rendered = app.webViews.descendants(matching: .any)
            .matching(NSPredicate(format: "label == %@ OR value == %@", "MusicXML 谱面", "MusicXML 谱面")).firstMatch
        XCTAssertTrue(rendered.waitForExistence(timeout: 60),
                      "The actual OSMD dynamic module must load and render the MusicXML SVG")
        // Compare the complete status directly. Indexed traversal can become
        // stale while WebKit updates an OSMD tree after returning from practice;
        // substring predicates over AXValue also throw on numeric SVG values.
        let loaded = text(expectedFeedback, in: app)
        let loadedExists = loaded.waitForExistence(timeout: 20)
        if !loadedExists {
            let hierarchy = XCTAttachment(string: app.debugDescription)
            hierarchy.name = "Figma-MusicXML-status-missing-actual-hierarchy"
            hierarchy.lifetime = .keepAlways
            add(hierarchy)
            capture(app, name: "Figma-MusicXML-status-actual-view")
        }
        XCTAssertTrue(loadedExists, "The rendered score must preserve the exact expected product feedback: \(expectedFeedback)")
        XCTAssertTrue(text("4 个音符 / 休止符", in: app).exists)
        let scoreHierarchy = XCTAttachment(string: app.debugDescription)
        scoreHierarchy.name = "Figma-rendered-score-actual-hierarchy"
        scoreHierarchy.lifetime = .keepAlways
        add(scoreHierarchy)
        let controls = noteControls(app)
        let names = Set(controls.flatMap { element in
            [element.label, element.identifier, element.value as? String ?? ""].map(normalizedName)
        })
        XCTAssertEqual(expectedPitches.count, 4)
        for (index, pitch) in expectedPitches.enumerated() {
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
        makeReturnNavigationHittable(button("‹ 我的曲谱", in: app), in: app)
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
        scrollIOSControlIntoView(element, in: app, preferredUpward: upward)
        #endif
    }

    @MainActor
    private func makeInteractionHittable(_ element: XCUIElement, in app: XCUIApplication,
                                        upward: Bool = true) {
        #if os(iOS)
        scrollIOSControlIntoView(element, in: app, preferredUpward: upward)
        #else
        for _ in 0..<12 where !element.isHittable {
            app.webViews.firstMatch.scroll(byDeltaX: 0, deltaY: upward ? -420 : 420)
        }
        #endif
    }

    #if os(iOS)
    @MainActor
    private func scrollIOSControlIntoView(_ element: XCUIElement, in app: XCUIApplication,
                                         preferredUpward: Bool) {
        let web = app.webViews.firstMatch
        // The real iPhone failure recording shows whole-view swipes passing
        // C4/D4 and stopping at E4/F4. Inspect each new AX frame and reverse
        // when needed. Drag inside the target column so nested scrolling can
        // receive the same touch a user would make, without JS or layout edits.
        for _ in 0..<12 where !element.isHittable {
            let webFrame = web.frame
            let viewport = webFrame.intersection(app.frame)
            guard !viewport.isNull, !viewport.isEmpty,
                  viewport.width > 40, viewport.height > 60 else { break }
            let target = element.frame
            let hasFrame = !target.isNull && !target.isEmpty && !target.isInfinite
            let upward: Bool
            if hasFrame && target.minY < viewport.minY + 16 {
                upward = false
            } else if hasFrame && target.maxY > viewport.maxY - 16 {
                upward = true
            } else {
                upward = preferredUpward
            }
            let x = hasFrame ? min(max(target.midX, viewport.minX + viewport.width * 0.1),
                                   viewport.maxX - viewport.width * 0.1) : viewport.midX
            let high = viewport.minY + viewport.height * 0.3
            let low = viewport.minY + viewport.height * 0.7
            let start = web.coordinate(withNormalizedOffset: CGVector(
                dx: (x - webFrame.minX) / webFrame.width,
                dy: ((upward ? low : high) - webFrame.minY) / webFrame.height))
            let end = web.coordinate(withNormalizedOffset: CGVector(
                dx: (x - webFrame.minX) / webFrame.width,
                dy: ((upward ? high : low) - webFrame.minY) / webFrame.height))
            start.press(forDuration: 0.1, thenDragTo: end)
        }
        if !element.isHittable {
            attachHierarchy(app, name: "Figma-control-scroll-exhausted-actual-hierarchy")
            capture(app, name: "Figma-control-scroll-exhausted-actual-view")
        }
        // Callers still require isHittable and tap the actual element; reaching
        // this limit never counts as successful selection or saved content.
    }
    #endif

    @MainActor
    private func dismissIOSKeyboardIfPresent(_ app: XCUIApplication) -> Bool {
        #if os(iOS)
        // Actual iPhone captures expose a Done accessory; the iPad capture
        // exposes Hide keyboard inside the keyboard. Tap a reachable native
        // dismissal control before saving or returning to the page header.
        if app.keyboards.firstMatch.exists {
            let accessories = ["Done", "完成"].flatMap {
                app.buttons.matching(identifier: $0).allElementsBoundByIndex
            }
            let hideKeyboard = app.keyboards.firstMatch.buttons
                .matching(identifier: "Hide keyboard").allElementsBoundByIndex
            guard let dismissal = (accessories + hideKeyboard).first(where: { $0.isHittable }) else {
                attachHierarchy(app, name: "Figma-return-navigation-keyboard-dismiss-missing")
                capture(app, name: "Figma-return-navigation-keyboard-dismiss-missing")
                XCTFail("The visible native keyboard must have a reachable dismissal control")
                return false
            }
            dismissal.tap()
            let dismissed = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
                !app.keyboards.firstMatch.exists
            }, object: app)
            let result = XCTWaiter.wait(for: [dismissed], timeout: 10)
            if result != .completed {
                attachHierarchy(app, name: "Figma-return-navigation-keyboard-still-visible")
                capture(app, name: "Figma-return-navigation-keyboard-still-visible")
            }
            XCTAssertEqual(result, .completed,
                           "The real native dismissal control must hide the keyboard before saving or navigation")
            guard result == .completed else { return false }
        }
        #endif
        return true
    }

    @MainActor
    private func makeReturnNavigationHittable(_ element: XCUIElement, in app: XCUIApplication) {
        #if os(iOS)
        guard dismissIOSKeyboardIfPresent(app) else { return }
        // The header is at the document's upper boundary: complete downward
        // swipes cannot pass it. Short control-column drags are retained for
        // note selection, where overshooting an interior control was observed.
        // A partially clipped HTML button can report isHittable even when
        // XCTest chooses a point outside its actual native visible rectangle.
        // The failed iPhone capture had y=-22 for this 43-point header button.
        // Scroll normally until the complete real target is inside both the
        // window and WebKit; never compensate with synthetic coordinates.
        func fullyVisible() -> Bool {
            guard element.isHittable,
                  let geometry = try? nativeInteractionGeometry(element.label, in: app),
                  geometry.isConsistent else { return false }
            return geometry.window.insetBy(dx: -1, dy: -1).contains(geometry.target) &&
                geometry.webView.insetBy(dx: -1, dy: -1).contains(geometry.target)
        }
        for _ in 0..<12 where !fullyVisible() {
            app.webViews.firstMatch.swipeDown()
        }
        if !fullyVisible() {
            attachHierarchy(app, name: "Figma-return-navigation-scroll-exhausted")
            capture(app, name: "Figma-return-navigation-scroll-exhausted")
        }
        XCTAssertTrue(fullyVisible(),
                      "The entire return button must be visible in the current native window and WebKit before one real tap")
        #else
        makeInteractionHittable(element, in: app, upward: false)
        #endif
    }

    @MainActor
    private func selectHTMLValue(_ value: String, named label: String,
                                 in app: XCUIApplication) throws {
        #if os(macOS)
        let field = app.webViews.popUpButtons.matching(identifier: label).firstMatch
        #else
        // Actual baseline iPhone/iPad AX maps HTML selects to Other controls.
        let field = app.webViews.otherElements.matching(identifier: label).firstMatch
        #endif
        XCTAssertTrue(field.waitForExistence(timeout: 10))
        makeInteractionHittable(field, in: app)
        XCTAssertTrue(field.isHittable)
        field.tap()
        attachHierarchy(app, name: "Figma-new-interactions-\(label)-actual-system-options")
        #if os(macOS)
        let option = app.menuItems.matching(identifier: value).firstMatch
        XCTAssertTrue(option.waitForExistence(timeout: 10))
        option.tap()
        #else
        let wheel = app.pickerWheels.firstMatch
        let menuOption = app.menuItems.matching(identifier: value).firstMatch
        let buttonOption = app.buttons.matching(identifier: value).firstMatch
        let opened = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            wheel.exists || menuOption.exists || buttonOption.exists
        }, object: app)
        let result = XCTWaiter.wait(for: [opened], timeout: 10)
        if result != .completed { attachHierarchy(app, name: "Figma-new-interactions-select-options-missing") }
        XCTAssertEqual(result, .completed, "The real native select options must be available")
        if wheel.exists {
            wheel.adjust(toPickerWheelValue: value)
            let englishDone = app.buttons.matching(identifier: "Done").firstMatch
            let chineseDone = app.buttons.matching(identifier: "完成").firstMatch
            let finished = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
                englishDone.exists || chineseDone.exists
            }, object: app)
            XCTAssertEqual(XCTWaiter.wait(for: [finished], timeout: 10), .completed)
            (englishDone.exists ? englishDone : chineseDone).tap()
        } else {
            (menuOption.exists ? menuOption : buttonOption).tap()
        }
        #endif
        assertFieldValue(value, field: field, in: app, name: "Figma-new-interactions-\(label)-changed")
    }

    @MainActor
    private func assertFieldValue(_ value: String, field: XCUIElement,
                                  in app: XCUIApplication, name: String) {
        let changed = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            if let current = field.value as? String { return current == value }
            if let current = field.value as? NSNumber { return current.stringValue == value }
            return false
        }, object: app)
        let result = XCTWaiter.wait(for: [changed], timeout: 10)
        if result != .completed { attachHierarchy(app, name: "\(name)-actual-hierarchy") }
        XCTAssertEqual(result, .completed, "The actual editing control must show \(value)")
    }

    @MainActor
    private func relaunchLocalScore(_ app: XCUIApplication, checkpoint: String) throws -> XCUIApplication {
        let close = button("‹ 我的曲谱", in: app)
        makeReturnNavigationHittable(close, in: app)
        XCTAssertTrue(close.isHittable)
        close.tap()
        XCTAssertTrue(button("查看曲谱", in: app).waitForExistence(timeout: 10))
        return try relaunchFromLibrary(app, checkpoint: checkpoint)
    }

    @MainActor
    private func relaunchFromLibrary(_ app: XCUIApplication, checkpoint: String) throws -> XCUIApplication {
        // The failed iPhone run targeted the new process with a 1/3-size event
        // window while its attached snapshot still described the old process.
        // Drop both application and element proxies across that boundary. A
        // new proxy is a repair candidate; the actual native touch log and
        // xcresult event records must still confirm the injected coordinates.
        let previous = try waitForNativeInteractionGeometry("查看曲谱", in: app,
                                                           checkpoint: "\(checkpoint)-before-termination")
        let arguments = app.launchArguments
        var environment = app.launchEnvironment
        environment["NOTELITE_UI_LAUNCH_ID"] = UUID().uuidString
        attachHierarchy(app, name: "\(checkpoint)-terminated-process-hierarchy")
        app.terminate()
        XCTAssertTrue(app.wait(for: .notRunning, timeout: 15),
                      "The previous real application process must terminate before relaunch")

        let relaunched = XCUIApplication()
        relaunched.launchArguments = arguments
        relaunched.launchEnvironment = environment
        relaunched.launch()
        XCTAssertTrue(relaunched.wait(for: .runningForeground, timeout: 15),
                      "The new real application process must enter the foreground")
        let library = button("我的曲谱", in: relaunched)
        XCTAssertTrue(library.waitForExistence(timeout: 45))
        _ = try waitForNativeInteractionGeometry("我的曲谱", in: relaunched,
                                                 expectedWindowSize: previous.window.size,
                                                 expectedPresentedWindowSize: previous.presentedWindow.size,
                                                 checkpoint: "\(checkpoint)-before-library-tap")
        // Each destination receives one ordinary element tap. A failed tap is
        // never retried, replaced with coordinates, or replaced with JS.
        library.tap()
        let view = button("查看曲谱", in: relaunched)
        XCTAssertTrue(view.waitForExistence(timeout: 15),
                      "The actual IndexedDB score must persist across application relaunch")
        XCTAssertEqual(relaunched.webViews.buttons.matching(identifier: "查看曲谱").count, 1)
        _ = try waitForNativeInteractionGeometry("查看曲谱", in: relaunched,
                                                 expectedWindowSize: previous.window.size,
                                                 expectedPresentedWindowSize: previous.presentedWindow.size,
                                                 checkpoint: "\(checkpoint)-before-view-score-tap")
        view.tap()
        attachHierarchy(relaunched, name: "\(checkpoint)-after-single-view-score-tap-hierarchy")
        capture(relaunched, name: "\(checkpoint)-after-single-view-score-tap")
        return relaunched
    }

    private struct NativeInteractionGeometry: Equatable {
        let application: CGRect
        let window: CGRect
        let webView: CGRect
        let target: CGRect
        let presentedWindow: CGRect
        let presentedWebView: CGRect
        let presentedTarget: CGRect
        let computedCoordinateCenter: CGPoint
        let windowCoordinateOrigin: CGPoint
        let windowCoordinateX: CGPoint
        let windowCoordinateY: CGPoint

        var expectedCoordinateCenter: CGPoint {
            let horizontal = (presentedTarget.midX - presentedWindow.minX) / presentedWindow.width
            let vertical = (presentedTarget.midY - presentedWindow.minY) / presentedWindow.height
            return CGPoint(
                x: windowCoordinateOrigin.x + horizontal * (windowCoordinateX.x - windowCoordinateOrigin.x) +
                    vertical * (windowCoordinateY.x - windowCoordinateOrigin.x),
                y: windowCoordinateOrigin.y + horizontal * (windowCoordinateX.y - windowCoordinateOrigin.y) +
                    vertical * (windowCoordinateY.y - windowCoordinateOrigin.y))
        }

        var isConsistent: Bool {
            // An AX Application node can have no own rectangle (the actual
            // macOS artifact does not expose one). Its real Window owns the
            // native surface; keep the root frame as diagnostic metadata only.
            let rectangles = [window, webView, target, presentedWindow, presentedWebView, presentedTarget]
            guard rectangles.allSatisfy({ rect in
                !rect.isNull && !rect.isEmpty && !rect.isInfinite &&
                    [rect.minX, rect.minY, rect.width, rect.height].allSatisfy(\.isFinite)
            }) else { return false }
            guard window.insetBy(dx: -1, dy: -1).contains(target) &&
                webView.insetBy(dx: -1, dy: -1).contains(target) &&
                window.width + 1 >= webView.width && window.height + 1 >= webView.height &&
                presentedWindow.insetBy(dx: -1, dy: -1).contains(presentedTarget) &&
                presentedWebView.insetBy(dx: -1, dy: -1).contains(presentedTarget) &&
                presentedWindow.width + 1 >= presentedWebView.width &&
                presentedWindow.height + 1 >= presentedWebView.height else { return false }

            // iPadOS 26 compatibility mode may scale and center a landscape
            // scene in a portrait display. Its raw snapshot and the public
            // element.frame / screenPoint APIs expose different rectangles in
            // the actual CI evidence. Validate both complete trees and their
            // uniform presentation transform; never apply it to the real tap.
            let scaleX = presentedWindow.width / window.width
            let scaleY = presentedWindow.height / window.height
            guard abs(scaleX - scaleY) <= max(0.001, scaleX * 0.001) else { return false }
            func matchesPresentation(_ logical: CGRect, _ presented: CGRect) -> Bool {
                let expected = CGRect(
                    x: presentedWindow.minX + (logical.minX - window.minX) * scaleX,
                    y: presentedWindow.minY + (logical.minY - window.minY) * scaleY,
                    width: logical.width * scaleX, height: logical.height * scaleY)
                return abs(expected.minX - presented.minX) <= 1 &&
                    abs(expected.minY - presented.minY) <= 1 &&
                    abs(expected.width - presented.width) <= 1 &&
                    abs(expected.height - presented.height) <= 1
            }
            // screenPoint can use the display's fixed axes while frame uses
            // the current interface axes. Read that relation from the public
            // window coordinates, rather than assuming a rotation or changing
            // the coordinate used by an ordinary element tap.
            let points = [computedCoordinateCenter, windowCoordinateOrigin,
                          windowCoordinateX, windowCoordinateY]
            guard points.allSatisfy({ $0.x.isFinite && $0.y.isFinite }) else { return false }
            let dx = CGVector(dx: windowCoordinateX.x - windowCoordinateOrigin.x,
                              dy: windowCoordinateX.y - windowCoordinateOrigin.y)
            let dy = CGVector(dx: windowCoordinateY.x - windowCoordinateOrigin.x,
                              dy: windowCoordinateY.y - windowCoordinateOrigin.y)
            let lengthX = (dx.dx * dx.dx + dx.dy * dx.dy).squareRoot()
            let lengthY = (dy.dx * dy.dx + dy.dy * dy.dy).squareRoot()
            guard abs(lengthX - presentedWindow.width) <= 1,
                  abs(lengthY - presentedWindow.height) <= 1,
                  abs(dx.dx * dy.dx + dx.dy * dy.dy) <= max(1, lengthX * lengthY * 0.001) else { return false }
            return matchesPresentation(webView, presentedWebView) &&
                matchesPresentation(target, presentedTarget) &&
                abs(computedCoordinateCenter.x - expectedCoordinateCenter.x) <= 1 &&
                abs(computedCoordinateCenter.y - expectedCoordinateCenter.y) <= 1
        }

        func matchesWindowSize(_ size: CGSize?) -> Bool {
            guard let size else { return true }
            return abs(window.width - size.width) <= 1 && abs(window.height - size.height) <= 1
        }

        func matchesPresentedWindowSize(_ size: CGSize?) -> Bool {
            guard let size else { return true }
            return abs(presentedWindow.width - size.width) <= 1 &&
                abs(presentedWindow.height - size.height) <= 1
        }
    }

    @MainActor
    private func firstSnapshot(in root: any XCUIElementSnapshot,
                               matching predicate: (any XCUIElementSnapshot) -> Bool) -> (any XCUIElementSnapshot)? {
        if predicate(root) { return root }
        for child in root.children {
            if let found = firstSnapshot(in: child, matching: predicate) { return found }
        }
        return nil
    }

    @MainActor
    private func nativeInteractionGeometry(_ label: String,
                                           in app: XCUIApplication) throws -> NativeInteractionGeometry? {
        // Bracket the real, presented element frames with identical raw public
        // snapshots. A logical scene transition or a still-animating system
        // presentation must not be combined with a different window or target.
        let snapshot = try app.snapshot()
        guard let window = firstSnapshot(in: snapshot, matching: { $0.elementType == .window }),
              let web = firstSnapshot(in: window, matching: { $0.elementType == .webView }),
              let target = firstSnapshot(in: web, matching: {
                  // WebKit text buttons on macOS expose AXTitle, while
                  // aria-label controls expose AXDescription. Match the same
                  // public names as the element query without taking a second
                  // snapshot or substituting coordinates for the actual tap.
                  $0.elementType == .button &&
                      ($0.identifier == label || $0.label == label || $0.title == label)
              }) else { return nil }
        let presentedWindow = app.windows.firstMatch
        let presentedWebView = presentedWindow.webViews.firstMatch
        let presentedTarget = button(label, in: app)
        guard presentedWindow.exists, presentedWebView.exists, presentedTarget.exists else { return nil }
        let windowFrame = presentedWindow.frame
        let webViewFrame = presentedWebView.frame
        let targetFrame = presentedTarget.frame
        let point = presentedTarget.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).screenPoint
        let origin = presentedWindow.coordinate(withNormalizedOffset: .zero).screenPoint
        let x = presentedWindow.coordinate(withNormalizedOffset: CGVector(dx: 1, dy: 0)).screenPoint
        let y = presentedWindow.coordinate(withNormalizedOffset: CGVector(dx: 0, dy: 1)).screenPoint
        let after = try app.snapshot()
        guard let afterWindow = firstSnapshot(in: after, matching: { $0.elementType == .window }),
              let afterWeb = firstSnapshot(in: afterWindow, matching: { $0.elementType == .webView }),
              let afterTarget = firstSnapshot(in: afterWeb, matching: {
                  $0.elementType == .button &&
                      ($0.identifier == label || $0.label == label || $0.title == label)
              }),
              [snapshot.frame, window.frame, web.frame, target.frame] ==
                [after.frame, afterWindow.frame, afterWeb.frame, afterTarget.frame] else { return nil }
        return NativeInteractionGeometry(application: snapshot.frame, window: window.frame,
                                         webView: web.frame, target: target.frame,
                                         presentedWindow: windowFrame, presentedWebView: webViewFrame,
                                         presentedTarget: targetFrame, computedCoordinateCenter: point,
                                         windowCoordinateOrigin: origin, windowCoordinateX: x,
                                         windowCoordinateY: y)
    }

    @MainActor
    private func waitForNativeInteractionGeometry(_ label: String, in app: XCUIApplication,
                                                 expectedWindowSize: CGSize? = nil,
                                                 expectedPresentedWindowSize: CGSize? = nil,
                                                 checkpoint: String) throws -> NativeInteractionGeometry {
        var previous: NativeInteractionGeometry?
        var accepted: NativeInteractionGeometry?
        var consecutiveSamples = 0
        var stableSince = Date()
        let stable = XCTNSPredicateExpectation(predicate: NSPredicate { [weak self] _, _ in
            guard let self, app.state == .runningForeground,
                  let geometry = try? self.nativeInteractionGeometry(label, in: app),
                  geometry.isConsistent, geometry.matchesWindowSize(expectedWindowSize),
                  geometry.matchesPresentedWindowSize(expectedPresentedWindowSize),
                  self.button(label, in: app).isHittable else {
                previous = nil
                consecutiveSamples = 0
                stableSince = Date()
                return false
            }
            if geometry == previous {
                consecutiveSamples += 1
            } else {
                previous = geometry
                consecutiveSamples = 1
                stableSince = Date()
            }
            guard consecutiveSamples >= 3, Date().timeIntervalSince(stableSince) >= 1 else { return false }
            accepted = geometry
            return true
        }, object: app)
        let result = XCTWaiter.wait(for: [stable], timeout: 20)
        attachHierarchy(app, name: "\(checkpoint)-actual-process-hierarchy")
        capture(app, name: "\(checkpoint)-actual-screen")
        XCTAssertEqual(result, .completed,
                       "One current native window, WebKit tree and hittable target must agree and stabilize before a real tap")
        guard result == .completed, let geometry = accepted else {
            throw NSError(domain: "NoteLiteNativeGeometry", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "No stable native geometry for \(checkpoint)"])
        }
        let point = button(label, in: app).coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).screenPoint
        XCTAssertEqual(point.x, geometry.expectedCoordinateCenter.x, accuracy: 1,
                       "XCTest's horizontal coordinate must agree with the target in the public window coordinate basis")
        XCTAssertEqual(point.y, geometry.expectedCoordinateCenter.y, accuracy: 1,
                       "XCTest's vertical coordinate must agree with the target in the public window coordinate basis")
        let metrics: [String: Any] = [
            "checkpoint": checkpoint,
            "launchID": app.launchEnvironment["NOTELITE_UI_LAUNCH_ID"] ?? "initial-process",
            "applicationState": app.state.rawValue,
            "applicationFrame": frameValues(geometry.application),
            "windowFrame": frameValues(geometry.window),
            "webViewFrame": frameValues(geometry.webView),
            "targetFrame": frameValues(geometry.target),
            "presentedWindowFrame": frameValues(geometry.presentedWindow),
            "presentedWebViewFrame": frameValues(geometry.presentedWebView),
            "presentedTargetFrame": frameValues(geometry.presentedTarget),
            "presentationScale": geometry.presentedWindow.width / geometry.window.width,
            "windowCoordinateOrigin": ["x": geometry.windowCoordinateOrigin.x, "y": geometry.windowCoordinateOrigin.y],
            "windowCoordinateX": ["x": geometry.windowCoordinateX.x, "y": geometry.windowCoordinateX.y],
            "windowCoordinateY": ["x": geometry.windowCoordinateY.x, "y": geometry.windowCoordinateY.y],
            "expectedCoordinateCenter": ["x": geometry.expectedCoordinateCenter.x, "y": geometry.expectedCoordinateCenter.y],
            "computedCoordinateCenter": ["x": point.x, "y": point.y],
            "stableSamples": consecutiveSamples,
            "geometrySource": "Identical public raw snapshots bracket actual element.frame and screenPoint; logical and presented frames must both agree and stabilize",
            "touchScope": "Pre-touch accessibility geometry only; actual native touch and xcresult event records are separate evidence"
        ]
        let data = try JSONSerialization.data(withJSONObject: metrics, options: [.prettyPrinted, .sortedKeys])
        let attachment = XCTAttachment(string: String(decoding: data, as: UTF8.self))
        attachment.name = "\(checkpoint)-native-interaction-geometry"
        attachment.lifetime = .keepAlways
        add(attachment)
        return geometry
    }

    private func frameValues(_ rect: CGRect) -> [String: CGFloat] {
        ["x": rect.minX, "y": rect.minY, "width": rect.width, "height": rect.height]
    }

    @MainActor
    private func openScoreMetadata(_ app: XCUIApplication) {
        let tempo = app.webViews.textFields.matching(identifier: "谱面速度").firstMatch
        if tempo.exists { return }
        let summary = app.webViews.descendants(matching: .any)
            .matching(identifier: "编辑谱面前置信息").firstMatch
        XCTAssertTrue(summary.waitForExistence(timeout: 10))
        makeInteractionHittable(summary, in: app)
        XCTAssertTrue(summary.isHittable)
        summary.tap()
        XCTAssertTrue(tempo.waitForExistence(timeout: 10),
                      "A real disclosure tap must expose the numeric tempo editor")
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
