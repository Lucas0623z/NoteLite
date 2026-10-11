import XCTest
import AVFoundation
@testable import NoteLite

final class NoteWiseRecordedTranscriptionTests: XCTestCase {
    private struct Reference: Decodable {
        let sourceSHA256: String
        let cases: [ReferenceCase]
    }
    private struct ReferenceCase: Decodable {
        let name: String
        let frames: Int
        let sampleCount: Int
        let tuning: Double
        let noteCells: [[Double]]
        let onsetPeaks: [[Double]]
        let contourShift: Int
        let expectedNotes: [ReferenceNote]
    }
    private struct ReferenceNote: Decodable {
        let midi: Int
        let modelMIDI: Int
        let onsetMs: Double
        let offsetMs: Double
        let confidence: Double
        let cents: Double
    }

    func testSwiftDecoderMatchesPinnedOfficialPythonReference() throws {
        let fixture = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "NoteWiseDecoderReference", withExtension: "json"))
        let reference = try JSONDecoder().decode(Reference.self, from: Data(contentsOf: fixture))
        XCTAssertEqual(reference.sourceSHA256, "9c813509acf57ed9b902d2b9fcd9f8118b2c5ffe568a06df9cfa60f5c5ee2572")
        XCTAssertEqual(reference.cases.count, 6)
        for example in reference.cases {
            var frames = Array(repeating: Float(0), count: example.frames * 88)
            var onsets = frames
            var contour = Array(repeating: Float(0), count: example.frames * 264)
            for cell in example.noteCells {
                let pitch = Int(cell[0]), start = Int(cell[1]), end = Int(cell[2])
                for frame in start..<end {
                    frames[frame * 88 + pitch] = Float(cell[3])
                    contour[frame * 264 + pitch * 3 + example.contourShift] = 1
                }
            }
            for peak in example.onsetPeaks { onsets[Int(peak[1]) * 88 + Int(peak[0])] = Float(peak[2]) }
            let actual = try NoteWiseBasicPitchDecoder.decode(frames: frames, onsets: onsets, contour: contour,
                sampleCount: example.sampleCount, tuning: example.tuning)
            XCTAssertEqual(actual.notes.count, example.expectedNotes.count, example.name)
            for (note, expected) in zip(actual.notes, example.expectedNotes) {
                XCTAssertEqual(note.midi, expected.midi, example.name)
                XCTAssertEqual(note.modelMIDI, expected.modelMIDI, example.name)
                XCTAssertEqual(note.onsetMs, expected.onsetMs, accuracy: 0.00001, example.name)
                XCTAssertEqual(note.offsetMs, expected.offsetMs, accuracy: 0.00001, example.name)
                XCTAssertEqual(note.confidence, expected.confidence, accuracy: 0.000002, example.name)
                XCTAssertEqual(note.cents, expected.cents, accuracy: 0.00001, example.name)
                XCTAssertEqual(note.centsEvidence, "coarse-basic-pitch-contour")
                XCTAssertEqual(note.durationMs, note.offsetMs - note.onsetMs, accuracy: 0.00001)
            }
            XCTAssertEqual(Set(actual.notes.map(\.id)).count, actual.notes.count)
            XCTAssertTrue(JSONSerialization.isValidJSONObject(actual.dictionary))
        }
    }

    func testInvalidActivationAndCancellationAreRejected() throws {
        let count = 120 * 88
        var frames = Array(repeating: Float(0), count: count)
        frames[1] = .nan
        XCTAssertThrowsError(try NoteWiseBasicPitchDecoder.decode(frames: frames,
            onsets: Array(repeating: 0, count: count), contour: Array(repeating: 0, count: count * 3), sampleCount: 30768))
        XCTAssertThrowsError(try NoteWiseBasicPitchDecoder.decode(frames: Array(repeating: 0, count: count),
            onsets: Array(repeating: 0, count: count), contour: Array(repeating: 0, count: count * 3), sampleCount: 30768,
            tuning: 0))
        frames = Array(repeating: 0, count: count)
        for time in 10..<80 { frames[time * 88 + 39] = 0.8 }
        XCTAssertThrowsError(try NoteWiseBasicPitchDecoder.decode(frames: frames,
            onsets: Array(repeating: 0, count: count), contour: Array(repeating: 0, count: count * 3), sampleCount: 30768,
            checkCancellation: { throw CancellationError() })) { XCTAssertTrue($0 is CancellationError) }
    }

    func testActualBundledCoreMLTranscribesChordAndLaterRepeatedPitch() async throws {
        let recording = try syntheticRecording(silent: false)
        defer { try? FileManager.default.removeItem(at: recording) }
        let transcriber = NoteWisePolyphonicTranscriber()
        let actual = try await transcriber.transcribe(recordingURL: recording)
        let diagnostics = try attachDiagnostics(transcriber, name: "NoteWise-actual-CoreML-sounding-signal-diagnostics")
        XCTAssertGreaterThan(diagnostics.modelPredictionCount, 0, "The bundled model must actually run")
        XCTAssertGreaterThan(diagnostics.audioNonzeroSampleCount, 0)
        XCTAssertFalse(diagnostics.digitalSilenceConstraintApplied, "Sounding chords must retain the actual model and decoder output")
        XCTAssertEqual(actual.modelVersion, "0.4.0")
        XCTAssertEqual(actual.detectorVersion, "basic-pitch-coreml-0.4.0")
        XCTAssertEqual(actual.sampleRate, 22050)
        XCTAssertEqual(actual.durationMs, 6000, accuracy: 1)
        for (pitch, onset) in [(60, 1000.0), (64, 1000), (67, 1000), (62, 3000), (60, 4500)] {
            XCTAssertTrue(actual.notes.contains { $0.midi == pitch && abs($0.onsetMs - onset) < 150 },
                          "Actual bundled CoreML must detect known synthetic MIDI \(pitch) attack near \(onset) ms; \(actual.notes)")
        }
        XCTAssertTrue(actual.notes.allSatisfy { $0.offsetMs <= actual.durationMs && $0.durationMs > 0 })
        XCTAssertTrue(actual.notes.allSatisfy { $0.centsEvidence == "coarse-basic-pitch-contour" })
        let data = try JSONEncoder().encode(actual)
        let proof = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        proof.name = "NoteWise-actual-CoreML-synthetic-chord-and-reattack"
        proof.lifetime = .keepAlways
        add(proof)
    }

    func testActualBundledCoreMLSilenceDoesNotBecomeCorrectNotes() async throws {
        let recording = try syntheticRecording(silent: true)
        defer { try? FileManager.default.removeItem(at: recording) }
        let transcriber = NoteWisePolyphonicTranscriber()
        let actual = try await transcriber.transcribe(recordingURL: recording)
        // Preserve audio and raw-model evidence before any assertion can fail.
        let diagnostics = try attachDiagnostics(transcriber, name: "NoteWise-actual-CoreML-digital-silence-diagnostics")
        XCTAssertGreaterThan(diagnostics.modelPredictionCount, 0, "Silence must still exercise the actual bundled model")
        XCTAssertEqual(diagnostics.audioNonzeroSampleCount, 0, "The converted synthetic recording must be actual digital silence")
        XCTAssertEqual(diagnostics.audioPeakAbsolute, 0)
        XCTAssertEqual(diagnostics.audioRMS, 0)
        XCTAssertTrue(diagnostics.digitalSilenceConstraintApplied)
        XCTAssertTrue(actual.notes.isEmpty, "Actual CoreML silence must not manufacture performance notes")
        XCTAssertTrue(actual.uncertaintyIntervals.isEmpty)
        XCTAssertEqual(actual.durationMs, 6000, accuracy: 1)
    }

    private func attachDiagnostics(_ transcriber: NoteWisePolyphonicTranscriber,
                                   name: String) throws -> NoteWiseTranscriptionDiagnostics {
        let diagnostics = try XCTUnwrap(transcriber.diagnosticsSnapshot())
        let proof = XCTAttachment(data: try JSONEncoder().encode(diagnostics), uniformTypeIdentifier: "public.json")
        proof.name = name
        proof.lifetime = .keepAlways
        add(proof)
        return diagnostics
    }

    private func syntheticRecording(silent: Bool) throws -> URL {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("notewise-synthetic-\(UUID().uuidString).wav")
        let format = try XCTUnwrap(AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 44100, channels: 1, interleaved: false))
        let output = try AVAudioFile(forWriting: file, settings: [AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: 44100, AVNumberOfChannelsKey: 1, AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false, AVLinearPCMIsBigEndianKey: false])
        let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 44100 * 6))
        buffer.frameLength = buffer.frameCapacity
        let samples = try XCTUnwrap(buffer.floatChannelData?[0])
        let attacks: [(Double, Double, [Int])] = [(1, 1.3, [60, 64, 67]), (3, 1, [62]), (4.5, 0.8, [60])]
        for index in 0..<Int(buffer.frameLength) {
            let time = Double(index) / 44100
            var value: Double = 0
            if !silent {
                for (start, duration, pitches) in attacks {
                    let elapsed = time - start
                    guard elapsed >= 0 && elapsed < duration else { continue }
                    let envelope = min(1, elapsed / 0.015) * exp(-elapsed * 1.7) * min(1, (duration - elapsed) / 0.08)
                    for pitch in pitches {
                        let angle = 2 * Double.pi * 440 * pow(2, Double(pitch - 69) / 12) * elapsed
                        value += envelope * (sin(angle) + 0.25 * sin(2 * angle) + 0.1 * sin(3 * angle)) * 0.16
                    }
                }
            }
            samples[index] = Float(min(1, max(-1, value)))
        }
        try output.write(from: buffer)
        return file
    }
}
