import Foundation

struct NoteWiseFusionDiagnostics: Codable, Sendable {
    let version: String
    let platform: String
    let instrument: String
    let family: String
    let route: String
    let primaryDetector: String
    let contributors: [String]
    let primaryCandidates: Int
    let secondaryCandidates: Int
    let acceptedNotes: Int
    let unresolvedCandidates: Int
    let modelPredictionCount: Int
    let secondaryAvailable: Bool
}

private final class NoteWiseFusionCancellation: @unchecked Sendable {
    private let lock = NSLock()
    private var cancelled = false
    func cancel() { lock.lock(); cancelled = true; lock.unlock() }
    func check() throws {
        lock.lock(); let current = cancelled; lock.unlock()
        if current { throw CancellationError() }
    }
}

/// One product entry point; independent algorithms retain their own provenance.
/// Routing uses a broad confirmed instrument profile and observed polyphony,
/// never the next expected note. All recording reads and inference stay native.
final class NoteWiseFusionTranscriber: @unchecked Sendable {
    private let queue = DispatchQueue(label: "com.notelite.notewise.fusion-mono", qos: .userInitiated)
    private let polyphonic: NoteWisePolyphonicTranscriber
    private let operationLock = NSLock()
    private var processing = false
    init(bundle: Bundle = .main) { polyphonic = NoteWisePolyphonicTranscriber(bundle: bundle) }

    private func begin() throws {
        operationLock.lock(); defer { operationLock.unlock() }
        guard !processing else { throw CloudOMRError(code: "busy", message: "上一段录音正在本机复核，请稍后重试。") }
        processing = true
    }
    private func end() { operationLock.lock(); processing = false; operationLock.unlock() }

    func transcribe(recordingURL: URL, tuning: Double = 440, instrument: String = "piano",
                    polyphonic isPolyphonic: Bool = true) async throws -> NoteWiseRecordedTranscription {
        try Task.checkCancellation()
        guard tuning.isFinite, (400...480).contains(tuning) else { throw NoteWiseTranscriptionError.invalidOutput }
        let profile = try NoteWiseInstrumentProfiles.resolve(instrument)
        try begin(); defer { end() }
        let minimum = max(21, profile.minMidi), maximum = min(108, profile.maxMidi)
        let usePolyphonic = isPolyphonic || ["keyboard", "plucked"].contains(profile.family ?? "generic")
        if usePolyphonic {
            guard minimum <= maximum else { throw NoteWiseTranscriptionError.invalidOutput }
            // Keep out-of-profile evidence: narrowing neural decoding first
            // would silently discard a heard note outside the selected range.
            var result = constrainToProfile(try await polyphonic.transcribe(recordingURL: recordingURL,
                tuning: tuning), profile: profile)
            try Task.checkCancellation()
            result.fusionDiagnostics = diagnostics(profile, route: "polyphonic-recording",
                primary: result.detectorVersion, contributors: [result.detectorVersion, "pcm-spectral-evidence-1"],
                primaryCount: polyphonic.diagnosticsSnapshot()?.decodedNotesBeforeAudioConstraint ?? result.notes.count,
                secondaryCount: 0, accepted: result.notes.count, unresolved: result.uncertaintyIntervals.count,
                predictions: polyphonic.diagnosticsSnapshot()?.modelPredictionCount ?? 0, secondaryAvailable: true)
            if minimum != profile.minMidi || maximum != profile.maxMidi {
                result = withWarnings(result, ["所选乐器部分音域超出当前复音模型支持范围，超出范围不能据此评价。"])
            }
            return result
        }
        let primary = try await monophonic(recordingURL, tuning: tuning, profile: profile)
        try Task.checkCancellation()
        guard minimum <= maximum else {
            return unresolved(primary, profile: profile, reason: "乐器音域超出独立复核模型支持范围，需要复核。")
        }
        let secondary: NoteWiseRecordedTranscription
        do {
            secondary = constrainToProfile(try await polyphonic.transcribe(recordingURL: recordingURL,
                tuning: tuning), profile: profile)
        } catch NoteWiseTranscriptionError.missingModel {
            // A missing verifier must not turn primary candidates into confirmed
            // notes or destroy the recording/current immutable practice version.
            try Task.checkCancellation()
            return unresolved(primary, profile: profile, reason: "独立复核模型缺失，单音候选已保留待复核。")
        }
        try Task.checkCancellation()
        return try reconcile(primary, secondary: secondary, profile: profile,
            predictions: polyphonic.diagnosticsSnapshot()?.modelPredictionCount ?? 0,
            checkCancellation: { try Task.checkCancellation() })
    }

