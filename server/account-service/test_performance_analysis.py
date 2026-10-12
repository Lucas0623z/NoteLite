"""Real score-bound measurements, denominators, immutable versions and fact scope."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import uuid

import account_service as accounts
import performance_analysis as music
import practice_analysis as interpretation
from test_practice_analysis import Provider

FIXTURE = json.loads((Path(__file__).parent / "fixtures/notewise-v2.json").read_text(encoding="utf8"))


def report(xml=accounts.SAMPLE_XML, count=4, wrong=(), offset=150, take_id=None):
    take_id = take_id or str(uuid.uuid4())
    value = deepcopy(FIXTURE)
    value.update(takeId=take_id, eventId=take_id, sourceScoreSha256=hashlib.sha256(xml.encode()).hexdigest(), status="analysed", performanceDurationMs=count*1000+offset+100)
    attempt = take_id + ":1"
    value["attempts"] = [{"attemptId": attempt, "startMs": 0, "endMs": value["performanceDurationMs"], "interrupted": False}]
    value["expected"], value["actualEvents"], value["opportunities"] = [], [], []
    for index in range(count):
        step, midi = [("C",60), ("D",62), ("E",64), ("F",65)][index % 4]
        note_id = f"P1:{index//4}:{index%4}"
        occurrence = note_id + "@1"
        note = {"partId":"P1", "measureIndex":index//4,"noteIndex":index%4,"sourceNoteId":note_id,"occurrenceId":occurrence,"occurrenceOrdinal":1,"midi":midi,"writtenMidi":midi,"step":step,"alter":0,"octave":4,"transpose":0,"voice":"1","staff":"1","startMs":index*1000,"durationMs":1000,"onsetBeat":index,"durationBeat":1}
        value["expected"].append(note)
        event_id = f"midi-{index+1}"
        for kind, time in (("on",index*1000+offset), ("off",(index+1)*1000+offset)):
            value["actualEvents"].append({"eventId":event_id,"type":kind,"midi":midi+1 if index in wrong else midi,"timeMs":time,"confidence":1,"timingConfidence":1,"centsEvidence":"none",**({"releaseReliable":True} if kind=="off" else {})})
        op = deepcopy(FIXTURE["opportunities"][0])
        op.update(opportunityId=f"{attempt}:{occurrence}:{midi}", attemptId=attempt,occurrenceId=occurrence,sourceNoteIds=[note_id],expectedMidi=midi,actualEventIds=[event_id],measureIndex=index//4,noteIndex=index%4,onsetBeat=index)
        value["opportunities"].append(op)
    value["captureClock"]["phaseAnchor"] = "midi-1"
    return value


def normalize(value, xml=accounts.SAMPLE_XML):
    return music.normalize_performance(value, xml, hashlib.sha256(xml.encode()).hexdigest(), 1, "strict")


class NormalizationTests(unittest.TestCase):
    def test_service_variants_match_all_35_canonical_profiles_without_client_execution(self):
        # Parse the committed data snapshot only. No JS import, eval or runtime
        # subprocess is allowed when validating client-reported evidence.
        snapshot = json.loads((Path(__file__).resolve().parents[2] / "apple/NoteLite/NoteWiseProfiles.json").read_text(encoding="utf-8"))
        self.assertEqual(snapshot["schemaVersion"], 1)
        self.assertEqual(len(snapshot["profiles"]), 35)
        expected = {}
        for profile in snapshot["profiles"]:
            self.assertNotIn(profile["id"], expected)
            variants = {}
            for variant in profile["variants"]:
                self.assertNotIn(variant["id"], variants)
                self.assertIs(type(variant["transpose"]), int)
                variants[variant["id"]] = variant["transpose"]
            expected[profile["id"]] = variants
        self.assertEqual(music.INSTRUMENT_VARIANTS, expected)

    def test_added_instrument_choices_are_score_bound_and_keep_concert_compatibility(self):
        additions = [("clavinet", "concert", 0), ("english-horn", "f", -7),
                     ("piccolo", "octave", 12), ("guitar", "octave", -12), ("bass", "octave", -12),
                     ("sax", "bb-soprano", -2), ("sax", "eb-alto", -9),
                     ("sax", "bb-tenor", -14), ("sax", "eb-baritone", -21)]
        for profile, variant, semitones in additions + [(p, "concert", 0) for p in {p for p, _, _ in additions}]:
            with self.subTest(profile=profile, variant=variant):
                raw = report()
                raw["instrument"] = {"profileId": profile, "variant": variant, "transpose": semitones, "source": "manual"}
                for note, op in zip(raw["expected"], raw["opportunities"]):
                    note.update(midi=note["writtenMidi"] + semitones, transpose=semitones, transposeExplicit=False)
                    op["expectedMidi"] += semitones
                for event in raw["actualEvents"]:
                    event["midi"] += semitones
                result = normalize(raw)
                self.assertEqual(result["schemaVersion"], 2)
                self.assertEqual(result["expected"][0]["midi"], 60 + semitones)
                self.assertEqual(result["coverageByDimension"]["pitch"]["failed"], 0)
                self.assertFalse(result["verifiedByServer"])
                self.assertEqual(normalize(result), result)
                raw["instrument"]["transpose"] = semitones + 1
                with self.assertRaises(ValueError): normalize(raw)
                raw["instrument"].update(variant="undeclared-variant", transpose=semitones)
                with self.assertRaises(ValueError): normalize(raw)
                explicit = accounts.SAMPLE_XML.replace('</divisions>', '</divisions><transpose><chromatic>0</chromatic></transpose>')
                raw = report(explicit)
                raw["instrument"] = {"profileId": profile, "variant": variant, "transpose": semitones, "source": "manual"}
                for note in raw["expected"]:
                    note["transposeExplicit"] = True
                self.assertEqual(normalize(raw, explicit)["expected"][0]["midi"], 60, "explicit concert XML must not be double-transposed")

    def test_correct_nonzero_capture_offset_denominators_and_actual_tempo(self):
        value = normalize(report(offset=3500))
        self.assertEqual(value["coverageByDimension"]["pitch"], {"eligible":4,"evaluated":4,"failed":0,"pending":0})
        self.assertEqual(value["coverageByDimension"]["onset"]["failed"], 0)
        self.assertEqual(value["coverageByDimension"]["duration"]["evaluated"], 4)
        self.assertEqual(value["coverageByDimension"]["intonation"]["evaluated"], 0)
        self.assertEqual(value["serverMetrics"]["actualTempoQuarterBpm"], 60)
        self.assertFalse(value["verifiedByServer"])
        self.assertTrue(value["snapshotValidatedByServer"])

    def test_claimed_correct_and_duplicate_error_arrays_cannot_change_denominator(self):
        raw = report(wrong=(1,))
        error = {"type":"wrong","kind":"pitch","attemptId":raw["attempts"][0]["attemptId"],"opportunityId":raw["opportunities"][1]["opportunityId"]}
        raw["errors"] = [error, deepcopy(error), {**error,"type":"missed"}]
        result = normalize(raw)
        self.assertEqual(result["coverageByDimension"]["pitch"]["evaluated"], 4)
        self.assertEqual(result["coverageByDimension"]["pitch"]["failed"], 1)
        self.assertEqual(len([e for e in result["errors"] if e["kind"]=="pitch"]), 1)
        # A forged read-back metric is ignored, and a legitimate replay is stable.
        replay = deepcopy(result)
        replay["serverMetrics"]["coverageByDimension"]["pitch"]["failed"] = 0
        self.assertEqual(normalize(replay), result)

    def test_score_mismatch_cannot_be_repaired_by_changing_both_client_fields(self):
        raw = report()
        raw["expected"][0]["midi"] = 72
        raw["expected"][0]["writtenMidi"] = 72
        raw["opportunities"][0]["expectedMidi"] = 72
        with self.assertRaises(ValueError):
            normalize(raw)
        raw = report()
        raw["sourceScoreSha256"] = "b"*64
        with self.assertRaises(ValueError):
            normalize(raw)

    def test_stop_and_uncertain_capture_do_not_create_future_misses(self):
        raw = report()
        raw["actualEvents"] = raw["actualEvents"][:2]
        raw["attempts"][0]["interrupted"] = True
        raw["completed"] = False
        for op in raw["opportunities"][1:]:
            op.update(entered=False, terminal=False, completed=False, evaluated=False, outcome="pending", actualEventIds=[])
        result = normalize(raw)
        self.assertEqual(result["coverageByDimension"]["pitch"]["evaluated"], 1)
        self.assertEqual(result["coverageByDimension"]["pitch"]["failed"], 0)
        self.assertEqual(result["serverMetrics"]["unplayedOpportunities"], 3)
        self.assertEqual(result["coverageByDimension"]["duration"]["evaluated"], 0)
        raw["opportunities"][1].update(entered=True, terminal=True, outcome="missed")
        result = normalize(raw)
        self.assertEqual(result["coverageByDimension"]["pitch"]["pending"], 1)
        self.assertEqual(result["coverageByDimension"]["pitch"]["failed"], 0)

    def test_disabled_pitch_and_midi_cents_do_not_upgrade_capabilities(self):
        raw = report()
        raw["capabilities"]["pitch"] = False
        result = normalize(raw)
        self.assertEqual(result["coverageByDimension"]["pitch"]["evaluated"], 0)
        raw = report()
        raw["capabilities"]["intonation"] = True
        for event in raw["actualEvents"]:
            event.update(cents=0,centsEvidence="continuous-mpm-yin")
        self.assertEqual(normalize(raw)["coverageByDimension"]["intonation"]["evaluated"], 0)

    def test_multiple_attempts_have_separate_constant_capture_origin(self):
        raw = report()
        other = report(offset=10000,take_id=raw["takeId"])
        other_id = raw["takeId"]+":2"
        for event in other["actualEvents"]:
            event["eventId"] += "-second"
        for op in other["opportunities"]:
            op["attemptId"] = other_id
            op["opportunityId"] += "-second"
            op["actualEventIds"] = [eid+"-second" for eid in op["actualEventIds"]]
        raw["attempts"].append({"attemptId":other_id,"startMs":9000,"endMs":15000,"interrupted":False})
        raw["actualEvents"].extend(other["actualEvents"])
        raw["opportunities"].extend(other["opportunities"])
        raw["performanceDurationMs"] = 15000
        result = normalize(raw)
        self.assertEqual(result["coverageByDimension"]["onset"]["evaluated"], 8)
        self.assertEqual(result["coverageByDimension"]["onset"]["failed"], 0)

    def test_native_device_fields_and_long_uncertainty_preserve_pending(self):
        raw = report()
        for event in raw["actualEvents"]:
            event.update(sourceId=2**32-1, reason="", frequency=261.626)
            event["onsetMs" if event["type"] == "on" else "offsetMs"] = event["timeMs"]
        raw["recording"] = {"takeId": raw["takeId"], "available": False, "sampleRate": 0}
        raw["actualEvents"] = [e for e in raw["actualEvents"] if e["eventId"] != "midi-3"]
        raw["opportunities"][2].update(actualEventIds=[], outcome="missed")
        # A long low-confidence interval covers this note well beyond its start.
        raw["uncertainty"] = [{"timeMs": 0, "offsetMs": 4000, "reason": "模型片段证据不足"}]
        result = normalize(raw)
        self.assertEqual(result["coverageByDimension"]["pitch"], {"eligible":4,"evaluated":3,"failed":0,"pending":1})
        self.assertEqual(result["actualEvents"][0]["sourceId"], 2**32-1)
        self.assertEqual(normalize(result), result)
        invalid = deepcopy(raw)
        invalid["actualEvents"][0]["sourceId"] = 2**32
        with self.assertRaises(ValueError):
            normalize(invalid)
        invalid = deepcopy(raw)
        invalid["uncertainty"][0]["offsetMs"] = raw["performanceDurationMs"] + 1
        with self.assertRaises(ValueError):
            normalize(invalid)
        invalid = deepcopy(raw)
        invalid["actualEvents"][1]["sourceId"] = 1
        with self.assertRaises(ValueError):
            normalize(invalid)

    def test_manual_instrument_transposes_only_missing_xml_instruction(self):
        def transpose(raw, semitones, explicit):
            raw["instrument"] = {"profileId":"clarinet", "variant":"bb", "transpose":-2, "source":"manual"}
            for note, op in zip(raw["expected"], raw["opportunities"]):
                note.update(midi=note["midi"]+semitones, transpose=semitones, transposeExplicit=explicit)
                op["expectedMidi"] += semitones
            for event in raw["actualEvents"]:
                event["midi"] += semitones
            return raw
        result = normalize(transpose(report(), -2, False))
        self.assertEqual(result["expected"][0]["midi"], 58)
        self.assertEqual(result["coverageByDimension"]["pitch"]["failed"], 0)
        xml = accounts.SAMPLE_XML.replace('</divisions>', '</divisions><transpose><chromatic>-2</chromatic></transpose>')
        result = normalize(transpose(report(xml), -2, True), xml)
        self.assertEqual(result["expected"][0]["midi"], 58)
        # An explicit concert-pitch instruction overrides the manual Bb choice.
        xml = accounts.SAMPLE_XML.replace('</divisions>', '</divisions><transpose><chromatic>0</chromatic></transpose>')
        result = normalize(transpose(report(xml), 0, True), xml)
        self.assertEqual(result["expected"][0]["midi"], 60)
        invalid = transpose(report(), -2, False)
        invalid["instrument"]["transpose"] = -3
        with self.assertRaises(ValueError):
            normalize(invalid)

    def test_written_spelling_transposition_repeats_and_tie_duration(self):
        xml = '<score-partwise><part id="Bb"><measure><attributes><divisions>2</divisions><time><beats>2</beats><beat-type>4</beat-type></time><transpose><chromatic>-2</chromatic></transpose></attributes><barline><repeat direction="forward"/></barline><note><pitch><step>C</step><alter>1</alter><octave>4</octave></pitch><duration>2</duration><tie type="start"/></note><note><pitch><step>C</step><alter>1</alter><octave>4</octave></pitch><duration>2</duration><tie type="stop"/></note><barline><repeat direction="backward"/></barline></measure></part></score-partwise>'
        notes = music.score_timeline(xml)["notes"]
        self.assertEqual([(n["midi"],n["writtenMidi"],n["durationBeat"],n["occurrenceOrdinal"]) for n in notes],[(59,61,2,1),(59,61,2,2)])
        left = {"partId":"P","voice":"1","staff":"1","step":"C","octave":4,"writtenMidi":61}
        right = {**left,"step":"D","writtenMidi":63}
        self.assertEqual(music.interval_label(left,right)["label"],"大二度")
        enharmonic = {**left,"step":"D","writtenMidi":61}
        self.assertEqual(music.interval_label(left,enharmonic)["label"],"减二度")
        self.assertIsNone(music.interval_label(left,{**right,"voice":"2"}))

    def test_same_pitch_simultaneous_voices_are_one_opportunity(self):
        xml = '<score-partwise><part id="P1"><measure><attributes><divisions>1</divisions><time><beats>1</beats><beat-type>4</beat-type></time></attributes><note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note><backup><duration>1</duration></backup><note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><voice>2</voice></note></measure></part></score-partwise>'
        raw = report(xml,count=1)
        # This score has no printed tempo, so the default120 is scaled to60.
        second = deepcopy(raw["expected"][0])
        second.update(noteIndex=1,sourceNoteId="P1:0:1",occurrenceId="P1:0:1@1",voice="2")
        raw["expected"].append(second)
        raw["opportunities"][0]["sourceNoteIds"].append("P1:0:1")
        raw["opportunities"][0].update(voice="unknown",staff="unknown")
        result = normalize(raw,xml)
        self.assertEqual(result["coverageByDimension"]["pitch"]["evaluated"], 1)
        raw["opportunities"].append(deepcopy(raw["opportunities"][0]))
        with self.assertRaises(ValueError):
            normalize(raw,xml)


class AggregationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.moment = 1791766800
        self.store = accounts.Store(self.directory.name,clock=lambda:self.moment)
        self.owner = self.store.register({"username":"music_owner","password":"synthetic music test password","mode":"native"})["userId"]
        self.provider = Provider()
        self.analyzer = interpretation.PracticeAnalysis(self.store,self.provider,clock=lambda:self.moment)

    def tearDown(self):
        self.directory.cleanup()

    def event(self, analysis, *, xml=accounts.SAMPLE_XML, day=1):
        score_id, source = "notelite-four-notes-v1", "official"
        if xml != accounts.SAMPLE_XML:
            score = self.store.create_score(self.owner,{"title":"Synthetic score","musicxml":xml})
            score_id, source = score["id"], "personal"
        value = {"eventId":analysis["takeId"],"sourceKind":source,"scoreId":score_id,"scoreRevision":1,"mode":"strict","durationSeconds":30,"startedAt":accounts.now_stamp(self.moment-day*86400-60),"endedAt":accounts.now_stamp(self.moment-day*86400),"analysis":analysis}
        return self.store.add_history(self.owner,value)["event"]["eventId"]

    def test_actual_results_have_separate_denominators_positive_fact_no_raw_model_input(self):
        key = self.event(report(wrong=(1,)))
        prepared = self.analyzer.input(self.owner,[key])
        self.assertEqual(prepared["metrics"]["evaluatedOpportunities"],4)
        self.assertEqual(prepared["metrics"]["errorRate"],.25)
        self.assertEqual(prepared["metrics"]["performance"]["coverageByDimension"]["duration"]["evaluated"],3)
        self.assertEqual(prepared["modelInput"]["reportStatus"],"partial")
        self.assertTrue(any("明确正确 3 次" in f["statement"] for f in prepared["modelInput"]["facts"]))
        raw = interpretation.json_bytes(prepared["modelInput"]).decode()
        for prohibited in (key,"actualEvents","opportunities","score-partwise","P1:0:0"):
            self.assertNotIn(prohibited,raw)
        self.assertLessEqual(len(raw.encode()),interpretation.MAX_INPUT_BYTES)
        interpretation.validate_input(prepared["modelInput"],prepared["evidenceIndex"],self.analyzer.input_schema)

    def test_cache_changes_for_new_version_old_evidence_remains_pinned(self):
        raw = report(wrong=(1,))
        event_id = self.event(raw)
        before = self.analyzer.input(self.owner,[event_id])
        original = self.store.read_history_analysis(self.owner,event_id,1)
        corrected = report(take_id=event_id)
        self.store.add_history_analysis(self.owner,event_id,{"requestId":str(uuid.uuid4()),"parentVersion":1,"sourceHash":raw["sourceScoreSha256"],"analysis":corrected})
        after = self.analyzer.input(self.owner,[event_id])
        self.assertNotEqual(before["sourceHash"],after["sourceHash"])
        self.assertEqual(before["metrics"]["errorRate"],.25)
        self.assertEqual(after["metrics"]["errorRate"],0)
        old_refs = [event for entry in before["evidenceIndex"].values() for event in entry["events"]]
        self.assertTrue(all(e["analysisVersion"]==1 for e in old_refs if "analysisVersion" in e))
        self.assertEqual(self.store.read_history_analysis(self.owner,event_id,1),original)

    def test_fixed_rule_requires_multiple_days_takes_coverage_and_same_actual_tempo_scope(self):
        # Twenty authored notes, five4/4 measures, exact known C-D-E-F pattern.
        measure = '<measure><note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note><note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration></note><note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration></note><note><pitch><step>F</step><octave>4</octave></pitch><duration>1</duration></note></measure>'
        xml = '<score-partwise><part-list><score-part id="P1"><part-name>Test</part-name></score-part></part-list><part id="P1">'+measure*5+'</part></score-partwise>'
        ids=[]
        for day in (3,2,1):
            ids.append(self.event(report(xml,count=20),xml=xml,day=day))
        # The helper creates different personal IDs, but immutable contentSHA is
        # identical and explicitly the same difficulty/scope.
        prepared = self.analyzer.input(self.owner,ids)
        self.assertTrue(prepared["metrics"]["stableCapabilityRulesSatisfied"])
        self.assertTrue(any(f["kind"]=="strength" for f in prepared["modelInput"]["facts"]))
        single = self.analyzer.input(self.owner,ids[:1])
        self.assertFalse(single["metrics"]["stableCapabilityRulesSatisfied"])
        self.assertFalse(any(f["kind"] in {"strength","weakness","progress"} for f in single["modelInput"]["facts"]))


if __name__ == "__main__":
    unittest.main()
