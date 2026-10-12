"""Fusion arbitration regressions; real-model checks opt in with an installed runtime."""
import copy
import json
import math
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import wave

from analyze import analyze
from fusion import analyze_fusion, arbitrate_mono, plan_recording, profile_registry


def part(instrument="flute"):
    return {"id":"P1","instrument":instrument,"reliable":True,"transpositionConfirmed":True,
            "instrumentMappingResolved":True,"instrumentIds":[instrument],"requiresConfirmation":[]}


def note(midi=69,onset=.5,duration=1,confidence=.9,cents=0):
    return {"midi":midi,"onset":onset,"duration":duration,"confidence":confidence,"cents":cents}


def transcript(engine,notes):
    return {"schemaVersion":1,"engine":engine,"seconds":3,"notes":notes,"rawNotes":copy.deepcopy(notes),"uncertaintyIntervals":[]}


class FusionTest(unittest.TestCase):
    def test_registry_routes_keyboard_plucked_and_actual_overlap_without_expected_pitches(self):
        self.assertEqual(35,len(profile_registry()["profiles"]))
        for instrument,poly,primary in (("piano",False,"basic-pitch"),("guitar",False,"basic-pitch"),
            ("flute",False,"pyin"),("violin",True,"basic-pitch"),("voice",False,"pyin")):
            with self.subTest(instrument=instrument,poly=poly):
                plan=plan_recording([part(instrument)],poly)
                self.assertEqual(primary,plan["primary"]);self.assertEqual([],plan["requiresConfirmation"])
                self.assertNotIn("notes",plan)

    def test_unconfirmed_unknown_notation_and_multiple_sources_are_blocked(self):
        for selected in ([part("not-a-profile")],[part()|{"reliable":False}],
                         [part("clarinet")|{"transpositionConfirmed":False}],
                         [part("flute"),part("violin")|{"id":"P2"}]):
            with self.subTest(parts=selected),self.assertRaisesRegex(ValueError,"Confirm"):
                plan_recording(selected,False)

    def test_sequential_explicit_same_family_changes_union_ranges_but_mixes_do_not(self):
        selected=part()|{"instrumentIds":["flute","clarinet"]}
        plan=plan_recording([selected],False)
        self.assertEqual(["flute","clarinet"],plan["instrumentIds"]);self.assertEqual(34,plan["minMidi"])
        self.assertTrue(plan["diagnostics"])
        for actual in ([selected|{"instrumentMappingResolved":False}],[selected|{"instrumentIds":["flute","violin"]}]):
            with self.assertRaises(ValueError):plan_recording(actual,False)
        with self.assertRaises(ValueError):plan_recording([selected],True)

    def test_conflicting_detector_pitch_never_replaced_by_expected_score(self):
        primary=transcript("pyin",[note(69)]);validator=transcript("crepe",[note(70)])
        actual,decisions,uncertainty=arbitrate_mono(primary,validator,"evaluated",440)
        self.assertEqual(69,actual[0]["midi"]);self.assertTrue(actual[0]["reviewRequired"])
        self.assertEqual("detector-disagreement",decisions[0]["reason"]);self.assertTrue(uncertainty)
        self.assertNotIn("reviewRequired",primary["notes"][0])

    def test_agreement_keeps_original_confidence_and_held_note_cannot_confirm_reattack(self):
        primary=transcript("pyin",[note(onset=.5,duration=.15,confidence=.81),note(onset=.65,duration=.6,confidence=.82)])
        validator=transcript("crepe",[note(onset=.5,duration=.9,confidence=.96,cents=45)])
        actual,decisions,_=arbitrate_mono(primary,validator,"evaluated",440)
        self.assertEqual("agreement",decisions[0]["status"]);self.assertEqual(.81,actual[0]["confidence"])
        self.assertTrue(actual[1]["reviewRequired"]);self.assertEqual(.82,actual[1]["confidence"])

    def test_missing_validator_marks_in_range_uncertain_but_low_bass_is_not_negative(self):
        primary=transcript("pyin",[note(21),note(69,onset=1.6,duration=.8)])
        actual,decisions,uncertainty=arbitrate_mono(primary,None,"unavailable",440)
        self.assertEqual("primary-only",decisions[0]["status"]);self.assertNotIn("reviewRequired",actual[0])
        self.assertTrue(actual[1]["reviewRequired"]);self.assertEqual(1,len(uncertainty))

    def test_primary_missing_fails_without_running_or_inventing_detector(self):
        with patch("fusion.runtime_capabilities",return_value={"pyin":False}),self.assertRaisesRegex(ValueError,"primary detector"):
            analyze_fusion(Path("unused.wav"),Path("."),3,{"normalizedParts":[part()],"polyphonic":False},
                           lambda *args:self.fail("Missing detector must not run"))

    def test_fusion_passes_only_acoustic_scalars_and_discloses_unavailable_validator(self):
        received=[]
        def detector(path,home,options):received.append(options);return transcript("pyin",[note()])
        with patch("fusion.runtime_capabilities",return_value={"pyin":True,"crepe":False}):
            report=analyze_fusion(Path("unused.wav"),Path("."),3,
                {"normalizedParts":[part()],"polyphonic":False,"expectedMidi":69,"scoreNotes":[note()]},detector)
        self.assertEqual(1,len(received));self.assertNotIn("expectedMidi",received[0]);self.assertNotIn("scoreNotes",received[0])
        self.assertEqual("notewise-fusion",report["engine"]);self.assertTrue(report["notes"][0]["reviewRequired"])
        self.assertEqual("unavailable",report["fusion"]["validatorStatus"]);self.assertEqual([note()],report["rawNotes"])

    def test_missing_confidence_and_poly_without_waveform_attack_are_not_success(self):
        with patch("fusion.runtime_capabilities",return_value={"basic-pitch":True}):
            options={"normalizedParts":[part("piano")],"polyphonic":True}
            weak=note();del weak["confidence"]
            with self.assertRaisesRegex(ValueError,"acoustic note"):
                analyze_fusion(Path("unused.wav"),Path("."),3,options,lambda *args:transcript("basic-pitch",[weak]))
            report=analyze_fusion(Path("unused.wav"),Path("."),3,options,lambda *args:transcript("basic-pitch",[note()]))
            self.assertTrue(report["notes"][0]["reviewRequired"]);self.assertTrue(report["uncertaintyIntervals"])


