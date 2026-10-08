import copy
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).parent))
from onset_evidence import AcousticOnsets,gate_candidates,merge_basic_pitch
from mono_analysis import frames_to_notes


class AcousticEvidenceTest(unittest.TestCase):
    rate=48000

    def signal(self,kind='steady',seconds=2,chord=(60,)):
        times=np.arange(round(self.rate*seconds))/self.rate
        if kind=='crescendo':amplitude=.15+.6*times/seconds
        elif kind=='repeat':amplitude=.07+.38*np.exp(-(times%.125)/.028)
        else:amplitude=np.full(len(times),.22)
        audio=np.zeros(len(times))
        for midi in chord:
            frequency=440*2**((midi-69)/12)
            if kind=='vibrato':
                instantaneous=frequency*2**(.45*np.sin(2*np.pi*6*times)/12)
                phase=2*np.pi*np.cumsum(instantaneous)/self.rate
            else:phase=2*np.pi*frequency*times
            audio+=amplitude*np.sin(phase)/len(chord)
        return times,audio

    def test_steady_crescendo_and_frequency_vibrato_do_not_create_second_attacks(self):
        frame_times=np.arange(200)*.01;frequency=np.full(200,261.625565)
        candidates=[.25,.5,.8,1.1,1.5]
        for kind in ('steady','crescendo','vibrato'):
            _,audio=self.signal(kind)
            current_frequency=frequency*2**(.45*np.sin(2*np.pi*6*frame_times)/12) if kind=='vibrato' else frequency
            qualified,evidence=gate_candidates(audio,self.rate,candidates,frame_times,current_frequency)
            self.assertEqual([],qualified,(kind,evidence))
            raw=frames_to_notes(frame_times,current_frequency,np.ones(200),2,engine='test',onsets=candidates)
            cooked=frames_to_notes(frame_times,current_frequency,np.ones(200),2,engine='test',onsets=qualified)
            self.assertGreater(len(raw),1);self.assertEqual(1,len(cooked))

    def test_125ms_repeated_attacks_without_digital_silence_are_not_debounced(self):
        _,audio=self.signal('repeat',seconds=.8)
        # The floor remains audible throughout, unlike a silence-based splitter.
        self.assertGreater(min(np.sqrt(np.mean(block**2)) for block in np.array_split(audio,80)),.01)
        times=np.arange(80)*.01;frequency=np.full(80,261.625565)
        candidates=[.125*i for i in range(1,6)]
        qualified,evidence=gate_candidates(audio,self.rate,candidates,times,frequency)
        self.assertEqual(candidates,qualified,evidence)

    def test_basic_pitch_fragments_merge_without_mutating_original_bends(self):
        _,audio=self.signal('vibrato')
        notes=[{'midi':60,'modelMidi':60,'onset':t,'duration':.3,'confidence':.8,'pitchBendCents':[0,33.333,0]} for t in (.2,.5,.8)]
        snapshot=copy.deepcopy(notes)
        cooked,raw,proof=merge_basic_pitch(notes,audio,self.rate)
        self.assertEqual(snapshot,notes);self.assertEqual(snapshot,raw)
        self.assertEqual(1,len(cooked));self.assertAlmostEqual(.9,cooked[0]['duration'])
        self.assertEqual([0,1,2],cooked[0]['rawNoteIndices']);self.assertEqual(2,len(proof['mergedSamePitchFragments']))

    def test_repeated_chords_keep_all_attacks_without_digital_silence(self):
        _,audio=self.signal('repeat',seconds=.8,chord=(60,64,67))
        notes=[{'midi':midi,'modelMidi':midi,'onset':i*.125,'duration':.125,'confidence':.9,'pitchBendCents':[0,0]}
               for i in range(6) for midi in (60,64,67)]
        cooked,raw,proof=merge_basic_pitch(notes,audio,self.rate)
        self.assertEqual(18,len(raw));self.assertEqual(18,len(cooked),proof)
        self.assertFalse(any(n.get('reviewRequired') for n in cooked),proof)
        self.assertFalse(proof['mergedSamePitchFragments'])


if __name__=='__main__':unittest.main()
