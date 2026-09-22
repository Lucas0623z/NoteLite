import XCTest
#if os(iOS)
import UIKit
#endif

final class NoteLiteUITests: XCTestCase {
    @MainActor
    func testImportedMusicXMLOpensBundledPracticeAndCaptureScreens() {
        let app = XCUIApplication()
        app.launchArguments = ["--uitesting-import-demo"]
        app.launch()
        let score = app.descendants(matching: .any).matching(identifier: "score-row").firstMatch
        XCTAssertTrue(score.waitForExistence(timeout: 15), "Bundled MusicXML must enter the real library importer")
        attach(app, name: "Library")
        score.tap()
        let practice = app.buttons["practice-start"].firstMatch
        XCTAssertTrue(practice.waitForExistence(timeout: 10), "Imported structured scores need a practice entry")
        practice.tap()
        let title = app.webViews.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "晨光练习曲")).firstMatch
        XCTAssertTrue(title.waitForExistence(timeout: 30), "The native bridge must load MusicXML into the bundled renderer")
        attach(app, name: "Practice")
        #if os(iOS)
        if UIDevice.current.userInterfaceIdiom == .pad {
            XCUIDevice.shared.orientation = .landscapeLeft
            attach(app, name: "Practice-landscape")
            XCUIDevice.shared.orientation = .portrait
        }
        #endif
    }

    @MainActor
    private func attach(_ app: XCUIApplication, name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
