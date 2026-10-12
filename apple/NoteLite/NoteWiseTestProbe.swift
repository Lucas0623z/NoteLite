#if DEBUG
import Foundation
/// Unit-test entry through the same C wrapper used by actual microphone capture.
enum NoteWiseTestProbe {
    static func detect(_ samples:[Float],rate:Double=48000,a4:Double=440) throws -> [[String:Any]] {
        guard let dsp=nw_create(rate,a4,27.5,5000) else { throw NoteLiteError.invalidResponse }
        defer{nw_destroy(dsp)}
        var results:[[String:Any]]=[]
        func drain(){var value=nl_note_event();while nw_poll(dsp,&value) != 0 {results.append(["type":String(cString:value.type),"reason":String(cString:value.reason),"midi":Int(value.midi),"onsetMs":value.onset_ms,"timeMs":value.time_ms,"cents":value.cents,"confidence":value.confidence])}}
        for offset in stride(from:0,to:samples.count,by:4096){let block=Array(samples[offset..<min(offset+4096,samples.count)]);block.withUnsafeBufferPointer{nw_push(dsp,$0.baseAddress,$0.count)};drain()}
        nw_finish(dsp);drain();return results
    }
}
#endif