    private func diagnostics(_ profile: NoteWiseInstrumentProfile, route: String, primary: String,
                             contributors: [String], primaryCount: Int, secondaryCount: Int,
                             accepted: Int, unresolved: Int, predictions: Int,
                             secondaryAvailable: Bool) -> NoteWiseFusionDiagnostics {
        NoteWiseFusionDiagnostics(version: "notewise-fusion-1", platform: "apple-native",
            instrument: profile.id, family: profile.family ?? "generic", route: route,
            primaryDetector: primary, contributors: contributors, primaryCandidates: primaryCount,
            secondaryCandidates: secondaryCount, acceptedNotes: accepted, unresolvedCandidates: unresolved,
            modelPredictionCount: predictions, secondaryAvailable: secondaryAvailable)
    }
    private func withWarnings(_ value: NoteWiseRecordedTranscription, _ extra: [String]) -> NoteWiseRecordedTranscription {
        var result = NoteWiseRecordedTranscription(notes: value.notes, uncertaintyIntervals: value.uncertaintyIntervals,
            sampleRate: value.sampleRate, sampleCount: value.sampleCount, durationMs: value.durationMs,
            tuning: value.tuning, modelVersion: value.modelVersion, detectorVersion: value.detectorVersion,
            supportedPitchRange: value.supportedPitchRange, warnings: value.warnings + extra)
        result.fusionDiagnostics = value.fusionDiagnostics
        return result
    }
    private func constrainToProfile(_ value: NoteWiseRecordedTranscription,
                                    profile: NoteWiseInstrumentProfile) -> NoteWiseRecordedTranscription {
        let range = max(21, profile.minMidi)...min(108, profile.maxMidi)
        let outside = value.notes.filter { !range.contains($0.midi) }
        return NoteWiseRecordedTranscription(notes: value.notes.filter { range.contains($0.midi) },
            uncertaintyIntervals: value.uncertaintyIntervals + outside.map {
                NoteWiseRecordedUncertainty(onsetMs: $0.onsetMs, offsetMs: $0.offsetMs,
                    reason: "录音音高超出已确认乐器音域，需要复核乐器或演奏内容。")
            }, sampleRate: value.sampleRate, sampleCount: value.sampleCount, durationMs: value.durationMs,
            tuning: value.tuning, modelVersion: value.modelVersion, detectorVersion: value.detectorVersion,
            supportedPitchRange: ["minimumMIDI": range.lowerBound, "maximumMIDI": range.upperBound],
            warnings: value.warnings + (outside.isEmpty ? [] : ["超出所选乐器音域的听音候选已标为待复核。"]))
    }
    private func unresolved(_ primary: NoteWiseRecordedTranscription, profile: NoteWiseInstrumentProfile,
                            reason: String) -> NoteWiseRecordedTranscription {
        var result = NoteWiseRecordedTranscription(notes: [],
            uncertaintyIntervals: primary.uncertaintyIntervals + primary.notes.map {
                NoteWiseRecordedUncertainty(onsetMs: $0.onsetMs, offsetMs: $0.offsetMs, reason: reason)
            }, sampleRate: primary.sampleRate, sampleCount: primary.sampleCount, durationMs: primary.durationMs,
            tuning: primary.tuning, modelVersion: primary.modelVersion, detectorVersion: primary.detectorVersion,
            supportedPitchRange: primary.supportedPitchRange, warnings: primary.warnings + [reason])
        result.fusionDiagnostics = diagnostics(profile, route: "monophonic-recording",
            primary: primary.detectorVersion, contributors: [primary.detectorVersion],
            primaryCount: primary.notes.count, secondaryCount: 0, accepted: 0,
            unresolved: result.uncertaintyIntervals.count, predictions: 0, secondaryAvailable: false)
        return result
    }

