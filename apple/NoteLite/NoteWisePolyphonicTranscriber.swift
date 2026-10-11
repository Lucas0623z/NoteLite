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

/// The shipped CoreML model, PCM conversion and decoder all run on one native
/// queue. This module never fetches a model, uploads PCM, inspects a score or
/// blocks the UI/WebView to transcribe a recording.
final class NoteWisePolyphonicTranscriber: @unchecked Sendable {
    private let queue = DispatchQueue(label: "com.notelite.notewise.polyphonic", qos: .userInitiated)
    private let bundle: Bundle
    private var model: MLModel?
    init(bundle: Bundle = .main) { self.bundle = bundle }

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
                        try cancellation.check()
                        let audio = try readAudio(recordingURL, cancellation: cancellation)
                        let values = try infer(audio, cancellation: cancellation)
                        let result = try NoteWiseBasicPitchDecoder.decode(frames: values.frames, onsets: values.onsets,
                            contour: values.contour, sampleCount: audio.count, tuning: tuning,
                            minimumMIDI: minimumMIDI, maximumMIDI: maximumMIDI,
                            checkCancellation: { try cancellation.check() })
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
        configuration.computeUnits = .all
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
        guard url.isFileURL, url.pathExtension.lowercased() == "wav",
              let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize,
              size > 44, size <= CloudAccountClient.maximumRecordingBytes else {
            throw NoteWiseTranscriptionError.invalidRecording
        }
        let file = try AVAudioFile(forReading: url, commonFormat: .pcmFormatFloat32, interleaved: false)
        let source = file.processingFormat
        let seconds = Double(file.length) / source.sampleRate
        guard seconds > 0, seconds <= 600, (8000...96000).contains(source.sampleRate),
              (1...2).contains(source.channelCount),
              let destination = AVAudioFormat(commonFormat: .pcmFormatFloat32,
                sampleRate: Double(NoteWiseBasicPitchDecoder.sampleRate), channels: 1, interleaved: false),
              let converter = AVAudioConverter(from: source, to: destination) else {
            throw NoteWiseTranscriptionError.invalidRecording
        }
        var samples: [Float] = []
        samples.reserveCapacity(Int(ceil(seconds * destination.sampleRate)))
        var callbackError: Error?
        var iterations = 0
        while true {
            try cancellation.check()
            iterations += 1
            guard iterations <= 4096,
                  let output = AVAudioPCMBuffer(pcmFormat: destination, frameCapacity: 16384) else {
                throw NoteWiseTranscriptionError.invalidRecording
            }
            var conversionError: NSError?
            let status = converter.convert(to: output, error: &conversionError) { requested, status in
                if file.framePosition >= file.length { status.pointee = .endOfStream; return nil }
                guard let input = AVAudioPCMBuffer(pcmFormat: source,
                    frameCapacity: AVAudioFrameCount(min(requested, 16384))) else {
                    status.pointee = .noDataNow; callbackError = NoteWiseTranscriptionError.invalidRecording; return nil
                }
                do {
                    try file.read(into: input, frameCount: input.frameCapacity)
                    guard input.frameLength > 0 else { status.pointee = .endOfStream; return nil }
                    status.pointee = .haveData
                    return input
                } catch { callbackError = error; status.pointee = .noDataNow; return nil }
            }
            if let callbackError { throw callbackError }
            if let conversionError { throw conversionError }
            if output.frameLength > 0, let channel = output.floatChannelData?[0] {
                let values = UnsafeBufferPointer(start: channel, count: Int(output.frameLength))
                guard values.allSatisfy(\.isFinite) else { throw NoteWiseTranscriptionError.invalidRecording }
                samples.append(contentsOf: values)
            }
            guard samples.count <= NoteWiseBasicPitchDecoder.sampleRate * 600 + 16 else {
                throw NoteWiseTranscriptionError.invalidRecording
            }
            switch status {
            case .endOfStream:
                guard !samples.isEmpty else { throw NoteWiseTranscriptionError.invalidRecording }
                // Some resamplers round up their final packet. Keep only the
                // duration of the real recording, never decoder padding.
                return Array(samples.prefix(Int(ceil(seconds * destination.sampleRate))))
            case .error: throw NoteWiseTranscriptionError.invalidRecording
            case .haveData, .inputRanDry: continue
            @unknown default: throw NoteWiseTranscriptionError.invalidRecording
            }
        }
    }

    private struct Activations {
        var frames: [Float] = []
        var onsets: [Float] = []
        var contour: [Float] = []
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
