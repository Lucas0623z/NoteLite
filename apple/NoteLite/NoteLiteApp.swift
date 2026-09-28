import SwiftUI

@main
@MainActor
struct NoteLiteApp: App {
    @StateObject private var library = LibraryStore()
    @StateObject private var history = PracticeHistoryStore()

    var body: some Scene {
        WindowGroup {
            LibraryView()
                .environmentObject(library)
                .environmentObject(history)
                .tint(NoteLiteTheme.accent)
                .task {
                    #if DEBUG
                    if ProcessInfo.processInfo.arguments.contains("--uitesting-import-demo"),
                       library.records.isEmpty,
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
