"""Real HTTP/SQLite version, owner, score snapshot and teacher-sharing checks.

Uses a synthetic two-note MIDI matcher result and the real deterministic server
normalizer. No provider, recording, credentials or production data is accessed.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

import account_service as service
import test_account_service as fixtures
from performance_analysis import normalize_performance


class HistoryAnalysisVersionTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.AccountHTTPTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.AccountHTTPTests.tearDownClass.__func__)
    call = classmethod(fixtures.AccountHTTPTests.call.__func__)
    setUp = fixtures.AccountHTTPTests.setUp
    checked = fixtures.AccountHTTPTests.checked
    history = fixtures.AccountHTTPTests.history
    personal = fixtures.AccountHTTPTests.personal
    classroom = fixtures.AccountHTTPTests.classroom
    assignment = fixtures.AccountHTTPTests.assignment

    def analysis(self, event_id, *, xml=service.SAMPLE_XML, revision=1, tag="active-feedback-2"):
        raw = (Path(__file__).parent / "fixtures" / "notewise-v2.json").read_text(encoding="utf8")
        raw = raw.replace("33333333-3333-4333-8333-333333333333", event_id)
        value = json.loads(raw)
        value["sourceScoreSha256"] = hashlib.sha256(xml.encode()).hexdigest()
        value["scoreRevision"] = revision
        value["judgeRulesVersion"] = tag
        return value

    def event(self, *, owner="student", score="notelite-four-notes-v1", source="official", include_analysis=True):
        value = self.history(score, source, "strict")
        if include_analysis:
            value["analysis"] = self.analysis(value["eventId"])
        result = self.checked(201, "POST", "/history", value, owner)
        return value, result["event"]

    def version_body(self, event_id, parent, *, tag="review-2", request_id=None):
        analysis = self.analysis(event_id, tag=tag)
        return {"requestId": request_id or str(uuid.uuid4()), "parentVersion": parent,
                "sourceHash": analysis["sourceScoreSha256"], "analysis": analysis}

    def route(self, event_id):
        return "/history/" + event_id + "/analyses"

    def test_initial_v2_is_version_one_and_snapshot_remains_immutable(self):
        raw, saved = self.event()
        route = self.route(raw["eventId"])
        self.assertEqual(saved["analysisVersion"], 1)
        self.assertFalse(saved["analysis"]["verifiedByServer"])
        self.assertTrue(saved["snapshotValidatedByServer"])
        with self.store.connect() as db:
            original = dict(db.execute("SELECT * FROM history WHERE user_id=? AND event_id=?", (self.accounts["student"]["userId"], raw["eventId"])).fetchone())
        second = self.checked(201, "POST", route, self.version_body(raw["eventId"], 1), "student")
        self.assertEqual((second["version"], second["parentVersion"]), (2, 1))
        first = self.checked(200, "GET", route + "/1", account="student")
        self.assertEqual(first["analysisHash"], saved["analysisHash"])
        self.assertEqual(hashlib.sha256(service.analysis_json(first["analysis"]).encode()).hexdigest(), first["analysisHash"])
        collection = self.checked(200, "GET", route, account="student")
        self.assertEqual(collection["latestVersion"], 2)
        self.assertTrue(all("analysis" not in row for row in collection["analyses"]))
        current = next(row for row in self.checked(200, "GET", "/history", account="student")["events"] if row["eventId"] == raw["eventId"])
        self.assertEqual((current["analysisVersion"], current["analysisHash"]), (2, second["analysisHash"]))
        self.assertTrue(self.checked(200, "POST", "/history", raw, "student")["duplicate"])
        self.assertTrue(self.checked(200, "POST", "/history", {**raw, "analysis": saved["analysis"]}, "student")["duplicate"])
        with self.store.connect() as db:
            unchanged = dict(db.execute("SELECT * FROM history WHERE user_id=? AND event_id=?", (self.accounts["student"]["userId"], raw["eventId"])).fetchone())
        self.assertEqual(original, unchanged)

    def test_request_id_replays_exact_version_after_newer_review(self):
        raw, _ = self.event()
        route = self.route(raw["eventId"])
        body = self.version_body(raw["eventId"], 1)
        second = self.checked(201, "POST", route, body, "student")
        self.checked(201, "POST", route, self.version_body(raw["eventId"], 2, tag="review-3"), "student")
        duplicate = self.checked(200, "POST", route, body, "student")
        self.assertEqual(duplicate["version"], 2)
        self.assertEqual(duplicate["analysisHash"], second["analysisHash"])
        self.assertTrue(duplicate["duplicate"])
        normalized_replay = self.checked(200, "POST", route, {**body, "analysis": second["analysis"]}, "student")
        self.assertEqual(normalized_replay["analysisHash"], second["analysisHash"])
        self.checked(409, "POST", route, {**body, "parentVersion": 2}, "student")
        changed = deepcopy(body)
        changed["analysis"]["judgeRulesVersion"] = "different-review"
        self.checked(409, "POST", route, changed, "student")

    def test_concurrent_review_has_one_winner_and_stale_parent_conflicts(self):
        raw, _ = self.event()
        route = self.route(raw["eventId"])
        barrier = threading.Barrier(3)
        results = []
        def save(tag):
            barrier.wait()
            results.append(self.call("POST", route, self.version_body(raw["eventId"], 1, tag=tag), "student")[0])
        threads = [threading.Thread(target=save, args=(tag,)) for tag in ("review-a", "review-b")]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(sorted(results), [201, 409])
        self.assertEqual(self.checked(200, "GET", route, account="student")["latestVersion"], 2)

    def test_owner_event_take_and_score_hash_are_all_bound(self):
        raw, _ = self.event()
        route = self.route(raw["eventId"])
        body = self.version_body(raw["eventId"], 1)
        self.checked(401, "GET", route)
        for actor in ("teacher", "outsider"):
            self.checked(404, "GET", route, account=actor)
            self.checked(404, "GET", route + "/1", account=actor)
            self.checked(404, "POST", route, body, actor)
        self.checked(409, "POST", route, {**body, "sourceHash": "b" * 64}, "student")
        wrong_take = deepcopy(body)
        wrong_take["analysis"]["takeId"] = str(uuid.uuid4())
        self.checked(422, "POST", route, wrong_take, "student")
        other, _ = self.event()
        self.checked(422, "POST", self.route(other["eventId"]), body, "student")
        self.checked(404, "GET", route + "/99", account="student")
        self.checked(404, "GET", route + "?private=1", account="student")

    def test_original_xml_is_used_after_multi_device_score_edit(self):
        score = self.personal("student")
        raw, saved = self.event(score=score["id"], source="personal")
        edited_xml = service.SAMPLE_XML.replace("<step>C</step>", "<step>G</step>")
        updated = self.checked(200, "PUT", "/scores/" + score["id"], {"musicxml": edited_xml}, "student", {"If-Match": score["etag"]})
        self.assertEqual(updated["revision"], 2)
        route = self.route(raw["eventId"])
        second = self.checked(201, "POST", route, self.version_body(raw["eventId"], 1), "student")
        self.assertEqual(second["sourceHash"], saved["scoreSha256"])
        self.assertTrue(self.checked(200, "POST", "/history", raw, "student")["duplicate"])
        self.checked(409, "POST", route, {**self.version_body(raw["eventId"], 2), "sourceHash": hashlib.sha256(edited_xml.encode()).hexdigest()}, "student")
        original = self.call("GET", "/history/" + raw["eventId"] + "/musicxml", account="student")
        self.assertEqual(original[:2], (200, service.SAMPLE_XML.encode()))

    def test_teacher_submission_is_pinned_and_later_review_is_private(self):
        _, joined, assignment = self.assignment()
        raw, saved = self.event(score=joined["deliveredScores"][0]["id"], source="personal")
        submission_route = "/assignments/" + assignment["id"] + "/submissions"
        submitted = self.checked(201, "POST", submission_route, {"eventId": raw["eventId"], "analysisVersion": 1}, "student")
        self.assertEqual(submitted["analysisVersion"], 1)
        self.checked(201, "POST", self.route(raw["eventId"]), self.version_body(raw["eventId"], 1), "student")
        teacher = self.checked(200, "GET", submission_route, account="teacher")["submissions"][0]
        self.assertEqual((teacher["analysisVersion"], teacher["analysisHash"]), (1, saved["analysisHash"]))
        self.assertEqual(teacher["event"]["analysisVersion"], 1)
        self.assertEqual(teacher["event"]["analysis"], teacher["analysis"])
        self.assertNotEqual(teacher["analysis"]["judgeRulesVersion"], "review-2")
        duplicate = self.checked(200, "POST", submission_route, {"eventId": raw["eventId"]}, "student")
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["analysisVersion"], 1)
        self.checked(409, "POST", submission_route, {"eventId": raw["eventId"], "analysisVersion": 2}, "student")
        self.checked(404, "GET", self.route(raw["eventId"]), account="teacher")
        self.checked(404, "GET", submission_route, account="outsider")

    def test_legacy_history_can_gain_v2_review_without_rewriting_timer(self):
        raw, saved = self.event(include_analysis=False)
        self.assertEqual(saved["analysis"]["status"], "unanalysed")
        route = self.route(raw["eventId"])
        self.assertEqual(self.checked(200, "GET", route, account="student")["latestVersion"], 0)
        first = self.checked(201, "POST", route, self.version_body(raw["eventId"], 0), "student")
        self.assertEqual(first["version"], 1)
        self.assertTrue(self.checked(200, "POST", "/history", raw, "student")["duplicate"])
        self.checked(400, "POST", route, {**self.version_body(raw["eventId"], 1), "analysis": {"status": "analysed", "source": "client-reported", "errors": []}}, "student")
        free = self.history()
        self.checked(201, "POST", "/history", free, "student")
        self.checked(422, "POST", self.route(free["eventId"]), self.version_body(free["eventId"], 0), "student")

    def test_input_and_normalized_utf8_sizes_are_bounded(self):
        raw, _ = self.event()
        route = self.route(raw["eventId"])
        body = self.version_body(raw["eventId"], 1)
        oversized = deepcopy(body)
        oversized["analysis"]["uncertainty"] = ["中" * (service.MAX_ANALYSIS // 3 + 1)]
        self.checked(413, "POST", route, oversized, "student")
        value = body["analysis"]
        normalized = normalize_performance(value, service.SAMPLE_XML, body["sourceHash"], 1, "strict")
        before, after = len(service.analysis_json(value).encode()), len(service.analysis_json(normalized).encode())
        self.assertGreater(after, before)
        with patch.object(service, "MAX_ANALYSIS", (before + after) // 2):
            self.checked(413, "POST", route, body, "student")
        self.assertEqual(self.checked(200, "GET", route, account="student")["latestVersion"], 1)

    def test_corrupt_xml_or_analysis_fails_closed_without_source_exposure(self):
        raw, _ = self.event()
        route = self.route(raw["eventId"])
        owner = self.accounts["student"]["userId"]
        with self.store.connect() as db:
            db.execute("UPDATE history SET score_xml=? WHERE user_id=? AND event_id=?", ("invalid-secret-score-content", owner, raw["eventId"]))
        failed = self.checked(503, "GET", route + "/1", account="student")
        self.assertNotIn("invalid-secret-score-content", json.dumps(failed))
        with self.store.connect() as db:
            db.execute("UPDATE history SET score_xml=? WHERE user_id=? AND event_id=?", (service.SAMPLE_XML, owner, raw["eventId"]))
            original = db.execute("SELECT payload FROM history_analysis_versions WHERE user_id=? AND event_id=?", (owner, raw["eventId"])).fetchone()[0]
            db.execute("UPDATE history_analysis_versions SET payload='{}' WHERE user_id=? AND event_id=?", (owner, raw["eventId"]))
        self.checked(503, "GET", route + "/1", account="student")
        with self.store.connect() as db:
            db.execute("UPDATE history_analysis_versions SET payload=? WHERE user_id=? AND event_id=?", (original, owner, raw["eventId"]))
        self.checked(200, "GET", route + "/1", account="student")

    def test_request_schema_does_not_allow_private_or_server_claim_fields(self):
        raw, _ = self.event()
        route = self.route(raw["eventId"])
        body = self.version_body(raw["eventId"], 1)
        self.checked(400, "POST", route, {**body, "parentVersion": True}, "student")
        self.checked(400, "POST", route, {**body, "sourceHash": "not-a-hash"}, "student")
        self.checked(400, "POST", route, {**body, "privatePrompt": "must-not-be-stored"}, "student")
        forged = deepcopy(body)
        forged["analysis"]["verifiedByServer"] = True
        result = self.checked(201, "POST", route, forged, "student")
        self.assertFalse(result["analysis"]["verifiedByServer"])
        self.assertNotIn("score_xml", result)
        self.assertNotIn("musicxml", result)

    def test_storage_quota_rejection_rolls_back_entire_new_version(self):
        raw, _ = self.event()
        route = self.route(raw["eventId"])
        with patch.object(service, "MAX_ANALYSIS_STORAGE", 1):
            self.checked(413, "POST", route, self.version_body(raw["eventId"], 1), "student")
        self.assertEqual(self.checked(200, "GET", route, account="student")["latestVersion"], 1)


if __name__ == "__main__":
    unittest.main()
