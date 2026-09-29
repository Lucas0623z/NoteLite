import SwiftUI

@main
@MainActor
struct NoteLiteApp: App {
    @StateObject private var library: LibraryStore
    @StateObject private var history: PracticeHistoryStore

    init() {
        #if DEBUG
        if UICatalog.enabled {
            let stores = UICatalog.stores()
            _library = StateObject(wrappedValue: stores.0)
            _history = StateObject(wrappedValue: stores.1)
            return
        }
        #endif
        _library = StateObject(wrappedValue: LibraryStore())
        _history = StateObject(wrappedValue: PracticeHistoryStore())
    }

    var body: some Scene {
        WindowGroup {
            LibraryView()
                #if DEBUG
                .catalogWatermark()
                #endif
                .environmentObject(library)
                .environmentObject(history)
                .tint(NoteLiteTheme.accent)
                .task {
                    #if DEBUG
                    if ProcessInfo.processInfo.arguments.contains("--uitesting-import-practice-parts"),
                       let payload = ProcessInfo.processInfo.environment["NOTELITE_UI_PRACTICE_PARTS"]?.data(using: .utf8) {
                        await library.importPracticeUITestFixture(payload)
                    }
                    if ProcessInfo.processInfo.arguments.contains("--uitesting-import-demo"),
                       !library.records.contains(where: { $0.filename == "demo.musicxml" }),
                       let demo = Bundle.main.url(forResource: "demo", withExtension: "musicxml", subdirectory: "practice") {
                        await library.importFiles([demo])
                    }
                    #if EMBEDDED_OMR_RUNTIME
                    if ProcessInfo.processInfo.arguments.contains("--uitesting-import-omr-fixture"),
                       !library.records.contains(where: { $0.filename == "chula.png" }),
                       let score = Bundle.main.url(forResource: "chula", withExtension: "png",
                                                   subdirectory: "OMRResources/examples") {
                        await library.importFiles([score])
                    }
                    #endif
                    #endif
                }
                #if os(macOS)
                .frame(minWidth: 840, minHeight: 600)
                #endif
        }
        #if os(macOS)
        .defaultSize(width: 1440, height: 900)
        #endif
    }
}
