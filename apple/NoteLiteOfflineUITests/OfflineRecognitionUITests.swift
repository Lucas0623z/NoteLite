import XCTest

/// Included only in the build that embeds the real runtime, OCR and engine assets.
/// This never injects a fake engine or prerecorded MusicXML into the application.
final class OfflineRecognitionUITests: XCTestCase {
    @MainActor
    func testImportedImageRecognizesAndOpensPracticeWithoutServerSetup() {
        continueAfterFailure = false
        executionTimeAllowance = 2400
        let app = XCUIApplication()
        app.launchArguments = ["--uitesting-import-omr-fixture"]
        app.launch()
        let score = app.descendants(matching: .any).matching(identifier: "score-row").firstMatch
        XCTAssertTrue(score.waitForExistence(timeout: 30))
        score.tap()
        let start = app.buttons["recognition-start"]
        XCTAssertTrue(start.waitForExistence(timeout: 20))
        XCTAssertTrue(start.isEnabled, "A bundled engine must recognize without a server address or token")
        XCTAssertFalse(app.buttons["连接识谱服务器"].exists)
        XCTAssertFalse(app.buttons["practice-start"].exists,
                       "The scanned image must not have a prerecorded playable result")
        start.tap()
        let practice = app.buttons["practice-start"]
        XCTAssertTrue(practice.waitForExistence(timeout: 1800),
                      "The actual in-process engine must generate and save a playable score")
        let result = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        result.name = "Offline-recognition-complete"
        result.lifetime = .keepAlways
        add(result)

        // Reopen the stored result without a fixture-import argument or another
        // recognition request. The script also checks its persisted XML/MIDI.
        app.terminate()
        app.launchArguments = []
        app.launch()
        let restoredScore = app.descendants(matching: .any).matching(identifier: "score-row").firstMatch
        XCTAssertTrue(restoredScore.waitForExistence(timeout: 30))
        restoredScore.tap()
        let restoredPractice = app.buttons["practice-start"]
        XCTAssertTrue(restoredPractice.waitForExistence(timeout: 20),
                      "The saved recognized score must remain playable after restarting the app")
        XCTAssertFalse(app.buttons["recognition-start"].exists)
        restoredPractice.tap()

        // The empty HTML already contains the start button. Require metadata
        // loaded from this fixture's actual 19-measure MusicXML as well. The
        // compact layout hides the footer, so inspect the full range in settings.
        let fullRange = app.webViews.buttons.matching(identifier: "第 1–19 小节").firstMatch
        let compactRange = app.webViews.buttons.matching(identifier: "第 1–2 小节").firstMatch
        let loaded = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            fullRange.exists || compactRange.exists
        }, object: app)
        XCTAssertEqual(XCTWaiter.wait(for: [loaded], timeout: 90), .completed,
                       "The restored recognized MusicXML must load in the bundled practice renderer")
        (fullRange.exists ? fullRange : compactRange).tap()
        let end = app.webViews.textFields.matching(identifier: "结束小节序号").firstMatch
        XCTAssertTrue(end.waitForExistence(timeout: 10))
        XCTAssertEqual(end.value as? String, "19", "The restored recognized score must retain all 19 measures")
        app.webViews.buttons.matching(identifier: "完成").firstMatch.tap()
        let player = app.webViews.buttons.matching(identifier: "开始练习").firstMatch
        let ready = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "exists == true AND enabled == true"), object: player)
        XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 30), .completed,
                       "Practice must finish loading and enable its start control")
        XCTAssertTrue(player.isHittable)
        let rendered = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        rendered.name = "Recognized-score-practice"
        rendered.lifetime = .keepAlways
        add(rendered)
    }
}
