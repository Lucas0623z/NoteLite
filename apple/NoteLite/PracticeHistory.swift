import SwiftUI
import Combine

struct PracticeIssue: Codable, Identifiable {
    var id: String { "\(index)-\(kind)-\(beat)-\(played ?? -1)" }
    let kind: String
    let index: Int
    let measure: String
    let mi: Int
    let beat: Double
    let expected: [Int]?
    let played: Int?
    let cents: Double?
    let delta: Double?

    var label: String {
        switch kind {
        case "missing": return "漏音"
        case "early": return "抢拍"
        case "late": return "慢拍"
        case "intonation": return "音准偏差"
        case "extra": return "多弹"
        default: return "错音"
        }
    }
    var detail: String {
        let notes = (expected ?? []).map(Self.noteName).joined(separator: " + ")
        if kind == "missing" { return "未听到 \(notes)" }
        if kind == "intonation", let cents { return "\(Self.noteName(played ?? 60)) \(cents > 0 ? "偏高" : "偏低") \(Int(abs(cents))) 音分" }
        if let delta, kind == "early" || kind == "late" || kind == "extra" {
            return "\(Self.noteName(played ?? 60)) \(delta < 0 ? "提前" : "延后") \(Int(abs(delta))) ms"
        }
        return "应弹 \(notes)，听到 \(Self.noteName(played ?? 60))"
    }
    private static func noteName(_ midi: Int) -> String {
        let names = ["C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B"]
        return "\(names[((midi % 12) + 12) % 12])\(midi / 12 - 1)"
    }
}

struct PracticePositionResult: Codable, Equatable {
    let index: Int
    let measure: String
    let beat: Double
    let correct: Int
    let expected: Int
    let status: String
}

struct PracticeScope: Codable, Equatable {
    let part: String
    let from: Int
    let to: Int
}

private struct PracticeMetrics: Decodable {
    let firstTryCorrect: Int?
    let total: Int?
    let results: [PracticePositionResult]?
    let input: String?
    let mode: String?
    let bpm: Double?
    let scope: PracticeScope?
}

struct PracticeHistoryRecord: Codable, Identifiable {
    let id: UUID
    let scoreID: UUID
    let title: String
    let date: Date
    let durationSeconds: Double
    let completed: Bool
    let measureCount: Int
    let errors: [PracticeIssue]
    var artifactName: String? = nil
    var partTitle: String? = nil
    // Optional for records saved before detailed practice metrics were retained.
    var firstTryCorrect: Int? = nil
    var total: Int? = nil
    var results: [PracticePositionResult]? = nil
    var input: String? = nil
    var mode: String? = nil
    var bpm: Double? = nil
    var scope: PracticeScope? = nil
    var errorCount: Int { errors.count }
}

@MainActor
final class PracticeHistoryStore: ObservableObject {
    @Published private(set) var records: [PracticeHistoryRecord] = []
    @Published var errorMessage: String?
    private var fileURL: URL?

    init(root: URL? = nil) {
        do {
            let folder = try root ?? FileManager.default.url(for: .applicationSupportDirectory,
                in: .userDomainMask, appropriateFor: nil, create: true).appendingPathComponent("NoteLite")
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            let file = folder.appendingPathComponent("practice-history.json")
            if FileManager.default.fileExists(atPath: file.path) {
                records = try JSONDecoder().decode([PracticeHistoryRecord].self, from: Data(contentsOf: file))
            }
            fileURL = file
        } catch { errorMessage = "无法读取练习记录：\(error.localizedDescription)" }
    }

    func latest(for id: UUID) -> PracticeHistoryRecord? { records.first { $0.scoreID == id } }

    func latest(for id: UUID, part: PracticePart) -> PracticeHistoryRecord? {
        records.first { $0.scoreID == id && $0.artifactName == part.artifactName }
    }

    func save(report: [String: Any], for score: ScoreRecord, part: PracticePart? = nil) {
        guard let fileURL else { return }
        do {
            // The renderer may represent a measure label as a number or as a string (e.g. pickups).
            let normalized = (report["errors"] as? [[String: Any]] ?? []).map(Self.normalizeMeasure)
            let issues = try JSONDecoder().decode([PracticeIssue].self,
                from: JSONSerialization.data(withJSONObject: normalized))
            var metricPayload: [String: Any] = [:]
            for key in ["firstTryCorrect", "total", "results", "input", "mode", "bpm", "scope"] {
                if let value = report[key], !(value is NSNull) { metricPayload[key] = value }
            }
            if let results = report["results"] as? [[String: Any]] {
                metricPayload["results"] = results.map(Self.normalizeMeasure)
            }
            let metrics = try JSONDecoder().decode(PracticeMetrics.self,
                from: JSONSerialization.data(withJSONObject: metricPayload))
            try Self.validate(metrics)
            let record = PracticeHistoryRecord(id: UUID(), scoreID: score.id,
                title: report["title"] as? String ?? score.filename, date: Date(),
                durationSeconds: max(0, report["durationSeconds"] as? Double ?? 0),
                completed: report["completed"] as? Bool ?? false,
                measureCount: max(0, report["measureCount"] as? Int ?? 0), errors: issues,
                artifactName: part?.artifactName, partTitle: part?.title,
                firstTryCorrect: metrics.firstTryCorrect, total: metrics.total, results: metrics.results,
                input: metrics.input, mode: metrics.mode, bpm: metrics.bpm, scope: metrics.scope)
            let updated = Array(([record] + records).prefix(500))
            try JSONEncoder().encode(updated).write(to: fileURL, options: .atomic)
            records = updated
            errorMessage = nil
        } catch { errorMessage = "无法保存练习记录：\(error.localizedDescription)" }
    }

