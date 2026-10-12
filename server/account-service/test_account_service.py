"""Real loopback HTTP + durable SQLite + filesystem integration tests.

Synthetic accounts and tiny generated WAV only; no production credentials.
"""
import hashlib
from email.message import Message
from http.client import HTTPConnection
from http.cookies import SimpleCookie
import io
import json
from pathlib import Path
import secrets
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid
import wave

import account_service as service


class AccountHTTPTests(unittest.TestCase):
    def test_17_rejected_origin_drains_only_bounded_unread_body_and_preserves_403(self):
        entered = threading.Event()
        discarded = []
        original = service.Handler.discard_rejected_body
        def observed(handler):
            entered.set()
            result = original(handler)
            discarded.append(result)
            return result
        body = json.dumps({"title": "Never created after rejected origin"}).encode("utf8")
        with self.store.connect() as db:
            before = db.execute("SELECT count(*) FROM courses").fetchone()[0]
        # Split headers and body deliberately. The rejection must wait only for
        # this bounded unread body instead of closing while it is still sent.
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        try:
            with patch.object(service.Handler, "discard_rejected_body", observed):
                connection.putrequest("POST", service.PREFIX + "/courses", skip_host=True)
                for name, value in {"Host": "notelite.example", "Origin": "https://attacker.example", "Authorization": "Bearer " + self.accounts["student"]["token"], "Content-Type": "application/json", "Content-Length": str(len(body))}.items():
                    connection.putheader(name, value)
                connection.endheaders()
                self.assertTrue(entered.wait(1), "origin must reject before parsing the delayed body")
                connection.send(body)
                response = connection.getresponse()
                self.assertEqual(response.status, 403)
                self.assertEqual(response.getheader("Connection"), "close")
                self.assertEqual(json.loads(response.read()), {"error": "请求来源无效。"})
            self.assertEqual(discarded, [len(body)])
        finally:
            connection.close()
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM courses").fetchone()[0], before)

        class Connection:
            def __init__(self): self.timeout, self.applied = 30, []
            def gettimeout(self): return self.timeout
            def settimeout(self, value): self.timeout = value; self.applied.append(value)
        def handler(headers, raw=b"abc", started=False):
            value = object.__new__(service.Handler)
            value.headers = Message()
            for name, content in headers: value.headers[name] = content
            value._body_started, value.connection = started, Connection()
            value.rfile = io.BufferedReader(io.BytesIO(raw))
            return value
        for headers, started in [
            ([("Content-Length", str(service.MAX_REJECT_DRAIN + 1))], False),
            ([("Content-Length", "3"), ("Content-Length", "3")], False),
            ([("Content-Length", "3"), ("Transfer-Encoding", "chunked")], False),
            ([("Content-Length", "3"), ("Expect", "100-continue")], False),
            ([("Content-Length", "3")], True),
        ]:
            value = handler(headers, started=started)
            self.assertEqual(value.discard_rejected_body(), 0)
            self.assertEqual(value.rfile.read(), b"abc", "ambiguous, large or consumed bodies must not be drained")
            self.assertEqual(value.connection.applied, [])
        value = handler([("Content-Length", "3")])
        value.rfile.read1 = lambda _: b"x"
        with patch.object(service.time, "monotonic", side_effect=[0, 0.1, 0.3]):
            self.assertEqual(value.discard_rejected_body(), 1, "dripping bytes cannot extend the absolute deadline")
        self.assertAlmostEqual(value.connection.applied[0], 0.15)
        self.assertEqual(value.connection.timeout, 30)

    def test_15_existing_short_credentials_are_verified_without_weakening_registration(self):
        short = "synthetic"
        new = self.checked(201, "POST", "/register", {"username": "legacy_short", "password": "synthetic long initial password", "mode": "native"})
        # A synthetic older credential, only in this temporary database. Public
        # registration must still reject a new password shorter than 15 chars.
        salt, digest = service.password_hash(short, creating=False)
        with self.store.connect() as db:
            db.execute("UPDATE users SET salt=?,password_hash=? WHERE id=?", (salt, digest, new["userId"]))
        self.checked(400, "POST", "/register", {"username": "short_new", "password": short, "mode": "native"})
        self.checked(401, "POST", "/login", {"username": "legacy_short", "password": "incorrect", "mode": "native"})
        self.checked(401, "POST", "/login", {"username": "unknown_short", "password": short, "mode": "native"})
        for invalid in ("", "x" * 257):
            self.checked(400, "POST", "/login", {"username": "legacy_short", "password": invalid, "mode": "native"})
        authenticated = self.checked(201, "POST", "/login", {"username": "LEGACY_SHORT", "password": short, "mode": "native"})
        self.assertEqual(authenticated["userId"], new["userId"])
        self.accounts["legacy_short"] = authenticated
        self.checked(403, "DELETE", "/account", {"password": "incorrect", "confirmation": "DELETE_ACCOUNT"}, "legacy_short")
        deleted = self.checked(200, "DELETE", "/account", {"password": short, "confirmation": "DELETE_ACCOUNT"}, "legacy_short")
        self.assertTrue(deleted["accountDeleted"])
        self.checked(401, "GET", "/me", account="legacy_short")

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.TemporaryDirectory()
        cls.moment = [1791766800.0]
        cls.store = service.Store(cls.root.name, clock=lambda: cls.moment[0])
        cls.server = service.Server(("127.0.0.1", 0), cls.store, "https://notelite.example", secrets.token_urlsafe(32))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.accounts = {}
        for name in ("teacher", "student", "outsider"):
            result = cls.call("POST", "/register", {"username": name, "password": "a test-only long password " + name, "mode": "native", "deviceName": name})
            if result[0] != 201:
                raise RuntimeError("test account creation failed")
            cls.accounts[name] = result[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        cls.server.server_close()
        cls.root.cleanup()

    def setUp(self):
        self.server.limiter.buckets.clear()
        self.moment[0] = 1791766800.0
        self.store.max_recording = 100 * 1024 * 1024
        self.store.recording_quota = 1024 ** 3
        self.store.disk_reserve = 256 * 1024 * 1024

    @classmethod
    def call(cls, method, route, body=None, account=None, extra=None, raw=False):
        headers = {"Host": "notelite.example"}
        if account:
            headers["Authorization"] = "Bearer " + cls.accounts[account]["token"]
        if extra:
            headers.update(extra)
        if body is not None:
            body = body if raw else json.dumps(body, ensure_ascii=False).encode("utf8")
            headers.setdefault("Content-Type", "application/octet-stream" if raw else "application/json")
        connection = HTTPConnection("127.0.0.1", cls.server.server_port, timeout=10)
        connection.request(method, service.PREFIX + route if route.startswith("/") and not route.startswith("/internal/") else route, body, headers)
        response = connection.getresponse()
        data, returned = response.read(), dict(response.getheaders())
        if response.getheader("Content-Type", "").startswith("application/json"):
            data = json.loads(data)
        status = response.status
        connection.close()
        return status, data, returned

    def checked(self, expected, *args, **kwargs):
        result = self.call(*args, **kwargs)
        self.assertEqual(result[0], expected, result[1] if isinstance(result[1], dict) else "binary response")
        return result[1]

    def personal(self, owner="teacher"):
        return self.checked(201, "POST", "/scores", {"title": "Private exercise", "musicxml": service.SAMPLE_XML}, owner)

    def classroom(self, uses=50):
        course = self.checked(201, "POST", "/courses", {"title": "黑白键课堂"}, "teacher")
        shared = self.checked(201, "POST", "/courses/" + course["id"] + "/scores", {"sourceKind": "official", "scoreId": "notelite-four-notes-v1"}, "teacher")
        code = self.checked(201, "POST", "/courses/" + course["id"] + "/codes", {"maxUses": uses}, "teacher")
        return course, shared, code

    def history(self, score="notelite-four-notes-v1", source="official", mode="free", analysis=None):
        value = {"eventId": str(uuid.uuid4()), "sourceKind": source, "scoreId": score, "mode": mode, "durationSeconds": 30, "startedAt": "2026-10-11T23:39:20Z", "endedAt": "2026-10-11T23:39:50Z"}
        # Derive time from fixed server clock so fixture does not depend on date.
        value["startedAt"] = service.now_stamp(self.moment[0] - 60)
        value["endedAt"] = service.now_stamp(self.moment[0] - 30)
        if analysis is not None:
            value["analysis"] = analysis
        return value

    def assignment(self):
        course, shared, code = self.classroom()
        join = self.checked(200, "POST", "/course-codes/join", {"code": code["code"]}, "student")
        assignment = self.checked(201, "POST", "/courses/" + course["id"] + "/assignments", {"title": "练习第一小节", "courseScoreId": shared["id"], "dueAt": service.now_stamp(self.moment[0] + 3600), "requirements": "慢速练习，并提交自己的录音。"}, "teacher")
        return course, join, assignment

    def tiny_wav(self):
        data = io.BytesIO()
        with wave.open(data, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\0\0" * 100)
        return data.getvalue()

    def upload(self, assignment, data=None, sha=None):
        data = data or self.tiny_wav()
        uploaded = self.checked(201, "POST", "/uploads", {"assignmentId": assignment["id"], "size": len(data), "mime": "audio/wav", "sha256": sha or hashlib.sha256(data).hexdigest()}, "student")
        url = "/uploads/" + uploaded["uploadId"]
        self.checked(200, "PUT", url, data[:40], "student", {"Upload-Offset": "0"}, raw=True)
        self.checked(200, "PUT", url, data[40:], "student", {"Upload-Offset": "40"}, raw=True)
        return uploaded, data

    def test_01_two_device_sessions_share_uuid_and_durable_data(self):
        login = self.checked(201, "POST", "/login", {"username": "TEACHER", "password": "a test-only long password teacher", "mode": "native", "deviceName": "Second device"})
        self.assertEqual(login["userId"], self.accounts["teacher"]["userId"])
        self.assertNotEqual(login["sessionId"], self.accounts["teacher"]["sessionId"])
        score = self.personal()
        extra = {"Authorization": "Bearer " + login["token"]}
        self.checked(200, "GET", "/scores/" + score["id"], extra=extra)
        reopened = service.Store(self.root.name, clock=lambda: self.moment[0])
        self.assertEqual(reopened.authenticate(login["token"], "native")["user_id"], login["userId"])
        self.assertEqual(reopened.read_score(login["userId"], score["id"])[0]["revision"], 1)
        with self.store.connect() as db:
            values = " ".join(str(tuple(row)) for row in db.execute("SELECT * FROM users")) + " ".join(str(tuple(row)) for row in db.execute("SELECT * FROM sessions"))
        self.assertNotIn(login["token"], values)
        self.assertNotIn("a test-only long password teacher", values)
        self.assertEqual((service.SCRYPT_N, service.SCRYPT_R, service.SCRYPT_P), (2 ** 17, 8, 1))
        self.checked(401, "POST", "/login", {"username": "teacher", "password": "this is the wrong password", "mode": "native"})
        self.checked(400, "POST", "/register", {"username": "short", "password": "too short", "mode": "native"})
        self.checked(200, "DELETE", "/sessions/" + login["sessionId"], account="teacher")
        self.checked(401, "GET", "/me", extra=extra)
        self.checked(200, "GET", "/me", account="teacher")

    def test_02_browser_csrf_profile_origin_and_independent_logout(self):
        status, login, headers = self.call("POST", "/login", {"username": "student", "password": "a test-only long password student", "mode": "browser"}, extra={"Origin": self.server.origin})
        self.assertEqual(status, 201)
        self.assertNotIn("token", login)
        for property in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/"):
            self.assertIn(property, headers["Set-Cookie"])
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        browser = {"Cookie": cookie, "Origin": self.server.origin}
        first = self.checked(200, "GET", "/me", extra=browser)
        second = self.checked(200, "GET", "/me", extra=browser)
        self.assertEqual(first["csrf"], second["csrf"])
        self.checked(403, "POST", "/courses", {"title": "Blocked"}, extra=browser)
        browser["X-NoteLite-CSRF"] = login["csrf"]
        self.checked(201, "POST", "/courses", {"title": "Allowed"}, extra=browser)
        self.checked(403, "POST", "/courses", {"title": "Blocked"}, extra={**browser, "Origin": "https://attacker.example"})
        browser_token = cookie.split("=", 1)[1]
        self.checked(401, "GET", "/me", extra={"Authorization": "Bearer " + browser_token})
        self.checked(401, "GET", "/me", extra={"Cookie": service.COOKIE + "=" + self.accounts["student"]["token"]})
        self.checked(200, "POST", "/logout", extra=browser)
        self.checked(401, "GET", "/me", extra=browser)
        self.checked(200, "GET", "/me", account="student")

    def test_03_private_score_isolation_and_atomic_conflict(self):
        score = self.personal()
        route = "/scores/" + score["id"]
        self.checked(404, "GET", route, account="student")
        self.checked(404, "GET", route + "/musicxml", account="student")
        self.checked(404, "PUT", route, {"musicxml": service.SAMPLE_XML}, "student", {"If-Match": score["etag"]})
        self.checked(428, "PUT", route, {"musicxml": service.SAMPLE_XML}, "teacher")
        revised = service.SAMPLE_XML.replace("<step>C</step>", "<step>D</step>", 1)
        updated = self.checked(200, "PUT", route, {"musicxml": revised, "title": "Device 1 edit"}, "teacher", {"If-Match": score["etag"]})
        self.assertEqual(updated["revision"], 2)
        self.checked(409, "PUT", route, {"musicxml": service.SAMPLE_XML}, "teacher", {"If-Match": score["etag"]})
        status, xml, headers = self.call("GET", route + "/musicxml", account="teacher")
        self.assertEqual(status, 200)
        self.assertEqual(xml.decode(), revised)
        self.assertEqual(headers["ETag"], updated["etag"])
        self.checked(400, "POST", "/scores", {"title": "XXE", "musicxml": '<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/passwd">]><score-partwise>&x;</score-partwise>'}, "teacher")
        external = service.SAMPLE_XML.replace('<score-partwise version="4.0">', '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd"><score-partwise version="4.0">')
        accepted = self.checked(201, "POST", "/scores", {"title": "Real export external DTD", "musicxml": external}, "teacher")
        self.assertEqual(self.call("GET", "/scores/" + accepted["id"] + "/musicxml", account="teacher")[:2], (200, external.encode()))

    def test_04_official_history_dedup_pagination_and_no_fake_accuracy(self):
        catalog = self.checked(200, "GET", "/catalog", account="student")["scores"]
        self.assertEqual(catalog[0]["license"], "CC0-1.0")
        self.checked(200, "GET", "/catalog/notelite-four-notes-v1/musicxml", account="student")
        event = self.history()
        one = self.checked(201, "POST", "/history", event, "student")
        self.assertFalse(one["scoreValidated"])
        self.assertEqual(one["event"]["analysis"]["status"], "unanalysed")
        self.assertTrue(self.checked(200, "POST", "/history", event, "student")["duplicate"])
        self.checked(409, "POST", "/history", {**event, "durationSeconds": 29}, "student")
        self.checked(400, "POST", "/history", {**self.history(), "accuracy": 100}, "student")
        self.checked(400, "POST", "/history", {**self.history(), "analysis": {"status": "analysed", "source": "client-reported", "errors": []}}, "student")
        self.checked(400, "POST", "/history", {**self.history(), "durationSeconds": 60}, "student")
        page = self.checked(200, "GET", "/history?limit=1", account="student")
        self.assertIsNotNone(page["nextCursor"])
        self.checked(200, "GET", "/history?limit=1&cursor=" + page["nextCursor"], account="student")
        other = self.checked(200, "GET", "/history", account="outsider")
        self.assertNotIn(event["eventId"], [v["eventId"] for v in other["events"]])
        self.checked(404, "POST", "/history", self.history(self.personal()["id"], "personal"), "student")

    def test_05_course_code_preview_scope_limits_expiry_and_revoke(self):
        course, shared, code = self.classroom(uses=1)
        self.assertEqual(len(code["code"]), 6)
        self.assertTrue(all(c in service.CODE_ALPHABET for c in code["code"]))
        preview = self.checked(200, "POST", "/course-codes/preview", {"code": code["code"]}, "student")
        self.assertEqual(set(preview), {"courseId", "title", "teacher", "expiresAt", "sharingScope"})
        self.assertIn("不自动共享", preview["sharingScope"])
        first = self.checked(200, "POST", "/course-codes/join", {"code": code["code"]}, "student")
        again = self.checked(200, "POST", "/course-codes/join", {"code": code["code"]}, "student")
        self.assertTrue(again["alreadyJoined"])
        self.assertEqual(first["deliveredScores"], again["deliveredScores"])
        self.assertEqual(first["role"], "student")
        self.checked(409, "POST", "/course-codes/join", {"code": code["code"]}, "outsider")
        self.checked(404, "POST", "/courses/" + course["id"] + "/codes", {}, "student")
        self.checked(404, "GET", "/courses/" + course["id"] + "/roster", account="student")
        self.checked(404, "GET", "/courses/" + course["id"], account="outsider")
        fresh = self.checked(201, "POST", "/courses/" + course["id"] + "/codes", {"ttlSeconds": 60}, "teacher")
        self.moment[0] += 61
        self.checked(404, "POST", "/course-codes/join", {"code": fresh["code"]}, "outsider")
        self.moment[0] -= 61
        self.checked(200, "DELETE", "/courses/" + course["id"] + "/codes/" + fresh["codeId"], account="teacher")
        self.checked(404, "POST", "/course-codes/preview", {"code": fresh["code"]}, "outsider")
        with self.store.connect() as db:
            self.assertFalse(db.execute("SELECT 1 FROM codes WHERE hash=?", (code["code"],)).fetchone())

    def test_06_teacher_only_submitted_homework_recording_after_student_leaves(self):
        course, joined, assignment = self.assignment()
        student_score = joined["deliveredScores"][0]["id"]
        event = self.history(student_score, "personal", "follow", {"status": "uncertain", "source": "client-reported", "errors": [{"type": "uncertain", "measure": 1, "confidence": 0.4}]})
        self.checked(201, "POST", "/history", event, "student")
        uploaded, wav = self.upload(assignment)
        self.checked(409, "PUT", "/uploads/" + uploaded["uploadId"], b"abcd", "student", {"Upload-Offset": "0"}, raw=True)
        self.checked(404, "GET", "/uploads/" + uploaded["uploadId"], account="teacher")
        self.checked(404, "PUT", "/uploads/" + uploaded["uploadId"], b"abcd", "outsider", {"Upload-Offset": "0"}, raw=True)
        complete = self.checked(200, "POST", "/uploads/" + uploaded["uploadId"] + "/complete", account="student")
        self.assertTrue(complete["complete"])
        submitted = self.checked(201, "POST", "/assignments/" + assignment["id"] + "/submissions", {"eventId": event["eventId"], "uploadId": uploaded["uploadId"]}, "student")
        self.assertEqual(submitted["analysis"]["status"], "uncertain")
        self.assertFalse(submitted["analysis"]["verifiedByServer"])
        self.assertTrue(self.checked(200, "POST", "/assignments/" + assignment["id"] + "/submissions", {"eventId": event["eventId"], "uploadId": uploaded["uploadId"]}, "student")["duplicate"])
        teacher = self.checked(200, "GET", "/assignments/" + assignment["id"] + "/submissions", account="teacher")
        self.assertEqual(len(teacher["submissions"]), 1)
        self.assertEqual(teacher["submissions"][0]["student"], "student")
        audio_route = "/submissions/" + submitted["id"] + "/audio"
        self.assertEqual(self.call("GET", audio_route, account="teacher")[:2], (200, wav))
        self.assertEqual(self.call("GET", audio_route, account="student")[:2], (200, wav))
        status, portion, ranged = self.call("GET", audio_route, account="teacher", extra={"Range": "bytes=12-39"})
        self.assertEqual((status, portion), (206, wav[12:40]))
        self.assertEqual(ranged["Content-Range"], f"bytes 12-39/{len(wav)}")
        self.checked(416, "GET", audio_route, account="teacher", extra={"Range": "bytes=999999-"})
        self.checked(404, "GET", audio_route, account="outsider")
        original = self.call("GET", "/submissions/" + submitted["id"] + "/musicxml", account="teacher")
        self.assertEqual(original[:2], (200, service.SAMPLE_XML.encode()))
        self.checked(404, "GET", "/submissions/" + submitted["id"] + "/musicxml", account="outsider")
        self.checked(404, "GET", "/assignments/" + assignment["id"] + "/submissions", account="outsider")
        another_code = self.checked(201, "POST", "/courses/" + course["id"] + "/codes", {}, "teacher")
        self.checked(200, "POST", "/course-codes/join", {"code": another_code["code"]}, "outsider")
        self.assertEqual(self.checked(200, "GET", "/assignments/" + assignment["id"] + "/submissions", account="outsider")["submissions"], [])
        self.checked(404, "GET", audio_route, account="outsider")
        self.checked(404, "GET", "/submissions/" + submitted["id"], account="outsider")
        free_event = self.history(student_score, "personal", "free")
        self.checked(201, "POST", "/history", free_event, "student")
        self.checked(400, "POST", "/assignments/" + assignment["id"] + "/submissions", {"eventId": free_event["eventId"], "analysis": {"status": "analysed", "source": "client-reported", "errors": []}}, "student")
        self.checked(404, "POST", "/courses/" + course["id"] + "/assignments", {"title": "Self promotion", "courseScoreId": assignment["courseScoreId"]}, "student")
        self.checked(200, "DELETE", "/courses/" + course["id"] + "/membership", account="student")
        self.assertEqual(self.call("GET", audio_route, account="teacher")[:2], (200, wav))
        self.checked(404, "POST", "/uploads", {"assignmentId": assignment["id"], "size": len(wav), "mime": "audio/wav", "sha256": hashlib.sha256(wav).hexdigest()}, "student")
        private_history = self.checked(200, "GET", "/history", account="teacher")["events"]
        self.assertNotIn(event["eventId"], [e["eventId"] for e in private_history])

    def test_07_recording_integrity_real_format_and_quota_fail_closed(self):
        course, joined, assignment = self.assignment()
        uploaded, wav = self.upload(assignment, sha="0" * 64)
        self.checked(400, "POST", "/uploads/" + uploaded["uploadId"] + "/complete", account="student")
        bad = b"RIFF" + (100 - 8).to_bytes(4, "little") + b"WAVE" + b"x" * 88
        uploaded, _ = self.upload(assignment, bad)
        self.checked(400, "POST", "/uploads/" + uploaded["uploadId"] + "/complete", account="student")
        request = {"assignmentId": assignment["id"], "size": len(wav), "mime": "audio/wav", "sha256": hashlib.sha256(wav).hexdigest()}
        self.store.max_recording = 100
        self.checked(400, "POST", "/uploads", request, "student")
        self.store.max_recording = 100 * 1024 * 1024
        self.store.recording_quota = 100
        self.checked(413, "POST", "/uploads", request, "student")
        self.store.recording_quota = 1024 ** 3
        self.store.disk_reserve = 10 ** 18
        self.checked(507, "POST", "/uploads", request, "student")

    def test_08_unconfigured_ownership_and_migration_refuse_unverified_claims(self):
        self.checked(503, "POST", "/scores", {"title": "Unverified", "jobId": str(uuid.uuid4()), "scoreIndex": 0, "revision": 1}, "student")
        self.checked(503, "POST", "/legacy/claim", {"deviceToken": secrets.token_urlsafe(32), "deviceKind": "native"}, "student")
        self.checked(400, "POST", "/legacy/claim", {"deviceToken": secrets.token_urlsafe(32), "deviceKind": "native", "owner": self.accounts["teacher"]["userId"]}, "student")

    def test_09_internal_resolver_secret_profiles_and_no_credential_echo(self):
        request = {"token": self.accounts["teacher"]["token"], "kind": "native"}
        self.checked(404, "POST", "/internal/account/resolve", request)
        self.checked(404, "POST", "/internal/account/resolve", request, extra={"X-NoteLite-Internal-Key": "wrong"})
        resolved = self.checked(200, "POST", "/internal/account/resolve", request, extra={"X-NoteLite-Internal-Key": self.server.internal_key})
        self.assertEqual(resolved["owner"], self.accounts["teacher"]["userId"])
        self.assertNotIn(request["token"], json.dumps(resolved))
        self.assertNotIn(self.server.internal_key, json.dumps(resolved))
        self.checked(401, "POST", "/internal/account/resolve", {**request, "kind": "browser"}, extra={"X-NoteLite-Internal-Key": self.server.internal_key})

    def test_10_six_character_code_guessing_is_limited_by_account_and_ip(self):
        for _ in range(6):
            self.checked(404, "POST", "/course-codes/preview", {"code": "AAAAAA"}, "outsider")
        self.checked(429, "POST", "/course-codes/join", {"code": "AAAAAA"}, "outsider")
        self.server.limiter.buckets.clear()
        self.server.limiter.buckets[("course-code-ip", "127.0.0.1")] = [self.server.limiter.clock()] * 20
        self.checked(429, "POST", "/course-codes/preview", {"code": "AAAAAA"}, "student")
        self.server.limiter.buckets.clear()
        for _ in range(10):
            self.checked(401, "POST", "/login", {"username": "not_registered", "password": "a long invalid test password", "mode": "native"})
        self.checked(429, "POST", "/login", {"username": "not_registered", "password": "a long invalid test password", "mode": "native"})

    def test_11_duplicate_json_wrong_origin_host_and_oversize_are_rejected(self):
        self.checked(403, "GET", "/health", extra={"Host": "attacker.example"})
        self.checked(403, "GET", "/me", account="teacher", extra={"Origin": "https://attacker.example"})
        self.checked(400, "POST", "/scores", b'{"title":"a","title":"b","musicxml":"x"}', "teacher", {"Content-Type": "application/json"}, raw=True)
        self.checked(415, "POST", "/scores", b"abcd", "teacher", raw=True)
        self.checked(400, "GET", "/history?limit=1&limit=2", account="teacher")
        self.checked(404, "GET", "/scores/%2e%2e", account="teacher")

    def test_12_practice_snapshot_survives_later_edits_and_retry_after_edit(self):
        score = self.personal("student")
        event = {**self.history(score["id"], "personal"), "scoreRevision": 1}
        recorded = self.checked(201, "POST", "/history", event, "student")
        self.assertEqual(recorded["event"]["scoreSha256"], hashlib.sha256(service.SAMPLE_XML.encode()).hexdigest())
        changed = service.SAMPLE_XML.replace("<step>C</step>", "<step>G</step>", 1)
        self.checked(200, "PUT", "/scores/" + score["id"], {"musicxml": changed}, "student", {"If-Match": score["etag"]})
        self.assertTrue(self.checked(200, "POST", "/history", event, "student")["duplicate"])
        xml_route = "/history/" + event["eventId"] + "/musicxml"
        self.assertEqual(self.call("GET", xml_route, account="student")[:2], (200, service.SAMPLE_XML.encode()))
        self.checked(404, "GET", xml_route, account="teacher")
        self.checked(409, "POST", "/history", {**self.history(score["id"], "personal"), "scoreRevision": 1}, "student")

    def test_13_score_creation_request_id_is_idempotent_and_scoped(self):
        request = {"requestId": str(uuid.uuid4()), "title": "Offline practice copy", "musicxml": service.SAMPLE_XML}
        created = self.checked(201, "POST", "/scores", request, "student")
        duplicate = self.checked(200, "POST", "/scores", request, "student")
        self.assertEqual(created["id"], duplicate["id"])
        self.assertTrue(duplicate["duplicate"])
        self.checked(409, "POST", "/scores", {**request, "title": "Different title"}, "student")
        other = self.checked(201, "POST", "/scores", request, "outsider")
        self.assertNotEqual(created["id"], other["id"])

    def test_14_account_switch_hint_never_authorizes_another_identity(self):
        before = len(self.checked(200, "GET", "/scores", account="student")["scores"])
        wrong = {"X-NoteLite-Expected-User": self.accounts["teacher"]["userId"]}
        self.checked(409, "POST", "/scores", {"title": "Stale account upload", "musicxml": service.SAMPLE_XML}, "student", wrong)
        after = len(self.checked(200, "GET", "/scores", account="student")["scores"])
        self.assertEqual(before, after)
        valid = {"X-NoteLite-Expected-User": self.accounts["student"]["userId"]}
        self.checked(201, "POST", "/scores", {"title": "Confirmed identity", "musicxml": service.SAMPLE_XML}, "student", valid)
        self.checked(401, "GET", "/scores", extra=valid)


class OwnershipHookTests(unittest.TestCase):
    def test_revision_and_owner_must_be_verified_before_linked_xml_is_stored(self):
        with tempfile.TemporaryDirectory() as root:
            owned, job = str(uuid.uuid4()), str(uuid.uuid4())
            calls = []
            def hook(user_id, job_id, index, revision):
                calls.append((user_id, job_id, index, revision))
                if user_id != owned or job_id != job:
                    raise service.APIError(404, "任务不存在。")
                if revision != 3 or index != 0:
                    raise service.APIError(409, "版本已改变。")
                return service.SAMPLE_XML
            store = service.Store(root, omr_import=hook)
            with store.connect() as db:
                db.execute("INSERT INTO users VALUES(?,?,?,?,?)", (owned, "owned", "salt", "test-only-fixture", 1))
            valid = {"title": "Verified import", "jobId": job, "scoreIndex": 0, "revision": 3}
            score = store.create_score(owned, valid)
            self.assertEqual(score["omr"], {"jobId": job, "scoreIndex": 0, "revision": 3})
            with self.assertRaises(service.APIError) as blocked:
                store.create_score(str(uuid.uuid4()), valid)
            self.assertEqual(blocked.exception.status, 404)
            with self.assertRaises(service.APIError) as stale:
                store.create_score(owned, {**valid, "revision": 2})
            self.assertEqual(stale.exception.status, 409)
            self.assertEqual(len(store.list_scores(owned)), 1)
            self.assertEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
