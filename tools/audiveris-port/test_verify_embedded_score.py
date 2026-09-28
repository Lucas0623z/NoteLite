#!/usr/bin/env python3
"""Regression tests for the semantic acceptance gate, independent of recognition."""
import copy
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

import verify_embedded_score as verifier


class SemanticGateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)

    def xml(self, *, step="C", duration=4, divisions=4, x=10):
        path = self.root / f"score-{step}-{duration}-{divisions}-{x}.musicxml"
        path.write_text(f'''<?xml version="1.0"?>
        <score-partwise><part id="P1"><measure number="1">
        <attributes><divisions>{divisions}</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
        <note default-x="{x}"><pitch><step>{step}</step><octave>4</octave></pitch>
        <duration>{duration}</duration><voice>1</voice><type>quarter</type><staff>1</staff></note>
        <note><rest/><duration>{duration}</duration><voice>1</voice><type>quarter</type></note>
        </measure></part></score-partwise>''', encoding="utf-8")
        return verifier.musicxml_semantics(path)

    def test_layout_and_equivalent_time_resolution_do_not_change_music(self):
        self.assertEqual(self.xml(), self.xml(x=500))
        self.assertEqual(self.xml(), self.xml(duration=8, divisions=8))

    def test_changed_pitch_or_duration_fails_even_when_note_count_matches(self):
        reference = self.xml()
        for changed in [self.xml(step="D"), self.xml(duration=2)]:
            self.assertEqual(reference["counts"], changed["counts"])
            self.assertTrue(verifier.differences(reference, changed))

    def midi(self, pitch=60, end=96):
        # One note, at beat zero; running-status note-on with zero velocity ends it.
        track = bytes([0, 0x90, pitch, 100, end, pitch, 0, 0, 0xff, 0x2f, 0])
        path = self.root / f"score-{pitch}-{end}.mid"
        path.write_bytes(b"MThd" + struct.pack(">IHHH", 6, 0, 1, 96)
                         + b"MTrk" + struct.pack(">I", len(track)) + track)
        return verifier.midi_semantics(path)

    def test_midi_pitch_and_note_end_changes_fail_with_same_note_count(self):
        reference = self.midi()
        self.assertEqual(reference["note_on_count"], 1)
        for changed in [self.midi(pitch=61), self.midi(end=48)]:
            self.assertEqual(reference["note_on_count"], changed["note_on_count"])
            self.assertTrue(verifier.differences(reference, changed))

    def test_mxl_uses_declared_score_and_does_not_extract_files(self):
        self.xml()
        xml = next(self.root.glob("*.musicxml")).read_bytes()
        path = self.root / "score.mxl"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("META-INF/container.xml", '''<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>
            <rootfile full-path="nested/score.xml" media-type="application/vnd.recordare.musicxml+xml"/>
            </rootfiles></container>''')
            archive.writestr("unrelated.xml", "<not-a-score/>")
            archive.writestr("nested/score.xml", xml)
        self.assertEqual(verifier.musicxml_semantics(path), self.xml())
        self.assertFalse((self.root / "nested").exists())

    def test_missing_or_extra_semantic_event_fails(self):
        reference = self.midi()
        changed = copy.deepcopy(reference)
        changed["events"].pop()
        self.assertTrue(verifier.differences(reference, changed))

    def two_movements(self):
        directory = self.root / "document"
        directory.mkdir()
        for index, (step, pitch) in enumerate([("C", 60), ("D", 62)], start=1):
            self.xml(step=step)
            self.midi(pitch=pitch)
            (directory / f"document.mvt{index}.musicxml").write_bytes(
                (self.root / f"score-{step}-4-4-10.musicxml").read_bytes())
            (directory / f"document.mvt{index}.mid").write_bytes(
                (self.root / f"score-{pitch}-96.mid").read_bytes())
        return directory

    def test_two_movements_compare_every_score_and_midi_event(self):
        directory = self.two_movements()
        reference = verifier.score_semantics(directory, 2)
        self.assertEqual(verifier.semantic_summary(reference), {
            "movement_count": 2, "musicxml_counts": {"pitched_notes": 2, "other_notes": 2, "measures": 2},
            "midi_note_on_count": 2})
        second = directory / "document.mvt2.musicxml"
        second.write_text(second.read_text().replace("<step>D</step>", "<step>E</step>"))
        actual = verifier.score_semantics(directory, 2)
        self.assertEqual(verifier.semantic_summary(reference), verifier.semantic_summary(actual))
        self.assertTrue(verifier.differences(reference, actual))

    def test_missing_page_pair_fails_instead_of_accepting_first_page(self):
        directory = self.two_movements()
        (directory / "document.mvt2.musicxml").unlink()
        (directory / "document.mvt2.mid").unlink()
        with self.assertRaisesRegex(ValueError, "Expected 2 score/MIDI pairs"):
            verifier.score_semantics(directory, 2)

    def test_equal_counts_with_unpaired_midi_fail(self):
        directory = self.two_movements()
        (directory / "document.mvt2.mid").rename(directory / "unrelated.mid")
        with self.assertRaisesRegex(ValueError, "matching MusicXML and MIDI"):
            verifier.score_semantics(directory, 2)


if __name__ == "__main__":
    unittest.main()
