import sys
import json
import os
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


RUNTIME_HOME=Path(os.environ.get("NOTELITE_TEST_ANALYSIS_HOME",str(Path(__file__).parent/"runtime")))


class ScoreToolsTest(unittest.TestCase):
    def test_concert_score_and_manual_override_confirm_without_double_transposition(self):
        data=xml('<measure number="1">'+ATTR.format('')+note("C",2)+'</measure>')
        concert=data.replace(b'<part-list>',b'<defaults><concert-score/></defaults><part-list>')
        for options in ({},{"instrument":"clarinet","variant":"bb","transpose":-7}):
            result=normalize(concert,options)
            self.assertEqual(60,result["notes"][0]["midi"])
            self.assertTrue(result["notes"][0]["transposeExplicit"])
            self.assertTrue(result["parts"][0]["transpositionConfirmed"])
        for options in ({"instrument":"auto","transpose":0},{"byPart":{"P1":{"instrument":"auto","transpose":-2}}}):
            result=normalize(data,options)
            self.assertEqual(60 if "transpose" in options else 58,result["notes"][0]["midi"])
            self.assertTrue(result["parts"][0]["transpositionConfirmed"])
        for explicit in (concert,data.replace(b'</attributes>',b'<transpose><chromatic>0</chromatic></transpose></attributes>')):
            with self.assertRaisesRegex(ValueError,"Unknown instrument notation variant"):
                normalize(explicit,{"instrument":"clarinet","variant":"invalid"})

    def test_score_instrument_abbreviation_and_unknown_playback_piano_do_not_erase_identity(self):
        body='<measure number="1">'+ATTR.format('<transpose><chromatic>0</chromatic></transpose>')+note("C",2,'<instrument id="I1"/>')+'</measure>'
        head='<score-partwise><part-list><score-part id="P1"><part-name>Part 1</part-name><score-instrument id="I1"><instrument-name>Mystery reed</instrument-name>{}</score-instrument><midi-instrument id="I1"><midi-program>1</midi-program></midi-instrument></score-part></part-list><part id="P1">'
        unknown=normalize((head.format('')+body+SUFFIX).encode(),{})
        self.assertFalse(unknown["parts"][0]["reliable"])
        named=normalize((head.format('<instrument-abbreviation>Fl.</instrument-abbreviation>')+body+SUFFIX).encode(),{})
        self.assertEqual('flute',named["parts"][0]["instrument"])
        self.assertTrue(named["parts"][0]["reliable"])
        heading=(head.format('').replace('<part-name>Part 1</part-name>','<part-name>Flute</part-name>').replace('Mystery reed','Acoustic Grand Piano')+body.replace('<instrument id="I1"/>','')+SUFFIX).encode()
        self.assertEqual('flute',normalize(heading,{})["parts"][0]["instrument"])

    def test_selected_note_instrument_catalog_and_xml_references_are_retained(self):
        head='<score-partwise><part-list><score-part id="P1"><part-name>Wind</part-name><score-instrument id="I1"><instrument-name>Flute</instrument-name></score-instrument><score-instrument id="I2"><instrument-name>Clarinet</instrument-name></score-instrument></score-part></part-list><part id="P1">'
        body='<measure number="1">'+ATTR.format('<transpose><chromatic>0</chromatic></transpose>')+note("C",1,'<instrument id="I1"/>')+note("D",1,'<instrument id="I2"/>')+'</measure>'
        result=normalize((head+body+SUFFIX).encode(),{"expandRepeats":False})
        self.assertEqual([["I1"],["I2"]],[n["instrumentIds"] for n in result["notes"]])
        self.assertEqual(["flute","clarinet"],[n["resolvedInstrumentId"] for n in result["notes"]])
        self.assertEqual(["flute","clarinet"],result["parts"][0]["instrumentIds"])
        self.assertTrue(result["parts"][0]["instrumentMappingResolved"])
        self.assertTrue(result["parts"][0]["transpositionConfirmed"])
        missing=normalize((head+body.replace('<instrument id="I2"/>','')+SUFFIX).encode(),{})
        self.assertFalse(missing["parts"][0]["reliable"])
        self.assertIn("instrument-mapping-unresolved",missing["parts"][0]["requiresConfirmation"])

    def test_automatic_transposing_instrument_requires_notation_confirmation(self):
        data=xml('<measure number="1">'+ATTR.format('')+note("C",2)+'</measure>')
        result=normalize(data,{})
        self.assertTrue(result["parts"][0]["reliable"])
        self.assertFalse(result["parts"][0]["transpositionConfirmed"])
        self.assertIn("transposition-unconfirmed",result["parts"][0]["requiresConfirmation"])
        manual=normalize(data,{"instrument":"clarinet","variant":"bb"})
        self.assertTrue(manual["parts"][0]["transpositionConfirmed"])
        self.assertEqual(58,manual["notes"][0]["midi"])
        unknown=normalize(data,{"instrument":"drumkit"})
        self.assertFalse(unknown["parts"][0]["reliable"])

    def test_exact_general_midi_keyboard_and_reed_programs_are_resolved(self):
        clavi=xml('<measure number="1">'+ATTR.format('')+note("C",2)+'</measure>').replace(b'<part-name>Clarinet</part-name>',b'<part-name>Clavi</part-name>')
        self.assertEqual('clavinet',normalize(clavi,{})["parts"][0]["instrument"])
        for program,instrument in ((7,"harpsichord"),(8,"clavinet"),(22,"accordion"),(24,"accordion")):
            data=xml('<measure number="1">'+ATTR.format('')+note("C",2)+'</measure>').decode().replace('<part-name>Clarinet</part-name>',
                f'<part-name>Part 1</part-name><midi-instrument id="I1"><midi-program>{program}</midi-program></midi-instrument>')
            with self.subTest(program=program):self.assertEqual(instrument,normalize(data.encode(),{})["parts"][0]["instrument"])

    def test_added_notation_variants_and_selected_scope_have_actual_sound_pitches(self):
        data=xml('<measure number="1">'+ATTR.format('')+note("C",2)+'</measure>')
        for instrument,variant,pitch in (("guitar","octave",48),("piccolo","octave",72),("english-horn","f",53),("sax","eb-alto",51)):
            with self.subTest(instrument=instrument):
                result=normalize(data,{"instrument":instrument,"variant":variant})
                self.assertEqual(pitch,result["notes"][0]["midi"]);self.assertTrue(result["parts"][0]["transpositionConfirmed"])
        for instrument,pitch in (("contrabass",48),("euphonium",60)):
            with self.subTest(defaultVariant=instrument):
                result=normalize(data,{"instrument":instrument})
                self.assertEqual(pitch,result["notes"][0]["midi"])

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

    @unittest.skipUnless((RUNTIME_HOME/"native/nakamura/SprToFmt3x.exe").is_file(), "Install both actual baselines")
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
        home=RUNTIME_HOME.resolve()
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
                        align(payload,RUNTIME_HOME)
            with self.assertRaisesRegex(ValueError,"mi must be an integer"):
                align({"score":{"notes":[note_row|{"mi":.5}]},"performance":[note_row],"options":{"backend":backend}},RUNTIME_HOME)
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

    @unittest.skipUnless((RUNTIME_HOME/"native/nakamura/SprToFmt3x.exe").is_file(),"Install the native Nakamura baseline")
    def test_actual_nakamura_preserves_wrong_pitch_as_a_substitution_without_changing_detection(self):
        notes=[{"sourceNoteId":f"P1:{i}","occurrenceId":f"P1:{i}@0","midi":pitch,"onset":i,"duration":.8} for i,pitch in enumerate([60,62,64,65,67,69])]
        performance=[{"midi":pitch,"onset":time,"duration":.4,"confidence":.9} for pitch,time in [(60,2),(62,2.7),(70,3),(65,4.3),(67,5.1),(69,6.3)]]
        result=align_nakamura(notes,performance,RUNTIME_HOME.resolve())
        self.assertTrue(result["metadata"]["evaluated"])
        self.assertEqual(6,len(result["pairs"]))
        replacement=next(p for p in result["pairs"] if p["occurrenceId"]=="P1:2@0")
        # Nakamura calls this a pitch substitution; the common grader must
        # inspect actual MIDI and cannot treat every correspondence as correct.
        self.assertEqual(70,performance[replacement["detectionIndex"]]["midi"])
        self.assertEqual(64,notes[2]["midi"])


if __name__ == "__main__":unittest.main()
