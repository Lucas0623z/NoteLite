import Foundation
import Accelerate

/// A neural candidate is not evidence that a musical pitch was actually heard.
/// This independent PCM check uses relative spectral concentration and stable
/// pitch peaks. Multiplying every sample by any nonzero gain leaves its decision
/// unchanged; no loudness cutoff, score information or neural threshold is used.
final class NoteWiseAcousticEvidence {
    struct Summary {
        let notes: [NoteWiseRecordedNote]
        let uncertainty: [NoteWiseRecordedUncertainty]
        let broadbandCandidatesRejected: Int
        let unresolvedCandidates: Int
        let spectralFramesExamined: Int
        let maximumSpectralConcentration: Double
    }
    private struct Spectrum {
        let power: [Double]
        let total: Double
        let concentration: Double
    }
    private static let count = 4096 // 185.8 ms at the model's real PCM rate.
    private static let hop = 1024
    private let audio: [Float]
    private let setup: vDSP_DFT_SetupD
    private var cache: [Int: Spectrum] = [:]
    private var cacheOrder: [Int] = []
    private var examined = 0
    private var maximumConcentration: Double = 0

    init(audio: [Float]) throws {
        guard !audio.isEmpty, audio.allSatisfy(\.isFinite),
              let setup = vDSP_DFT_zop_CreateSetupD(nil, vDSP_Length(Self.count), .FORWARD) else {
            throw NoteWiseTranscriptionError.invalidOutput
        }
        self.audio = audio
        self.setup = setup
    }
    deinit { vDSP_DFT_DestroySetupD(setup) }

    private func spectrum(at milliseconds: Double) -> Spectrum {
        let sample = Int(milliseconds * Double(NoteWiseBasicPitchDecoder.sampleRate) / 1000)
        let center = max(0, min(audio.count - 1, sample)) / Self.hop * Self.hop
        if let cached = cache[center] { return cached }
        var real = [Double](repeating: 0, count: Self.count)
        let imaginary = real
        var outReal = real, outImaginary = real
        // Remove DC before applying a Hann window. Digital zero remains exact.
        let lower = max(0, center - Self.count / 2)
        let upper = min(audio.count, center + Self.count / 2)
        var mean: Double = 0
        if upper > lower {
            for index in lower..<upper { mean += Double(audio[index]) }
            mean /= Double(upper - lower)
        }
        for index in 0..<Self.count {
            let source = center - Self.count / 2 + index
            if source >= 0 && source < audio.count {
                let window = 0.5 - 0.5 * cos(2 * Double.pi * Double(index) / Double(Self.count - 1))
                real[index] = (Double(audio[source]) - mean) * window
            }
        }
        vDSP_DFT_ExecuteD(setup, real, imaginary, &outReal, &outImaginary)
        var power = [Double](repeating: 0, count: Self.count / 2)
        for index in 1..<power.count {
            power[index] = outReal[index] * outReal[index] + outImaginary[index] * outImaginary[index]
        }
        let total = power.reduce(0, +)
        // Broadband noise distributes energy over thousands of bins; sustained
        // musical partials concentrate it into a small set. Ratios are gain free.
        let concentration = total == 0 ? 0 : power.sorted(by: >).prefix(32).reduce(0, +) / total
        let result = Spectrum(power: power, total: total, concentration: concentration)
        maximumConcentration = max(maximumConcentration, concentration)
        examined += 1
        // A ten-minute recording never keeps a full spectrogram in memory.
        if cacheOrder.count == 64 { cache.removeValue(forKey: cacheOrder.removeFirst()) }
        cache[center] = result
        cacheOrder.append(center)
        return result
    }

    private func supports(_ frequency: Double, in spectrum: Spectrum) -> Bool {
        guard spectrum.total > 0, spectrum.concentration >= 0.35 else { return false }
        let bin = frequency * Double(Self.count) / Double(NoteWiseBasicPitchDecoder.sampleRate)
        guard bin >= 3, bin < Double(spectrum.power.count - 12) else { return false }
        // ±50 cents allows ordinary tuning/vibrato. Include the Hann main lobe
        // for low notes; compare against nearby bins outside that lobe.
        let width = max(1, Int(ceil(bin * (pow(2, 50.0 / 1200) - 1))))
        let center = Int(bin.rounded())
        let lower = max(1, center - width), upper = min(spectrum.power.count - 1, center + width)
        let peak = spectrum.power[lower...upper].max() ?? 0
        let band = spectrum.power[lower...upper].reduce(0, +)
        var surroundings: [Double] = []
        for offset in (width + 3)...(width + 11) {
            for index in [center - offset, center + offset] where index > 0 && index < spectrum.power.count {
                surroundings.append(spectrum.power[index])
            }
        }
        surroundings.sort()
        let floor = surroundings.isEmpty ? spectrum.total : surroundings[surroundings.count / 2]
        // Require a pitch-local peak at least 12 times the local median and a
        // measurable share of total signal energy, rather than accepting priors.
        return band / spectrum.total >= 0.005 && peak > 0 && (floor == 0 || peak / floor >= 12)
    }

    func qualify(_ decoded: NoteWiseRecordedTranscription,
                 checkCancellation: () throws -> Void = {}) throws -> Summary {
        var notes: [NoteWiseRecordedNote] = []
        var uncertainty: [NoteWiseRecordedUncertainty] = []
        var broadband = 0, unresolved = 0
        for note in decoded.notes {
            try checkCancellation()
            let times = [note.onsetMs + note.durationMs / 3, note.onsetMs + note.durationMs * 2 / 3]
            let spectra = times.map { spectrum(at: $0) }
            let frequency = 440 * pow(2, Double(note.modelMIDI - 69) / 12 + note.cents / 1200)
            if spectra.allSatisfy({ supports(frequency, in: $0) }) {
                notes.append(note)
            } else if spectra.allSatisfy({ $0.concentration < 0.20 }) {
                // Confirmed broadband/nonperiodic content cannot be a pitch
                // opportunity. Keep the raw candidate count in native diagnostics.
                broadband += 1
            } else {
                unresolved += 1
                uncertainty.append(NoteWiseRecordedUncertainty(onsetMs: note.onsetMs,
                    offsetMs: note.offsetMs, reason: "模型候选缺少稳定音高的录音证据，需要复核。"))
            }
        }
        for interval in decoded.uncertaintyIntervals {
            try checkCancellation()
            if spectrum(at: (interval.onsetMs + interval.offsetMs) / 2).concentration >= 0.20 {
                uncertainty.append(interval)
            }
        }
        return Summary(notes: notes, uncertainty: uncertainty,
            broadbandCandidatesRejected: broadband, unresolvedCandidates: unresolved,
            spectralFramesExamined: examined, maximumSpectralConcentration: maximumConcentration)
    }
}
