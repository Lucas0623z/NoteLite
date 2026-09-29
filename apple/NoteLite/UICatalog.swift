#if DEBUG
import SwiftUI
import Foundation

/// Explicitly opt-in fixtures for documentation screenshots. No network or OMR is run.
/// Every launch owns a new temporary store; the user's library and settings are not used.
@MainActor
enum UICatalog {
    static var enabled: Bool { ProcessInfo.processInfo.arguments.contains("--ui-catalog") }
    static var scenario: String { ProcessInfo.processInfo.environment["NOTELITE_UI_CATALOG_SCENE"] ?? "library" }
    static let originalID = UUID(uuidString: "A0000000-0000-0000-0000-000000000001")!
    static let structuredID = UUID(uuidString: "A0000000-0000-0000-0000-000000000002")!
    static let resultID = UUID(uuidString: "A0000000-0000-0000-0000-000000000003")!
    static var localEngine: Bool {
        #if os(macOS)
        return false
        #else
        return true
        #endif
    }
    static var detailID: UUID? {
        switch scenario {
        case "detail-ready", "part-picker": return resultID
        case "detail-new", "detail-running", "detail-failed", "source-preview": return originalID
        default: return nil
        }
    }

    static func stores() -> (LibraryStore, PracticeHistoryStore) {
        precondition(enabled)
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("NoteLite-UICatalog-" + UUID().uuidString, isDirectory: true)
        let defaults = UserDefaults(suiteName: "NoteLite.UICatalog." + UUID().uuidString)!
        do {
            let storage = try DocumentStorage(root: root)
            if scenario != "empty" {
                let date = Date(timeIntervalSince1970: 1_790_596_800)
                let original = ScoreRecord(id: originalID, filename: "识谱原稿 · 模拟样本.pdf", sourceName: "source.pdf", importedAt: date)
                var structured = ScoreRecord(id: structuredID, filename: "晨光练习曲.musicxml", sourceName: "source.musicxml", importedAt: date.addingTimeInterval(-3600))
                structured.phase = .ready
                var result = ScoreRecord(id: resultID, filename: "分部练习 · 模拟结果.pdf", sourceName: "source.pdf", importedAt: date.addingTimeInterval(-7200))
                result.phase = .ready
                result.recognitionLocation = localEngine ? .device : .server
                result.downloadedArtifacts = ["练习曲.mvt1.musicxml", "练习曲.mvt1.mid", "练习曲.mvt2.musicxml", "练习曲.mvt2.mid"]
                for record in [original, structured, result] {
                    try FileManager.default.createDirectory(at: storage.sourceURL(for: record).deletingLastPathComponent(), withIntermediateDirectories: true)
                }
                try LocalOMRDebugFixture.writeStaffPDF(to: storage.sourceURL(for: original))
                try LocalOMRDebugFixture.writeStaffPDF(to: storage.sourceURL(for: result))
                guard let demo = Bundle.main.url(forResource: "demo", withExtension: "musicxml", subdirectory: "practice") else {
                    throw NoteLiteError.server("截图样本缺少捆绑 MusicXML。")
                }
                let xml = try Data(contentsOf: demo)
                try xml.write(to: storage.sourceURL(for: structured))
                // A minimal valid MIDI file; never presented as an engine-generated export.
                let midi = Data([0x4d,0x54,0x68,0x64,0,0,0,6,0,0,0,1,0,96,0x4d,0x54,0x72,0x6b,0,0,0,4,0,0xff,0x2f,0])
                try storage.installEmbeddedArtifacts(result.downloadedArtifacts.map {
                    EmbeddedArtifact(name: $0, data: $0.hasSuffix(".mid") ? midi : xml)
                }, for: result)
                try storage.save([original, structured, result])
            }
            let library = LibraryStore(defaults: defaults, storageRoot: root,
                                       localRecognizer: CatalogRecognizer(isAvailable: localEngine))
            let history = PracticeHistoryStore(root: root)
            if scenario != "empty", let score = library.record(structuredID) {
                let report: [String: Any] = [
                    "title": "晨光练习曲 · 模拟练习", "durationSeconds": 142.0,
                    "completed": false, "measureCount": 4,
                    "errors": [
                        ["kind": "wrong", "index": 2, "measure": "1", "mi": 0, "beat": 3.0, "expected": [64], "played": 65],
                        ["kind": "early", "index": 5, "measure": "2", "mi": 1, "beat": 2.0, "expected": [67], "played": 67, "delta": -145.0],
                        ["kind": "intonation", "index": 8, "measure": "3", "mi": 2, "beat": 1.0, "expected": [65], "played": 65, "cents": 29.0],
                        ["kind": "missing", "index": 10, "measure": "3", "mi": 2, "beat": 3.0, "expected": [62]]
                    ]
                ]
                history.save(report: report, for: score)
            }
            library.prepareCatalogPresentation(scenario)
            return (library, history)
        } catch {
            let library = LibraryStore(defaults: defaults, storageRoot: root,
                                       localRecognizer: CatalogRecognizer(isAvailable: localEngine))
            library.errorMessage = "UI截图样本初始化失败：\(error.localizedDescription)"
            return (library, PracticeHistoryStore(root: root))
        }
    }
}

private struct CatalogRecognizer: EmbeddedRecognizing {
    let isAvailable: Bool
    func recognize(source: URL) async throws -> [EmbeddedArtifact] {
        while true { try await Task.sleep(nanoseconds: 1_000_000_000) }
    }
}

extension View {
    @MainActor @ViewBuilder func catalogWatermark() -> some View {
        if UICatalog.enabled {
            safeAreaInset(edge: .bottom, spacing: 0) {
                Text("UI 截图样本 · 模拟数据 · 未执行识谱")
                    .font(.system(size: 11)).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity).padding(.vertical, 4)
                    .background(.regularMaterial).accessibilityIdentifier("catalog-ready")
            }
        } else { self }
    }
}
#endif
