import Foundation
import AVFoundation

/// Streams validated local PCM into a native consumer. A nil target keeps the
/// device/file rate for MPM/YIN; neural input explicitly requests 22050 Hz.
enum NoteWiseRecordingReader {
    struct Metadata {
        let sampleRate: Double
        let sampleCount: Int
        let durationMs: Double
    }
    static func stream(_ url: URL, targetSampleRate: Double? = nil,
                       checkCancellation: () throws -> Void,
                       consume: (UnsafeBufferPointer<Float>, Double) throws -> Void) throws -> Metadata {
        try checkCancellation()
        guard url.isFileURL, url.pathExtension.lowercased() == "wav",
              let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize,
              size > 44, size <= CloudAccountClient.maximumRecordingBytes else {
            throw NoteWiseTranscriptionError.invalidRecording
        }
        let file = try AVAudioFile(forReading: url, commonFormat: .pcmFormatFloat32, interleaved: false)
        let source = file.processingFormat
        let seconds = Double(file.length) / source.sampleRate
        let rate = targetSampleRate ?? source.sampleRate
        guard seconds > 0, seconds <= 600, (8000...96000).contains(source.sampleRate),
              (8000...96000).contains(rate), (1...2).contains(source.channelCount),
              let destination = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: rate,
                  channels: 1, interleaved: false),
              let converter = AVAudioConverter(from: source, to: destination) else {
            throw NoteWiseTranscriptionError.invalidRecording
        }
        let expected = Int(ceil(seconds * rate))
        var callbackError: Error?
        var iterations = 0, count = 0
        while true {
            try checkCancellation()
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
                let length = min(Int(output.frameLength), max(0, expected - count))
                let values = UnsafeBufferPointer(start: channel, count: length)
                guard values.allSatisfy(\.isFinite) else { throw NoteWiseTranscriptionError.invalidRecording }
                if length > 0 { try consume(values, rate); count += length }
            }
            switch status {
            case .endOfStream:
                guard count > 0 else { throw NoteWiseTranscriptionError.invalidRecording }
                return Metadata(sampleRate: rate, sampleCount: count, durationMs: Double(count) * 1000 / rate)
            case .error: throw NoteWiseTranscriptionError.invalidRecording
            case .haveData, .inputRanDry: continue
            @unknown default: throw NoteWiseTranscriptionError.invalidRecording
            }
        }
    }
    static func readModelPCM(_ url: URL, checkCancellation: () throws -> Void) throws -> [Float] {
        var samples: [Float] = []
        _ = try stream(url, targetSampleRate: Double(NoteWiseBasicPitchDecoder.sampleRate),
            checkCancellation: checkCancellation) { values, _ in samples.append(contentsOf: values) }
        return samples
    }
}