    func delete(id: UUID) {
        guard records.contains(where: { $0.id == id }) else { return }
        replaceRecords(records.filter { $0.id != id })
    }

    func clear() { replaceRecords([]) }

    private func replaceRecords(_ updated: [PracticeHistoryRecord]) {
        guard let fileURL else {
            errorMessage = errorMessage ?? "无法保存练习记录，请先解决本地存储错误。"
            return
        }
        do {
            try JSONEncoder().encode(updated).write(to: fileURL, options: .atomic)
            records = updated
            errorMessage = nil
        } catch { errorMessage = "无法保存练习记录：\(error.localizedDescription)" }
    }

    private static func normalizeMeasure(_ item: [String: Any]) -> [String: Any] {
        var value = item
        if let label = item["measure"] as? String { value["measure"] = label }
        else if let number = item["measure"] as? NSNumber { value["measure"] = number.stringValue }
        else { value["measure"] = "—" }
        return value
    }

    private static func validate(_ metrics: PracticeMetrics) throws {
        if let total = metrics.total, total < 0 { throw NoteLiteError.invalidResponse }
        if let correct = metrics.firstTryCorrect,
           correct < 0 || metrics.total.map({ correct > $0 }) == true { throw NoteLiteError.invalidResponse }
        if let results = metrics.results {
            guard results.allSatisfy({ $0.index >= 0 && $0.beat.isFinite && $0.correct >= 0 &&
                $0.expected >= $0.correct && ["correct", "corrected", "missing"].contains($0.status) }),
                metrics.total.map({ results.count <= $0 }) ?? true,
                metrics.firstTryCorrect.map({ $0 <= results.count }) ?? true else { throw NoteLiteError.invalidResponse }
        }
        if let bpm = metrics.bpm, !bpm.isFinite || bpm <= 0 { throw NoteLiteError.invalidResponse }
        if let scope = metrics.scope, scope.part.isEmpty || scope.from < 1 || scope.to < scope.from {
            throw NoteLiteError.invalidResponse
        }
    }
}

struct PracticeHistoryView: View {
    @EnvironmentObject private var history: PracticeHistoryStore
    @EnvironmentObject private var library: LibraryStore
    @State private var practicing: PracticeSelection?

    var body: some View {
        Group {
            if history.records.isEmpty {
                VStack(spacing: 12) {
                    Image(systemName: "clock").font(.largeTitle).foregroundStyle(.secondary)
                    Text("还没有练习记录").font(.title2.weight(.medium))
                    Text("完成一次练习后，在这里查看错音和需要重练的小节。")
                        .foregroundStyle(.secondary).multilineTextAlignment(.center)
                }.frame(maxWidth: .infinity, maxHeight: .infinity).padding(24)
            } else {
                List(history.records) { record in
                    NavigationLink {
                        review(record)
                    } label: {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(record.title).font(.headline)
                            if let part = record.partTitle { Text(part).font(.subheadline) }
                            Text(record.date, style: .date).font(.caption).foregroundStyle(.secondary)
                            Text("\(record.measureCount) 小节 · \(record.errorCount) 处记录\(record.completed ? "" : " · 未完成")")
                                .font(.subheadline).foregroundStyle(.secondary)
                        }.padding(.vertical, 8)
                    }
                }.listStyle(.plain)
            }
        }
        .navigationTitle("练习记录")
        #if os(iOS)
        .fullScreenCover(item: $practicing) { selection in
            PracticeView(record: selection.score, part: selection.part, onDismiss: { practicing = nil })
        }
        #else
        .sheet(item: $practicing) { selection in
            PracticeView(record: selection.score, part: selection.part, onDismiss: { practicing = nil })
                .noteLiteSheetSize(idealWidth: 1440, idealHeight: 900)
        }
        #endif
        .alert("练习记录", isPresented: Binding(get: { history.errorMessage != nil },
            set: { if !$0 { history.errorMessage = nil } })) {
            Button("好", role: .cancel) { history.errorMessage = nil }
        } message: { Text(history.errorMessage ?? "") }
    }

    private func review(_ record: PracticeHistoryRecord) -> some View {
        List {
            Section {
                Text(record.title).font(.title2.weight(.medium))
                if let part = record.partTitle { Text(part).font(.headline) }
                Text("\(Int(record.durationSeconds / 60)) 分 \(Int(record.durationSeconds) % 60) 秒 · \(record.measureCount) 小节")
                    .foregroundStyle(.secondary)
                if !record.completed { Text("本次练习未完成；未演奏的部分未评分。").foregroundStyle(.secondary) }
            }
            Section("需要再练的地方") {
                if record.errors.isEmpty {
                    Text("本次未记录错音。").foregroundStyle(.secondary)
                }
                ForEach(Array(record.errors.enumerated()), id: \.offset) { _, issue in
                    VStack(alignment: .leading, spacing: 6) {
                        Text("第 \(issue.measure) 小节 · 第 \(issue.beat.formatted()) 拍 · \(issue.label)")
                            .foregroundStyle(NoteLiteTheme.wrong)
                        Text(issue.detail).font(.subheadline)
                    }.padding(.vertical, 6)
                }
            }
            if let score = library.record(record.scoreID),
               let part = library.practicePart(score, artifactName: record.artifactName) {
                Section {
                    Button("再练一遍") { practicing = PracticeSelection(score: score, part: part) }
                        .buttonStyle(.borderedProminent)
                }
            }
        }.listStyle(.plain).navigationTitle("练习回顾")
    }
}
