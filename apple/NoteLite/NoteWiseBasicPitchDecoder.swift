// Copyright 2022 Spotify AB; Swift adaptation copyright 2026 NoteLite contributors.
// Adapted from basic_pitch/note_creation.py at v0.4.0 under Apache-2.0.
// The original license ships in NoteWiseModels/BASIC-PITCH-LICENSE.
import Foundation

struct NoteWiseRecordedNote: Codable, Sendable {
    let id: String
    let midi: Int
    let modelMIDI: Int
    let onsetMs: Double
    let offsetMs: Double
    let durationMs: Double
    let confidence: Double
    let cents: Double
    let centsEvidence: String
    let releaseReliable: Bool
}

struct NoteWiseRecordedUncertainty: Codable, Sendable {
    let onsetMs: Double
    let offsetMs: Double
    let reason: String
}

struct NoteWiseRecordedTranscription: Codable, Sendable {
    let notes: [NoteWiseRecordedNote]
    let uncertaintyIntervals: [NoteWiseRecordedUncertainty]
    let sampleRate: Int
    let sampleCount: Int
    let durationMs: Double
    let tuning: Double
    let modelVersion: String
    let detectorVersion: String
    let supportedPitchRange: [String: Int]
    let warnings: [String]
    var fusionDiagnostics: NoteWiseFusionDiagnostics? = nil

    var dictionary: [String: Any] {
        // This fixed Codable structure contains only JSON-compatible scalars.
        guard let data = try? JSONEncoder().encode(self),
              let result = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return [:] }
        return result
    }
}

enum NoteWiseTranscriptionError: LocalizedError {
    case invalidRecording
    case missingModel
    case modelContract
    case invalidOutput
    case tooDense
    var errorDescription: String? {
        switch self {
        case .invalidRecording: return "录后复核需要完整录音，时长最多 10 分钟，文件最多 100 MB。"
        case .missingModel: return "本机听音复核模型缺失，请重新安装应用。"
        case .modelContract: return "本机听音复核模型版本不匹配，请重新安装应用。"
        case .invalidOutput: return "此次录音无法生成可靠的复核数据，已保留原练习记录。"
        case .tooDense: return "此次录音包含过多重叠信号，无法完成本机复核；已保留原练习记录。"
        }
    }
}

/// Preserves the pinned official decoder's onset, residual-energy and contour
/// rules. Model activations are not calibrated probabilities; contour cents
/// stay explicitly coarse and cannot become a precise intonation verdict.
enum NoteWiseBasicPitchDecoder {
    static let sampleRate = 22050
    static let inputSamples = 43844
    static let outputFrames = 172
    static let overlapFrames = 30
    static let frameHop = 256
    static let pitches = 88
    static let contours = 264
    static let maximumNotes = 20000
    private struct FrameNote {
        let start: Int
        let end: Int
        let pitch: Int
        let amplitude: Float
    }
    private struct EnergyPeak {
        let index: Int
        let amplitude: Float
    }

    static func frameTime(_ frame: Int) -> Double {
        let hop = Double(frameHop) / Double(sampleRate)
        let correction = hop * (Double(outputFrames) - Double(inputSamples) / Double(frameHop)) + 0.0018
        return Double(frame) * hop - correction * floor(Double(frame) / Double(outputFrames))
    }

