"""Exercise actual HTTP and subprocess boundaries; fixture does not validate OMR accuracy."""

from __future__ import annotations

import http.client
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from urllib.parse import quote
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from notelite_bridge import APIError, BridgeServer, JavaEngine, JobService, MAX_UPLOAD


TOKEN = "test-token-never-use-in-production-123456789"
FIXTURE = Path(__file__).with_name("fake_engine.py")


def fixture_command(source, output):
    return [sys.executable, str(FIXTURE), "-batch", "-transcribe", "-export", "-export-midi",
            "-output", str(output), "--", str(source)]


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.service = JobService(Path(self.temporary.name), TOKEN, fixture_command,
                                  timeout=2, queue_size=1)
        self.server = BridgeServer(("127.0.0.1", 0), self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.service.close()
        self.temporary.cleanup()

    def request(self, method, path, body=None, headers=None, authenticate=True):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        values = {"Authorization": f"Bearer {TOKEN}"} if authenticate else {}
        values.update(headers or {})
        connection.request(method, path, body, values)
        response = connection.getresponse()
        status, data = response.status, response.read()
        content_type = response.getheader("Content-Type", "")
        connection.close()
        return status, json.loads(data) if data and "application/json" in content_type else data

    def submit(self, body=b"%PDF-1.7 test", filename="score.pdf"):
        return self.request("POST", "/v1/jobs?filename=" + quote(filename, safe=""), body)

    def finished(self, job_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status, job = self.request("GET", f"/v1/jobs/{job_id}")
            self.assertEqual(status, 200)
            if job["state"] in {"succeeded", "failed"}:
                return job
            time.sleep(0.02)
        self.fail("Job did not finish")

    def test_real_http_lifecycle_download_delete_and_restart(self):
        status, queued = self.submit(filename="练习 & score.pdf")
        self.assertEqual(status, 202)
        self.assertEqual(queued["state"], "queued")
        job = self.finished(queued["id"])
        self.assertEqual(job["state"], "succeeded")
        self.assertEqual(job["filename"], "练习 & score.pdf")
        self.assertIsNone(job["error"])
        self.assertEqual(len(job["artifacts"]), 3)
        musicxml = next(a for a in job["artifacts"] if a["name"].endswith(".musicxml"))
        status, data = self.request("GET", musicxml["path"])
        self.assertEqual((status, data), (200, b'<score-partwise version="4.0"/>'))
        self.assertEqual(self.request("GET", musicxml["path"], authenticate=False)[0], 401)
        self.assertEqual(self.request("GET", f'/v1/jobs/{job["id"]}/artifacts/../../job.json')[0], 404)
        # A new service instance recovers metadata and artifacts, without rerunning the engine.
        self.service.close()
        self.service = JobService(Path(self.temporary.name), TOKEN, fixture_command)
        self.server.service = self.service
        self.assertEqual(self.request("GET", f'/v1/jobs/{job["id"]}')[1], job)
        self.assertEqual(self.request("DELETE", f'/v1/jobs/{job["id"]}')[0], 204)
        self.assertEqual(self.request("GET", f'/v1/jobs/{job["id"]}')[0], 404)
        self.assertFalse((Path(self.temporary.name) / job["id"]).exists())

    def test_health_public_jobs_and_uploads_require_authentication(self):
        self.assertEqual(self.request("GET", "/v1/health", authenticate=False), (200, {"status": "ok"}))
        self.assertEqual(self.request("POST", "/v1/jobs?filename=score.pdf", b"%PDF-1.7",
                                      authenticate=False)[0], 401)
        self.assertEqual(self.request("GET", "/v1/jobs/" + str(uuid.uuid4()),
                                      headers={"Authorization": "Bearer wrong"})[0], 401)
        self.assertEqual(self.service.jobs, {})

    def test_oversize_zero_malformed_and_missing_lengths(self):
        self.assertEqual(self.request("POST", "/v1/jobs?filename=score.pdf", b"",
                                      {"Content-Length": str(MAX_UPLOAD + 1)})[0], 413)
        self.assertEqual(self.submit(b"")[0], 413)
        self.assertEqual(self.request("POST", "/v1/jobs?filename=score.pdf", b"",
                                      {"Content-Length": "-1"})[0], 400)
        self.assertEqual(self.request("POST", "/v1/jobs?filename=score.pdf", b"",
                                      {"Transfer-Encoding": "chunked"})[0], 400)
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        connection.putrequest("POST", "/v1/jobs?filename=score.pdf")
        connection.putheader("Authorization", f"Bearer {TOKEN}")
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual(response.status, 411)
        response.read()
        connection.close()
        self.assertEqual(self.service.jobs, {})

    def test_signature_extension_and_filename_validation(self):
        for filename, body, status in [
            ("../evil.pdf", b"%PDF-1.7", 400),
            ("C:\\evil.pdf", b"%PDF-1.7", 400),
            ("x\n.pdf", b"%PDF-1.7", 400),
            ("x.svg", b"<svg/>", 415),
            ("x.png", b"%PDF-1.7", 415),
        ]:
            with self.subTest(filename=filename):
                self.assertEqual(self.submit(body, filename)[0], status)
        self.assertEqual(list(Path(self.temporary.name).iterdir()), [])
        self.assertEqual(self.request("POST", "/v1/jobs?filename=x.pdf&filename=y.pdf", b"x")[0], 400)

    def test_boundary_and_truncated_upload_release_capacity(self):
        self.service.max_upload = 16
        with self.assertRaises(APIError) as error:
            self.service.submit("x.pdf", io.BytesIO(b"%PDF-"), 10)
        self.assertEqual(error.exception.status, 400)
        self.assertEqual(self.service.reserved, 0)
        self.assertEqual(self.submit(b"%PDF-" + b"x" * 11)[0], 202)
        self.assertEqual(self.submit(b"%PDF-" + b"x" * 12)[0], 413)

    def test_rejected_upload_cleanup_failure_does_not_leak_capacity(self):
        self.service.max_jobs = 1
        with self.assertLogs("notelite.bridge", level="ERROR") as messages:
            with mock.patch("notelite_bridge.shutil.rmtree", side_effect=OSError("File temporarily locked")):
                status, error = self.submit(b"invalid PDF")
        self.assertEqual(status, 415)
        self.assertIn("contents do not match", error["error"])
        self.assertIn("Could not remove rejected upload directory", messages.output[0])
        self.assertEqual(self.service.reserved, 0)
        status, queued = self.submit()
        self.assertEqual(status, 202)
        self.assertEqual(self.finished(queued["id"])["state"], "succeeded")

    def test_queue_bound_and_running_delete_conflict(self):
        status, first = self.submit(b"%PDF-1.7 SLOW")
        self.assertEqual(status, 202)
        status, second = self.submit(b"%PDF-1.7 SLOW")
        self.assertEqual(status, 202)
        self.assertEqual(self.submit()[0], 503)
        self.assertEqual(self.request("DELETE", f'/v1/jobs/{first["id"]}')[0], 409)
        self.assertEqual(self.finished(second["id"])["state"], "succeeded")
        self.assertEqual(self.submit()[0], 202)

    def test_failure_exit_and_no_export_are_not_success(self):
        for directive, error_text in [(b"FAIL", "status 7"), (b"NO_EXPORT", "No MusicXML")]:
            with self.subTest(directive=directive):
                _, queued = self.submit(b"%PDF-1.7 " + directive)
                job = self.finished(queued["id"])
                self.assertEqual(job["state"], "failed")
                self.assertIn(error_text, job["error"])
                self.assertEqual(job["artifacts"], [])

    def test_process_deadline_kills_worker_process_and_allows_next_job(self):
        self.service.timeout = 0.2
        _, queued = self.submit(b"%PDF-1.7 TIMEOUT")
        job = self.finished(queued["id"])
        self.assertEqual(job["state"], "failed")
        self.assertIn("time limit", job["error"])
        self.service.timeout = 2
        _, queued = self.submit()
        self.assertEqual(self.finished(queued["id"])["state"], "succeeded")

    def test_storage_limit_and_delete_release_capacity(self):
        self.service.max_jobs = 1
        _, queued = self.submit()
        self.finished(queued["id"])
        self.assertEqual(self.submit()[0], 503)
        self.assertEqual(self.request("DELETE", f'/v1/jobs/{queued["id"]}')[0], 204)
        self.assertEqual(self.submit()[0], 202)

    def test_restart_marks_incomplete_jobs_failed(self):
        self.service.close()
        job_id = str(uuid.uuid4())
        directory = Path(self.temporary.name) / job_id
        directory.mkdir()
        (directory / "job.json").write_text(json.dumps({"id": job_id, "filename": "score.pdf",
            "state": "running", "error": None}), encoding="utf-8")
        self.service = JobService(Path(self.temporary.name), TOKEN, fixture_command)
        self.server.service = self.service
        status, job = self.request("GET", f"/v1/jobs/{job_id}")
        self.assertEqual(status, 200)
        self.assertEqual(job["state"], "failed")
        self.assertIn("restart", job["error"])

    def test_invalid_token_and_real_engine_command(self):
        with self.assertRaises(ValueError):
            JobService(Path(self.temporary.name), "short", fixture_command)
        engine = JavaEngine.__new__(JavaEngine)
        engine.java = "java"
        engine.distribution = Path(self.temporary.name)
        engine.heap = "4g"
        command = engine.command(Path("source.pdf"), Path("output"))
        self.assertEqual(command[-8:], ["-batch", "-transcribe", "-export", "-export-midi", "-output",
                                       "output", "--", "source.pdf"])
        self.assertIn("--enable-preview", command)
        self.assertIn("NoteLite", command)


if __name__ == "__main__":
    unittest.main()
