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


if __name__ == "__main__":
    unittest.main()
