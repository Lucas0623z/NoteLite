#!/usr/bin/env python3
"""Independent HTTP/persistence tests with the real Java MIDI converter.

These are module boundary tests, not Audiveris image-recognition accuracy tests.
The tiny XML inputs deliberately isolate edits/ties and multi-movement storage.
All storage, mock engine output and listeners are local temporary resources.
Run: python test_server_independent.py
Optional OMR_TEST_CONVERTER='["/usr/local/bin/omr-midi"]' selects an installed
converter. Otherwise local module/lib/omr-midi.jar and audited DEB JARs are used.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.util
import io
import json
import os
import platform
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
import zipfile

MODULE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("omr_http_under_test", MODULE / "server.py")
server_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_module)
TOKEN = "independent-local-test-token-0123456789abcdef"

SCORE_A = b'''<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
<part id="P1"><measure number="1" implicit="yes"><attributes><divisions>480</divisions></attributes>
<note><pitch><step>C</step><octave>4</octave></pitch><duration>480</duration><voice>1</voice><type>quarter</type></note>
<note><pitch><step>D</step><octave>4</octave></pitch><duration>480</duration><voice>1</voice><type>quarter</type></note>
</measure></part></score-partwise>'''
SCORE_B = SCORE_A.replace(b"<step>C</step>", b"<step>F</step>").replace(b"<step>D</step>", b"<step>G</step>")


def converter_command():
    configured = os.environ.get("OMR_TEST_CONVERTER")
    if configured:
        command = json.loads(configured)
        if not isinstance(command, list) or not command:
            raise ValueError("OMR_TEST_CONVERTER must be a JSON argv array")
        return command
    java = shutil.which("java")
    libs = MODULE.parent / "assets" / "opt" / "audiveris" / "lib" / "app"
    converter = MODULE / "lib" / "omr-midi.jar"
    if not java or not converter.is_file() or not (libs / "proxymusic-4.0.3.jar").is_file():
        raise unittest.SkipTest("real Java converter unavailable; set OMR_TEST_CONVERTER to installed converter")
    return [java, "-Dfile.encoding=UTF-8", "-cp", str(converter) + os.pathsep + str(libs / "*"),
            "com.notelite.omr.score.OmrMidiConverter"]


def sounding_pitches(data):
    """Independent SMF event read; silent legal edits return [], not failure."""
    assert data[:4] == b"MThd" and len(data) >= 14
    header_length, format_number, tracks, ppq = struct.unpack_from(">IHHH", data, 4)
    assert format_number in (0, 1) and tracks > 0 and ppq > 0 and not ppq & 0x8000
    cursor = 8 + header_length
    notes = []

    def vlq(position, end):
        value = 0
        for _ in range(4):
            assert position < end
            byte = data[position]
            position += 1
            value = value * 128 + (byte & 127)
            if byte < 128:
                return value, position
        raise AssertionError("invalid MIDI VLQ")

    for _ in range(tracks):
        assert data[cursor:cursor + 4] == b"MTrk"
        length = struct.unpack_from(">I", data, cursor + 4)[0]
        cursor += 8
        end = cursor + length
        assert end <= len(data)
        running, ended, tick, active = None, False, 0, {}
        while cursor < end:
            delta, cursor = vlq(cursor, end)
            tick += delta
            status = data[cursor]
            if status >= 128:
                cursor += 1
                running = status if status < 240 else None
            else:
                assert running is not None
                status = running
            if status == 255:
                kind = data[cursor]
                cursor += 1
                size, cursor = vlq(cursor, end)
                cursor += size
                if kind == 47:
                    assert size == 0 and cursor == end
                    ended = True
            elif status in (240, 247):
                size, cursor = vlq(cursor, end)
                cursor += size
            else:
                size = 1 if status & 240 in (192, 208) else 2
                assert cursor + size <= end and all(value < 128 for value in data[cursor:cursor + size])
                if status & 240 == 144 and data[cursor + 1] > 0:
                    notes.append(data[cursor])
                    active.setdefault((status & 15, data[cursor]), []).append(tick)
                elif status & 240 == 128 or status & 240 == 144 and data[cursor + 1] == 0:
                    key = (status & 15, data[cursor])
                    assert active.get(key), "note-off without an active note-on"
                    assert tick > active[key].pop(0), "sounding note has no positive duration"
                cursor += size
        assert ended
        assert not any(active.values()), "dangling note-on at end of track"
    assert cursor == len(data)
    return notes


def mxl(movements):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
        roots = "".join(f'<rootfile full-path="{name}" media-type="application/vnd.recordare.musicxml+xml"/>'
                        for name, _ in movements)
        archive.writestr("META-INF/container.xml", "<container><rootfiles>" + roots + "</rootfiles></container>")
        for name, xml in movements:
            archive.writestr(name, xml)
    return data.getvalue()


class IndependentServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.command = converter_command()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="notelite-omr-independent-")
        self.storage = Path(self.temp.name) / "jobs"
        self.service = server_module.JobService(self.storage, TOKEN, midi_command=self.command,
                                               timeout=10, midi_timeout=20)
        self.http = None
        self.thread = None

    def tearDown(self):
        if self.http:
            self.http.shutdown()
            self.http.server_close()
            self.thread.join(timeout=5)
        self.service.close()
        self.assertFalse(self.service.worker.is_alive(), "worker leaked after close")
        self.temp.cleanup()

    def submit(self, name="example.musicxml", data=SCORE_A):
        job = self.service.submit(name, io.BytesIO(data), len(data))
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            job = self.service.get(job["id"])
            if job["state"] in {"succeeded", "failed"}:
                break
            time.sleep(.01)
        self.assertEqual(job["state"], "succeeded", job)
        return job

    def artifact(self, job_id, kind, index=0):
        stream, _, revision = self.service.artifact(job_id, kind, index)
        with stream:
            return stream.read(), revision

    def assert_unchanged(self, job_id, revision, xml, midi):
        self.assertEqual(self.service.get(job_id)["revision"], revision)
        self.assertEqual(self.artifact(job_id, "musicxml"), (xml, revision))
        self.assertEqual(self.artifact(job_id, "midi"), (midi, revision))

    def start_http(self):
        self.http = server_module.Server(("127.0.0.1", 0), self.service)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        return "http://127.0.0.1:" + str(self.http.server_port)

    def request(self, base, path, *, method="GET", data=None, authenticated=True, headers=None):
        values = {"Authorization": "Bearer " + TOKEN} if authenticated else {}
        values.update(headers or {})
        request = Request(base + path, data=data, method=method, headers=values)
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, response.read(), dict(response.headers)
        except HTTPError as error:
            return error.code, error.read(), dict(error.headers)

    def test_real_converter_edit_updates_xml_and_midi_same_revision(self):
        job = self.submit()
        self.assertEqual(sounding_pitches(self.artifact(job["id"], "midi")[0]), [60, 62])
        updated = self.service.edit(job["id"], revision=job["revision"], edits=[
            {"partId": "P1", "measureIndex": 0, "noteIndex": 0, "pitch": {"step": "E", "octave": 4}}])
        xml, xml_revision = self.artifact(job["id"], "musicxml")
        midi, midi_revision = self.artifact(job["id"], "midi")
        self.assertEqual((xml_revision, midi_revision), (updated["revision"], updated["revision"]))
        self.assertEqual(ET.fromstring(xml).findtext("part/measure/note/pitch/step"), "E")
        self.assertEqual(sounding_pitches(midi), [64, 62])

    def test_converter_failure_preserves_old_xml_midi_and_metadata(self):
        job = self.submit()
        xml, revision = self.artifact(job["id"], "musicxml")
        midi, _ = self.artifact(job["id"], "midi")
        metadata = (self.storage / job["id"] / "job.json").read_bytes()
        self.service.midi_command = [sys.executable, "-c", "import sys;sys.exit(9)"]
        with self.assertRaises(server_module.APIError) as error:
            self.service.edit(job["id"], edits=[{"partId": "P1", "measureIndex": 0, "noteIndex": 0, "step": "F"}])
        self.assertEqual(error.exception.status, 422)
        self.assert_unchanged(job["id"], revision, xml, midi)
        self.assertEqual((self.storage / job["id"] / "job.json").read_bytes(), metadata)
        self.assertFalse(list((self.storage / job["id"] / "revisions").glob(".pending-*")))

    def test_metadata_failure_orphan_never_publishes_and_restart_reads_old(self):
        job = self.submit()
        xml, revision = self.artifact(job["id"], "musicxml")
        midi, _ = self.artifact(job["id"], "midi")
        with patch.object(self.service, "_save", side_effect=OSError("injected metadata commit failure")):
            with self.assertRaises(OSError):
                self.service.edit(job["id"], edits=[{"partId": "P1", "measureIndex": 0, "noteIndex": 0, "step": "F"}])
        self.assert_unchanged(job["id"], revision, xml, midi)
        self.service.close()
        self.service = server_module.JobService(self.storage, TOKEN, midi_command=self.command, timeout=10, midi_timeout=20)
        self.assert_unchanged(job["id"], revision, xml, midi)
        updated = self.service.edit(job["id"], revision=revision,
                                    edits=[{"partId": "P1", "measureIndex": 0, "noteIndex": 0, "step": "G"}])
        self.assertGreater(updated["revision"], revision + 1)
        self.assertEqual(sounding_pitches(self.artifact(job["id"], "midi")[0]), [67, 62])

    def test_multi_root_mxl_preserves_order_and_edit_only_selected_movement(self):
        payload = mxl([("second.musicxml", SCORE_B), ("first.musicxml", SCORE_A)])
        job = self.submit("two-movements.mxl", payload)
        self.assertEqual(len(job["scores"]), 2)
        xml0, revision = self.artifact(job["id"], "musicxml", 0)
        midi0, _ = self.artifact(job["id"], "midi", 0)
        self.assertEqual(sounding_pitches(midi0), [65, 67])
        self.assertEqual(sounding_pitches(self.artifact(job["id"], "midi", 1)[0]), [60, 62])
        updated = self.service.edit(job["id"], index=1, revision=revision,
                                    edits=[{"partId": "P1", "measureIndex": 0, "noteIndex": 0, "step": "E"}])
        self.assertEqual(self.artifact(job["id"], "musicxml", 0), (xml0, updated["revision"]))
        self.assertEqual(self.artifact(job["id"], "midi", 0), (midi0, updated["revision"]))
        self.assertEqual(sounding_pitches(self.artifact(job["id"], "midi", 1)[0]), [64, 62])

    def test_stale_revision_and_invalid_locator_do_not_change_files(self):
        job = self.submit()
        xml, revision = self.artifact(job["id"], "musicxml")
        midi, _ = self.artifact(job["id"], "midi")
        for options in ({"revision": revision - 1}, {"index": 1}, {"revision": True}):
            with self.subTest(options=options), self.assertRaises(server_module.APIError):
                self.service.edit(job["id"], edits=[{"partId": "P1", "measureIndex": 0, "noteIndex": 0, "step": "E"}], **options)
            self.assert_unchanged(job["id"], revision, xml, midi)
        for edit in ({"partId": "P2", "measureIndex": 0, "noteIndex": 0, "step": "E"},
                     {"partId": "P1", "measureIndex": -1, "noteIndex": 0, "step": "E"},
                     {"partId": "P1", "measureIndex": 0, "noteIndex": 99, "step": "E"}):
            with self.subTest(edit=edit), self.assertRaises(server_module.APIError):
                self.service.edit(job["id"], edits=[edit])
            self.assert_unchanged(job["id"], revision, xml, midi)

    def test_concurrent_edit_conflict_keeps_readers_on_old_pair(self):
        job = self.submit()
        xml, revision = self.artifact(job["id"], "musicxml")
        midi, _ = self.artifact(job["id"], "midi")
        entered, release = threading.Event(), threading.Event()
        original = server_module.run_command
        outcome = []

        def delayed(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            return original(*args, **kwargs)

        def edit():
            try:
                outcome.append(self.service.edit(job["id"], revision=revision,
                                                edits=[{"partId": "P1", "measureIndex": 0, "noteIndex": 0, "step": "E"}]))
            except Exception as error:
                outcome.append(error)

        with patch.object(server_module, "run_command", side_effect=delayed):
            thread = threading.Thread(target=edit)
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                self.assert_unchanged(job["id"], revision, xml, midi)
                with self.assertRaises(server_module.APIError) as error:
                    self.service.edit(job["id"], revision=revision,
                                      edits=[{"partId": "P1", "measureIndex": 0, "noteIndex": 0, "step": "F"}])
                self.assertEqual(error.exception.status, 409)
            finally:
                release.set()
                thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(outcome), 1)
        self.assertIsInstance(outcome[0], dict, outcome)
        self.assertEqual(sounding_pitches(self.artifact(job["id"], "midi")[0]), [64, 62])

    def test_successful_job_reopens_after_restart_with_same_artifacts(self):
        job = self.submit("保留原稿.musicxml")
        xml, revision = self.artifact(job["id"], "musicxml")
        midi, _ = self.artifact(job["id"], "midi")
        self.service.close()
        self.service = server_module.JobService(self.storage, TOKEN, midi_command=self.command, timeout=10, midi_timeout=20)
        self.assertEqual(self.service.get(job["id"])["filename"], "保留原稿.musicxml")
        self.assertEqual(self.service.get(job["id"])["state"], "succeeded")
        self.assert_unchanged(job["id"], revision, xml, midi)
        self.assertEqual(self.artifact(job["id"], "original")[0], SCORE_A)

    def test_full_rest_and_delete_all_notes_remain_legal_silent_midi(self):
        job = self.submit()
        base = {"partId": "P1", "measureIndex": 0}
        updated = self.service.edit(job["id"], edits=[{**base, "noteIndex": 0, "rest": True},
                                                     {**base, "noteIndex": 1, "rest": True}])
        self.assertEqual(sounding_pitches(self.artifact(job["id"], "midi")[0]), [])
        self.assertEqual(sum(note["rest"] for note in self.service.notes(job["id"])["notes"]), 2)
        self.service.edit(job["id"], revision=updated["revision"],
                          edits=[{**base, "noteIndex": 0, "delete": True}, {**base, "noteIndex": 1, "delete": True}])
        self.assertEqual(sounding_pitches(self.artifact(job["id"], "midi")[0]), [])
        self.assertEqual(self.service.notes(job["id"])["notes"], [])

    def test_unauthorized_read_all_job_routes_denied(self):
        job = self.submit()
        base = self.start_http()
        routes = ["/api/jobs", f'/api/jobs/{job["id"]}'] + [f'/api/jobs/{job["id"]}/{suffix}'
                  for suffix in ("score/notes", "score/musicxml", "score/midi", "original", "log", "project/omr")]
        for path in routes:
            with self.subTest(path=path):
                status, payload, headers = self.request(base, path, authenticated=False)
                self.assertEqual(status, 401, payload)
                self.assertEqual(headers.get("Cache-Control"), "no-store")
        status, payload, _ = self.request(base, f'/api/jobs/{job["id"]}/score/midi')
        self.assertEqual(status, 200)
        self.assertEqual(sounding_pitches(payload), [60, 62])

    def test_http_wrong_origin_invalid_types_and_revision_rejected(self):
        job = self.submit()
        base = self.start_http()
        path = f'/api/jobs/{job["id"]}/score/notes'
        valid = {"partId": "P1", "measureIndex": 0, "noteIndex": 0, "step": "E"}
        status, _, _ = self.request(base, path, method="PATCH", data=json.dumps(valid).encode(),
                                    headers={"Origin": "https://example.invalid"})
        self.assertEqual(status, 403)
        for extra in ({"step": 1}, {"partId": []}, {"type": []}, {"dot": True},
                      {"duration": float("nan")}, {"octave": 10 ** 400},
                      {"duration": 10 ** 400}, {"score": 10 ** 400}, {"revision": 0}):
            with self.subTest(extra=extra):
                status, payload, _ = self.request(base, path, method="PATCH",
                                                 data=json.dumps({**valid, **extra}).encode())
                self.assertIn(status, {400, 409}, payload)
        self.assertEqual(self.service.get(job["id"])["revision"], job["revision"])

    def test_external_dtd_not_fetched_and_utf16_entity_rejected_before_commit(self):
        calls = []

        class Capture(BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"private-test-token")

            def log_message(self, *_):
                pass

        trap = HTTPServer(("127.0.0.1", 0), Capture)
        thread = threading.Thread(target=trap.serve_forever, daemon=True)
        thread.start()
        plain = SCORE_A[SCORE_A.index(b"<score-partwise"):].decode()
        url = f"http://127.0.0.1:{trap.server_port}/remote.dtd"
        try:
            good = (f'<?xml version="1.0"?><!DOCTYPE score-partwise SYSTEM "{url}">\n' + plain).encode()
            job = self.submit("normal-external-doctype.musicxml", good)
            self.assertEqual(sounding_pitches(self.artifact(job["id"], "midi")[0]), [60, 62])
            xml, revision = self.artifact(job["id"], "musicxml")
            midi, _ = self.artifact(job["id"], "midi")
            malicious = f'<?xml version="1.0"?><!DOCTYPE score-partwise [<!ENTITY probe SYSTEM "{url}">]>' + plain.replace("Piano", "&probe;")
            for data in (malicious.encode(), malicious.encode("utf-16")):
                with self.subTest(encoding=data[:2]), self.assertRaises(server_module.APIError) as error:
                    self.service.edit(job["id"], data=data)
                self.assertEqual(error.exception.status, 400)
                self.assert_unchanged(job["id"], revision, xml, midi)
            self.assertEqual(calls, [])
        finally:
            trap.shutdown()
            trap.server_close()
            thread.join(timeout=5)

    def test_rejected_upload_releases_reservation_and_creates_no_job(self):
        for filename, data in (("../escape.png", b"not-a-png"), ("spoof.pdf", b"not-a-pdf"),
                               ("entity.musicxml", b'<!DOCTYPE score-partwise [<!ENTITY x "bad">]><score-partwise/>')):
            with self.subTest(filename=filename), self.assertRaises(server_module.APIError):
                self.service.submit(filename, io.BytesIO(data), len(data))
        self.assertEqual(self.service.reserved, 0)
        self.assertEqual(self.service.jobs, {})
        self.assertEqual(list(self.storage.iterdir()), [])
        self.submit()


if __name__ == "__main__":
    # Optional evidence output records the exact source tested, including skips.
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--report", type=Path)
    args, remaining = parser.parse_known_args()
    if not args.report:
        unittest.main(argv=[sys.argv[0], *remaining], verbosity=2)
    else:
        paths = [MODULE / "server.py", Path(__file__), MODULE / "lib" / "omr-midi.jar"]
        before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths if path.is_file()}
        records = []

        class EvidenceResult(unittest.TextTestResult):
            def startTest(self, test):
                self.started = time.monotonic()
                super().startTest(test)

            def record(self, test, status, detail=None):
                value = {"name": test.id(), "status": status, "elapsedSeconds": time.monotonic() - self.started}
                if detail:
                    value["detail"] = detail
                records.append(value)

            def addSuccess(self, test):
                super().addSuccess(test)
                self.record(test, "passed")

            def addFailure(self, test, err):
                super().addFailure(test, err)
                self.record(test, "failed", self._exc_info_to_string(err, test))

            def addError(self, test, err):
                super().addError(test, err)
                self.record(test, "error", self._exc_info_to_string(err, test))

            def addSkip(self, test, reason):
                super().addSkip(test, reason)
                self.record(test, "skipped", reason)

        started = time.monotonic()
        program = unittest.main(argv=[sys.argv[0], *remaining], exit=False,
                                testRunner=unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult))
        result = program.result
        after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths if path.is_file()}
        report = {"schemaVersion": 1, "timestampUTC": datetime.now(timezone.utc).isoformat(),
                  "scope": "Independent local HTTP/edit/persistence boundary tests with real Java MIDI; not Audiveris image-recognition or Linux deployment acceptance.",
                  "platform": platform.platform(), "pythonExecutable": sys.executable,
                  "pythonVersion": platform.python_version(), "converterCommand": converter_command(),
                  "sourceHashesBefore": before, "sourceHashesAfter": after,
                  "sourcesUnchangedDuringTests": before == after,
                  "elapsedSeconds": time.monotonic() - started,
                  "testsRun": result.testsRun, "passed": sum(record["status"] == "passed" for record in records),
                  "failed": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
                  "success": result.wasSuccessful() and not result.skipped and before == after,
                  "tests": records}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
        sys.exit(0 if report["success"] else 1)
