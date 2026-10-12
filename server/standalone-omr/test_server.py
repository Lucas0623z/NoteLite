#!/usr/bin/env python3
"""Local regression tests; real extracted MIDI converter, no simulated OMR claims.

OMR_TEST_MIDI_COMMAND is a JSON argv prefix, e.g. ["/usr/local/bin/omr-midi"].
On the development machine the Java classpath uses the official extracted deb.
Run: python3 test_server.py --output /path/to/test-results.json
"""
from __future__ import annotations
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

import server

HERE = Path(__file__).resolve().parent
TOKEN = "test-access-token-" + "a" * 32


def xml(step="C", *, chord=False, transpose=0):
    chord_note = '<note><chord/><pitch><step>E</step><octave>4</octave></pitch><duration>4</duration><type>quarter</type></note>' if chord else ""
    transposition = f'<transpose><diatonic>-1</diatonic><chromatic>{transpose}</chromatic></transpose>' if transpose else ""
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "https://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Flute</part-name><score-instrument id="I1"><instrument-name>Flute</instrument-name></score-instrument><midi-instrument id="I1"><midi-channel>1</midi-channel><midi-program>74</midi-program></midi-instrument></score-part></part-list>
<part id="P1"><measure number="1"><attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef>{transposition}</attributes>
<note><pitch><step>{step}</step><octave>4</octave></pitch><duration>4</duration><type>quarter</type></note>{chord_note}
<note><pitch><step>D</step><octave>4</octave></pitch><duration>4</duration><type>quarter</type></note>
<note><rest/><duration>8</duration><type>half</type></note></measure></part></score-partwise>'''.encode()


def mxl(scores):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        paths = [f"movement-{n}.musicxml" for n in range(len(scores))]
        archive.writestr("META-INF/container.xml", '<container><rootfiles>' + ''.join(f'<rootfile full-path="{path}" media-type="application/vnd.recordare.musicxml+xml"/>' for path in paths) + '</rootfiles></container>')
        for path, data in zip(paths, scores):
            archive.writestr(path, data)
    return buffer.getvalue()


def midi_prefix():
    configured = os.environ.get("OMR_TEST_MIDI_COMMAND")
    if configured:
        return json.loads(configured)
    if os.name != "nt" and Path("/usr/local/bin/omr-midi").is_file():
        return ["/usr/local/bin/omr-midi"]
    java = Path(os.environ.get("OMR_TEST_JAVA", "D:/Chatgpt/toolchains/jdk-21.0.12.1+1/bin/java.exe"))
    dependencies = HERE.parent / "assets/opt/audiveris/lib/app"
    if not java.is_file() or not dependencies.is_dir() or not (HERE / "lib/omr-midi.jar").is_file():
        return None
    return [str(java), "-Djava.awt.headless=true", "-cp", str(HERE / "lib/omr-midi.jar") + os.pathsep + str(dependencies / "*"), "com.notelite.omr.score.OmrMidiConverter"]


def midi_notes(data):
    """Read note-on/off tick spans from real SMF, including running status."""
    if data[:4] != b"MThd":
        raise AssertionError("No MIDI header")
    tracks = int.from_bytes(data[10:12], "big")
    ppq = int.from_bytes(data[12:14], "big")
    offset, notes = 14, []
    for track_index in range(tracks):
        if data[offset:offset + 4] != b"MTrk":
            raise AssertionError("No MIDI track")
        length = int.from_bytes(data[offset + 4:offset + 8], "big")
        track = data[offset + 8:offset + 8 + length]
        offset += 8 + length
        cursor, ticks, running, active = 0, 0, None, {}
        def vlq():
            nonlocal cursor
            value = 0
            for _ in range(4):
                octet = track[cursor]
                cursor += 1
                value = (value << 7) | (octet & 127)
                if not octet & 128:
                    return value
            raise AssertionError("MIDI VLQ exceeds four bytes")
        while cursor < len(track):
            ticks += vlq()
            status = track[cursor]
            if status & 128:
                cursor += 1
                if status < 240:
                    running = status
            else:
                status = running
                if status is None:
                    raise AssertionError("Invalid running status")
            if status == 255:
                cursor += 1  # Meta type.
                meta_length = vlq()
                cursor += meta_length
            elif status in (240, 247):
                sysex_length = vlq()
                cursor += sysex_length
                running = None
            else:
                size = 1 if status >> 4 in (12, 13) else 2
                payload = track[cursor:cursor + size]
                cursor += size
                kind, channel = status >> 4, status & 15
                if kind == 9 and payload[1]:
                    active.setdefault((channel, payload[0]), []).append(ticks)
                elif kind == 8 or kind == 9:
                    key = (channel, payload[0])
                    if active.get(key):
                        start = active[key].pop(0)
                        notes.append({"pitch": payload[0], "onsetTicks": start, "durationTicks": ticks - start, "track": track_index})
        if any(active.values()):
            raise AssertionError("MIDI note left sounding")
    return ppq, sorted(notes, key=lambda n: (n["onsetTicks"], n["pitch"]))


class ValidationTests(unittest.TestCase):
    def assert_api(self, code, callback):
        with self.assertRaises(server.APIError) as error:
            callback()
        self.assertEqual(code, error.exception.status)

    def test_official_doctype_without_external_fetch_and_utf16(self):
        self.assertEqual("score-partwise", server.tag(server.safe_xml(xml())))
        data = xml().decode().replace('encoding="UTF-8"', 'encoding="UTF-16"').encode("utf-16")
        self.assertEqual("score-partwise", server.tag(server.safe_xml(data)))

    def test_entity_and_internal_subset_rejected_in_utf16_too(self):
        unsafe = xml().replace(b'<!DOCTYPE score-partwise PUBLIC', b'<!DOCTYPE score-partwise [<!ENTITY x SYSTEM "file:///etc/passwd">]><!--').replace(b'<score-partwise version', b'--><score-partwise version', 1)
        self.assert_api(400, lambda: server.safe_xml(unsafe))
        self.assert_api(400, lambda: server.safe_xml(unsafe.decode().replace('encoding="UTF-8"', 'encoding="UTF-16"').encode("utf16")))
        self.assert_api(400, lambda: server.safe_xml(b'<!DOCTYPE score-partwise [ ]>' + xml().split(b'<score-partwise', 1)[1].join([b'<score-partwise', b''])))

    def test_mxl_all_declared_movements_and_invalid_second_entry(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "score.mxl"
            path.write_bytes(mxl([xml(), xml("G")]))
            self.assertEqual(2, len(server.source_scores(path)))
            self.assertEqual("G", server.note_listing(server.source_scores(path)[1][1])["notes"][0]["pitch"]["step"])
            self.assert_api(400, lambda: server.mxl_xml(path))
            path.write_bytes(mxl([xml(), b'<!DOCTYPE score-partwise [<!ENTITY e SYSTEM "file:///etc/passwd">]><score-partwise/>']))
            self.assert_api(400, lambda: server.source_scores(path))

    def test_mxl_traversal_duplicate_and_xml_bomb_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "score.mxl"
            for name, body, code in [("../outside.musicxml", xml(), 400), ("score.musicxml", b" " * (server.MAX_XML + 1), 413)]:
                with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr(name, body)
                self.assert_api(code, lambda: server.source_scores(path))
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("score.musicxml", xml())
                with self.assertWarns(UserWarning):
                    archive.writestr("score.musicxml", xml("G"))
            self.assert_api(400, lambda: server.source_scores(path))

    def test_edit_bad_json_shapes_raise_400_without_typeerror(self):
        base = {"partId": "P1", "measureIndex": 0, "noteIndex": 0}
        for extra in [{"partId": []}, {"pitch": {"step": None}}, {"pitch": {"step": 60}}, {"type": []}, {"duration": float("nan")}, {"measureIndex": 10 ** 300}, {"measureIndex": .5}, {"delete": "true"}]:
            self.assert_api(400, lambda extra=extra: server.apply_edits(xml(), [base | extra]))

    def test_delete_indices_are_original_and_chord_base_is_promoted(self):
        modified = server.apply_edits(xml(chord=True), [{"partId": "P1", "measureIndex": 0, "noteIndex": 0, "delete": True}, {"partId": "P1", "measureIndex": 0, "noteIndex": 2, "pitch": {"step": "G"}}])
        notes = server.note_listing(modified)["notes"]
        self.assertEqual(["E", "G", None], [note["pitch"]["step"] if note["pitch"] else None for note in notes])
        self.assertFalse(notes[0]["chord"])
        self.assertEqual(["P1:0", "P1:1", "P1:2"], [note["sourceNoteId"] for note in notes])

    def test_worker_timeout_is_bounded_and_keeps_log(self):
        with tempfile.TemporaryDirectory() as temp:
            root, started = Path(temp), time.monotonic()
            self.assert_api(504, lambda: server.run_command([sys.executable, "-c", "import time; time.sleep(60)"], root, root / "engine.log", .1, "timeout-regression"))
            self.assertLess(time.monotonic() - started, 5)
            self.assertIn("timeout-regression", (root / "engine.log").read_text())

    def test_natural_movement_order(self):
        self.assertEqual(["mvt1.mxl", "mvt2.mxl", "mvt10.mxl"], [p.name for p in sorted(map(Path, ["mvt10.mxl", "mvt2.mxl", "mvt1.mxl"]), key=server.natural_key)])


class ActualMidiTests(unittest.TestCase):
    def setUp(self):
        command = midi_prefix()
        if command is None:
            self.skipTest("Actual MIDI converter not configured; set OMR_TEST_MIDI_COMMAND JSON")
        self.temp = tempfile.TemporaryDirectory(prefix="notelite-omr-real-midi-")
        self.root = Path(self.temp.name)
        self.service = server.JobService(self.root / "jobs", TOKEN, midi_command=command, midi_timeout=30)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.service.close)

    def wait(self, job_id):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            job = self.service.get(job_id)
            if job["state"] in {"succeeded", "failed"}:
                self.assertEqual("succeeded", job["state"], job)
                return job
            time.sleep(.03)
        self.fail("Import timed out")

    def submit(self, data=None, name="original.musicxml"):
        data = data or xml()
        return self.wait(self.service.submit(name, io.BytesIO(data), len(data))["id"])

    def artifact(self, job_id, kind, score=0):
        stream, _, _ = self.service.artifact(job_id, kind, score)
        with stream:
            return stream.read()

    def test_actual_pitch_duration_rest_delete_and_version_backup(self):
        original = xml()
        job = self.submit(original)
        self.assertEqual("import", job["recognitionMode"])
        ppq, notes = midi_notes(self.artifact(job["id"], "midi"))
        self.assertEqual([60, 62], [note["pitch"] for note in notes])
        self.assertEqual(ppq, notes[0]["durationTicks"])
        old_xml = self.artifact(job["id"], "musicxml")
        updated = self.service.edit(job["id"], revision=1, edits=[{"partId": "P1", "measureIndex": 0, "noteIndex": 0, "pitch": {"step": "F", "alter": 1, "octave": 5}, "duration": 6, "type": "quarter", "dot": 1}])
        ppq, notes = midi_notes(self.artifact(job["id"], "midi"))
        self.assertEqual(78, notes[0]["pitch"])
        self.assertEqual(ppq * 3 // 2, notes[0]["durationTicks"])
        self.assertEqual(1, self.service.notes(job["id"])["notes"][0]["dot"])
        self.assertEqual(original, self.artifact(job["id"], "original"))
        self.assertEqual(old_xml, (self.service.directory(job["id"]) / "revisions/00000001/score-000.musicxml").read_bytes())
        self.service.edit(job["id"], revision=updated["revision"], edits=[{"partId": "P1", "measureIndex": 0, "noteIndex": 0, "rest": True}, {"partId": "P1", "measureIndex": 0, "noteIndex": 1, "delete": True}])
        self.assertEqual([], midi_notes(self.artifact(job["id"], "midi"))[1])
        self.assertTrue(self.service.notes(job["id"])["notes"][0]["rest"])
        server.validate_midi(self.service.file(job["id"], self.service.jobs[job["id"]]["scores"][0]["midi"]))

    def test_conversion_failure_rolls_back_xml_midi_metadata(self):
        job = self.submit()
        before = {kind: self.artifact(job["id"], kind) for kind in ("musicxml", "midi", "original")}
        metadata = (self.service.directory(job["id"]) / "job.json").read_bytes()
        self.service.midi_command = [sys.executable, "-c", "raise SystemExit(7)"]
        with self.assertRaises(server.APIError) as error:
            self.service.edit(job["id"], data=xml("G"), revision=1)
        self.assertEqual(422, error.exception.status)
        self.assertEqual(metadata, (self.service.directory(job["id"]) / "job.json").read_bytes())
        self.assertEqual(1, self.service.get(job["id"])["revision"])
        for kind, value in before.items():
            self.assertEqual(value, self.artifact(job["id"], kind))

    def test_metadata_failure_does_not_publish_orphan_and_next_save_recovers(self):
        job = self.submit()
        before = self.artifact(job["id"], "musicxml")
        with patch.object(self.service, "_save", side_effect=OSError("simulated disk failure")):
            with self.assertRaises(OSError):
                self.service.edit(job["id"], data=xml("E"), revision=1)
        self.assertEqual(1, self.service.get(job["id"])["revision"])
        self.assertEqual(before, self.artifact(job["id"], "musicxml"))
        updated = self.service.edit(job["id"], data=xml("G"), revision=1)
        self.assertEqual(3, updated["revision"])
        self.assertEqual([67, 62], [n["pitch"] for n in midi_notes(self.artifact(job["id"], "midi"))[1]])

    def test_mxl_multiple_real_midis_and_transposition(self):
        job = self.submit(mxl([xml(), xml("G", transpose=-2)]), "two-movements.mxl")
        self.assertEqual(2, len(job["scores"]))
        self.assertEqual(["0", "1"], [score["id"] for score in job["scores"]])
        first = self.artifact(job["id"], "midi", 0)
        self.assertEqual([65, 60], [n["pitch"] for n in midi_notes(self.artifact(job["id"], "midi", 1))[1]])
        self.service.edit(job["id"], index=1, revision=1, edits=[{"partId": "P1", "measureIndex": 0, "noteIndex": 0, "pitch": {"step": "A"}}])
        self.assertEqual(first, self.artifact(job["id"], "midi", 0))
        self.assertEqual([67, 60], [n["pitch"] for n in midi_notes(self.artifact(job["id"], "midi", 1))[1]])


def main():
    output = None
    if "--output" in sys.argv:
        index = sys.argv.index("--output")
        output = Path(sys.argv[index + 1])
        del sys.argv[index:index + 2]
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {"schemaVersion": 1, "scope": "Independent server security/XML/edits + actual standalone MIDI; no remote OMR claim", "testsRun": result.testsRun, "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped), "failed": len(result.failures) + len(result.errors), "skipped": len(result.skipped), "failures": [{"test": str(test), "detail": detail} for test, detail in result.failures + result.errors], "skipReasons": [{"test": str(test), "reason": reason} for test, reason in result.skipped], "actualMidiConfigured": midi_prefix() is not None}
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf8")
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
