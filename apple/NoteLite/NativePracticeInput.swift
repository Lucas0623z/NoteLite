import Foundation
import AVFoundation
import CoreMIDI

/// MIDI 1.0 stream decoding, including running status, real-time bytes, and split packets.
struct MIDINoteParser {
    private var status: UInt8 = 0
    private var pending: [UInt8] = []
    private var systemExclusive = false

    mutating func consume(_ bytes: [UInt8]) -> [Int] {
        var notes: [Int] = []
        for byte in bytes {
            if byte >= 0xF8 { continue }
            if byte & 0x80 != 0 {
                pending.removeAll(keepingCapacity: true)
                if byte == 0xF0 { systemExclusive = true; status = 0; continue }
                if byte == 0xF7 { systemExclusive = false; status = 0; continue }
                if byte >= 0xF0 { status = 0; continue }
                systemExclusive = false
                status = byte
                continue
            }
            guard !systemExclusive, status >= 0x80 else { continue }
            pending.append(byte)
            let command = status & 0xF0
            let needed = command == 0xC0 || command == 0xD0 ? 1 : 2
            if pending.count == needed {
                if command == 0x90 && pending[1] > 0 { notes.append(Int(pending[0])) }
                pending.removeAll(keepingCapacity: true)
            }
        }
        return notes
    }
}

private final class MIDIStreamDecoder: @unchecked Sendable {
    private let lock = NSLock()
    private var parsers: [UInt: MIDINoteParser] = [:]
    func notes(_ bytes: [UInt8], source: UInt) -> [Int] {
        lock.lock()
        defer { lock.unlock() }
        var parser = parsers[source] ?? MIDINoteParser()
        let result = parser.consume(bytes)
        parsers[source] = parser
        return result
    }
}

private final class MicrophoneFrames: @unchecked Sendable {
    private var samples: [Float] = []
    func append(_ buffer: AVAudioPCMBuffer) -> [[Float]] {
        guard let channel = buffer.floatChannelData?[0] else { return [] }
        samples.append(contentsOf: UnsafeBufferPointer(start: channel, count: Int(buffer.frameLength)))
        var frames: [[Float]] = []
        while samples.count >= 4096 {
            frames.append(Array(samples.prefix(4096)))
            samples.removeFirst(4096)
        }
        return frames
    }
}

@MainActor
final class NativePracticeInput {
    var onNotes: (([Int]) -> Void)?
    var onAudio: (([Float], Double) -> Void)?
    var onError: ((String) -> Void)?
    private var engine: AVAudioEngine?
    private var midiClient = MIDIClientRef()
    private var midiPort = MIDIPortRef()
    private var sources: Set<MIDIEndpointRef> = []
    private var generation = UUID()
    private var engineObserver: NSObjectProtocol?
    private var interruptionObserver: NSObjectProtocol?
    private var tapInstalled = false
    #if os(iOS)
    private var audioSessionActive = false
    #endif