class ActualRuntimeFusionTest(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("NOTELITE_TEST_ANALYSIS_HOME"),"Set actual installed runtime for acoustic fusion tests")
    def test_actual_mono_low_bass_poly_and_silence(self):
        home=Path(os.environ["NOTELITE_TEST_ANALYSIS_HOME"])
        cases=(("mono",[440*2**(.25/12)],"flute",False),("low",[27.5],"tuba",False),
               ("poly",[261.6256,329.6276,391.9954],"piano",True),("silence",[],"flute",False),
               ("silence-poly",[],"piano",True))
        with tempfile.TemporaryDirectory() as directory:
            for label,frequencies,instrument,poly in cases:
                with self.subTest(label=label):
                    rate=22050;duration=3;path=Path(directory)/(label+".wav")
                    samples=[]
                    for i in range(rate*duration):
                        t=i/rate;envelope=min(1,max(0,(t-.5)/.015),max(0,(2.3-t)/.03))
                        value=envelope*sum(math.sin(2*math.pi*f*t) for f in frequencies)/max(1,len(frequencies))*.45
                        samples.append(round(value*32767))
                    with wave.open(str(path),"wb") as wav:
                        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate);wav.writeframes(struct.pack("<"+"h"*len(samples),*samples))
                    report=analyze(path,home,{"engine":"notewise-fusion","normalizedParts":[part(instrument)],"polyphonic":poly,"verified":True,"input":"recording"})
                    self.assertEqual("notewise-fusion",report["engine"])
                    self.assertFalse(report["fusion"]["expectedScoreNotesUsedByDetectors"])
                    if label.startswith("silence"):self.assertEqual([],report["notes"])
                    else:self.assertTrue(report["notes"])
                    if label=="low":
                        bass=next(n for n in report["notes"] if n["midi"]==21)
                        self.assertEqual("outside-validator-safe-range",bass["fusionDecision"]["reason"])
                        self.assertNotIn("reviewRequired",bass)
                    if label=="mono":self.assertTrue(any(n["midi"]==69 and n["fusionDecision"]["status"]=="agreement" for n in report["notes"]))
                    if label=="poly":self.assertEqual({60,64,67},{n["midi"] for n in report["notes"]})


if __name__=="__main__":unittest.main()
