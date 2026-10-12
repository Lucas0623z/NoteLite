"""Owner-scoped settings/export: real HTTP and SQLite, synthetic accounts only."""
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import uuid

import account_service as service
import test_account_service as fixtures


class AccountProfileTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.AccountHTTPTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.AccountHTTPTests.tearDownClass.__func__)
    call = classmethod(fixtures.AccountHTTPTests.call.__func__)
    checked = fixtures.AccountHTTPTests.checked
    history = fixtures.AccountHTTPTests.history

    def setUp(self):
        fixtures.AccountHTTPTests.setUp(self)
        with self.store.connect() as db:
            db.execute("DELETE FROM profile_requests")
            db.execute("DELETE FROM profiles")

    def read(self, owner="teacher", headers=None):
        return self.checked(200, "GET", "/profile", account=owner, extra=headers)

    def write(self, changes, etag='"profile-0"', owner="teacher", request_id=None, expected=200, headers=None):
        return self.checked(expected, "PUT", "/profile", {"requestId": request_id or str(uuid.uuid4()), "changes": changes}, owner, {"If-Match": etag, **(headers or {})})

    def test_default_is_stable_owner_scoped_and_read_does_not_create_a_profile(self):
        self.assertEqual(self.call("GET", "/profile")[0], 401)
        status, value, headers = self.call("GET", "/profile", account="teacher")
        self.assertEqual(status, 200)
        self.assertEqual(value["userId"], self.accounts["teacher"]["userId"])
        self.assertEqual(value["revision"], 0)
        self.assertEqual(headers["ETag"], '"profile-0"')
        self.assertEqual(value["preferences"], self.store.default_preferences())
        self.assertEqual(self.read(), value)
        self.assertNotEqual(self.read("student")["userId"], value["userId"])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM profiles").fetchone()[0], 0)

    def test_two_sessions_read_same_persistent_profile_and_partial_options_merge(self):
        second = self.store.login({"username": "teacher", "password": "a test-only long password teacher", "mode": "native"})
        first = self.write({"displayName": "练琴者", "email": "public@example.test", "phone": "+86 123", "selectedCourse": "打击乐-钢琴", "options": {"音效": True, "连胜提醒": False}})
        via_second = self.checked(200, "GET", "/profile", extra={"Authorization": "Bearer " + second["token"]})
        self.assertEqual(via_second, first)
        changed = self.write({"theme": "dark", "options": {"连胜提醒": True}}, first["etag"])
        self.assertEqual(changed["revision"], 2)
        self.assertEqual(changed["preferences"]["displayName"], "练琴者")
        self.assertEqual(changed["preferences"]["options"], {"音效": True, "连胜提醒": True})
        self.assertEqual(self.read("student")["preferences"], self.store.default_preferences())

    def test_concurrent_same_etag_has_one_winner_and_one_412_without_lost_update(self):
        def submit(name):
            return self.call("PUT", "/profile", {"requestId": str(uuid.uuid4()), "changes": {"displayName": name}}, "teacher", {"If-Match": '"profile-0"'})
        with ThreadPoolExecutor(2) as executor:
            results = list(executor.map(submit, ["Device A", "Device B"]))
        self.assertEqual(sorted(r[0] for r in results), [200, 412])
        winner = next(r[1] for r in results if r[0] == 200)
        self.assertEqual(self.read(), winner)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM profile_requests").fetchone()[0], 1)

    def test_lost_response_replay_returns_original_even_after_another_device_update(self):
        request_id = str(uuid.uuid4())
        changes = {"displayName": "First persisted update", "options": {"音效": False}}
        first = self.write(changes, request_id=request_id)
        latest = self.write({"displayName": "Other device"}, first["etag"])
        self.assertEqual(self.write(changes, request_id=request_id), first)
        self.assertEqual(self.read(), latest)
        self.write({"displayName": "Different request content"}, request_id=request_id, expected=409)
        self.assertEqual(self.read(), latest)

    def test_request_id_is_per_owner_and_cannot_select_another_owner_in_body(self):
        request_id = str(uuid.uuid4())
        self.write({"displayName": "Teacher only"}, request_id=request_id)
        student = self.write({"displayName": "Student only"}, owner="student", request_id=request_id)
        self.assertEqual(student["revision"], 1)
        self.assertEqual(student["preferences"]["displayName"], "Student only")
        self.checked(400, "PUT", "/profile", {"requestId": str(uuid.uuid4()), "changes": {}, "userId": self.accounts["student"]["userId"]}, "teacher", {"If-Match": '"profile-1"'})
        self.assertEqual(self.read()["preferences"]["displayName"], "Teacher only")

    def test_precondition_is_mandatory_and_weak_or_wildcard_tags_do_not_write(self):
        body = {"requestId": str(uuid.uuid4()), "changes": {"theme": "dark"}}
        self.assertEqual(self.call("PUT", "/profile", body, "teacher")[0], 428)
        for etag in ('"profile-1"', '*', 'W/"profile-0"'):
            self.write({"theme": "dark"}, etag=etag, expected=412)
        self.assertEqual(self.read()["revision"], 0)

    def test_fields_types_control_characters_and_prototype_keys_are_rejected(self):
        invalid = [
            {"extra": True}, {"displayName": None}, {"displayName": "x" * 81}, {"displayName": "unsafe\nname"},
            {"email": "x" * 255}, {"phone": 123}, {"phone": "x" * 41}, {"avatar": "svg"}, {"avatar": []},
            {"theme": True}, {"theme": "system"}, {"selectedCourse": "foreign-course-id"}, {"selectedCourse": []},
            {"options": []}, {"options": {"音效": 1}}, {"options": {"__proto__": True}}, {"options": {"prototype": True}},
            {"options": {"constructor": True}}, {"options": {"\x00": True}}, {"options": {"x" * 81: True}},
            {"avatarImage": 7}, {"avatarImage": "data:image/svg+xml;base64,PHN2Zz4="},
        ]
        for changes in invalid:
            with self.subTest(changes=next(iter(changes))):
                self.write(changes, expected=400)
        self.assertEqual(self.read()["revision"], 0)
        for body in ({"changes": {}}, {"requestId": "not-a-uuid", "changes": {}}, {"requestId": str(uuid.uuid4()), "changes": None}):
            self.assertEqual(self.call("PUT", "/profile", body, "teacher", {"If-Match": '"profile-0"'})[0], 400)

    def test_avatar_formats_are_bounded_and_container_signature_must_match(self):
        tag = '"profile-0"'
        for mime, content in (("png", b"\x89PNG\r\n\x1a\nfixture"), ("jpeg", b"\xff\xd8\xfffixture"), ("webp", b"RIFF1234WEBPfixture")):
            image = "data:image/" + mime + ";base64," + base64.b64encode(content).decode()
            result = self.write({"avatar": "custom", "avatarImage": image}, tag)
            self.assertEqual(result["preferences"]["avatarImage"], image)
            tag = result["etag"]
        for image in ("data:image/png;base64,QUJD", "data:image/png;base64,A", "data:image/jpeg;base64,AA==", "data:image/webp;base64,UklGRg=="):
            self.write({"avatarImage": image}, tag, expected=400)
        self.write({"avatarImage": "data:image/png;base64," + "A" * service.MAX_AVATAR_CHARACTERS}, tag, expected=413)
        cleared = self.write({"avatarImage": None, "avatar": "mascot"}, tag)
        self.assertIsNone(cleared["preferences"]["avatarImage"])

    def test_merged_option_limit_rolls_back_and_json_byte_limit_is_not_character_count(self):
        result = self.write({"options": {"开关" + str(i): False for i in range(150)}})
        self.write({"options": {"开关" + str(i): True for i in range(150, 251)}}, result["etag"], expected=400)
        self.assertEqual(self.read(), result)
        with self.assertRaises(service.APIError) as caught:
            service.profile_json({"displayName": "中" * 100000})
        self.assertEqual(caught.exception.status, 413)
        # No body is sent: the server must reject the declared oversized request
        # before parsing it, and must not wait indefinitely for those bytes.
        from http.client import HTTPConnection
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request("PUT", service.PREFIX + "/profile", headers={"Host": "notelite.example", "Authorization": "Bearer " + self.accounts["teacher"]["token"], "Content-Type": "application/json", "Content-Length": str(service.MAX_PROFILE + 1), "If-Match": result["etag"]})
            response = connection.getresponse()
            self.assertEqual(response.status, 413)
            response.read()
        finally:
            connection.close()

    def test_browser_csrf_origin_expected_user_and_duplicate_json_preserve_profile(self):
        browser = self.store.login({"username": "teacher", "password": "a test-only long password teacher", "mode": "browser"})
        body = {"requestId": str(uuid.uuid4()), "changes": {"theme": "dark"}}
        headers = {"Cookie": service.COOKIE + "=" + browser["token"], "Origin": self.server.origin, "If-Match": '"profile-0"'}
        self.assertEqual(self.call("PUT", "/profile", body, extra=headers)[0], 403)
        headers["X-NoteLite-CSRF"] = browser["csrf"]
        self.assertEqual(self.call("PUT", "/profile", body, extra={**headers, "Origin": "https://attacker.example"})[0], 403)
        self.assertEqual(self.call("PUT", "/profile", body, extra={**headers, "X-NoteLite-Expected-User": self.accounts["student"]["userId"]})[0], 409)
        self.assertEqual(self.read()["revision"], 0)
        self.checked(200, "PUT", "/profile", body, extra=headers)
        duplicate = ('{"requestId":"' + str(uuid.uuid4()) + '","changes":{"theme":"light","theme":"dark"}}').encode()
        self.assertEqual(self.call("PUT", "/profile", duplicate, "teacher", {"Content-Type": "application/json", "If-Match": '"profile-1"'}, raw=True)[0], 400)
        self.assertEqual(self.read()["revision"], 1)

    def test_sqlite_restart_restores_profile_idempotency_and_old_database_upgrades(self):
        with tempfile.TemporaryDirectory() as directory:
            store = service.Store(directory, clock=lambda: self.moment[0])
            account = store.register({"username": "upgrade_fixture", "password": "synthetic persistent password", "mode": "native"})
            user = account["userId"]
            store.add_history(user, self.history())
            with store.connect() as db:
                db.execute("DROP TABLE profile_requests")
                db.execute("DROP TABLE profiles")
            upgraded = service.Store(directory, clock=lambda: self.moment[0])
            self.assertEqual(upgraded.read_profile(user)["revision"], 0)
            request = {"requestId": str(uuid.uuid4()), "changes": {"displayName": "Persistent Chinese 名字", "theme": "dark"}}
            stored = upgraded.update_profile(user, request, '"profile-0"')
            reopened = service.Store(directory, clock=lambda: self.moment[0])
            self.assertEqual(reopened.read_profile(user), stored)
            self.assertEqual(reopened.update_profile(user, request, '"profile-0"'), stored)
            self.assertEqual(len(reopened.list_history(user)["events"]), 1)
            self.assertEqual(reopened.authenticate(account["token"], "native")["user_id"], user)
            with reopened.connect() as db:
                self.assertEqual(list(db.execute("PRAGMA foreign_key_check")), [])

    def test_permanent_deletion_removes_profile_requests_and_fences_late_writes(self):
        name = "profile_del_" + uuid.uuid4().hex[:12]
        account = self.checked(201, "POST", "/register", {"username": name, "password": "synthetic profile deletion password", "mode": "native"})
        self.accounts[name] = account
        self.write({"email": "private@example.test", "avatar": "portrait"}, owner=name)
        self.checked(200, "DELETE", "/account", {"password": "synthetic profile deletion password", "confirmation": "DELETE_ACCOUNT"}, name)
        self.assertEqual(self.call("GET", "/profile", account=name)[0], 401)
        with self.store.connect() as db:
            for table in ("profiles", "profile_requests"):
                self.assertEqual(db.execute("SELECT COUNT(*) FROM " + table + " WHERE user_id=?", (account["userId"],)).fetchone()[0], 0)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO profiles VALUES(?,?,?,?)", (account["userId"], '{}', 1, self.moment[0]))
        with self.assertRaises(service.APIError) as caught:
            self.store.update_profile(account["userId"], {"requestId": str(uuid.uuid4()), "changes": {}}, '"profile-0"')
        self.assertEqual(caught.exception.status, 401)

    def test_export_restores_owner_data_without_credentials_or_another_users_records(self):
        saved = self.write({"displayName": "Exported settings", "email": "private@example.test"})
        score = self.checked(201, "POST", "/scores", {"title": "Export private score", "musicxml": service.SAMPLE_XML}, "teacher")
        event = self.history(score["id"], "personal")
        self.checked(201, "POST", "/history", event, "teacher")
        outsider = self.checked(201, "POST", "/scores", {"title": "Do not export outsider score", "musicxml": service.SAMPLE_XML}, "outsider")
        self.checked(201, "POST", "/history", self.history(outsider["id"], "personal"), "outsider")
        self.assertEqual(self.call("GET", "/account/export")[0], 401)
        exported = self.checked(200, "GET", "/account/export", account="teacher")
        self.assertEqual(exported["profile"], saved)
        self.assertTrue(exported["profileRequests"])
        self.assertTrue(any(s["id"] == score["id"] and s["musicxml"] == service.SAMPLE_XML for s in exported["scores"]))
        self.assertTrue(any(h["event"]["eventId"] == event["eventId"] and h["musicxml"] == service.SAMPLE_XML for h in exported["history"]))
        encoded = json.dumps(exported)
        self.assertNotIn(outsider["id"], encoded)
        for secret in ("password_hash", "salt", "token_hash", "csrf_hash", self.accounts["teacher"]["token"], self.accounts["outsider"]["token"]):
            self.assertNotIn(secret, encoded)
        self.assertEqual(self.call("GET", "/account/export", account="teacher", extra={"X-NoteLite-Expected-User": self.accounts["outsider"]["userId"]})[0], 409)

    def test_export_over_limit_is_explicit_413_without_partial_success(self):
        self.write({"displayName": "Not silently truncated"})
        with patch.object(service, "MAX_ACCOUNT_EXPORT", 100):
            status, result, _ = self.call("GET", "/account/export", account="teacher")
        self.assertEqual(status, 413)
        self.assertEqual(set(result), {"error"})
        self.assertEqual(self.read()["preferences"]["displayName"], "Not silently truncated")

    def test_export_includes_immutable_detection_version_and_completed_ai_cache(self):
        from pathlib import Path
        import hashlib
        import practice_analysis
        from test_practice_analysis import Provider
        event = self.history(mode="strict")
        detection = json.loads((Path(__file__).parent / "fixtures/notewise-v2.json").read_text(encoding="utf8"))
        detection["takeId"] = detection["eventId"] = event["eventId"]
        detection["sourceScoreSha256"] = hashlib.sha256(service.SAMPLE_XML.encode()).hexdigest()
        event["analysis"] = detection
        self.checked(201, "POST", "/history", event, "teacher")
        provider = Provider()
        analyzer = practice_analysis.PracticeAnalysis(self.store, provider, clock=lambda: self.moment[0])
        request_id = str(uuid.uuid4())
        with patch.object(self.server, "practice_analysis", analyzer):
            report = self.checked(200, "POST", "/practice-analysis", {"requestId": request_id, "eventIds": [event["eventId"]]}, "teacher")
        self.assertEqual(len(provider.calls), 1)
        exported = self.checked(200, "GET", "/account/export", account="teacher")
        versions = [a for a in exported["historyAnalyses"] if a["event_id"] == event["eventId"]]
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]["version"], 1)
        self.assertEqual(versions[0]["analysis"]["eventId"], event["eventId"])
        requests = [a for a in exported["practiceAnalysisRequests"] if a["request_id"] == request_id]
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["result"], report)
        self.assertTrue(any(a["result"] == report["output"] for a in exported["practiceAnalysisCache"]))
        other = self.checked(200, "GET", "/account/export", account="outsider")
        self.assertFalse(any(a["request_id"] == request_id for a in other["practiceAnalysisRequests"]))
        self.assertNotIn(event["eventId"], json.dumps(other))

    def test_teacher_export_does_not_include_student_submitted_private_history(self):
        course, shared, code = fixtures.AccountHTTPTests.classroom(self)
        self.checked(200, "POST", "/course-codes/join", {"code": code["code"]}, "student")
        assignment = self.checked(201, "POST", "/courses/" + course["id"] + "/assignments", {"title": "Explicitly scoped homework", "courseScoreId": shared["id"]}, "teacher")
        event = self.history()
        self.checked(201, "POST", "/history", event, "student")
        submission = self.checked(201, "POST", "/assignments/" + assignment["id"] + "/submissions", {"eventId": event["eventId"]}, "student")
        self.checked(200, "GET", "/submissions/" + submission["id"], account="teacher")
        teacher = self.checked(200, "GET", "/account/export", account="teacher")
        self.assertNotIn(event["eventId"], json.dumps(teacher))
        self.assertNotIn(submission["id"], json.dumps(teacher))
        student = self.checked(200, "GET", "/account/export", account="student")
        self.assertTrue(any(s["id"] == submission["id"] for s in student["submissions"]))


if __name__ == "__main__":
    unittest.main()
