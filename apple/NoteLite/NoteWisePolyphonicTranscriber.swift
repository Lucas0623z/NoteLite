import Foundation
import AVFoundation
import CoreML

private final class NoteWiseTranscriptionCancellation: @unchecked Sendable {
    private let lock = NSLock()
    private var cancelled = false
    func cancel() { lock.lock(); cancelled = true; lock.unlock() }
    func check() throws {
        lock.lock(); let value = cancelled; lock.unlock()
        if value { throw CancellationError() }
    }
}

/// Bounded numeric evidence for native verification. No PCM, file path,
/// account data or score enters this snapshot or the WebView result.
struct NoteWiseTranscriptionDiagnostics: Codable, Sendable {
    let computeUnitsRequested: String
    let modelPredictionCount: Int
    let audioSampleCount: Int
    let audioNonzeroSampleCount: Int
    let audioPeakAbsolute: Double
    let audioRMS: Double
    let maximumNoteActivation: Float
    let maximumOnsetActivation: Float
    let maximumContourActivation: Float
    let decodedNotesBeforeAudioConstraint: Int
    let digitalSilenceConstraintApplied: Bool
    let signalQualifiedNotes: Int
    let broadbandCandidatesRejected: Int
    let unresolvedCandidates: Int
    let spectralFramesExamined: Int
    let maximumSpectralConcentration: Double
}

/// The shipped CoreML model, PCM conversion and decoder all run on one native
/// queue. This module never fetches a model, uploads PCM, inspects a score or
/// blocks the UI/WebView to transcribe a recording.
final class NoteWisePolyphonicTranscriber: @unchecked Sendable {
    private let queue = DispatchQueue(label: "com.notelite.notewise.polyphonic", qos: .userInitiated)
    private let bundle: Bundle
    private let computeUnits: MLComputeUnits
    private var model: MLModel?
    private let diagnosticLock = NSLock()
    private var diagnosticValue: NoteWiseTranscriptionDiagnostics?
    // Backend selection alone did not fix the observed upstream division bug.
    // The bundled graph restores TF zero-safe semantics; actual PCM separately
    // qualifies neural candidates. CPU is the reproducible default, with .all
    // retained for genuine same-input numerical regression comparisons.
    init(bundle: Bundle = .main, computeUnits: MLComputeUnits = .cpuOnly) {
        self.bundle = bundle
        self.computeUnits = computeUnits
    }

    func diagnosticsSnapshot() -> NoteWiseTranscriptionDiagnostics? {
        diagnosticLock.lock()
        defer { diagnosticLock.unlock() }
        return diagnosticValue
    }

    private func storeDiagnostics(_ value: NoteWiseTranscriptionDiagnostics?) {
        diagnosticLock.lock()
        diagnosticValue = value
        diagnosticLock.unlock()
    }

