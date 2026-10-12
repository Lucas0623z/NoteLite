import XCTest
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
}
