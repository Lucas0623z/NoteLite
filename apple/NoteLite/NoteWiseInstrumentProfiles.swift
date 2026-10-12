import Foundation

struct NoteWiseInstrumentProfile: Decodable {
    let id: String
    let name: String
    let minMidi: Int
    let maxMidi: Int
    let windowSize: Int
    let family: String?
    func frequency(_ midi: Int, tuning: Double) -> Double { tuning * pow(2, Double(midi - 69) / 12) }
}

enum NoteWiseInstrumentProfiles {
    private struct Manifest: Decodable { let schemaVersion: Int; let profiles: [NoteWiseInstrumentProfile] }
    // Generated and checked against the existing shared Windows resolver, never next-note biased.
    private static let manifest: Result<Manifest, Error> = Result {
        guard let url = Bundle.main.url(forResource: "NoteWiseProfiles", withExtension: "json") else {
            throw NoteLiteError.server("乐器配置未随应用安装，请更新应用。")
        }
        return try JSONDecoder().decode(Manifest.self, from: Data(contentsOf: url))
    }
    static func resolve(_ id: String) throws -> NoteWiseInstrumentProfile {
        let value = try manifest.get()
        guard value.schemaVersion == 1, let result = value.profiles.first(where: { $0.id == id }),
              result.minMidi >= 0, result.maxMidi <= 127, result.minMidi < result.maxMidi,
              [4096, 8192].contains(result.windowSize) else { throw NoteLiteError.invalidResponse }
        return result
    }
}
