#!/usr/bin/env python3
"""Use real deployed-module source and Java MIDI exporter through the gateway.

This verifies XML import/edit/export compatibility. It does not run Linux OMR
on Windows or claim TLS/public deployment verification.
"""
import argparse
import hashlib
from http.client import HTTPConnection
import importlib.util
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
import xml.etree.ElementTree as ET

import gateway

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
XML = b'''<?xml version="1.0" encoding="utf-8"?>
<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
<part id="P1"><measure number="1"><attributes><divisions>4</divisions><key><fifths>0</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes>
<note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>quarter</type></note>
<note><pitch><step>E</step><octave>4</octave></pitch><duration>4</duration><type>quarter</type></note>
<note><rest/><duration>8</duration><type>half</type></note></measure></part></score-partwise>'''


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--module", type=Path, default=WORK / "server-omr/module/server.py")
    parser.add_argument("--java", type=Path, default=Path("D:/Chatgpt/toolchains/jdk-21.0.12.1+1/bin/java.exe"))
    parser.add_argument("--classpath", default=str(WORK / "server-omr/module/lib/omr-midi.jar") + os.pathsep + str(WORK / "server-omr/assets/opt/audiveris/lib/app/*"))
    parser.add_argument("--output", type=Path, default=HERE / "module-compatibility-report.json")
    args = parser.parse_args()
    omr = module(args.module, "existing_omr")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        service = omr.JobService(root / "omr", secrets.token_urlsafe(32), engine_command=["OMR_NOT_INVOKED_FOR_XML_IMPORT"], midi_command=[str(args.java), "-cp", args.classpath, "com.notelite.omr.score.OmrMidiConverter"])
        upstream = omr.Server(("127.0.0.1", 0), service)
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        store = gateway.Store(root / "gateway")
        server = gateway.Server(("127.0.0.1", 0), store, "https://124.221.211.156", service.token, upstream_port=upstream.server_port)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        token = None
        def call(method, path, body=None, extra=None):
            if isinstance(body, dict):
                body = json.dumps(body).encode()
            headers = {"Authorization": "Bearer " + token} if token else {}
            headers.update(extra or {})
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=30)
            try:
                connection.request(method, path, body, headers)
                response = connection.getresponse()
                data = response.read()
                is_json = response.getheader("Content-Type", "").startswith("application/json")
                return response.status, json.loads(data) if is_json else data, dict(response.getheaders())
            finally:
                connection.close()
        try:
            pair = store.pair()
            status, credential, _ = call("POST", "/api/pair", {"code": pair["code"], "deviceName": "Compatibility probe", "mode": "native"})
            assert status == 201, credential
            token = credential["token"]
            status, job, _ = call("POST", "/api/jobs?filename=probe.musicxml", XML)
            assert status == 202, job
            job_id = job["id"]
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                status, job, _ = call("GET", "/api/jobs/" + job_id)
                assert status == 200, job
                if job["state"] in {"succeeded", "failed"}:
                    break
                time.sleep(.1)
            assert job["state"] == "succeeded", job
            assert job["revision"] == 1 and len(job["scores"]) == 1, job
            base = "/api/jobs/" + job_id
            _, before_xml, _ = call("GET", base + "/score/musicxml")
            _, before_midi, _ = call("GET", base + "/score/midi")
            assert before_midi.startswith(b"MThd")
            _, listing, _ = call("GET", base + "/score/notes")
            assert len(listing["notes"]) == 3 and listing["revision"] == 1
            status, updated, _ = call("PATCH", base + "/score/notes", {"revision": 1, "score": 0, "edits": [{"partId": "P1", "measureIndex": 0, "noteIndex": 0, "pitch": {"step": "D", "octave": 5, "alter": 0}}]})
            assert status == 200 and updated["revision"] == 2, updated
            _, edited_xml, xml_headers = call("GET", base + "/score/musicxml")
            _, edited_midi, midi_headers = call("GET", base + "/score/midi")
            assert xml_headers["ETag"] == midi_headers["ETag"] == '"2"'
            assert edited_xml != before_xml and edited_midi != before_midi
            pitch = ET.fromstring(edited_xml).find("part/measure/note/pitch")
            assert pitch.findtext("step") == "D" and pitch.findtext("octave") == "5"
            assert call("PATCH", base + "/score/notes", {"revision": 1, "score": 0, "edits": [{"partId": "P1", "measureIndex": 0, "noteIndex": 0, "duration": 8}]})[0] == 409
            assert call("PUT", base + "/score", b"<bad>", {"If-Match": '"2"'})[0] == 400
            _, after_failure, _ = call("GET", base + "/score/midi")
            assert after_failure == edited_midi
            assert call("GET", "/api/jobs")[1]["jobs"][0]["id"] == job_id
            output = {"status": "passed", "actual_upstream_source": str(args.module.absolute()), "actual_java_midi_exporter": True, "linux_omr_not_executed": True, "public_tls_not_tested": True, "passed_checks": ["native_pairing", "raw_XML_job_upload", "actual_Module_JobService", "actual_Java_MIDI", "full_job_and_note_schema", "pitch_edit_changes_XML_and_MIDI", "matching_revision_ETags", "stale_revision_409", "invalid_XML_rollback", "owner_job_list"], "before_midi_sha256": hashlib.sha256(before_midi).hexdigest(), "after_midi_sha256": hashlib.sha256(edited_midi).hexdigest(), "credentials_logged": False}
            args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf8")
            print(json.dumps(output))
        finally:
            server.shutdown()
            server.server_close()
            upstream.shutdown()
            upstream.server_close()
            service.close()


if __name__ == "__main__":
    main()