    func start(_ mode: String) async throws {
        try Task.checkCancellation()
        stop()
        let current = generation
        if mode == "microphone" {
            let permitted = await AVCaptureDevice.requestAccess(for: .audio)
            guard current == generation else { throw CancellationError() }
            try Task.checkCancellation()
            guard permitted else { throw NoteLiteError.server("麦克风未获授权。请在系统设置中允许 NoteLite 使用麦克风。") }
            #if os(iOS)
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .measurement, options: [.defaultToSpeaker, .allowBluetooth])
            try session.setActive(true)
            audioSessionActive = true
            #endif
            let engine = AVAudioEngine()
            self.engine = engine
            let input = engine.inputNode
            let format = input.outputFormat(forBus: 0)
            guard format.sampleRate > 0, format.channelCount > 0 else {
                stop()
                throw NoteLiteError.server("未找到可用麦克风，请检查系统声音输入设置。")
            }
            let frames = MicrophoneFrames()
            input.installTap(onBus: 0, bufferSize: 4096, format: format) { [weak self] buffer, _ in
                let batches = frames.append(buffer)
                let rate = buffer.format.sampleRate
                Task { @MainActor [weak self] in
                    guard let self, self.generation == current else { return }
                    for batch in batches { self.onAudio?(batch, rate) }
                }
            }
            tapInstalled = true
            do { engine.prepare(); try engine.start() }
            catch { stop(); throw error }
            engineObserver = NotificationCenter.default.addObserver(forName: .AVAudioEngineConfigurationChange,
                object: engine, queue: .main) { [weak self] _ in
                    Task { @MainActor [weak self] in
                        guard let self, self.generation == current else { return }
                        self.stop()
                        self.onError?("声音输入设备发生变化，请检查连接后继续练习。")
                    }
                }
            #if os(iOS)
            interruptionObserver = NotificationCenter.default.addObserver(forName: AVAudioSession.interruptionNotification,
                object: session, queue: .main) { [weak self] notification in
                    guard let type = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
                          type == AVAudioSession.InterruptionType.began.rawValue else { return }
                    Task { @MainActor [weak self] in
                        guard let self, self.generation == current else { return }
                        self.stop()
                        self.onError?("声音输入被系统中断，准备好后可继续练习。")
                    }
                }
            #endif
        } else if mode == "midi" {
            let decoder = MIDIStreamDecoder()
            let clientStatus = MIDIClientCreateWithBlock("NoteLite Practice" as CFString, &midiClient) { [weak self] _ in
                Task { @MainActor [weak self] in
                    guard let self, self.generation == current else { return }
                    self.refreshMIDISources()
                }
            }
            guard clientStatus == noErr else { stop(); throw NoteLiteError.server("无法启动 MIDI 服务（\(clientStatus)）。") }
            let portStatus = MIDIInputPortCreateWithBlock(midiClient, "Practice Input" as CFString, &midiPort) { [weak self] list, connection in
                let source = UInt(bitPattern: connection)
                var packet = UnsafeRawPointer(list).advanced(by: MemoryLayout<MIDIPacketList>.offset(of: \.packet)!)
                    .assumingMemoryBound(to: MIDIPacket.self)
                var notes: [Int] = []
                for _ in 0..<list.pointee.numPackets {
                    let bytes = UnsafeRawPointer(packet).advanced(by: MemoryLayout<MIDIPacket>.offset(of: \.data)!)
                        .assumingMemoryBound(to: UInt8.self)
                    notes.append(contentsOf: decoder.notes(Array(UnsafeBufferPointer(start: bytes,
                        count: Int(packet.pointee.length))), source: source))
                    packet = UnsafePointer(MIDIPacketNext(packet))
                }
                guard !notes.isEmpty else { return }
                Task { @MainActor [weak self] in
                    guard let self, self.generation == current else { return }
                    self.onNotes?(notes)
                }
            }
            guard portStatus == noErr else { stop(); throw NoteLiteError.server("无法打开 MIDI 输入（\(portStatus)）。") }
            refreshMIDISources()
            guard !sources.isEmpty else {
                stop()
                throw NoteLiteError.server("没有连接的 MIDI 乐器。请连接 USB 或系统中已配对的蓝牙 MIDI 乐器。")
            }
        } else { throw NoteLiteError.server("不支持此演奏输入。") }
    }

    private func refreshMIDISources() {
        guard midiPort != 0 else { return }
        let available = Set((0..<MIDIGetNumberOfSources()).map { MIDIGetSource($0) }.filter { $0 != 0 })
        let hadSources = !sources.isEmpty
        for source in sources.subtracting(available) { MIDIPortDisconnectSource(midiPort, source) }
        sources.formIntersection(available)
        for source in available.subtracting(sources) {
            if MIDIPortConnectSource(midiPort, source, UnsafeMutableRawPointer(bitPattern: UInt(source))) == noErr {
                sources.insert(source)
            }
        }
        if hadSources && sources.isEmpty {
            stop()
            onError?("MIDI 乐器已断开，练习已停止。重新连接后可以继续。")
        }
    }

    func stop() {
        generation = UUID()
        if let engineObserver { NotificationCenter.default.removeObserver(engineObserver) }
        engineObserver = nil
        if let interruptionObserver { NotificationCenter.default.removeObserver(interruptionObserver) }
        interruptionObserver = nil
        if let engine {
            if tapInstalled { engine.inputNode.removeTap(onBus: 0) }
            engine.stop()
        }
        tapInstalled = false
        engine = nil
        #if os(iOS)
        if audioSessionActive {
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
            audioSessionActive = false
        }
        #endif
        if midiPort != 0 { MIDIPortDispose(midiPort); midiPort = 0 }
        if midiClient != 0 { MIDIClientDispose(midiClient); midiClient = 0 }
        sources.removeAll()
    }
}
