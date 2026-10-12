import Foundation
import AVFoundation
import CryptoKit
import Darwin

@MainActor
protocol NoteWiseCapturing: AnyObject {
    var onPCM: ((AVAudioPCMBuffer, AVAudioTime) -> Void)? { get set }
    var onMIDI: (([MIDIPerformanceEvent]) -> Void)? { get set }
    var onError: ((String) -> Void)? { get set }
    func start(_ mode: String) async throws
    func stop()
}
extension NativePracticeInput: NoteWiseCapturing {}

/// The producer's serial PCM order is retained even if its MainActor Tasks run
/// in another order. A normal stop synchronously drains this same small inbox
/// after the native writer finishes; abort never delivers a detached inbox.
private final class NoteWiseEventInbox: @unchecked Sendable {
    private let lock = NSLock()
    private var values: [[String: Any]] = []
    func append(_ value: [String: Any]) { lock.lock(); values.append(value); lock.unlock() }
    func drain() -> [[String: Any]] {
        lock.lock(); defer { lock.unlock() }
        let result = values; values.removeAll(keepingCapacity: true); return result
    }
}

private enum NoteWiseCaptureResult: Sendable {
    case unavailable
    case recording(available: Bool, sampleRate: Double, sampleCount: UInt64,
                   durationMs: Double, size: Int, interrupted: Bool)
    var dictionary: [String: Any] {
        switch self {
        case .unavailable: return ["available":false]
        case let .recording(available, rate, count, duration, size, interrupted):
            return ["available":available,"sampleRate":rate,"sampleCount":count,
                "durationMs":duration,"mime":"audio/wav","size":size,"interrupted":interrupted]
        }
    }
}

/// Detection and disk recording run on this serial native queue, never the UI or WebView.
private final class NoteWiseAudioProcessor: @unchecked Sendable {
    let queue: DispatchQueue
    private var dsp: OpaquePointer?
    private var file: AVAudioFile?
    private var rate: Double = 0
    private var failed = false
    private var count: UInt64 = 0
    private var totalBytes = 0
    private var detectorOffsetMs:Double = 0
    private let submissionLock = NSLock()
    private var acceptingBuffers = true
    private let a4: Double
    private let minimum: Double
    private let maximum: Double
    private let window: Int
    private let url: URL
    private let event: @Sendable ([String: Any]) -> Void
    private let error: @Sendable (String) -> Void
    init(url: URL, a4: Double, minimum: Double, maximum: Double, window: Int, queue: DispatchQueue? = nil,
         event: @escaping @Sendable ([String: Any]) -> Void, error: @escaping @Sendable (String) -> Void) {
        self.queue = queue ?? DispatchQueue(label: "com.notelite.notewise.capture", qos: .userInitiated)
        self.url=url; self.a4=a4; self.minimum=minimum; self.maximum=maximum; self.window=window; self.event=event; self.error=error
    }
    deinit { if let dsp { nw_destroy(dsp) } }
    func append(_ buffer: AVAudioPCMBuffer, _ time: AVAudioTime) {
        guard let source = buffer.floatChannelData?[0], buffer.frameLength > 0,
              let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: buffer.format.sampleRate, channels: 1, interleaved: false),
              let copy = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: buffer.frameLength) else { return }
        copy.frameLength = buffer.frameLength
        copy.floatChannelData![0].update(from: source, count: Int(buffer.frameLength))
        submissionLock.lock()
        defer { submissionLock.unlock() }
        guard acceptingBuffers else { return }
        queue.async { [self] in
            guard !failed else { return }
            do {
                if dsp == nil {
                    // A paused take keeps its WAV format and sample clock.
                    // Check before overwriting rate when rebuilding the DSP.
                    if file != nil, rate != format.sampleRate {
                        throw NoteLiteError.server("录音采样率变化，已停止本次输入。请结束保存后重新开始。")
                    }
                    rate = format.sampleRate
                    guard let detector = nw_create_profile(rate, a4, minimum, min(maximum, rate / 2 - 1), window) else { throw NoteLiteError.server("此采样率或乐器音域不能初始化听音，请更换声音输入。") }
                    dsp = detector
                    if file == nil { file = try AVAudioFile(forWriting: url, settings: [AVFormatIDKey: kAudioFormatLinearPCM,
                        AVSampleRateKey: rate, AVNumberOfChannelsKey: 1, AVLinearPCMBitDepthKey: 16,
                        AVLinearPCMIsFloatKey: false, AVLinearPCMIsBigEndianKey: false]) }
                }
                guard rate == format.sampleRate else { throw NoteLiteError.server("录音采样率变化，已停止本次输入。") }
                totalBytes += Int(copy.frameLength) * 2
                guard totalBytes <= CloudAccountClient.maximumRecordingBytes - 4096 else { throw NoteLiteError.server("本次录音达到 100 MB，请结束并保存练习。") }
                try file?.write(from: copy)
                nw_push(dsp!, copy.floatChannelData![0], Int(copy.frameLength))
                count += UInt64(copy.frameLength)
                drain()
            } catch {
                failed = true; self.error(error.localizedDescription)
            }
        }
    }
    private func drain() {
        var value = nl_note_event()
        while nw_poll(dsp!, &value) != 0 {
            let type = String(cString: value.type), reason = String(cString: value.reason)
            var result: [String: Any] = ["type": type == "note-on" ? "on" : type == "note-off" ? "off" : type == "note-update" ? "update" : "uncertainty",
                "eventId": "audio-\(Int(detectorOffsetMs))-\(value.id)", "timeMs": value.time_ms+detectorOffsetMs, "onsetMs": value.onset_ms+detectorOffsetMs,
                "sampleCount": value.sample_count + UInt64(max(0, (detectorOffsetMs * rate / 1000).rounded())), "sampleRate": rate,
                "confidence": value.confidence, "timingConfidence": value.timing_confidence, "reason": reason,
                "releaseReliable": type == "note-off" && reason != "stop", "centsEvidence": "continuous-mpm-yin"]
            if value.midi >= 0 { result["midi"] = value.midi; result["cents"] = value.cents; result["frequency"] = value.frequency }
            if value.offset_ms.isFinite { result["offsetMs"] = value.offset_ms+detectorOffsetMs }
            event(result)
        }
    }
    func pause() {
        submissionLock.lock()
        defer { submissionLock.unlock() }
        guard acceptingBuffers else { return }
        queue.async { [self] in
            if let dsp { nw_finish(dsp); drain(); nw_destroy(dsp); self.dsp=nil }
            detectorOffsetMs = rate>0 ? 1000 * Double(count)/rate : 0
        }
    }
    func finish() async -> NoteWiseCaptureResult {
        await withCheckedContinuation { continuation in
            submissionLock.lock()
            defer { submissionLock.unlock() }
            acceptingBuffers = false
            queue.async { [self] in
                if let dsp { nw_finish(dsp); drain(); nw_destroy(dsp); self.dsp = nil }
                file = nil
                continuation.resume(returning: .recording(available: count > 0 && !failed, sampleRate: rate,
                    sampleCount: count, durationMs: rate > 0 ? 1000 * Double(count) / rate : 0,
                    size: totalBytes, interrupted: failed))
            }
        }
    }
}