    /// Deliberately testable independent reconciliation. Neither side supplies a
    /// correct-note probability, and neither may silently overrule a conflict.
    func reconcile(_ primary: NoteWiseRecordedTranscription, secondary: NoteWiseRecordedTranscription,
                   profile: NoteWiseInstrumentProfile, predictions: Int = 0,
                   checkCancellation: () throws -> Void = {}) throws -> NoteWiseRecordedTranscription {
        try checkCancellation()
        var accepted: [NoteWiseRecordedNote] = [], used = Set<String>()
        var uncertainty = primary.uncertaintyIntervals + secondary.uncertaintyIntervals
        func overlap(_ left: NoteWiseRecordedNote, _ right: NoteWiseRecordedNote) -> Double {
            max(0, min(left.offsetMs, right.offsetMs) - max(left.onsetMs, right.onsetMs))
        }
        for note in primary.notes {
            try checkCancellation()
            let candidates = secondary.notes.filter {
                !used.contains($0.id) && $0.midi == note.midi && $0.confidence >= 0.5 &&
                abs($0.onsetMs - note.onsetMs) <= 150 &&
                overlap(note, $0) >= min(note.durationMs, $0.durationMs) * 0.5 &&
                abs($0.cents - note.cents) <= 50
            }.sorted { abs($0.onsetMs - note.onsetMs) < abs($1.onsetMs - note.onsetMs) }
            let conflictingPolyphony = secondary.notes.contains {
                $0.midi != note.midi && $0.confidence >= 0.5 && overlap(note, $0) > 100
            }
            let uncertainOverlap = uncertainty.contains {
                min(note.offsetMs, $0.offsetMs) - max(note.onsetMs, $0.onsetMs) > 100
            }
            if let match = candidates.first, !conflictingPolyphony, !uncertainOverlap,
               note.confidence >= 0.9, (21...108).contains(note.midi),
               (profile.minMidi...profile.maxMidi).contains(note.midi) {
                accepted.append(note); used.insert(match.id)
            } else {
                uncertainty.append(NoteWiseRecordedUncertainty(onsetMs: note.onsetMs, offsetMs: note.offsetMs,
                    reason: conflictingPolyphony ? "单音听音与复音复核发现重叠音高，需要复核。" :
                        "两种独立听音证据未能一致确认此音符，需要复核。"))
            }
        }
        for note in secondary.notes where !used.contains(note.id) {
            try checkCancellation()
            uncertainty.append(NoteWiseRecordedUncertainty(onsetMs: note.onsetMs, offsetMs: note.offsetMs,
                reason: "复核模型候选缺少单音检测的独立确认，需要复核。"))
        }
        uncertainty.sort { $0.onsetMs == $1.onsetMs ? $0.offsetMs < $1.offsetMs : $0.onsetMs < $1.onsetMs }
        var result = NoteWiseRecordedTranscription(notes: accepted, uncertaintyIntervals: uncertainty,
            sampleRate: primary.sampleRate, sampleCount: primary.sampleCount, durationMs: primary.durationMs,
            tuning: primary.tuning, modelVersion: secondary.modelVersion, detectorVersion: primary.detectorVersion,
            supportedPitchRange: primary.supportedPitchRange,
            warnings: primary.warnings + ["单音候选经过独立模型交叉复核，算法不一致的部分保留待复核。"])
        result.fusionDiagnostics = diagnostics(profile, route: "monophonic-recording",
            primary: primary.detectorVersion,
            contributors: [primary.detectorVersion, secondary.detectorVersion, "pcm-spectral-evidence-1"],
            primaryCount: primary.notes.count, secondaryCount: secondary.notes.count, accepted: accepted.count,
            unresolved: uncertainty.count, predictions: predictions, secondaryAvailable: true)
        return result
    }

