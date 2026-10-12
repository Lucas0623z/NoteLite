import XCTest
import AVFoundation
@testable import NoteLite

final class NoteWiseTests:XCTestCase {
    func testBundledInstrumentProfilesCoverCanonicalSixteenRangesAndRejectUnknownIDs() throws {
        let expected=["piano":21,"violin":55,"viola":48,"cello":36,"contrabass":24,"harp":24,"flute":48,"clarinet":34,"bassoon":22,"oboe":53,"horn":28,"trumpet":42,"trombone":28,"tuba":21,"euphonium":28,"voice":36]
        for (id,minimum) in expected {
            let profile=try NoteWiseInstrumentProfiles.resolve(id)
            XCTAssertEqual(profile.minMidi,minimum);XCTAssertGreaterThan(profile.maxMidi,minimum)
            XCTAssertEqual(profile.frequency(69,tuning:442),442,accuracy:0.000001)
        }
        XCTAssertThrowsError(try NoteWiseInstrumentProfiles.resolve("unknown"))
    }
    func testMIDIReleaseVelocityZeroAndRunningStatusKeepCompleteEvents() {
        var parser=MIDINoteParser()
        let notes=parser.consumeEvents([0x92,60,100,0xF8,64,90,60,0,0x82,64,12],timestamp:123)
        XCTAssertEqual(notes.map(\.type),["on","on","off","off"])
        XCTAssertEqual(notes.map(\.midi),[60,64,60,64])
        XCTAssertEqual(notes.map(\.channel),[2,2,2,2]);XCTAssertEqual(notes.map(\.velocity),[100,90,0,12])
        XCTAssertTrue(notes.allSatisfy{$0.timestamp==123})
    }
    func testSplitMIDIStreamPreservesNoteOffWithoutInventingNotesFromSysex() {
        var parser=MIDINoteParser()
        XCTAssertTrue(parser.consumeEvents([0x90,60],timestamp:10).isEmpty)
        XCTAssertEqual(parser.consumeEvents([100],timestamp:20).first?.type,"on")
        XCTAssertTrue(parser.consumeEvents([0xF0,90,10,0xF7],timestamp:30).isEmpty)
        XCTAssertEqual(parser.consumeEvents([0x80,60,0],timestamp:40).first?.type,"off")
    }
    func testActualSharedMPMYINWrapperDetectsA4AndReliableSilenceRelease() throws {
        let rate=48000.0
        var audio=[Float](repeating:0,count:4800)
        audio += (0..<19200).map {Float(0.2*sin(2*Double.pi*440*Double($0)/rate))}
        audio += [Float](repeating:0,count:14400)
        let events=try NoteWiseTestProbe.detect(audio)
        let ons=events.filter{$0["type"] as? String=="note-on"},offs=events.filter{$0["type"] as? String=="note-off"}
        XCTAssertEqual(ons.count,1);XCTAssertEqual(offs.count,1)
        XCTAssertEqual(ons.first?["midi"] as? Int,69)
        XCTAssertLessThan(abs(try XCTUnwrap(ons.first?["onsetMs"] as? Double)-100),15)
        XCTAssertEqual(offs.first?["reason"] as? String,"silence")
        XCTAssertLessThan(abs(try XCTUnwrap(ons.first?["cents"] as? Double)),2)
    }
    func testSilenceDoesNotInventCorrectNotesAndStopReleaseIsNotNatural() throws {
        XCTAssertTrue(try NoteWiseTestProbe.detect([Float](repeating:0,count:48000)).isEmpty)
        let audio=(0..<24000).map{Float(0.2*sin(2*Double.pi*442*Double($0)/48000))}
        let events=try NoteWiseTestProbe.detect(audio,a4:442)
        XCTAssertEqual(events.filter{$0["type"] as? String=="note-on"}.count,1)
        XCTAssertEqual(events.last?["reason"] as? String,"stop")
    }
    func testSharedDSPEventSampleCountsUseActual441004800096000PCMClocks() throws {
        for rate in [44100.0, 48000, 96000] {
            var audio = [Float](repeating: 0, count: Int(rate / 10))
            audio += (0..<Int(rate * 0.4)).map { Float(0.2 * sin(2 * Double.pi * 440 * Double($0) / rate)) }
            audio += [Float](repeating: 0, count: Int(rate * 0.3))
            let events = try NoteWiseTestProbe.detect(audio, rate: rate)
            XCTAssertEqual(events.filter { $0["type"] as? String == "note-on" }.count, 1)
            XCTAssertEqual(events.filter { $0["type"] as? String == "note-off" }.count, 1)
            for event in events {
                let count = try XCTUnwrap(event["sampleCount"] as? UInt64)
                let time = try XCTUnwrap(event["timeMs"] as? Double)
                XCTAssertEqual(Double(count), time * rate / 1000, accuracy: 0.51)
            }
        }
    }
    @MainActor func testSameTakeResumeFreezesInputTuningAndInstrumentWithoutStoppingCapture() async throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("notewise-config-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let input = NoteWiseConfigurationTestCapture()
        let session = NoteWiseSession(input: input, recordingsDirectory: folder)
        let id = UUID().uuidString.lowercased(), scope = "https://124.221.211.156|guest"
        let payload: [String: Any] = ["takeId": id, "inputKind": "microphone", "tuning": 440.0, "instrument": "violin"]
        _ = try await session.start(payload, scope: scope)
        session.pause()
        _ = try await session.start(payload, scope: scope)
        XCTAssertEqual(input.starts, 2)
        let stops = input.stops
        for (field, changed) in [("inputKind", "midi" as Any), ("tuning", 442.0 as Any), ("instrument", "piano" as Any)] {
            var modified = payload; modified[field] = changed
            do { _ = try await session.start(modified, scope: scope); XCTFail("A running take cannot change \(field)") }
            catch { XCTAssertEqual((error as? CloudOMRError)?.code, "take_configuration_changed") }
            try session.checkActive(id, scope: scope)
            XCTAssertEqual(input.starts, 2)
            XCTAssertEqual(input.stops, stops)
        }
        _ = await session.stop()
        _ = try await session.start(["takeId": UUID().uuidString.lowercased(), "inputKind": "midi", "tuning": 442.0], scope: scope)
        XCTAssertEqual(input.starts, 3)
        _ = await session.stop()
    }
    @MainActor func testResumedTakeRejectsChangedPCMRateBeforeChangingRecordingClock() async throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("notewise-rate-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let input = NoteWiseConfigurationTestCapture()
        let session = NoteWiseSession(input: input, recordingsDirectory: folder)
        let payload: [String: Any] = ["takeId": UUID().uuidString.lowercased(), "inputKind": "microphone",
            "tuning": 440.0, "instrument": "violin"]
        var interrupted = false
        session.event = { if $0["status"] as? String == "interrupted" { interrupted = true } }
        func submit(_ rate: Double) throws {
            let format = try XCTUnwrap(AVAudioFormat(commonFormat: .pcmFormatFloat32,
                sampleRate: rate, channels: 1, interleaved: false))
            let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(rate / 10)))
            buffer.frameLength = buffer.frameCapacity
            let samples = try XCTUnwrap(buffer.floatChannelData?[0])
            for index in 0..<Int(buffer.frameLength) { samples[index] = Float(.2 * sin(2 * Double.pi * 440 * Double(index) / rate)) }
            input.onPCM?(buffer, AVAudioTime(sampleTime: 0, atRate: rate))
        }
        let scope = "https://124.221.211.156|guest"
        _ = try await session.start(payload, scope: scope)
        try submit(44100)
        session.pause()
        _ = try await session.start(payload, scope: scope)
        try submit(48000)
        for _ in 0..<100 where !interrupted { try await Task.sleep(nanoseconds: 10_000_000) }
        XCTAssertTrue(interrupted, "Changed hardware PCM rate must interrupt, not corrupt the previous WAV clock")
        let result = await session.stop()
        XCTAssertEqual(result["sampleRate"] as? Double, 44100)
        XCTAssertEqual(result["sampleCount"] as? UInt64, 4410)
        XCTAssertEqual(result["interrupted"] as? Bool, true)
        let file = try session.recording(payload["takeId"] as! String, scope: scope)
        let recording = try AVAudioFile(forReading: file)
        XCTAssertEqual(recording.processingFormat.sampleRate, 44100)
        XCTAssertEqual(recording.length, 4410, "Only buffers from the original clock may be written")
    }
}

@MainActor private final class NoteWiseConfigurationTestCapture: NoteWiseCapturing {
    var onPCM: ((AVAudioPCMBuffer, AVAudioTime) -> Void)?
    var onMIDI: (([MIDIPerformanceEvent]) -> Void)?
    var onError: ((String) -> Void)?
    var starts = 0, stops = 0
    func start(_ mode: String) async throws { starts += 1 }
    func stop() { stops += 1 }
}
