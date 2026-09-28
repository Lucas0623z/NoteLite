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
        practice.tap()
        let player = app.webViews.buttons.matching(identifier: "开始练习").firstMatch
        XCTAssertTrue(player.waitForExistence(timeout: 90),
                      "The real newly recognized MusicXML must load in the bundled practice renderer")
        XCTAssertTrue(player.isHittable)
        let rendered = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        rendered.name = "Recognized-score-practice"
        rendered.lifetime = .keepAlways
        add(rendered)
    }
}
