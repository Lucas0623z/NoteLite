"""Synthetic account deletion: real HTTP, SQLite, filesystem and late writers.

No production account, credentials, data or provider is contacted.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
import unittest
from unittest.mock import patch
import uuid

import account_service as service
import practice_analysis as analysis
import test_account_service as fixtures
from test_practice_analysis import Provider

PASSWORD = "only synthetic deletion test password"


class AccountDeletionTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.AccountHTTPTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.AccountHTTPTests.tearDownClass.__func__)
    call = classmethod(fixtures.AccountHTTPTests.call.__func__)
    checked = fixtures.AccountHTTPTests.checked
    history = fixtures.AccountHTTPTests.history
    setUp = fixtures.AccountHTTPTests.setUp
    tiny_wav = fixtures.AccountHTTPTests.tiny_wav

    def user(self):
        name = "del_" + uuid.uuid4().hex[:20]
        self.accounts[name] = self.checked(201, "POST", "/register", {"username": name, "password": PASSWORD, "mode": "native"})
        return name

    def remove(self, owner, **body):
        return self.call("DELETE", "/account", {"password": PASSWORD, "confirmation": "DELETE_ACCOUNT", **body}, owner)

    def classroom(self, teacher, student):
        course = self.checked(201, "POST", "/courses", {"title": "Synthetic deletion classroom"}, teacher)
        shared = self.checked(201, "POST", "/courses/" + course["id"] + "/scores", {"sourceKind": "official", "scoreId": "notelite-four-notes-v1"}, teacher)
        code = self.checked(201, "POST", "/courses/" + course["id"] + "/codes", {}, teacher)
        self.checked(200, "POST", "/course-codes/join", {"code": code["code"]}, student)
        assignment = self.checked(201, "POST", "/courses/" + course["id"] + "/assignments", {"title": "Synthetic homework", "courseScoreId": shared["id"]}, teacher)
        return course, assignment

    def submission(self, student, assignment):
        event = self.history()
        self.checked(201, "POST", "/history", event, student)
        data = self.tiny_wav()
        import hashlib
        upload = self.checked(201, "POST", "/uploads", {"assignmentId": assignment["id"], "size": len(data), "mime": "audio/wav", "sha256": hashlib.sha256(data).hexdigest()}, student)
        self.checked(200, "PUT", "/uploads/" + upload["uploadId"], data, student, {"Upload-Offset": "0"}, raw=True)
        self.checked(200, "POST", "/uploads/" + upload["uploadId"] + "/complete", {}, student)
        submitted = self.checked(201, "POST", "/assignments/" + assignment["id"] + "/submissions", {"eventId": event["eventId"], "uploadId": upload["uploadId"]}, student)
        return event, upload, submitted

    def test_password_confirmation_expected_owner_and_browser_csrf_are_required(self):
        owner = self.user()
        self.assertEqual(self.call("DELETE", "/account", {"password": PASSWORD, "confirmation": "DELETE_ACCOUNT"})[0], 401)
        for body, status in [({"confirmation": "cancel"}, 400), ({"password": "wrong but sufficiently long"}, 403), ({"userId": self.accounts["teacher"]["userId"]}, 400)]:
            self.assertEqual(self.remove(owner, **body)[0], status)
        self.assertEqual(self.call("DELETE", "/account", {"password": PASSWORD, "confirmation": "DELETE_ACCOUNT"}, owner, {"X-NoteLite-Expected-User": self.accounts["teacher"]["userId"]})[0], 409)
        browser = self.store.login({"username": owner, "password": PASSWORD, "mode": "browser"})
        headers = {"Cookie": service.COOKIE + "=" + browser["token"], "Origin": self.server.origin}
        body = {"password": PASSWORD, "confirmation": "DELETE_ACCOUNT"}
        self.assertEqual(self.call("DELETE", "/account", body, extra=headers)[0], 403)
        self.checked(200, "GET", "/me", account=owner)
        headers["X-NoteLite-CSRF"] = browser["csrf"]
        status, result, response_headers = self.call("DELETE", "/account", body, extra=headers)
        self.assertEqual(status, 200)
        self.assertTrue(result["deleted"])
        self.assertIn("Max-Age=0", response_headers["Set-Cookie"])

    def test_real_user_scores_history_versions_analysis_cache_and_all_sessions_are_removed(self):
        owner = self.user()
        user = self.accounts[owner]["userId"]
        other_device = self.store.login({"username": owner, "password": PASSWORD, "mode": "native"})
        score = self.checked(201, "POST", "/scores", {"title": "Synthetic private XML", "musicxml": service.SAMPLE_XML, "requestId": str(uuid.uuid4())}, owner)
        event = self.history(score["id"], "personal", "strict")
        value = json.loads((Path(__file__).parent / "fixtures/notewise-v2.json").read_text(encoding="utf8"))
        import hashlib
        value["takeId"] = value["eventId"] = event["eventId"]
        value["sourceScoreSha256"] = hashlib.sha256(service.SAMPLE_XML.encode()).hexdigest()
        event["analysis"] = value
        self.checked(201, "POST", "/history", event, owner)
        analyzer = analysis.PracticeAnalysis(self.store, Provider(), clock=lambda: self.moment[0])
        analyzer.analyse(user, str(uuid.uuid4()))
        status, result, _ = self.remove(owner)
        self.assertEqual(status, 200)
        self.assertEqual(result, {"authenticated": False, "accountDeleted": True, "deletionRequested": True, "deleted": True, "status": "completed"})
        for token in (self.accounts[owner]["token"], other_device["token"]):
            self.assertEqual(self.call("GET", "/me", extra={"Authorization": "Bearer " + token})[0], 401)
        self.assertEqual(self.call("POST", "/login", {"username": owner, "password": PASSWORD, "mode": "native"})[0], 401)
        with self.store.connect() as db:
            for table, key in [("users", "id"), ("sessions", "user_id"), ("scores", "user_id"), ("score_requests", "user_id"), ("history", "user_id"), ("history_analysis_versions", "user_id"), ("practice_analysis_v2_requests", "user_id"), ("practice_analysis_v2_cache", "user_id")]:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM " + table + " WHERE " + key + "=?", (user,)).fetchone()[0], 0, table)
            self.assertEqual(list(db.execute("PRAGMA foreign_key_check")), [])
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO practice_analysis_v2_cache VALUES(?,?,?,?)", (user, "late", "private cached response", self.moment[0]))
        recreated = self.checked(201, "POST", "/register", {"username": owner, "password": PASSWORD, "mode": "native"})
        self.assertNotEqual(recreated["userId"], user)
        self.assertEqual(self.store.list_scores(recreated["userId"]), [])

    def test_student_deletion_removes_teacher_copy_and_recording_but_preserves_class_and_other_user(self):
        student = self.user()
        course, assignment = self.classroom("teacher", student)
        event, upload, submitted = self.submission(student, assignment)
        self.checked(200, "GET", "/submissions/" + submitted["id"], account="teacher")
        self.assertEqual(self.remove(student)[0], 200)
        self.assertFalse(self.store.recording_path(upload["uploadId"]).exists())
        self.checked(200, "GET", "/courses/" + course["id"], account="teacher")
        self.assertEqual(self.checked(200, "GET", "/assignments/" + assignment["id"] + "/submissions", account="teacher")["submissions"], [])
        self.checked(404, "GET", "/submissions/" + submitted["id"], account="teacher")
        self.checked(200, "GET", "/me", account="student")
        with self.store.connect() as db:
            self.assertEqual(list(db.execute("PRAGMA foreign_key_check")), [])

    def test_teacher_deletion_closes_class_and_removes_shared_audio_but_keeps_student_copies_and_private_history(self):
        teacher, student = self.user(), self.user()
        course, assignment = self.classroom(teacher, student)
        event, upload, _ = self.submission(student, assignment)
        with self.store.connect() as db:
            copy_id = db.execute("SELECT score_id FROM course_deliveries WHERE course_id=? AND user_id=?", (course["id"], self.accounts[student]["userId"])).fetchone()[0]
        score = self.checked(200, "GET", "/scores/" + copy_id, account=student)
        self.assertEqual(self.remove(teacher)[0], 200)
        self.checked(404, "GET", "/courses/" + course["id"], account=student)
        self.checked(200, "GET", "/scores/" + score["id"] + "/musicxml", account=student)
        self.assertTrue(any(item["eventId"] == event["eventId"] for item in self.checked(200, "GET", "/history", account=student)["events"]))
        self.assertFalse(self.store.recording_path(upload["uploadId"]).exists())
        with self.store.connect() as db:
            self.assertEqual(list(db.execute("PRAGMA foreign_key_check")), [])

    def test_unavailable_omr_is_pending_and_restart_retries_without_retaining_account_identity(self):
        owner = self.user()
        user = self.accounts[owner]["userId"]
        def unavailable(_): raise service.APIError(503, "Synthetic worker temporarily unavailable")
        with patch.object(self.store, "omr_delete", unavailable):
            status, result, _ = self.remove(owner)
        self.assertEqual(status, 202)
        self.assertFalse(result["deleted"])
        self.assertTrue(result["accountDeleted"])
        self.assertEqual(result["status"], "pending")
        with self.store.connect() as db:
            self.assertIsNone(db.execute("SELECT * FROM users WHERE id=?", (user,)).fetchone())
            queue = dict(db.execute("SELECT * FROM account_deletions WHERE user_id=?", (user,)).fetchone())
            self.assertEqual(set(queue), {"user_id", "recordings", "created"})
            self.assertNotIn(owner, json.dumps(queue))
        calls = []
        reopened = service.Store(self.root.name, clock=lambda: self.moment[0], omr_delete=lambda value: calls.append(value))
        reopened.process_deletions()
        self.assertIn(user, calls)
        with reopened.connect() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM account_deletions WHERE user_id=?", (user,)).fetchone())

    def test_previously_authenticated_request_and_delayed_provider_cannot_resurrect_personal_data(self):
        owner = self.user()
        user = self.accounts[owner]["userId"]
        self.checked(201, "POST", "/history", self.history(), owner)
        provider = Provider()
        entered, release = threading.Event(), threading.Event()
        def delayed(value):
            entered.set()
            release.wait(5)
            return provider(value)
        delayed.prompt = provider.prompt
        delayed.model = provider.model
        analyzer = analysis.PracticeAnalysis(self.store, delayed, clock=lambda: self.moment[0])
        failures = []
        def run():
            try: analyzer.analyse(user, str(uuid.uuid4()))
            except Exception as error: failures.append(error)
        thread = threading.Thread(target=run)
        thread.start()
        self.assertTrue(entered.wait(3))
        self.assertEqual(self.remove(owner)[0], 200)
        release.set()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertTrue(failures)
        self.assertIsInstance(failures[0], service.APIError)
        self.assertEqual(failures[0].status, 401)
        with self.store.owner_scope(user), self.assertRaises(service.APIError):
            self.store.create_score(user, {"title": "Late write", "musicxml": service.SAMPLE_XML})
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM practice_analysis_v2_cache WHERE user_id=?", (user,)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM practice_analysis_v2_requests WHERE user_id=?", (user,)).fetchone()[0], 0)

    def test_sql_failure_rolls_back_owner_fence_and_account_data(self):
        owner = self.user()
        user = self.accounts[owner]["userId"]
        events = []
        @contextmanager
        def fence(_):
            events.append("entered")
            try:
                yield
            except Exception:
                events.append("rollback")
                raise
            else:
                events.append("commit")
        with self.store.connect() as db:
            db.execute("CREATE TRIGGER fail_synthetic_account_delete BEFORE DELETE ON users WHEN OLD.id='" + user + "' BEGIN SELECT RAISE(ABORT,'synthetic SQL failure'); END")
        try:
            with patch.object(self.store, "omr_fence", fence):
                self.assertEqual(self.remove(owner)[0], 500)
        finally:
            with self.store.connect() as db: db.execute("DROP TRIGGER fail_synthetic_account_delete")
        self.assertEqual(events, ["entered", "rollback"])
        self.checked(200, "GET", "/me", account=owner)
        self.assertEqual(self.remove(owner)[0], 200)

    def test_fence_failure_before_delete_keeps_account_and_post_commit_failure_is_pending(self):
        owner = self.user()
        @contextmanager
        def fail_before(_):
            raise service.APIError(503, "Synthetic fence unavailable")
            yield
        with patch.object(self.store, "omr_fence", fail_before):
            self.assertEqual(self.remove(owner)[0], 503)
        self.checked(200, "GET", "/me", account=owner)
        @contextmanager
        def fail_after(_):
            yield
            raise service.APIError(503, "Synthetic gateway commit failure")
        def cleanup_unavailable(_): raise service.APIError(503, "Synthetic cleanup unavailable")
        with patch.object(self.store, "omr_fence", fail_after), patch.object(self.store, "omr_delete", cleanup_unavailable):
            status, result, _ = self.remove(owner)
        self.assertEqual(status, 202)
        self.assertTrue(result["accountDeleted"])
        self.assertFalse(result["deleted"])
        self.assertEqual(self.call("GET", "/me", account=owner)[0], 401)


if __name__ == "__main__": unittest.main()
