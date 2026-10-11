"""Meaningful HTTP security/ownership regression tests; no simulated OMR claims."""
import hashlib
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import tempfile
import threading
import time
import unittest
from urllib.parse import urlsplit
import uuid

import gateway


class UpstreamHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, status, value, mime="application/json"):
        data = json.dumps(value).encode() if isinstance(value, (dict, list)) else value
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Type", mime)
        self.send_header("ETag", '"1"')
        self.end_headers()
        self.wfile.write(data)

    def dispatch(self):
        self.server.received.append((self.command, self.path, dict(self.headers)))
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}" or self.headers.get("Origin"):
            self.reply(403, {"error": "host/origin incompatible"})
            return
        if self.headers.get("Authorization") != "Bearer " + self.server.token:
            self.reply(401, {"error": "administrator token required"})
            return
        path = urlsplit(self.path).path
        if path == "/api/health":
            self.reply(200, {"status": "ok", "engine": "Audiveris", "engineVersion": "5.11.0"})
        elif path == "/api/jobs" and self.command == "POST":
            self.rfile.read(int(self.headers["Content-Length"]))
            job = {"id": self.headers.get("X-NoteLite-Job-Id") or str(uuid.uuid4()), "state": "succeeded", "filename": "score.musicxml", "revision": 1, "scores": [], "artifacts": {}}
            if getattr(self.server, "upload_entered", None):
                self.server.upload_entered.set()
                self.server.upload_release.wait(5)
            self.server.jobs[job["id"]] = job
            if getattr(self.server, "lose_upload_response", False):
                self.close_connection = True
                return
            self.reply(202, job)
        elif path == "/api/jobs" and self.command == "GET":
            self.reply(200, {"jobs": list(self.server.jobs.values())})
        elif path.startswith("/api/jobs/"):
            pieces = path.split("/")
            job = self.server.jobs.get(pieces[3])
            if not job:
                self.reply(404, {"error": "job absent"})
            elif len(pieces) == 4:
                self.reply(200, job)
            elif self.command in {"PUT", "PATCH"}:
                body = self.rfile.read(int(self.headers["Content-Length"]))
                revision = int(self.headers.get("If-Match", "0").strip('"')) if self.command == "PUT" else json.loads(body)["revision"]
                if revision != job["revision"]:
                    self.reply(409, {"error": "stale revision"})
                else:
                    job["revision"] += 1
                    self.reply(200, job)
            elif path.endswith("musicxml"):
                self.reply(200, b'<?xml version="1.0"?><score-partwise><part-list/></score-partwise>', "application/vnd.recordare.musicxml+xml")
            elif path.endswith("/log"):
                self.reply(422, {"error": "future upstream accidentally echoes " + self.server.token})
            else:
                self.reply(200, {"revision": job["revision"], "parts": [], "notes": []})
        else:
            self.reply(404, {"error": "route absent"})

    do_GET = do_POST = do_PATCH = do_PUT = dispatch


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = gateway.Store(Path(self.temp.name))
        self.admin = secrets.token_urlsafe(32)
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
        self.upstream.token, self.upstream.jobs, self.upstream.received = self.admin, {}, []
        threading.Thread(target=self.upstream.serve_forever, daemon=True).start()
        self.server = gateway.Server(("127.0.0.1", 0), self.store, "https://124.221.211.156", self.admin, upstream_port=self.upstream.server_port)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.upstream.shutdown()
        self.upstream.server_close()
        self.temp.cleanup()

    def request(self, method, path, body=None, headers=None):
        if isinstance(body, dict):
            body = json.dumps(body).encode()
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            data = response.read()
            values = dict(response.getheaders())
            result = json.loads(data) if values.get("Content-Type", "").startswith("application/json") else data
            return response.status, result, values
        finally:
            connection.close()

    def pair(self, owner=None, kind="native"):
        pair = self.store.pair(owner)
        headers = {"Origin": self.server.origin} if kind == "browser" else {}
        status, result, response_headers = self.request("POST", "/api/pair", {"code": pair["code"], "deviceName": "Test iPad", "mode": kind}, headers)
        self.assertEqual(status, 201, result)
        return result, response_headers

    def create(self, device):
        status, result, _ = self.request("POST", "/api/jobs?filename=score.musicxml", b"<score-partwise/>", {"Authorization": "Bearer " + device["token"]})
        self.assertEqual(status, 202, result)
        return result

    def test_health_and_public_host_origin_validation(self):
        status, health, _ = self.request("GET", "/api/health", headers={"Host": "124.221.211.156", "Origin": self.server.origin})
        self.assertEqual(status, 200)
        self.assertEqual(health["engine"], "NoteLite")
        self.assertEqual(health["engineVersion"], "5.11.0")
        self.assertEqual(health["authentication"], "device-or-session")
        self.assertEqual(self.request("GET", "/api/health", headers={"Host": "attacker.example"})[0], 403)
        self.assertEqual(self.request("GET", "/api/health", headers={"Origin": "null"})[0], 403)
        self.assertEqual(self.request("GET", "/api/health", headers={"Origin": "https://attacker.example"})[0], 403)

    def test_pair_once_expires_and_credentials_not_admin_or_stored_plaintext(self):
        pair = self.store.pair()
        body = {"code": pair["code"], "deviceName": "iPhone", "mode": "native"}
        status, device, _ = self.request("POST", "/api/pair", body)
        self.assertEqual(status, 201)
        self.assertNotEqual(device["token"], self.admin)
        self.assertNotIn("csrf", device)
        self.assertEqual(self.request("POST", "/api/pair", body)[0], 401)
        expired = self.store.pair(ttl=-1)
        self.assertEqual(self.request("POST", "/api/pair", dict(body, code=expired["code"]))[0], 401)
        stored = self.store.path.read_bytes()
        self.assertNotIn(device["token"].encode(), stored)
        self.assertNotIn(pair["code"].encode(), stored)
        self.assertNotIn(self.admin.encode(), stored)

    def test_admin_internal_token_does_not_authenticate_client(self):
        self.assertEqual(self.request("GET", "/api/jobs", headers={"Authorization": "Bearer " + self.admin})[0], 401)
        self.assertEqual(self.request("GET", "/api/jobs")[0], 401)

    def test_job_owner_filter_blocks_other_owner_and_admin_fixtures(self):
        first, _ = self.pair()
        own = self.create(first)
        second, _ = self.pair(str(uuid.uuid4()))
        other = self.create(second)
        admin_job = str(uuid.uuid4())
        self.upstream.jobs[admin_job] = {"id": admin_job, "revision": 1}
        headers = {"Authorization": "Bearer " + first["token"]}
        self.assertEqual(self.request("GET", "/api/jobs")[0], 401)
        status, value, _ = self.request("GET", "/api/jobs", headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual([job["id"] for job in value["jobs"]], [own["id"]])
        for job in (other["id"], admin_job):
            for suffix in ("", "/score/musicxml", "/score/midi", "/original", "/project/omr", "/log"):
                self.assertEqual(self.request("GET", "/api/jobs/" + job + suffix, headers=headers)[0], 404)
            self.assertEqual(self.request("PATCH", "/api/jobs/" + job + "/score/notes", {"revision": 1}, headers)[0], 404)

    def test_same_owner_separate_device_and_restart_persist(self):
        first, _ = self.pair()
        job = self.create(first)
        second, _ = self.pair(first["owner"])
        self.assertNotEqual(first["token"], second["token"])
        self.assertEqual(self.request("GET", "/api/jobs/" + job["id"], headers={"Authorization": "Bearer " + second["token"]})[0], 200)
        reloaded = gateway.Store(Path(self.temp.name))
        reloaded.own(job["id"], first["owner"])
        self.assertEqual(reloaded.device(second["token"], "native")["owner"], first["owner"])

    def test_fixed_upstream_host_admin_header_and_no_browser_headers(self):
        first, _ = self.pair()
        job = self.create(first)
        status, data, headers = self.request("GET", "/api/jobs/" + job["id"] + "/score/musicxml?score=0", headers={"Authorization": "Bearer " + first["token"], "Origin": self.server.origin, "Cookie": "bad=untrusted", "X-Forwarded-Host": "attacker.example"})
        self.assertEqual(status, 200)
        self.assertTrue(data.startswith(b"<?xml"))
        self.assertEqual(headers["ETag"], '"1"')
        received = self.upstream.received[-1][2]
        self.assertEqual(received["Host"], f"127.0.0.1:{self.upstream.server_port}")
        self.assertEqual(received["Authorization"], "Bearer " + self.admin)
        self.assertNotIn("Origin", received)
        self.assertNotIn("Cookie", received)
        self.assertNotIn("X-Forwarded-Host", received)

    def test_browser_pair_session_cookie_csrf_and_revoke(self):
        device, response_headers = self.pair(kind="browser")
        self.assertNotIn("token", device)
        cookie_header = response_headers["Set-Cookie"]
        for attribute in ("Secure", "HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(attribute, cookie_header)
        cookie = cookie_header.split(";", 1)[0]
        status, session, _ = self.request("GET", "/api/session", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertEqual(session["csrf"], device["csrf"])
        self.assertEqual(self.request("POST", "/api/jobs?filename=score.xml", b"<xml/>", {"Cookie": cookie, "Origin": self.server.origin})[0], 403)
        headers = {"Cookie": cookie, "Origin": self.server.origin, "X-NoteLite-CSRF": device["csrf"]}
        status, job, _ = self.request("POST", "/api/jobs?filename=score.xml", b"<xml/>", headers)
        self.assertEqual(status, 202)
        status, _, _ = self.request("PATCH", "/api/jobs/" + job["id"] + "/score/notes", {"revision": 1, "score": 0, "edits": []}, headers)
        self.assertEqual(status, 200)
        self.assertEqual(self.request("POST", "/api/session/logout", b"{}", headers)[0], 200)
        self.assertEqual(self.request("GET", "/api/session", headers={"Cookie": cookie})[0], 401)

    def test_revision_required_and_conflict_keeps_existing_revision(self):
        device, _ = self.pair()
        job = self.create(device)
        headers = {"Authorization": "Bearer " + device["token"]}
        patch = "/api/jobs/" + job["id"] + "/score/notes"
        self.assertEqual(self.request("PATCH", patch, {"edits": []}, headers)[0], 400)
        self.assertEqual(self.request("PATCH", patch, {"revision": 1, "edits": []}, headers)[0], 200)
        self.assertEqual(self.request("PATCH", patch, {"revision": 1, "edits": []}, headers)[0], 409)
        self.assertEqual(self.upstream.jobs[job["id"]]["revision"], 2)
        put = "/api/jobs/" + job["id"] + "/score?score=0"
        self.assertEqual(self.request("PUT", put, b"<xml/>", headers)[0], 400)
        self.assertEqual(self.request("PUT", put, b"<xml/>", dict(headers, **{"If-Match": '"2"'}))[0], 200)

    def test_route_allowlist_rejects_encoded_ids_and_absolute_urls(self):
        device, _ = self.pair()
        headers = {"Authorization": "Bearer " + device["token"]}
        for route in ("/api/jobs/../../access-token", "/api/jobs/%2e%2e/score", "http://attacker.example/api/jobs", "/api/admin", "/api/jobs?filename=a&filename=b"):
            self.assertIn(self.request("GET", route, headers=headers)[0], (400, 403, 404))
        job = self.create(device)
        self.assertEqual(self.request("DELETE", "/api/jobs/" + job["id"], headers=headers)[0], 405)

    def test_internal_token_redacted_even_from_upstream_error(self):
        device, _ = self.pair()
        job = self.create(device)
        status, value, _ = self.request("GET", "/api/jobs/" + job["id"] + "/log", headers={"Authorization": "Bearer " + device["token"]})
        self.assertEqual(status, 422)
        self.assertNotIn(self.admin, json.dumps(value))
        self.assertIn("已隐藏", value["error"])

    def test_oversize_and_unsupported_body_framing(self):
        device, _ = self.pair()
        headers = {"Authorization": "Bearer " + device["token"], "Content-Length": str(gateway.MAX_UPLOAD + 1)}
        self.assertEqual(self.request("POST", "/api/jobs?filename=score.xml", b"", headers)[0], 413)
        self.assertEqual(self.request("POST", "/api/jobs?filename=score.xml", b"x", dict(headers, **{"Content-Length": "1", "Content-Encoding": "gzip"}))[0], 400)

    def test_native_session_logout_revokes_device(self):
        device, _ = self.pair()
        headers = {"Authorization": "Bearer " + device["token"]}
        self.assertEqual(self.request("GET", "/api/session", headers=headers)[0], 200)
        self.assertEqual(self.request("POST", "/api/session/logout", b"{}", headers)[0], 200)
        self.assertEqual(self.request("GET", "/api/session", headers=headers)[0], 401)

    def test_pair_rate_limit_invalid_names_and_modes(self):
        valid = self.store.pair()
        body = {"code": valid["code"], "deviceName": "x\nsecret", "mode": "native"}
        self.assertEqual(self.request("POST", "/api/pair", body)[0], 400)
        for _ in range(5):
            self.request("POST", "/api/pair", {"code": "invalid", "deviceName": "iPad", "mode": "native"})
        self.assertEqual(self.request("POST", "/api/pair", dict(body, deviceName="iPad"))[0], 429)

    def test_pair_file_is_private_and_cannot_overwrite(self):
        path = Path(self.temp.name) / "device.pairing.json"
        pair = self.store.pair()
        gateway.private_json(path, pair)
        self.assertEqual(json.loads(path.read_text())["code"], pair["code"])
        with self.assertRaises(FileExistsError):
            gateway.private_json(path, {"code": "overwritten"})
        self.assertEqual(json.loads(path.read_text())["code"], pair["code"])


if __name__ == "__main__":
    unittest.main()
