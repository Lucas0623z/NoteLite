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
        let recording = try syntheticRecording(signal: .music)
        defer { try? FileManager.default.removeItem(at: recording) }
        let transcriber = NoteWisePolyphonicTranscriber()
        let actual = try await transcriber.transcribe(recordingURL: recording)
        let diagnostics = try attachDiagnostics(transcriber, name: "NoteWise-actual-CoreML-sounding-signal-diagnostics")
        XCTAssertEqual(diagnostics.computeUnitsRequested, "cpuOnly")
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
        let comparison = NoteWisePolyphonicTranscriber(computeUnits: .all)
        _ = try await comparison.transcribe(recordingURL: recording)
        _ = try attachDiagnostics(comparison, name: "NoteWise-actual-CoreML-all-sounding-signal-comparison")
    }

    func testActualBundledCoreMLSilenceDoesNotBecomeCorrectNotes() async throws {
        let recording = try syntheticRecording(signal: .digitalSilence)
        defer { try? FileManager.default.removeItem(at: recording) }
        let transcriber = NoteWisePolyphonicTranscriber()
        let actual = try await transcriber.transcribe(recordingURL: recording)
        // Preserve audio and raw-model evidence before any assertion can fail.
        let diagnostics = try attachDiagnostics(transcriber, name: "NoteWise-actual-CoreML-digital-silence-diagnostics")
        XCTAssertEqual(diagnostics.computeUnitsRequested, "cpuOnly")
        XCTAssertGreaterThan(diagnostics.modelPredictionCount, 0, "Silence must still exercise the actual bundled model")
        XCTAssertEqual(diagnostics.audioNonzeroSampleCount, 0, "The converted synthetic recording must be actual digital silence")
        XCTAssertEqual(diagnostics.audioPeakAbsolute, 0)
        XCTAssertEqual(diagnostics.audioRMS, 0)
        XCTAssertEqual(diagnostics.decodedNotesBeforeAudioConstraint, 0, "CPU inference must itself decode no digital-silence notes")
        XCTAssertTrue(diagnostics.digitalSilenceConstraintApplied)
        XCTAssertTrue(actual.notes.isEmpty, "Actual CoreML silence must not manufacture performance notes")
        XCTAssertTrue(actual.uncertaintyIntervals.isEmpty)
        XCTAssertEqual(actual.durationMs, 6000, accuracy: 1)
        let comparison = NoteWisePolyphonicTranscriber(computeUnits: .all)
        _ = try await comparison.transcribe(recordingURL: recording)
        _ = try attachDiagnostics(comparison, name: "NoteWise-actual-CoreML-all-digital-silence-comparison")
    }

    func testActualBundledCoreMLNonzeroQuietNoiseHasNoPerformanceNotes() async throws {
        let recording = try syntheticRecording(signal: .quietDither)
        defer { try? FileManager.default.removeItem(at: recording) }
        let transcriber = NoteWisePolyphonicTranscriber()
        let actual = try await transcriber.transcribe(recordingURL: recording)
        let diagnostics = try attachDiagnostics(transcriber, name: "NoteWise-actual-CoreML-nonzero-quiet-noise-diagnostics")
        // Retain the alternative backend's real activations without claiming that
        // an accelerator ran, or that its low-level-noise output is correct.
        let comparison = NoteWisePolyphonicTranscriber(computeUnits: .all)
        _ = try await comparison.transcribe(recordingURL: recording)
        _ = try attachDiagnostics(comparison, name: "NoteWise-actual-CoreML-all-nonzero-quiet-noise-comparison")
        XCTAssertEqual(diagnostics.computeUnitsRequested, "cpuOnly")
        XCTAssertGreaterThan(diagnostics.modelPredictionCount, 0)
        XCTAssertGreaterThan(diagnostics.audioNonzeroSampleCount, 0, "The converted fixture must contain actual nonzero samples")
        XCTAssertGreaterThan(diagnostics.audioPeakAbsolute, 0)
        XCTAssertGreaterThan(diagnostics.audioRMS, 0)
        XCTAssertFalse(diagnostics.digitalSilenceConstraintApplied, "Digital-zero filtering cannot make the noise regression pass")
        // Upstream normalizes any nonzero noise. The actual e1ac regression
        // recorded six raw candidates, not six heard musical events. Preserve
        // their count; only independent PCM evidence can qualify a performance.
        XCTAssertEqual(diagnostics.signalQualifiedNotes, 0)
        XCTAssertEqual(diagnostics.unresolvedCandidates, 0)
        XCTAssertEqual(diagnostics.broadbandCandidatesRejected, diagnostics.decodedNotesBeforeAudioConstraint)
        XCTAssertTrue(actual.notes.isEmpty, "Quiet non-musical noise must not manufacture performance notes")
        XCTAssertTrue(actual.uncertaintyIntervals.isEmpty)
        XCTAssertEqual(actual.durationMs, 6000, accuracy: 1)
    }

    func testActualBundledCoreMLSoftChordAndReattackSurviveAcousticQualification() async throws {
        let recording = try syntheticRecording(signal: .softMusic)
        defer { try? FileManager.default.removeItem(at: recording) }
        let transcriber = NoteWisePolyphonicTranscriber()
        let actual = try await transcriber.transcribe(recordingURL: recording)
        let diagnostics = try attachDiagnostics(transcriber, name: "NoteWise-actual-CoreML-soft-music-diagnostics")
        XCTAssertGreaterThan(diagnostics.modelPredictionCount, 0)
        XCTAssertFalse(diagnostics.digitalSilenceConstraintApplied)
        XCTAssertGreaterThan(diagnostics.audioNonzeroSampleCount, 0)
        XCTAssertGreaterThan(diagnostics.signalQualifiedNotes, 0)
        // Same musical fixture at 1/100 amplitude (-40 dB). A loudness cutoff
        // would discard it; spectral ratios must retain all original attacks.
        for (pitch, onset) in [(60, 1000.0), (64, 1000), (67, 1000), (62, 3000), (60, 4500)] {
            XCTAssertTrue(actual.notes.contains { $0.midi == pitch && abs($0.onsetMs - onset) < 150 },
                "Soft actual MIDI \(pitch) near \(onset) ms must remain detectable: \(actual.notes)")
        }
        XCTAssertTrue(actual.notes.allSatisfy { $0.centsEvidence == "coarse-basic-pitch-contour" })
        let attachment = XCTAttachment(data: try JSONEncoder().encode(actual), uniformTypeIdentifier: "public.json")
        attachment.name = "NoteWise-actual-CoreML-soft-chord-and-reattack"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    func testActualBundledCoreMLLoudBroadbandNoiseHasNoPerformanceNotes() async throws {
        let recording = try syntheticRecording(signal: .loudNoise)
        defer { try? FileManager.default.removeItem(at: recording) }
        let transcriber = NoteWisePolyphonicTranscriber()
        let actual = try await transcriber.transcribe(recordingURL: recording)
        let diagnostics = try attachDiagnostics(transcriber, name: "NoteWise-actual-CoreML-loud-noise-diagnostics")
        XCTAssertGreaterThan(diagnostics.modelPredictionCount, 0)
        XCTAssertFalse(diagnostics.digitalSilenceConstraintApplied)
        XCTAssertGreaterThan(diagnostics.audioNonzeroSampleCount, 0)
        XCTAssertEqual(diagnostics.signalQualifiedNotes, 0)
        XCTAssertEqual(diagnostics.unresolvedCandidates, 0)
        XCTAssertEqual(diagnostics.broadbandCandidatesRejected, diagnostics.decodedNotesBeforeAudioConstraint)
        XCTAssertTrue(actual.notes.isEmpty, "Increasing broadband-noise amplitude must not make it musical")
        XCTAssertTrue(actual.uncertaintyIntervals.isEmpty)
    }

    func testAcousticEvidenceIsGainInvariantAndRejectsWrongPitchCandidates() throws {
        let sampleRate = NoteWiseBasicPitchDecoder.sampleRate
        let tone = (0..<sampleRate).map { Float(sin(2 * Double.pi * 440 * Double($0) / Double(sampleRate))) }
        let correct = NoteWiseRecordedNote(id: "synthetic-correct", midi: 69, modelMIDI: 69,
            onsetMs: 200, offsetMs: 800, durationMs: 600, confidence: 0.8, cents: 0,
            centsEvidence: "coarse-basic-pitch-contour", releaseReliable: true)
        let wrong = NoteWiseRecordedNote(id: "synthetic-wrong", midi: 70, modelMIDI: 70,
            onsetMs: 200, offsetMs: 800, durationMs: 600, confidence: 0.99, cents: 0,
            centsEvidence: "coarse-basic-pitch-contour", releaseReliable: true)
        let raw = NoteWiseRecordedTranscription(notes: [correct, wrong], uncertaintyIntervals: [],
            sampleRate: sampleRate, sampleCount: tone.count, durationMs: 1000, tuning: 440,
            modelVersion: "0.4.0", detectorVersion: "basic-pitch-coreml-0.4.0",
            supportedPitchRange: ["minimumMIDI": 21, "maximumMIDI": 108], warnings: [])
        for gain in [Float(1), 0.01, 0.000001] {
            let actual = try NoteWiseAcousticEvidence(audio: tone.map { $0 * gain }).qualify(raw)
            XCTAssertEqual(actual.notes.map(\.id), [correct.id])
            XCTAssertEqual(actual.unresolvedCandidates, 1)
            XCTAssertEqual(actual.uncertainty.count, 1, "Unsupported tonal candidates must remain pending")
        }
        XCTAssertThrowsError(try NoteWiseAcousticEvidence(audio: tone).qualify(raw,
            checkCancellation: { throw CancellationError() })) { XCTAssertTrue($0 is CancellationError) }
    }

    func testAcousticBassPeakCannotConfirmTheAdjacentSemitone() throws {
        let sampleRate = NoteWiseBasicPitchDecoder.sampleRate
        let tone = (0..<sampleRate).map { Float(sin(2 * Double.pi * 27.5 * Double($0) / Double(sampleRate))) }
        let notes = [21, 22].map { pitch in
            NoteWiseRecordedNote(id: "synthetic-bass-\(pitch)", midi: pitch, modelMIDI: pitch,
                onsetMs: 200, offsetMs: 800, durationMs: 600, confidence: 0.99, cents: 0,
                centsEvidence: "coarse-basic-pitch-contour", releaseReliable: true)
        }
        let raw = NoteWiseRecordedTranscription(notes: notes, uncertaintyIntervals: [],
            sampleRate: sampleRate, sampleCount: tone.count, durationMs: 1000, tuning: 440,
            modelVersion: "0.4.0", detectorVersion: "basic-pitch-coreml-0.4.0",
            supportedPitchRange: ["minimumMIDI": 21, "maximumMIDI": 108], warnings: [])
        for gain in [Float(1), 0.01, 0.000001] {
            let actual = try NoteWiseAcousticEvidence(audio: tone.map { $0 * gain }).qualify(raw)
            XCTAssertEqual(actual.notes.map(\.midi), [21], "One low-frequency peak cannot confirm both adjacent notes")
            XCTAssertEqual(actual.unresolvedCandidates, 1)
            XCTAssertEqual(actual.uncertainty.count, 1, "Unresolved tonal candidates must remain available for review")
        }
    }

    func testAcousticQualificationUsesCalibratedPitchAndTuning() throws {
        let sampleRate = NoteWiseBasicPitchDecoder.sampleRate
        for (tuning, bend) in [(480.0, 1.0 / 3), (440.0, 2.0 / 3)] {
            let modelMIDI = 69
            let calibrated = Double(modelMIDI) + bend - 12 * log2(tuning / 440)
            let midi = Int(calibrated.rounded())
            let cents = (calibrated - Double(midi)) * 100
            XCTAssertNotEqual(midi, modelMIDI, "Both cases exercise actual model/calibrated pitch divergence")
            let frequency = 440 * pow(2, bend / 12)
            let tone = (0..<sampleRate).map { Float(sin(2 * Double.pi * frequency * Double($0) / Double(sampleRate))) }
            let notes = [0, 1].map { offset in
                NoteWiseRecordedNote(id: "synthetic-calibrated-\(offset)", midi: midi + offset,
                    modelMIDI: modelMIDI + offset, onsetMs: 200, offsetMs: 800, durationMs: 600,
                    confidence: 0.99, cents: cents, centsEvidence: "coarse-basic-pitch-contour", releaseReliable: true)
            }
            let raw = NoteWiseRecordedTranscription(notes: notes, uncertaintyIntervals: [],
                sampleRate: sampleRate, sampleCount: tone.count, durationMs: 1000, tuning: tuning,
                modelVersion: "0.4.0", detectorVersion: "basic-pitch-coreml-0.4.0",
                supportedPitchRange: ["minimumMIDI": 21, "maximumMIDI": 108], warnings: [])
            for gain in [Float(1), 0.01, 0.000001] {
                let actual = try NoteWiseAcousticEvidence(audio: tone.map { $0 * gain }).qualify(raw)
                XCTAssertEqual(actual.notes.map(\.id), [notes[0].id], "Tune/contour calibration must preserve the actual pitch")
                XCTAssertEqual(actual.unresolvedCandidates, 1)
                XCTAssertEqual(actual.uncertainty.count, 1)
            }
        }
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

    func testActualFusionMonophonicDSPAndBundledModelIndependentlyConfirmRepeatedNotes() async throws {
        let recording = try syntheticRecording(signal: .monophonicMusic)
        defer { try? FileManager.default.removeItem(at: recording) }
        let actual = try await NoteWiseFusionTranscriber().transcribe(recordingURL: recording,
            instrument: "clarinet", polyphonic: false)
        let diagnostics = try XCTUnwrap(actual.fusionDiagnostics)
        XCTAssertEqual(actual.detectorVersion, "native-mpm-yin-1")
        XCTAssertEqual(actual.sampleRate, 44100)
        XCTAssertEqual(diagnostics.route, "monophonic-recording")
        XCTAssertEqual(diagnostics.instrument, "clarinet")
        XCTAssertGreaterThan(diagnostics.primaryCandidates, 0, "The actual shared DSP must run")
        XCTAssertGreaterThan(diagnostics.secondaryCandidates, 0, "The actual independent model must run")
        XCTAssertGreaterThan(diagnostics.modelPredictionCount, 0)
        XCTAssertTrue(diagnostics.secondaryAvailable)
        for (pitch, onset) in [(60, 1000.0), (62, 3000.0), (60, 4500.0)] {
            XCTAssertTrue(actual.notes.contains { $0.midi == pitch && abs($0.onsetMs - onset) < 150 },
                "Independent native/model evidence must confirm MIDI \(pitch) near \(onset): \(actual.notes)")
        }
        XCTAssertTrue(actual.notes.allSatisfy { $0.confidence >= 0.9 && $0.centsEvidence == "continuous-mpm-yin" })
        XCTAssertEqual(actual.supportedPitchRange, ["minimumMIDI": 34, "maximumMIDI": 103])
        attachFusion(actual, name: "NoteWise-actual-fusion-monophonic-dsp-and-model")
    }
    func testActualFusionPolyphonicRouteRetainsChordAndUsesConfirmedViolinRange() async throws {
        let recording = try syntheticRecording(signal: .music)
        defer { try? FileManager.default.removeItem(at: recording) }
        let fusion = NoteWiseFusionTranscriber()
        let actual = try await fusion.transcribe(recordingURL: recording,
            instrument: "violin", polyphonic: true)
        let diagnostics = try XCTUnwrap(actual.fusionDiagnostics)
        XCTAssertEqual(actual.detectorVersion, "basic-pitch-coreml-0.4.0")
        XCTAssertEqual(diagnostics.route, "polyphonic-recording")
        XCTAssertEqual(diagnostics.instrument, "violin")
        XCTAssertGreaterThan(diagnostics.modelPredictionCount, 0)
        XCTAssertEqual(actual.supportedPitchRange, ["minimumMIDI": 55, "maximumMIDI": 108])
        for pitch in [60, 64, 67] {
            XCTAssertTrue(actual.notes.contains { $0.midi == pitch && abs($0.onsetMs - 1000) < 150 })
        }
        XCTAssertTrue(actual.notes.allSatisfy { (55...108).contains($0.midi) })
        attachFusion(actual, name: "NoteWise-actual-fusion-polyphonic-violin-range")
        let keyboard = try await fusion.transcribe(recordingURL: recording, instrument: "piano", polyphonic: false)
        XCTAssertEqual(keyboard.fusionDiagnostics?.route, "polyphonic-recording",
            "The keyboard family must automatically route chords even with an old false polyphonic hint")
        XCTAssertGreaterThan(try XCTUnwrap(keyboard.fusionDiagnostics).modelPredictionCount, 0)
        for pitch in [60, 64, 67] {
            XCTAssertTrue(keyboard.notes.contains { $0.midi == pitch && abs($0.onsetMs - 1000) < 150 })
        }
        attachFusion(keyboard, name: "NoteWise-actual-fusion-keyboard-auto-route")
    }
    func testActualFusionSilenceAndCancellationCannotBecomeConfirmedNotes() async throws {
        let recording = try syntheticRecording(signal: .digitalSilence)
        defer { try? FileManager.default.removeItem(at: recording) }
        let actual = try await NoteWiseFusionTranscriber().transcribe(recordingURL: recording,
            instrument: "flute", polyphonic: false)
        XCTAssertTrue(actual.notes.isEmpty)
        XCTAssertTrue(actual.uncertaintyIntervals.isEmpty)
        XCTAssertGreaterThan(try XCTUnwrap(actual.fusionDiagnostics).modelPredictionCount, 0)
        let task = Task { try await NoteWiseFusionTranscriber().transcribe(recordingURL: recording,
            instrument: "flute", polyphonic: false) }
        task.cancel()
        do { _ = try await task.value; XCTFail("Cancellation must preserve the prior practice version, not return an empty success") }
        catch { XCTAssertTrue(error is CancellationError) }
    }
    func testActualFusionOutOfInstrumentRangeIsRetainedAsUncertainty() async throws {
        let recording = try syntheticRecording(signal: .belowViolinRange)
        defer { try? FileManager.default.removeItem(at: recording) }
        let actual = try await NoteWiseFusionTranscriber().transcribe(recordingURL: recording,
            instrument: "violin", polyphonic: true)
        let diagnostics = try XCTUnwrap(actual.fusionDiagnostics)
        XCTAssertGreaterThan(diagnostics.modelPredictionCount, 0)
        XCTAssertGreaterThan(diagnostics.primaryCandidates, 0, "Actual full-range model must hear the low candidates")
        XCTAssertTrue(actual.notes.isEmpty, "Out-of-profile notes cannot become confirmed violin performance")
        for onset in [1000.0, 3000.0, 4500.0] {
            XCTAssertTrue(actual.uncertaintyIntervals.contains { abs($0.onsetMs - onset) < 150 })
        }
        XCTAssertEqual(actual.supportedPitchRange, ["minimumMIDI": 55, "maximumMIDI": 108])
        attachFusion(actual, name: "NoteWise-actual-fusion-out-of-range-uncertainty")
    }
    func testFusionConflictingPitchAndModelOnlyCandidatesRemainUncertain() throws {
        let note = NoteWiseRecordedNote(id: "primary", midi: 60, modelMIDI: 60,
            onsetMs: 100, offsetMs: 700, durationMs: 600, confidence: 0.99, cents: 0,
            centsEvidence: "continuous-mpm-yin", releaseReliable: true)
        let conflicting = NoteWiseRecordedNote(id: "secondary", midi: 61, modelMIDI: 61,
            onsetMs: 110, offsetMs: 710, durationMs: 600, confidence: 0.8, cents: 0,
            centsEvidence: "coarse-basic-pitch-contour", releaseReliable: true)
        let profile = try NoteWiseInstrumentProfiles.resolve("clarinet")
        func result(_ notes: [NoteWiseRecordedNote], detector: String) -> NoteWiseRecordedTranscription {
            NoteWiseRecordedTranscription(notes: notes, uncertaintyIntervals: [], sampleRate: 44100,
                sampleCount: 44100, durationMs: 1000, tuning: 440, modelVersion: "0.4.0",
                detectorVersion: detector, supportedPitchRange: ["minimumMIDI": 34, "maximumMIDI": 103], warnings: [])
        }
        let fusion = NoteWiseFusionTranscriber()
        let primary = result([note], detector: "native-mpm-yin-1")
        let secondary = result([conflicting], detector: "basic-pitch-coreml-0.4.0")
        let conflict = try fusion.reconcile(primary, secondary: secondary, profile: profile)
        XCTAssertTrue(conflict.notes.isEmpty)
        XCTAssertEqual(conflict.uncertaintyIntervals.count, 2)
        let onlyModel = try fusion.reconcile(result([], detector: "native-mpm-yin-1"),
            secondary: secondary, profile: profile)
        XCTAssertTrue(onlyModel.notes.isEmpty)
        XCTAssertEqual(onlyModel.uncertaintyIntervals.count, 1)
        XCTAssertThrowsError(try fusion.reconcile(primary, secondary: secondary, profile: profile,
            checkCancellation: { throw CancellationError() })) { XCTAssertTrue($0 is CancellationError) }
    }
    private func attachFusion(_ value: NoteWiseRecordedTranscription, name: String) {
        guard let data = try? JSONEncoder().encode(value) else { XCTFail("Fusion evidence must encode"); return }
        let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }

    private enum SyntheticSignal { case music, monophonicMusic, belowViolinRange, softMusic, digitalSilence, quietDither, loudNoise }

    private func syntheticRecording(signal: SyntheticSignal) throws -> URL {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("notewise-synthetic-\(UUID().uuidString).wav")
        let format = try XCTUnwrap(AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 44100, channels: 1, interleaved: false))
        let output = try AVAudioFile(forWriting: file, settings: [AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: 44100, AVNumberOfChannelsKey: 1, AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false, AVLinearPCMIsBigEndianKey: false])
        let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 44100 * 6))
        buffer.frameLength = buffer.frameCapacity
        let samples = try XCTUnwrap(buffer.floatChannelData?[0])
        let attacks: [(Double, Double, [Int])] = [(1, 1.3, [60, 64, 67]), (3, 1, [62]), (4.5, 0.8, [60])]
        var noiseState: UInt32 = 0x6e6f7465
        for index in 0..<Int(buffer.frameLength) {
            let time = Double(index) / 44100
            var value: Double = 0
            if signal == .quietDither || signal == .loudNoise {
                // Seeded triangular 16-bit quantization-scale noise, without a
                // deterministic musical tone. No microphone or private recording.
                noiseState = noiseState &* 1664525 &+ 1013904223
                let left = Int(noiseState >> 16)
                noiseState = noiseState &* 1664525 &+ 1013904223
                let right = Int(noiseState >> 16)
                value = Double(left - right) / 65536 * (signal == .loudNoise ? 0.5 : 2.0 / 32768)
            } else if signal == .music || signal == .softMusic || signal == .monophonicMusic || signal == .belowViolinRange {
                for (start, duration, pitches) in attacks {
                    let elapsed = time - start
                    guard elapsed >= 0 && elapsed < duration else { continue }
                    let envelope = min(1, elapsed / 0.015) * exp(-elapsed * 1.7) * min(1, (duration - elapsed) / 0.08)
                    let soundingPitches = signal == .belowViolinRange ? [pitches[0] - 12] :
                        signal == .monophonicMusic ? Array(pitches.prefix(1)) : pitches
                    for pitch in soundingPitches {
                        let angle = 2 * Double.pi * 440 * pow(2, Double(pitch - 69) / 12) * elapsed
                        value += envelope * (sin(angle) + 0.25 * sin(2 * angle) + 0.1 * sin(3 * angle)) * 0.16
                    }
                }
                if signal == .softMusic { value *= 0.01 }
            }
            samples[index] = Float(min(1, max(-1, value)))
        }
        try output.write(from: buffer)
        return file
    }
}