    static func decode(frames: [Float], onsets: [Float], contour: [Float], sampleCount: Int,
                       tuning: Double = 440, minimumMIDI: Int = 21, maximumMIDI: Int = 108,
                       checkCancellation: () throws -> Void = {}) throws -> NoteWiseRecordedTranscription {
        guard sampleCount > 0, sampleCount <= sampleRate * 600,
              tuning.isFinite, (400...480).contains(tuning),
              (21...108).contains(minimumMIDI), (minimumMIDI...108).contains(maximumMIDI),
              !frames.isEmpty, frames.count % pitches == 0, onsets.count == frames.count,
              contour.count == frames.count * 3,
              [frames, onsets, contour].allSatisfy({ $0.allSatisfy({ $0.isFinite && $0 >= 0 && $0 <= 1.001 }) }) else {
            throw NoteWiseTranscriptionError.invalidOutput
        }
        let count = frames.count / pitches
        let seconds = Double(sampleCount) / Double(sampleRate)
        let onsetThreshold: Float = 0.5, frameThreshold: Float = 0.3
        let minimumLength = 11, tolerance = 11
        var energy = frames
        var inferred = onsets
        // A4 may move the expected boundary by more than one semitone. Keep
        // two adjacent model bins until calibrated pitches are filtered below.
        // Apply this constraint before inferred onset normalization, matching
        // the upstream decoder's frequency-constraint ordering.
        let lowest = max(0, minimumMIDI - 23), highest = min(87, maximumMIDI - 19)
        if lowest > 0 || highest < 87 {
            for time in 0..<count {
                for pitch in 0..<pitches where pitch < lowest || pitch > highest {
                    energy[time * pitches + pitch] = 0
                    inferred[time * pitches + pitch] = 0
                }
            }
        }
        var differences = Array(repeating: Float(0), count: frames.count)
        var maximumDifference: Float = 0
        let maximumOnset = inferred.max() ?? 0
        if count > 2 {
            for time in 2..<count {
                for pitch in 0..<pitches {
                    let index = time * pitches + pitch
                    let difference = max(0, min(energy[index] - energy[index - pitches],
                                                energy[index] - energy[index - 2 * pitches]))
                    differences[index] = difference
                    maximumDifference = max(maximumDifference, difference)
                }
            }
        }
        if maximumDifference > 0 {
            for index in inferred.indices {
                inferred[index] = max(inferred[index], differences[index] * maximumOnset / maximumDifference)
            }
        }
        func clear(_ time: Int, _ pitch: Int) {
            energy[time * pitches + pitch] = 0
            if pitch > 0 { energy[time * pitches + pitch - 1] = 0 }
            if pitch < 87 { energy[time * pitches + pitch + 1] = 0 }
        }
        func amplitude(_ start: Int, _ end: Int, _ pitch: Int) -> Float {
            var total: Float = 0
            for time in start..<end { total += frames[time * pitches + pitch] }
            return total / Float(end - start)
        }
        var notes: [FrameNote] = []
        // scipy.argrelmax's strict neighbouring comparison and the upstream
        // reversed time/frequency ordering preserve repeated attacks.
        if count > 2 {
            for start in stride(from: count - 2, through: 1, by: -1) {
                if start % 64 == 0 { try checkCancellation() }
                for pitch in stride(from: 87, through: 0, by: -1) {
                    let index = start * pitches + pitch
                    guard inferred[index] >= onsetThreshold,
                          inferred[index] > inferred[index - pitches],
                          inferred[index] > inferred[index + pitches] else { continue }
                    var end = start + 1, below = 0
                    while end < count - 1 && below < tolerance {
                        below = energy[end * pitches + pitch] < frameThreshold ? below + 1 : 0
                        end += 1
                    }
                    end -= below
                    guard end - start > minimumLength else { continue }
                    for time in start..<end { clear(time, pitch) }
                    notes.append(FrameNote(start: start, end: end, pitch: pitch, amplitude: amplitude(start, end, pitch)))
                    if notes.count > maximumNotes { throw NoteWiseTranscriptionError.tooDense }
                }
            }
        }
        // Residual values only change to zero. One descending queue yields
        // exactly the same max/tie order as the upstream repeated argmax,
        // without rescanning the whole recording for every residual note.
        var peaks: [EnergyPeak] = []
        for index in energy.indices where energy[index] > frameThreshold {
            peaks.append(EnergyPeak(index: index, amplitude: energy[index]))
            if peaks.count > 512000 { throw NoteWiseTranscriptionError.tooDense }
        }
        peaks.sort { $0.amplitude == $1.amplitude ? $0.index < $1.index : $0.amplitude > $1.amplitude }
        for (position, peak) in peaks.enumerated() {
            if position % 128 == 0 { try checkCancellation() }
            guard energy[peak.index] > frameThreshold else { continue }
            let middle = peak.index / pitches, pitch = peak.index % pitches
            energy[peak.index] = 0
            var time = middle + 1, below = 0
            while time < count - 1 && below < tolerance {
                below = energy[time * pitches + pitch] < frameThreshold ? below + 1 : 0
                clear(time, pitch)
                time += 1
            }
            let end = time - 1 - below
            time = middle - 1; below = 0
            while time > 0 && below < tolerance {
                below = energy[time * pitches + pitch] < frameThreshold ? below + 1 : 0
                clear(time, pitch)
                time -= 1
            }
            let start = time + 1 + below
            guard start >= 0, end < count, end - start > minimumLength else { continue }
            notes.append(FrameNote(start: start, end: end, pitch: pitch, amplitude: amplitude(start, end, pitch)))
            if notes.count > maximumNotes { throw NoteWiseTranscriptionError.tooDense }
        }
        var recorded: [NoteWiseRecordedNote] = []
        let tuningShift = 12 * log2(tuning / 440)
        for frameNote in notes {
            try checkCancellation()
            let center = frameNote.pitch * 3
            let low = max(0, center - 25), high = min(contours - 1, center + 25)
            var bends: [Int] = []
            for time in frameNote.start..<frameNote.end {
                var winner = low, salience: Double = -1
                for bin in low...high {
                    let distance = Double(bin - center)
                    let weighted = Double(contour[time * contours + bin]) * exp(-distance * distance / 50)
                    if weighted > salience { salience = weighted; winner = bin }
                }
                bends.append(winner - center)
            }
            bends.sort()
            let bend: Double
            if bends.count % 2 == 0 { bend = Double(bends[bends.count / 2 - 1] + bends[bends.count / 2]) / 2 }
            else { bend = Double(bends[bends.count / 2]) }
            let modelMIDI = frameNote.pitch + 21
            let calibrated = Double(modelMIDI) + bend / 3 - tuningShift
            let midi = Int(calibrated.rounded(.toNearestOrEven))
            let start = max(0, frameTime(frameNote.start)), end = min(seconds, frameTime(frameNote.end))
            guard (minimumMIDI...maximumMIDI).contains(midi), end > start else { continue }
            recorded.append(NoteWiseRecordedNote(id: "", midi: midi, modelMIDI: modelMIDI,
                onsetMs: start * 1000, offsetMs: end * 1000, durationMs: (end - start) * 1000,
                confidence: Double(min(1, max(0, frameNote.amplitude))), cents: (calibrated - Double(midi)) * 100,
                centsEvidence: "coarse-basic-pitch-contour", releaseReliable: end < seconds - 2 * Double(frameHop) / Double(sampleRate)))
        }
        recorded.sort { $0.onsetMs == $1.onsetMs ? $0.midi < $1.midi : $0.onsetMs < $1.onsetMs }
        recorded = recorded.enumerated().map { index, note in
            NoteWiseRecordedNote(id: "recorded-\(index + 1)", midi: note.midi, modelMIDI: note.modelMIDI,
                onsetMs: note.onsetMs, offsetMs: note.offsetMs, durationMs: note.durationMs,
                confidence: note.confidence, cents: note.cents, centsEvidence: note.centsEvidence,
                releaseReliable: note.releaseReliable)
        }
        let uncertainty = recorded.compactMap { note -> NoteWiseRecordedUncertainty? in
            guard note.confidence < 0.4 || !note.releaseReliable else { return nil }
            return NoteWiseRecordedUncertainty(onsetMs: note.onsetMs, offsetMs: note.offsetMs,
                reason: note.confidence < 0.4 ? "low-confidence-transcription" : "recording-ended-before-reliable-release")
        }
        return NoteWiseRecordedTranscription(notes: recorded, uncertaintyIntervals: uncertainty,
            sampleRate: sampleRate, sampleCount: sampleCount, durationMs: seconds * 1000, tuning: tuning,
            modelVersion: "0.4.0", detectorVersion: "basic-pitch-coreml-0.4.0",
            supportedPitchRange: ["minimumMIDI": minimumMIDI, "maximumMIDI": maximumMIDI],
            warnings: ["复核置信度属于模型信号强度，并非正确率。", "模型音高轮廓约为三分之一半音，精确音准仍需独立证据。"])
    }
}
