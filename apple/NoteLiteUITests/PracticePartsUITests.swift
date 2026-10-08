import XCTest

/// Verifies navigation with actual saved desktop exports; this is not an OMR test.
final class PracticePartsUITests: XCTestCase {
    @MainActor
    func testEachSavedPartCanBeChosenAndLoadedAfterRelaunch() throws {
        continueAfterFailure = false
        executionTimeAllowance = 300
        let bundle = Bundle(for: Self.self)
        func data(_ name: String) throws -> Data {
            let url = try XCTUnwrap(bundle.url(forResource: name, withExtension: nil, subdirectory: "Fixtures"))
            return try Data(contentsOf: url)
        }
        let names = ["multipage.mvt1.mxl", "multipage.mvt1.mid", "multipage.mvt2.mxl", "multipage.mvt2.mid"]
        let payload: [String: Any] = [
            "source": try data("chula.png").base64EncodedString(),
            "artifacts": try names.map { ["name": $0, "data": try data($0).base64EncodedString()] },
        ]
        let app = XCUIApplication()
        app.launchArguments = ["--uitesting-import-practice-parts"]
        app.launchEnvironment["NOTELITE_UI_PRACTICE_PARTS"] = String(
            data: try JSONSerialization.data(withJSONObject: payload), encoding: .utf8)
        if let swiftPath = ProcessInfo.processInfo.environment["NOTELITE_SIM_SWIFT_PATH"], swiftPath.hasPrefix("/") {
            app.launchEnvironment["DYLD_FALLBACK_LIBRARY_PATH"] = swiftPath
        }
        app.launch()
        try skipLegacySelectorsForRedesignedMobileUI(app)
        openFixture(app)
        app.terminate()
        app.launchArguments = []
        app.launchEnvironment.removeValue(forKey: "NOTELITE_UI_PRACTICE_PARTS")
        app.launch()
        openFixture(app)
        for number in [2, 1] {
            let start = app.buttons["practice-start"].firstMatch
            XCTAssertTrue(start.waitForExistence(timeout: 15))
            start.tap()
            let choice = app.descendants(matching: .any)
                .matching(identifier: "practice-part-multipage.mvt\(number).mxl").firstMatch
            XCTAssertTrue(choice.waitForExistence(timeout: 5))
            XCTAssertEqual(choice.label, "第 \(number) 部分")
            choice.tap()
            let loaded = app.webViews.staticTexts.matching(NSPredicate(
                format: "label == %@ OR value == %@", "37 - CHULA PAROARA", "37 - CHULA PAROARA")).firstMatch
            XCTAssertTrue(loaded.waitForExistence(timeout: 45), "The selected saved MusicXML must load")
            assertMeasureCount(app)
            let player = app.webViews.buttons.matching(identifier: "开始练习").firstMatch
            let ready = XCTNSPredicateExpectation(
                predicate: NSPredicate(format: "exists == true AND enabled == true"), object: player)
            XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 10), .completed)
            let capture = XCTAttachment(screenshot: app.screenshot())
            capture.name = "Saved-practice-part-\(number)"
            capture.lifetime = .keepAlways
            add(capture)
            app.buttons["practice-close"].firstMatch.tap()
            XCTAssertTrue(start.waitForExistence(timeout: 10))
        }
    }

    @MainActor
    private func assertMeasureCount(_ app: XCUIApplication) {
        // The compact layout hides the footer and displays only two measures.
        // Open the actual range control, which focuses its first number field,
        // so the selected full-score range is visible on every screen size.
        let fullRange = app.webViews.buttons.matching(identifier: "第 1–19 小节").firstMatch
        let compactRange = app.webViews.buttons.matching(identifier: "第 1–2 小节").firstMatch
        let loaded = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            fullRange.exists || compactRange.exists
        }, object: app)
        XCTAssertEqual(XCTWaiter.wait(for: [loaded], timeout: 10), .completed)
        (fullRange.exists ? fullRange : compactRange).tap()
        let end = app.webViews.textFields.matching(identifier: "结束小节序号").firstMatch
        XCTAssertTrue(end.waitForExistence(timeout: 10))
        XCTAssertEqual(end.value as? String, "19", "The saved part must contain all 19 measures")
        let done = app.webViews.buttons.matching(identifier: "完成").firstMatch
        XCTAssertTrue(done.isHittable, "The settings close control must stay reachable with the number keyboard open")
        let viewport = app.webViews.firstMatch.frame
        XCTAssertFalse(viewport.isNull, "The practice renderer must have a visible frame")
        XCTAssertGreaterThanOrEqual(done.frame.minX, viewport.minX)
        XCTAssertLessThanOrEqual(done.frame.maxX, viewport.maxX)
        done.tap()
    }

    @MainActor
    private func openFixture(_ app: XCUIApplication) {
        let row = app.descendants(matching: .any).matching(identifier: "score-row")
            .matching(NSPredicate(format: "label CONTAINS %@ OR value CONTAINS %@",
                                  "多部分练习样本", "多部分练习样本")).firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 20))
        row.tap()
        XCTAssertTrue(app.buttons["practice-start"].firstMatch.waitForExistence(timeout: 15))
    }
}