@MainActor
final class NoteWiseSession {
    private let input: NoteWiseCapturing
    private let takeStore: NoteWiseTakeStore
    private let processingQueue: DispatchQueue?
    private var deletedScopes = Set<String>()
    private var processor: NoteWiseAudioProcessor?
    private var takeID: String?
    private var scope = ""
    private var sequence = 0
    private var generation = UUID()
    private var midiID = 0
    private var midiStarted: Double = 0
    private var midiOffset: Double = 0
    private var activeMIDI: [String: String] = [:]
    private var connected = false
    private struct TakeConfiguration: Equatable {
        let inputKind: String
        let tuning: Double
        let instrument: String
    }
    private var takeConfiguration: TakeConfiguration?
    private var inputInbox: NoteWiseEventInbox?
    private var normalStop: (generation: UUID, task: Task<NoteWiseCaptureResult, Never>)?
    var event: (([String: Any]) -> Void)?

    init(input: NoteWiseCapturing? = nil, recordingsDirectory: URL? = nil, processingQueue: DispatchQueue? = nil) {
        self.input = input ?? NativePracticeInput()
        takeStore = NoteWiseTakeStore(directory: recordingsDirectory)
        self.processingQueue = processingQueue
    }
    private func validate(_ id: String) throws -> String {
        try takeStore.identifier(id)
    }
    private func requireAvailable(scope: String) throws {
        deletedScopes.formUnion(try takeStore.pendingPurges())
        guard !deletedScopes.contains(scope) else {
            throw CloudOMRError(code: "account_deleted", message: "此账户已注销。", status: 410)
        }
    }
    func resumePendingAccountDeletions() async throws {
        let pending = try takeStore.pendingPurges()
        deletedScopes.formUnion(pending)
        let store = takeStore
        try await Task.detached(priority: .utility) {
            for scope in pending { try store.purge(scope: scope) }
        }.value
    }
    /// Called only after the account service has accepted verified deletion.
    /// Synchronous state detachment prevents new guest input being stopped by
    /// this old account's asynchronous queue drain.
    func deleteRecordings(accountScope: String, waitingFor readers: [Task<Void, Never>] = []) async throws -> Int {
        try takeStore.checkAccountScope(accountScope)
        deletedScopes.insert(accountScope)
        let writer = scope == accountScope ? detachCapture() : nil
        let persistence: Result<Void, Error> = Result { try takeStore.schedulePurge(scope: accountScope) }
        _ = await writer?.finish()
        for reader in readers { await reader.value }
        try persistence.get()
        let store = takeStore
        return try await Task.detached(priority: .utility) { try store.purge(scope: accountScope) }.value
    }
    private func emit(_ value: [String: Any]) {
        guard let takeID else { return }
        sequence += 1
        event?(value.merging(["type": "notewiseInput", "takeId": takeID, "sequence": sequence]) { old, _ in old })
    }
    private func flush(_ inbox: NoteWiseEventInbox, id: String, scope: String, generation: UUID) {
        guard takeID == id, self.scope == scope, self.generation == generation else { return }
        for value in inbox.drain() {
            if value["status"] as? String == "interrupted" { input.stop() }
            emit(value)
        }
    }
    func start(_ payload: [String: Any], scope: String) async throws -> [String: Any] {
        try requireAvailable(scope: scope)
        try Task.checkCancellation()
        guard let raw=payload["takeId"] as? String, let kind=payload["inputKind"] as? String,
              ["midi", "microphone"].contains(kind), let a4=payload["tuning"] as? Double,
              a4.isFinite, (400...480).contains(a4) else { throw NoteLiteError.invalidResponse }
        let id=try validate(raw)
        guard normalStop?.generation != generation else {
            throw CloudOMRError(code: "take_stopping", message: "本次练习正在结束保存，请保存完成后重新开始。", status: 409)
        }
        if payload["instrument"] != nil && !(payload["instrument"] is String) { throw NoteLiteError.invalidResponse }
        let profile=try NoteWiseInstrumentProfiles.resolve(payload["instrument"] as? String ?? "piano")
        let configuration = TakeConfiguration(inputKind: kind, tuning: a4, instrument: profile.id)
        if takeID == id && self.scope == scope && takeConfiguration != configuration {
            throw CloudOMRError(code: "take_configuration_changed", message: "本次练习的输入、乐器和调音已经固定，请先结束保存，再更改设置。", status: 409)
        }
        if takeID != nil && (takeID != id || self.scope != scope) {
            if self.scope == scope { _ = await stop() } else { _ = await abort() }
        }
        try requireAvailable(scope: scope)
        try Task.checkCancellation()
        let current=generation
        if takeID == nil {
            try takeStore.register(id, scope: scope, inputKind: kind)
            takeID=id; self.scope=scope; sequence=0; midiOffset=0; midiID=0; takeConfiguration=configuration
            if kind == "microphone" {
                let inbox = NoteWiseEventInbox(); inputInbox = inbox
                processor = NoteWiseAudioProcessor(url: try takeStore.audioURL(id), a4: a4,
                    minimum: profile.frequency(profile.minMidi, tuning: a4), maximum: profile.frequency(profile.maxMidi, tuning: a4), window: profile.windowSize,
                    queue: processingQueue,
                    event: { [weak self] value in
                        inbox.append(["inputKind":"microphone", "event":value])
                        Task { @MainActor [weak self] in self?.flush(inbox, id: id, scope: scope, generation: current) }
                    },
                    error: { [weak self] message in
                        inbox.append(["status":"interrupted", "message":message])
                        Task { @MainActor [weak self] in self?.flush(inbox, id: id, scope: scope, generation: current) }
                    })
            }
        }
        if kind == "microphone" {
            let processor=self.processor
            input.onPCM = { buffer,time in processor?.append(buffer,time) }
        } else {
            midiStarted=ProcessInfo.processInfo.systemUptime
            input.onMIDI = { [weak self] values in
                guard let self, self.generation == current, self.takeID == id, self.scope == scope else { return }
                for value in values {
                    var info=mach_timebase_info_data_t(); mach_timebase_info(&info)
                    let timestamp=value.timestamp == 0 ? ProcessInfo.processInfo.systemUptime : Double(value.timestamp)*Double(info.numer)/Double(info.denom)/1_000_000_000
                    let at=max(0,(timestamp-self.midiStarted)*1000)+self.midiOffset
                    let key="\(value.sourceID):\(value.channel):\(value.midi)"
                    var id=self.activeMIDI[key]
                    if value.type == "on" { self.midiID += 1; id="midi-\(self.midiID)"; self.activeMIDI[key]=id }
                    if value.type == "off" { self.activeMIDI.removeValue(forKey:key) }
                    guard let id else { continue }
                    self.emit(["inputKind":"midi", "event":["eventId":id, "type":value.type, "midi":value.midi,
                        "channel":value.channel,"velocity":value.velocity,"sourceId":value.sourceID,"timeMs":at,"confidence":1.0,
                        "timingConfidence":1.0,"centsEvidence":"none","releaseReliable":true]])
                }
            }
        }
        input.onError = { [weak self] message in
            guard let self, self.generation == current, self.takeID == id, self.scope == scope else { return }
            self.emit(["status":"interrupted","message":message])
        }
        do { try await input.start(kind); try Task.checkCancellation() }
        catch { if current == generation { _ = await abort() }; throw error }
        guard current == generation else { throw CancellationError() }
        connected=true
        return ["connected":true,"takeId":id,"inputKind":kind,"detectorVersion":kind == "midi" ? "midi-stream-2" : "native-mpm-yin-1",
            "captureClock":["source":kind == "midi" ? "host-monotonic" : "audio-sample","unit":"ms","timingCalibrated":false],
            "capabilities":["pitch":true,"onset":true,"duration":true,"intonation":kind == "microphone","polyphony":kind == "midi","recording":kind == "microphone"]]
    }
    func pause() {
        connected=false
        if midiStarted > 0 { midiOffset += max(0,(ProcessInfo.processInfo.systemUptime-midiStarted)*1000); midiStarted=0 }
        input.stop(); processor?.pause(); activeMIDI.removeAll()
        emit(["status":"paused"])
    }
    func interruptIfConnected(_ message:String) { guard connected else{return};pause();emit(["status":"interrupted","message":message]) }
    func checkActive(_ raw:String,scope:String) throws {
        try requireAvailable(scope: scope)
        guard try validate(raw)==takeID, self.scope==scope else { throw NoteLiteError.invalidResponse }
    }
    private func detachCapture() -> NoteWiseAudioProcessor? {
        connected = false
        input.stop(); input.onPCM = nil; input.onMIDI = nil; input.onError = nil
        generation = UUID()
        let writer = processor
        processor = nil; inputInbox = nil; normalStop = nil; takeID = nil; takeConfiguration = nil; scope = ""; activeMIDI.removeAll()
        return writer
    }
    /// Cancelled starts, account changes and WebView termination detach first.
    /// The old native queue may finish its file but cannot deliver to a new take.
    func abort() async -> [String: Any] {
        let id=takeID
        let writer = detachCapture()
        let result=await writer?.finish() ?? .unavailable
        return result.dictionary.merging(["takeId":id ?? ""]) { old,_ in old }
    }
    func stop() async -> [String: Any] {
        guard let id = takeID else { return ["available":false,"takeId":""] }
        let current = generation, owner = scope, inbox = inputInbox
        let finishing: Task<NoteWiseCaptureResult, Never>
        if let pending = normalStop, pending.generation == current { finishing = pending.task }
        else {
            connected = false
            input.stop(); input.onPCM = nil; input.onMIDI = nil; input.onError = nil
            let writer = processor
            finishing = Task { await writer?.finish() ?? .unavailable }
            normalStop = (current, finishing)
        }
        let result = await finishing.value
        // Account deletion/abort can detach while the native queue is draining.
        // A stale stop must neither publish its tail nor stop the new account.
        if takeID == id, scope == owner, generation == current {
            if let inbox { flush(inbox, id: id, scope: owner, generation: current) }
            _ = detachCapture()
        }
        return result.dictionary.merging(["takeId":id]) { old,_ in old }
    }
    func recording(_ raw: String, scope: String) throws -> URL {
        try requireAvailable(scope: scope)
        let id=try validate(raw)
        guard takeID != id else { throw NoteLiteError.server("请先结束并保存这次录音。") }
        return try takeStore.recording(id, scope: scope)
    }

    func recordingStatus(_ raw: String, scope: String) throws -> [String: Any] {
        try requireAvailable(scope: scope)
        let id = try validate(raw)
        guard takeID != id || self.scope != scope else {
            return ["takeId": id, "available": false, "storage": "device", "reason": "recording_in_progress"]
        }
        let available = try takeStore.hasRecording(id, scope: scope)
        if available { return ["takeId": id, "available": true, "storage": "device"] }
        // Missing and differently owned files have the same public result.
        return ["takeId": id, "available": false, "storage": "device", "reason": "not_on_this_device"]
    }
}