    func transcribe(recordingURL: URL, tuning: Double = 440,
                    minimumMIDI: Int = 21, maximumMIDI: Int = 108) async throws -> NoteWiseRecordedTranscription {
        guard tuning.isFinite, (400...480).contains(tuning),
              (21...108).contains(minimumMIDI), (minimumMIDI...108).contains(maximumMIDI) else {
            throw NoteWiseTranscriptionError.invalidOutput
        }
        let cancellation = NoteWiseTranscriptionCancellation()
        return try await withTaskCancellationHandler(operation: {
            try Task.checkCancellation()
            return try await withCheckedThrowingContinuation { continuation in
                queue.async { [self] in
                    do {
                        storeDiagnostics(nil)
                        try cancellation.check()
                        let audio = try readAudio(recordingURL, cancellation: cancellation)
                        var nonzeroSamples = 0
                        var peak: Double = 0
                        var squaredSum: Double = 0
                        for sample in audio {
                            if sample != 0 { nonzeroSamples += 1 }
                            let value = Double(sample)
                            peak = max(peak, abs(value))
                            squaredSum += value * value
                        }
                        // Run the actual pinned model even for digital silence.
                        // Its priors alone cannot prove a heard musical event.
                        let values = try infer(audio, cancellation: cancellation)
                        let decoded = try NoteWiseBasicPitchDecoder.decode(frames: values.frames, onsets: values.onsets,
                            contour: values.contour, sampleCount: audio.count, tuning: tuning,
                            minimumMIDI: minimumMIDI, maximumMIDI: maximumMIDI,
                            checkCancellation: { try cancellation.check() })
                        let digitalSilence = nonzeroSamples == 0
                        let acoustic = try NoteWiseAcousticEvidence(audio: audio).qualify(decoded,
                            checkCancellation: { try cancellation.check() })
                        let result = NoteWiseRecordedTranscription(notes: digitalSilence ? [] : acoustic.notes,
                            uncertaintyIntervals: digitalSilence ? [] : acoustic.uncertainty,
                            sampleRate: decoded.sampleRate, sampleCount: decoded.sampleCount,
                            durationMs: decoded.durationMs, tuning: decoded.tuning,
                            modelVersion: decoded.modelVersion, detectorVersion: decoded.detectorVersion,
                            supportedPitchRange: decoded.supportedPitchRange,
                            warnings: decoded.warnings + (digitalSilence ? ["录音为数字静音，没有可听见的音乐事件。"] :
                                (acoustic.unresolvedCandidates > 0 ? ["部分模型候选缺少稳定音高的录音证据，已标为待复核。"] : [])))
                        let requestedUnits: String
                        switch computeUnits {
                        case .all: requestedUnits = "all"
                        case .cpuOnly: requestedUnits = "cpuOnly"
                        case .cpuAndGPU: requestedUnits = "cpuAndGPU"
                        case .cpuAndNeuralEngine: requestedUnits = "cpuAndNeuralEngine"
                        @unknown default: requestedUnits = "unknown"
                        }
                        storeDiagnostics(NoteWiseTranscriptionDiagnostics(computeUnitsRequested: requestedUnits,
                            modelPredictionCount: values.predictionCount, audioSampleCount: audio.count,
                            audioNonzeroSampleCount: nonzeroSamples, audioPeakAbsolute: peak,
                            audioRMS: sqrt(squaredSum / Double(audio.count)),
                            maximumNoteActivation: values.frames.max() ?? 0,
                            maximumOnsetActivation: values.onsets.max() ?? 0,
                            maximumContourActivation: values.contour.max() ?? 0,
                            decodedNotesBeforeAudioConstraint: decoded.notes.count,
                            digitalSilenceConstraintApplied: digitalSilence,
                            signalQualifiedNotes: acoustic.notes.count,
                            broadbandCandidatesRejected: acoustic.broadbandCandidatesRejected,
                            unresolvedCandidates: acoustic.unresolvedCandidates,
                            spectralFramesExamined: acoustic.spectralFramesExamined,
                            maximumSpectralConcentration: acoustic.maximumSpectralConcentration))
                        try cancellation.check()
                        continuation.resume(returning: result)
                    } catch { continuation.resume(throwing: error) }
                }
            }
        }, onCancel: { cancellation.cancel() })
    }

    private func loadModel() throws -> MLModel {
        if let model { return model }
        guard let url = bundle.url(forResource: "NoteWiseBasicPitch", withExtension: "mlmodelc") else {
            throw NoteWiseTranscriptionError.missingModel
        }
        let configuration = MLModelConfiguration()
        configuration.computeUnits = computeUnits
        let loaded = try MLModel(contentsOf: url, configuration: configuration)
        let input = loaded.modelDescription.inputDescriptionsByName["input_2"]?.multiArrayConstraint
        guard input?.shape.map(\.intValue) == [1, NoteWiseBasicPitchDecoder.inputSamples, 1],
              Set(loaded.modelDescription.outputDescriptionsByName.keys) == ["Identity", "Identity_1", "Identity_2"] else {
            throw NoteWiseTranscriptionError.modelContract
        }
        model = loaded
        return loaded
    }

