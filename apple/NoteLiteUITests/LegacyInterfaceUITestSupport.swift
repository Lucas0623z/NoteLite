import XCTest

@MainActor
func skipLegacySelectorsForRedesignedMobileUI(_ app: XCUIApplication) throws {
    #if os(iOS)
    let mobile = app.webViews.matching(identifier: "yinban-mobile-interface").firstMatch
    if mobile.waitForExistence(timeout: 2) {
        throw XCTSkip("The redesigned mobile interface is covered by MobileInterfaceUITests; this case checks legacy LibraryView selectors.")
    }
    #endif
}
