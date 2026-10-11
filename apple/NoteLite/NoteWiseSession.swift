import Foundation
import AVFoundation
import CryptoKit
import Darwin

/// Detection and disk recording run on this serial native queue, never the UI or WebView.
private final class NoteWiseAudioProcessor: @unchecked Sendable {
    let queue = DispatchQueue(label: "com.notelite.notewise.capture", qos: .userInitiated)
    private var dsp: OpaquePointer?
    private var file: AVAudioFile?
    private var rate: Double = 0
    private var failed = false
    private var count: UInt64 = 0
    private var totalBytes = 0
    private var detectorOffsetMs:Double = 0
    private let a4: Double
    private let minimum: Double
    private let maximum: Double
    private let window: Int
    private let url: URL
    private let event: @Sendable ([String: Any]) -> Void
    private let error: @Sendable (String) -> Void
    init(url: URL, a4: Double, minimum: Double, maximum: Double, window: Int,
         event: @escaping @Sendable ([String: Any]) -> Void, error: @escaping @Sendable (String) -> Void) {
        self.url=url; self.a4=a4; self.minimum=minimum; self.maximum=maximum; self.window=window; self.event=event; self.error=error
    }
    deinit { if let dsp { nw_destroy(dsp) } }
    func append(_ buffer: AVAudioPCMBuffer, _ time: AVAudioTime) {
        guard let source = buffer.floatChannelData?[0], buffer.frameLength > 0,
              let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: buffer.format.sampleRate, channels: 1, interleaved: false),
              let copy = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: buffer.frameLength) else { return }
        copy.frameLength = buffer.frameLength
        copy.floatChannelData![0].update(from: source, count: Int(buffer.frameLength))
        queue.async { [self] in
            guard !failed else { return }
            do {
                if dsp == nil {
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
                "sampleCount": UInt64(max(0, (value.time_ms+detectorOffsetMs) * rate / 1000)), "sampleRate": rate,
                "confidence": value.confidence, "timingConfidence": value.timing_confidence, "reason": reason,
                "releaseReliable": type == "note-off" && reason != "stop", "centsEvidence": "continuous-mpm-yin"]
            if value.midi >= 0 { result["midi"] = value.midi; result["cents"] = value.cents; result["frequency"] = value.frequency }
            if value.offset_ms.isFinite { result["offsetMs"] = value.offset_ms+detectorOffsetMs }
            event(result)
        }
    }
    func pause() {
        queue.async { [self] in
            if let dsp { nw_finish(dsp); drain(); nw_destroy(dsp); self.dsp=nil }
            detectorOffsetMs = rate>0 ? 1000 * Double(count)/rate : 0
        }
    }
    func finish() async -> [String: Any] {
        await withCheckedContinuation { continuation in
            queue.async { [self] in
                if let dsp { nw_finish(dsp); drain() }
                file = nil
                continuation.resume(returning: ["available": count > 0 && !failed, "sampleRate": rate,
                    "sampleCount": count, "durationMs": rate > 0 ? 1000 * Double(count) / rate : 0,
                    "mime": "audio/wav", "size": totalBytes, "interrupted": failed])
            }
        }
    }
}

@MainActor
final class NoteWiseSession {
    private let input = NativePracticeInput()
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
    var event: (([String: Any]) -> Void)?

    private func folder() throws -> URL {
        let root = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
            appropriateFor: nil, create: true).appendingPathComponent("NoteLite/NoteWiseTakes", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        return root
    }
    private func validate(_ id: String) throws -> String {
        guard let value=UUID(uuidString: id) else { throw NoteLiteError.invalidResponse }; return value.uuidString.lowercased()
    }
    private func emit(_ value: [String: Any]) {
        guard let takeID else { return }
        sequence += 1
        event?(value.merging(["type": "notewiseInput", "takeId": takeID, "sequence": sequence]) { old, _ in old })
    }
    func start(_ payload: [String: Any], scope: String) async throws -> [String: Any] {
        guard let raw=payload["takeId"] as? String, let kind=payload["inputKind"] as? String,
              ["midi", "microphone"].contains(kind), let a4=payload["tuning"] as? Double,
              a4.isFinite, (400...480).contains(a4) else { throw NoteLiteError.invalidResponse }
        let id=try validate(raw)
        let profile=kind == "microphone" ? try NoteWiseInstrumentProfiles.resolve(payload["instrument"] as? String ?? "piano") : nil
        if takeID != nil && (takeID != id || self.scope != scope) { _ = await stop() }
        let current=generation
        if takeID == nil {
            takeID=id; self.scope=scope; sequence=0; midiOffset=0; midiID=0
            let identity: [String: Any] = ["takeId": id, "scope": scope, "inputKind": kind, "createdAt": ISO8601DateFormatter().string(from: Date())]
            try JSONSerialization.data(withJSONObject: identity).write(to: folder().appendingPathComponent(id+".json"), options: .atomic)
            if kind == "microphone" {
                guard let profile else { throw NoteLiteError.invalidResponse }
                processor = NoteWiseAudioProcessor(url: try folder().appendingPathComponent(id+".wav"), a4: a4,
                    minimum: profile.frequency(profile.minMidi, tuning: a4), maximum: profile.frequency(profile.maxMidi, tuning: a4), window: profile.windowSize,
                    event: { [weak self] value in Task { @MainActor [weak self] in guard let self,self.takeID==id,self.generation==current else{return};self.emit(["inputKind":"microphone", "event":value]) } },
                    error: { [weak self] message in Task { @MainActor [weak self] in guard let self,self.takeID==id,self.generation==current else{return};self.input.stop();self.emit(["status":"interrupted", "message":message]) } })
            }
        }
        if kind == "microphone" {
            let processor=self.processor
            input.onPCM = { buffer,time in processor?.append(buffer,time) }
        } else {
            midiStarted=ProcessInfo.processInfo.systemUptime
            input.onMIDI = { [weak self] values in
                guard let self else { return }
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
        input.onError = { [weak self] message in self?.emit(["status":"interrupted","message":message]) }
        do { try await input.start(kind); try Task.checkCancellation() }
        catch { _ = await stop(); throw error }
        guard current == generation else { input.stop(); throw CancellationError() }
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
        guard try validate(raw)==takeID, self.scope==scope else { throw NoteLiteError.invalidResponse }
    }
    func stop() async -> [String: Any] {
        connected=false
        input.stop(); generation=UUID()
        let result=await processor?.finish() ?? ["available":false]
        let id=takeID
        processor=nil; takeID=nil; activeMIDI.removeAll()
        return result.merging(["takeId":id ?? ""]) { old,_ in old }
    }
    func recording(_ raw: String, scope: String) throws -> URL {
        let id=try validate(raw), root=try folder()
        let identity=try JSONSerialization.jsonObject(with: Data(contentsOf: root.appendingPathComponent(id+".json"))) as? [String: Any]
        guard identity?["scope"] as? String == scope, identity?["inputKind"] as? String == "microphone" else { throw NoteLiteError.invalidResponse }
        let url=root.appendingPathComponent(id+".wav")
        guard FileManager.default.fileExists(atPath:url.path), takeID != id else { throw NoteLiteError.server("请先结束并保存这次录音。") }
        return url
    }
}
