import Foundation

struct PracticePart: Identifiable, Equatable {
    let artifactName: String?
    let url: URL
    let title: String?
    var id: String { artifactName ?? "source" }
}

struct PracticeSelection: Identifiable {
    let score: ScoreRecord
    let part: PracticePart
    var id: String { score.id.uuidString + "/" + part.id }
}
