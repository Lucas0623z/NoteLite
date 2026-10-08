import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import wave
sys.path.insert(0,str(Path(__file__).parent))
from mono_analysis import analyze_mono, uncertain_frames
import numpy as np


class ActualEngineTest(unittest.TestCase):
    def test_real_basic_pitch_preserves_repeated_polyphonic_chords_after_evidence_processing(self):
        from analyze import analyze
        home=(Path(__file__).parent/"runtime").resolve();rate=22050;seconds=3
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"repeated-chords.wav"
            times=np.arange(rate*seconds)/rate
            envelope=np.full(len(times),.004)
            for onset in (.25,1.25):
                envelope += np.where((times>=onset)&(times<onset+.55),.16*np.minimum(1,np.maximum(0,(times-onset)/.01)),0)
            signal=sum(envelope*np.sin(2*np.pi*440*2**((midi-69)/12)*times) for midi in (60,64,67))
            with wave.open(str(path),"wb") as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate);wav.writeframes((signal*32767).astype('<i2').tobytes())
            result=analyze(path,home,{"engine":"basic-pitch"})
            notes=[n for n in result["notes"] if n["confidence"]>=.4 and not n.get("reviewRequired")]
            for midi in (60,64,67):
                attacks=[n for n in notes if n["midi"]==midi]
                self.assertEqual(2,len(attacks),(midi,notes))
                self.assertTrue(all(abs(n["onset"]-t)<.12 for n,t in zip(attacks,(.25,1.25))),attacks)
            self.assertTrue(result["postprocessing"]["rawNotesPreserved"])
            self.assertGreaterEqual(len(result["rawNotes"]),len(notes))

    def test_low_tuba_range_adapts_actual_pyin_window_without_55hz_cutoff(self):
        rate=48000;seconds=3
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"low.wav"
            with wave.open(str(path),"wb") as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate)
                times=np.arange(rate*seconds)/rate
                signal=np.where((times>=.5)&(times<2.3),.23*np.sin(2*np.pi*27.5*times),0)
                wav.writeframes((signal*32767).astype('<i2').tobytes())
            output=analyze_mono(path,Path(__file__).parent/"runtime",seconds,{"engine":"pyin","minHz":24,"maxHz":100})
            self.assertEqual(22050,output["configuration"]["sampleRate"])
            self.assertGreaterEqual(output["configuration"]["window"],4*22050/24)
            self.assertTrue(any(n["midi"]==21 and n["duration"]>1 for n in output["notes"]),output["notes"])
            self.assertLessEqual(output["supportedPitchRange"]["minMidi"],21)

    def test_low_confidence_audible_frames_are_uncertain_but_silence_is_not(self):
        times=np.arange(100)/100
        audio=np.zeros(1000);audio[300:700]=.1
        intervals=uncertain_frames(times,np.zeros(100),audio,1000,1,.5)
        self.assertEqual(1,len(intervals))
        self.assertGreater(intervals[0]["onset"],.25)
        self.assertLess(intervals[0]["onset"]+intervals[0]["duration"],.75)

    def test_real_pyin_and_official_crepe_cpu_measure_detuned_note_and_release(self):
        home=Path(__file__).parent/"runtime"
        self.assertTrue((home/"models/crepe-tiny.onnx").is_file(),"Install runtime before actual engine tests")
        rate=22050;seconds=3
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"detuned.wav"
            with wave.open(str(path),"wb") as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate)
                frames=bytearray()
                for k in range(rate*seconds):
                    time=k/rate
                    value=0 if not .5<=time<2.3 else .22*math.sin(2*math.pi*440*2**(.25/12)*(time-.5))
                    frames.extend(struct.pack('<h',round(value*32767)))
                wav.writeframes(frames)
            for engine in ("pyin","crepe"):
                result=analyze_mono(path,home,seconds,{"engine":engine,"a4":440,"minHz":100,"maxHz":1000})
                print(engine,json.dumps(result["notes"]))
                correct=[n for n in result["notes"] if n["midi"]==69 and n["duration"]>1]
                self.assertTrue(correct,engine)
                self.assertLess(abs(correct[0]["cents"]-25),12,engine)
                self.assertLess(abs(correct[0]["onset"]-.5),.15,engine)
                self.assertLess(abs(correct[0]["duration"]-1.8),.25,engine)


if __name__=="__main__":unittest.main()