    private func readAudio(_ url: URL, cancellation: NoteWiseTranscriptionCancellation) throws -> [Float] {
        try NoteWiseRecordingReader.readModelPCM(url, checkCancellation: { try cancellation.check() })
    }

    private struct Activations {
        var frames: [Float] = []
        var onsets: [Float] = []
        var contour: [Float] = []
        var predictionCount = 0
    }

    private func infer(_ audio: [Float], cancellation: NoteWiseTranscriptionCancellation) throws -> Activations {
        let model = try loadModel()
        let frameHop = NoteWiseBasicPitchDecoder.frameHop
        let inputCount = NoteWiseBasicPitchDecoder.inputSamples
        let halfOverlap = NoteWiseBasicPitchDecoder.overlapFrames / 2
        let prefixSamples = halfOverlap * frameHop
        let hop = inputCount - NoteWiseBasicPitchDecoder.overlapFrames * frameHop
        let expectedFrames = Int(floor(Double(audio.count) * 86 / Double(NoteWiseBasicPitchDecoder.sampleRate)))
        var result = Activations()
        for position in stride(from: 0, to: audio.count + prefixSamples, by: hop) {
            try cancellation.check()
            try autoreleasepool {
                let input = try MLMultiArray(shape: [1, NSNumber(value: inputCount), 1], dataType: .float32)
                let pointer = input.dataPointer.assumingMemoryBound(to: Float.self)
                for index in 0..<inputCount {
                    let source = position + index - prefixSamples
                    pointer[index] = source >= 0 && source < audio.count ? audio[source] : 0
                }
                let provider = try MLDictionaryFeatureProvider(dictionary: ["input_2": MLFeatureValue(multiArray: input)])
                let prediction = try model.prediction(from: provider)
                result.predictionCount += 1
                try append(prediction.featureValue(for: "Identity_1")?.multiArrayValue, bins: 88,
                           into: &result.frames, expectedFrames: expectedFrames)
                try append(prediction.featureValue(for: "Identity_2")?.multiArrayValue, bins: 88,
                           into: &result.onsets, expectedFrames: expectedFrames)
                try append(prediction.featureValue(for: "Identity")?.multiArrayValue, bins: 264,
                           into: &result.contour, expectedFrames: expectedFrames)
            }
            if result.frames.count / 88 >= expectedFrames { break }
        }
        guard result.frames.count / 88 == expectedFrames, expectedFrames > 0 else {
            throw NoteWiseTranscriptionError.invalidOutput
        }
        return result
    }

    private func append(_ array: MLMultiArray?, bins: Int, into values: inout [Float], expectedFrames: Int) throws {
        guard let array, array.shape.map(\.intValue) == [1, NoteWiseBasicPitchDecoder.outputFrames, bins],
              array.strides.count == 3 else { throw NoteWiseTranscriptionError.modelContract }
        let timeStride = array.strides[1].intValue, pitchStride = array.strides[2].intValue
        let lower = NoteWiseBasicPitchDecoder.overlapFrames / 2
        let upper = NoteWiseBasicPitchDecoder.outputFrames - lower
        for frame in lower..<upper {
            if values.count / bins >= expectedFrames { break }
            for pitch in 0..<bins {
                let index = frame * timeStride + pitch * pitchStride
                let value: Float
                switch array.dataType {
                case .float32: value = array.dataPointer.assumingMemoryBound(to: Float.self)[index]
                case .double: value = Float(array.dataPointer.assumingMemoryBound(to: Double.self)[index])
                // CoreML's indexed NSNumber accessor supports float16 on Intel
                // macOS too, where Swift.Float16 is unavailable. Indices also
                // preserve the model's actual strides rather than flattening it.
                case .float16:
                    value = array[[NSNumber(value: 0), NSNumber(value: frame), NSNumber(value: pitch)]].floatValue
                default: throw NoteWiseTranscriptionError.modelContract
                }
                guard value.isFinite && value >= 0 && value <= 1.001 else { throw NoteWiseTranscriptionError.invalidOutput }
                values.append(value)
            }
        }
    }
}