    private func monophonic(_ url: URL, tuning: Double,
                            profile: NoteWiseInstrumentProfile) async throws -> NoteWiseRecordedTranscription {
        let cancellation = NoteWiseFusionCancellation()
        return try await withTaskCancellationHandler(operation: {
            try Task.checkCancellation()
            return try await withCheckedThrowingContinuation { continuation in
                queue.async {
                    do { continuation.resume(returning: try Self.detect(url, tuning: tuning, profile: profile,
                        checkCancellation: { try cancellation.check() })) }
                    catch { continuation.resume(throwing: error) }
                }
            }
        }, onCancel: { cancellation.cancel() })
    }
    private static func detect(_ url: URL, tuning: Double, profile: NoteWiseInstrumentProfile,
                               checkCancellation: () throws -> Void) throws -> NoteWiseRecordedTranscription {
        var dsp: OpaquePointer?
        defer { if let dsp { nw_destroy(dsp) } }
        var attacks: [UInt64: nl_note_event] = [:], intervals: [UInt64: Double] = [:]
        var notes: [NoteWiseRecordedNote] = [], uncertainty: [NoteWiseRecordedUncertainty] = []
        func drain() throws {
            guard let dsp else { return }
            var event = nl_note_event()
            while nw_poll(dsp, &event) != 0 {
                try checkCancellation()
                switch String(cString: event.type) {
                case "note-on": attacks[event.id] = event
                case "note-off":
                    guard let attack = attacks.removeValue(forKey: event.id), event.offset_ms > attack.onset_ms else { continue }
                    notes.append(NoteWiseRecordedNote(id: "mono-\(event.id)", midi: Int(attack.midi), modelMIDI: Int(attack.midi),
                        onsetMs: attack.onset_ms, offsetMs: event.offset_ms, durationMs: event.offset_ms - attack.onset_ms,
                        confidence: min(1, max(0, min(attack.confidence, event.confidence))), cents: event.cents,
                        centsEvidence: "continuous-mpm-yin", releaseReliable: String(cString: event.reason) != "stop"))
                    if notes.count > NoteWiseBasicPitchDecoder.maximumNotes { throw NoteWiseTranscriptionError.tooDense }
                case "uncertainty":
                    if event.offset_ms.isFinite {
                        let onset = intervals.removeValue(forKey: event.id) ?? event.onset_ms
                        uncertainty.append(NoteWiseRecordedUncertainty(onsetMs: max(0, onset),
                            offsetMs: max(onset, event.offset_ms), reason: String(cString: event.reason)))
                    } else { intervals[event.id] = event.onset_ms }
                default: break
                }
            }
        }
        let metadata = try NoteWiseRecordingReader.stream(url, checkCancellation: checkCancellation) { values, rate in
            if dsp == nil {
                guard let detector = nw_create_profile(rate, tuning, profile.frequency(profile.minMidi, tuning: tuning),
                    min(profile.frequency(profile.maxMidi, tuning: tuning), rate / 2 - 1), profile.windowSize) else {
                    throw NoteWiseTranscriptionError.invalidRecording
                }
                dsp = detector
            }
            // Frequent drains keep the bounded C callback queue lossless even
            // when AVAudioConverter returns a larger packet than the live tap.
            for offset in stride(from: 0, to: values.count, by: 4096) {
                try checkCancellation()
                nw_push(dsp!, values.baseAddress!.advanced(by: offset), min(4096, values.count - offset))
                try drain()
            }
        }
        nw_finish(dsp!)
        try drain()
        notes.sort { $0.onsetMs < $1.onsetMs }
        return NoteWiseRecordedTranscription(notes: notes, uncertaintyIntervals: uncertainty,
            sampleRate: Int(metadata.sampleRate.rounded()), sampleCount: metadata.sampleCount, durationMs: metadata.durationMs,
            tuning: tuning, modelVersion: "none", detectorVersion: "native-mpm-yin-1",
            supportedPitchRange: ["minimumMIDI": profile.minMidi, "maximumMIDI": profile.maxMidi],
            warnings: ["单音听音的周期性置信度不是正确率；录音结束处的释放不用于时值评分。"])
    }
}
