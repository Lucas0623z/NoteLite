import sys
import json
import subprocess
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).parent))
from score_tools import normalize, align, align_parangonar, align_nakamura

PREFIX = '<score-partwise version="3.1"><part-list><score-part id="P1"><part-name>Clarinet</part-name></score-part></part-list><part id="P1">'
SUFFIX = '</part></score-partwise>'
ATTR = '<attributes><divisions>1</divisions><time><beats>2</beats><beat-type>4</beat-type></time>{}</attributes>'
def note(step="C", duration=1, extra=""):
    return f'<note><pitch><step>{step}</step><octave>4</octave></pitch><duration>{duration}</duration><voice>1</voice><staff>1</staff>{extra}</note>'
def xml(body):return (PREFIX+body+SUFFIX).encode()


class ScoreToolsTest(unittest.TestCase):
    def test_real_short_context_subprocess_returns_promptly_without_fabricated_baseline(self):
        # Execute the real helper module in a fresh process: the former 1x1
        # upstream backtracking loop would hit this 15-second test deadline.
        notes=[{"sourceNoteId":"P1:0","occurrenceId":"P1:0@0","midi":60.0,"onset":0.0,"duration":4.0}]
        performance=[{"midi":60.0,"onset":.007333,"duration":1.14,"confidence":.999848}]
        source=str(Path(__file__).parent.resolve())
        script=f"import sys,json;sys.path.insert(0,{source!r});from score_tools import align;from pathlib import Path;p=json.loads(sys.stdin.read());print(json.dumps(align(p,Path('.'))))"
        for backend in ("parangonar","nakamura"):
            for score,actual in ((notes,performance),
                                 (notes+[notes[0]|{"sourceNoteId":"P1:1","occurrenceId":"P1:1@0","midi":64.0}],performance),
                                 (notes,performance+[performance[0]|{"midi":64.0}])):
                with self.subTest(backend=backend,scoreNotes=len(score),performanceNotes=len(actual)):
                    completed=subprocess.run([sys.executable,"-c",script],input=json.dumps({"score":{"notes":score},"performance":actual,"options":{"backend":backend}}),text=True,capture_output=True,timeout=15,check=True)
                    result=json.loads(completed.stdout)
                    self.assertFalse(result["metadata"]["evaluated"])
                    self.assertEqual("insufficient-context",result["metadata"]["reason"])
                    self.assertEqual([],result["pairs"]);self.assertEqual([],result["missing"]);self.assertEqual([],result["extra"])
                    self.assertTrue(result["warnings"])

    @unittest.skipUnless((Path(__file__).parent/"runtime/native/nakamura/SprToFmt3x.exe").is_file(), "Install both actual baselines")
    def test_saved_json_float_roundtrip_uses_real_partitura_and_both_baselines(self):
        data=xml('<measure number="1">'+ATTR.replace('<beats>2</beats>','<beats>6</beats>').format('')
                 +''.join(note(step) for step in ('C','D','E','F','G','A'))+'</measure>')
        score=normalize(data,{"from":1.0,"to":1.0,"expandRepeats":False})
        performance=[{"midi":pitch,"onset":time,"duration":.4,"confidence":.9,"cents":12.75}
                     for pitch,time in [(60,2),(62,2.7),(70,3),(65,4.3),(67,5.1),(69,6.3)]]
        # This reproduces Java's saved JSON number representation, including
        # MIDI, source ordinals and occurrence indexes encoded as 60.0/0.0.
        payload=json.loads(json.dumps({"score":score,"performance":performance}),parse_int=float)
        original=json.dumps(payload,sort_keys=True)
        home=(Path(__file__).parent/"runtime").resolve()
        for backend in ("parangonar","nakamura"):
            with self.subTest(backend=backend):
                result=align(payload|{"options":{"backend":backend}},home)
                self.assertTrue(result["metadata"]["evaluated"])
                self.assertEqual(backend,result["engine"])
                self.assertTrue(all(isinstance(p["detectionIndex"],int) for p in result["pairs"]))
                self.assertEqual({"P1:0@0","P1:1@0","P1:3@0","P1:4@0","P1:5@0"},
                                 {p["occurrenceId"] for p in result["pairs"] if p["occurrenceId"]!="P1:2@0"})
                if backend=="parangonar":
                    self.assertIn("P1:2@0",result["missing"]);self.assertIn(2,result["extra"])
                else:
                    substitution=next(p for p in result["pairs"] if p["occurrenceId"]=="P1:2@0")
                    self.assertEqual(70.0,payload["performance"][substitution["detectionIndex"]]["midi"])
        self.assertEqual(original,json.dumps(payload,sort_keys=True))
        self.assertIsInstance(payload["score"]["notes"][0]["midi"],float)
        self.assertEqual(12.75,payload["performance"][0]["cents"])

    def test_fractional_or_nonfinite_identity_is_rejected_without_truncation(self):
        note_row={"id":"P1:0","midi":60.0,"onset":0.0,"duration":.75}
        for backend in ("parangonar","nakamura"):
            for midi in (60.5,-1,128,float('nan'),float('inf'),True):
                with self.subTest(backend=backend,midi=midi):
                    payload={"score":{"notes":[note_row|{"midi":midi}]},"performance":[note_row],"options":{"backend":backend}}
                    with self.assertRaisesRegex(ValueError,"midi must be an integer"):
                        align(payload,Path(__file__).parent/"runtime")
            with self.assertRaisesRegex(ValueError,"mi must be an integer"):
                align({"score":{"notes":[note_row|{"mi":.5}]},"performance":[note_row],"options":{"backend":backend}},Path(__file__).parent/"runtime")
        with self.assertRaisesRegex(ValueError,"from must be an integer"):
            normalize(xml('<measure number="1">'+ATTR.format('')+note("C",2)+'</measure>'),{"from":1.5})

    def test_local_omr_list_metadata_blocks_playback_piano_without_confirmation(self):
        data=xml('<measure number="1">'+ATTR.format('')+note("C",2)+'</measure>')
        result=normalize(data,{"metadata":{"origin":"local-omr","parts":[{"id":"P1","name":"Piano","program":1,"confirmed":False}]}})
        self.assertFalse(result["parts"][0]["reliable"])
        self.assertEqual("auto",result["parts"][0]["instrument"])
        manual=normalize(data,{"instrument":"piano","metadata":{"origin":"local-omr","parts":[{"id":"P1","confirmed":False}]}})
        self.assertTrue(manual["parts"][0]["reliable"])

    def test_imported_named_part_is_inferred_without_automatic_transposition(self):
        result=normalize(xml('<measure number="1">'+ATTR.format('')+note("C",2)+'</measure>'),{})
        self.assertEqual("clarinet",result["parts"][0]["instrument"])
        self.assertTrue(result["parts"][0]["reliable"])
        self.assertEqual(60,result["notes"][0]["midi"])

    def test_actual_partitura_unfold_preserves_xml_ordinals_including_rest(self):
        data=xml('<measure number="1">'+ATTR.format('')+'<barline location="left"><repeat direction="forward"/></barline><note><rest/><duration>1</duration></note>'+note()+'<barline location="right"><repeat direction="backward"/></barline></measure><measure number="2">'+note("D",2)+'</measure>')
        result=normalize(data,{"byPart":{"P1":{"instrument":"clarinet","variant":"bb"}}})
        self.assertEqual(["P1:1","P1:1","P1:2"],[n["sourceNoteId"] for n in result["notes"]])
        self.assertEqual(["P1:1@0","P1:1@1","P1:2@0"],[n["occurrenceId"] for n in result["notes"]])
        self.assertEqual([1,3,4],[n["onset"] for n in result["notes"]])
        self.assertEqual([58,58,60],[n["midi"] for n in result["notes"]])
        self.assertEqual([0,0,1],[n["mi"] for n in result["notes"]])

    def test_explicit_xml_transposition_is_not_applied_twice_by_manual_variant(self):
        data=xml('<measure number="1">'+ATTR.format('<transpose><diatonic>-1</diatonic><chromatic>-2</chromatic></transpose>')+note("C",2)+'</measure>')
        result=normalize(data,{"byPart":{"P1":{"instrument":"clarinet","variant":"a"}}})
        self.assertEqual(58,result["notes"][0]["midi"]);self.assertEqual(60,result["notes"][0]["writtenMidi"])
        self.assertTrue(result["notes"][0]["transposeExplicit"])

    def test_ties_use_source_attack_id_and_combined_duration(self):
        data=xml('<measure number="1">'+ATTR.format('')+note("C",2,'<tie type="start"/>')+'</measure><measure number="2">'+note("C",2,'<tie type="stop"/>')+'</measure>')
        result=normalize(data,{"expandRepeats":False})
        self.assertEqual(1,len(result["notes"]));self.assertEqual(4,result["notes"][0]["duration"])
        self.assertEqual("P1:0",result["notes"][0]["sourceNoteId"])

    def test_actual_parangonar_matches_variable_tempo_and_survives_missing_inserted_attacks(self):
        notes=[{"sourceNoteId":f"P1:{i}","occurrenceId":f"P1:{i}@0","midi":pitch,"onset":i,"duration":.8} for i,pitch in enumerate([60,62,64,65,67,69])]
        performance=[{"midi":pitch,"onset":time,"duration":.4,"confidence":.9} for pitch,time in [(60,2),(62,2.7),(70,3),(65,4.3),(67,5.1),(69,6.3)]]
        result=align_parangonar(notes,performance)
        self.assertEqual("DualDTWNoteMatcher",result["metadata"]["algorithm"])
        self.assertIn("P1:2@0",result["missing"]);self.assertIn(2,result["extra"])
        self.assertEqual(5,len(result["pairs"]))

    @unittest.skipUnless((Path(__file__).parent/"runtime/native/nakamura/SprToFmt3x.exe").is_file(),"Install the native Nakamura baseline")
    def test_actual_nakamura_preserves_wrong_pitch_as_a_substitution_without_changing_detection(self):
        notes=[{"sourceNoteId":f"P1:{i}","occurrenceId":f"P1:{i}@0","midi":pitch,"onset":i,"duration":.8} for i,pitch in enumerate([60,62,64,65,67,69])]
        performance=[{"midi":pitch,"onset":time,"duration":.4,"confidence":.9} for pitch,time in [(60,2),(62,2.7),(70,3),(65,4.3),(67,5.1),(69,6.3)]]
        result=align_nakamura(notes,performance,(Path(__file__).parent/"runtime").resolve())
        self.assertTrue(result["metadata"]["evaluated"])
        self.assertEqual(6,len(result["pairs"]))
        replacement=next(p for p in result["pairs"] if p["occurrenceId"]=="P1:2@0")
        # Nakamura calls this a pitch substitution; the common grader must
        # inspect actual MIDI and cannot treat every correspondence as correct.
        self.assertEqual(70,performance[replacement["detectionIndex"]]["midi"])
        self.assertEqual(64,notes[2]["midi"])


if __name__ == "__main__":unittest.main()
