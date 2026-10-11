"""V2 contract, real HTTP account boundaries and one-call provider tests.

No production credentials or remote model calls. Provider transport is exercised
with a synthetic key and captured request/response objects.
"""
from copy import deepcopy
from http.client import HTTPConnection
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import shutil
import unittest
from unittest.mock import patch
import uuid

import account_service as accounts
import practice_analysis as module

SYNTHETIC_PROMPT = "Synthetic test instruction: interpret supplied aggregate facts and return contract JSON."


def synthetic_input():
    return {"schemaVersion": "2.0", "reportStatus": "investment_only", "locale": "zh-CN", "snapshotId": "synthetic-snapshot", "aggregateVersion": "synthetic-2.0", "coverage": {"description": "Synthetic timer fixture", "omittedDetail": False, "selectionPolicy": "Synthetic fact only", "limitations": ["Synthetic data only"]}, "facts": [{"factId": "synthetic-timer", "kind": "practice_investment", "dimension": "practice_investment", "label": "Synthetic timer", "statement": "Synthetic timer recorded 30 seconds.", "displayValue": "30 seconds", "claimState": "verified_fact", "scope": "Synthetic fixture", "confidence": "high", "evidenceRefs": ["synthetic-evidence"], "limitations": ["Not a performance assessment"]}]}


def valid_output(data):
    observations, pending = [], []
    for fact in data["facts"]:
        item = {"title": fact["label"], "description": fact["statement"], "factIds": [fact["factId"]]}
        if fact["kind"] in {"practice_investment", "performance_observation"} and len(observations) < 4:
            observations.append(item)
        elif fact["claimState"] == "pending_review" and len(pending) < 4:
            pending.append(item)
    return {"schemaVersion": "2.0", "status": data["reportStatus"], "summary": "已整理当前记录的计时和分析状态，演奏结论以现有证据为限。", "observations": observations, "weaknesses": [], "strengths": [], "progress": [], "pendingReview": pending, "suggestions": [], "limitations": data["coverage"]["limitations"]}


class Provider:
    model = "test-provider-v2"
    settings = module.SETTINGS
    prompt = SYNTHETIC_PROMPT

    def __init__(self, change=None):
        self.calls = []
        self.change = change

    def __call__(self, data):
        self.calls.append(deepcopy(data))
        result = valid_output(data)
        return self.change(result, data) if self.change else result


class PracticeAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.moment = 1791766800.0
        cls.store = accounts.Store(cls.directory.name, clock=lambda: cls.moment)
        with patch.dict(os.environ, {"NOTELITE_DEEPSEEK_KEY_FILE": ""}):
            cls.server = accounts.Server(("127.0.0.1", 0), cls.store, "https://notelite.example")
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.identities = [cls.store.register({"username": name, "password": "long synthetic test password " + name, "mode": "native"}) for name in ("analysis_owner", "analysis_other")]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(5)
        cls.server.server_close()
        cls.directory.cleanup()

    def setUp(self):
        self.server.limiter.buckets.clear()
        with self.store.connect() as db:
            db.execute("DELETE FROM practice_analysis_v2_cache") if db.execute("SELECT 1 FROM sqlite_master WHERE name='practice_analysis_v2_cache'").fetchone() else None
            db.execute("DELETE FROM practice_analysis_v2_requests") if db.execute("SELECT 1 FROM sqlite_master WHERE name='practice_analysis_v2_requests'").fetchone() else None
            db.execute("DELETE FROM history")
        self.provider = Provider()
        self.analyzer = module.PracticeAnalysis(self.store, self.provider, clock=lambda: self.moment)
        self.server.practice_analysis = self.analyzer

    def request(self, body, identity=0, headers=None):
        extra = {"Host": "notelite.example", "Content-Type": "application/json"}
        if identity is not None:
            extra["Authorization"] = "Bearer " + self.identities[identity]["token"]
        if headers:
            extra.update(headers)
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        connection.request("POST", "/api/account/practice-analysis", module.json_bytes(body), extra)
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def event(self, analysis=None, identity=0, duration=30, mode="free"):
        value = {"eventId": str(uuid.uuid4()), "sourceKind": "official", "scoreId": "notelite-four-notes-v1", "scoreRevision": 1, "mode": mode, "durationSeconds": duration, "startedAt": accounts.now_stamp(self.moment - 120), "endedAt": accounts.now_stamp(self.moment - 1)}
        if analysis is not None:
            value["analysis"] = analysis
        self.store.add_history(self.identities[identity]["userId"], value)
        return value["eventId"]

    def body(self, event_ids=None, request_id=None):
        return {"requestId": request_id or str(uuid.uuid4()), **({"eventIds": event_ids} if event_ids is not None else {})}

    def test_01_real_http_auth_no_records_and_other_owner_records(self):
        self.assertEqual(self.request(self.body(), identity=None)[0], 401)
        self.assertEqual(self.request(self.body())[0], 409)
        own = self.event()
        self.assertEqual(self.request(self.body([own]), identity=1)[0], 404)
        self.assertEqual(self.request(self.body([own]), headers={"X-NoteLite-Expected-User": self.identities[1]["userId"]})[0], 409)
        self.assertEqual(len(self.provider.calls), 0)
        self.server.practice_analysis = None
        self.assertEqual(self.request(self.body([own]))[0], 503)

    def test_02_timing_null_produces_investment_not_strength_and_no_raw_input(self):
        event = self.event()
        status, result = self.request(self.body([event]))
        self.assertEqual(status, 200)
        self.assertEqual(result["output"]["schemaVersion"], "2.0")
        self.assertEqual(result["output"]["status"], "investment_only")
        self.assertEqual(result["generationStatus"], "completed")
        self.assertEqual(result["output"]["strengths"], [])
        self.assertEqual(result["metrics"]["unanalysedRecordCount"], 1)
        self.assertIsNone(result["metrics"]["evaluatedOpportunities"])
        self.assertTrue(result["output"]["observations"])
        sent = self.provider.calls[0]
        self.assertEqual(set(sent), {"schemaVersion", "reportStatus", "locale", "snapshotId", "aggregateVersion", "coverage", "facts"})
        self.assertNotIn(event, module.json_bytes(sent).decode())
        self.assertNotIn("score-partwise", module.json_bytes(sent).decode())
        for fact in sent["facts"]:
            self.assertTrue(all(result["evidenceIndex"][key]["events"] for key in fact["evidenceRefs"]))

    def test_03_client_counts_deduplicate_but_do_not_invent_denominators(self):
        marker = {"type": "wrong", "noteId": "untrusted-note-text-do-not-send", "playedMidi": 66, "expectedMidi": 64, "confidence": 0.9}
        self.event({"status": "analysed", "source": "client-reported", "errors": [marker, {**marker, "confidence": 0.8}, {"type": "rhythm", "noteId": "n2"}, {"type": "uncertain", "noteId": "n3"}]}, mode="follow")
        status, result = self.request(self.body())
        self.assertEqual(status, 200)
        self.assertEqual(result["output"]["status"], "partial")
        self.assertEqual(result["metrics"]["confirmedClientErrorCount"], 2)
        self.assertEqual(result["metrics"]["pendingClientErrorCount"], 1)
        self.assertEqual(result["output"]["weaknesses"], [])
        self.assertEqual(result["output"]["progress"], [])
        self.assertIsNone(result["metrics"]["errorRate"])
        self.assertNotIn("untrusted-note-text-do-not-send", module.json_bytes(self.provider.calls).decode())

    def test_04_uncertain_state_including_empty_results_remains_pending(self):
        self.event({"status": "uncertain", "source": "client-reported", "errors": [{"type": "wrong", "noteId": "n1"}]}, mode="follow")
        self.event({"status": "uncertain", "source": "client-reported", "errors": []}, mode="follow")
        _, result = self.request(self.body())
        self.assertEqual(result["metrics"]["confirmedClientErrorCount"], 0)
        self.assertTrue(result["output"]["pendingReview"])
        pending_ids = {f["factId"] for f in result["facts"] if f["claimState"] == "pending_review"}
        self.assertFalse(any(pending_ids.intersection(o["factIds"]) for o in result["output"]["observations"]))
        self.assertEqual(result["output"]["strengths"], [])

    def test_05_completed_empty_array_unknown_scope_is_not_zero_error_strength(self):
        self.event({"status": "analysed", "source": "client-reported", "errors": []}, mode="strict")
        _, result = self.request(self.body())
        self.assertEqual(result["output"]["status"], "investment_only")
        self.assertEqual(result["metrics"]["emptyAnalysisRecordCount"], 1)
        self.assertTrue(any(f["factId"] == "empty-analysis-scope-unknown" for f in result["facts"]))
        self.assertEqual(result["output"]["strengths"], [])

    def test_06_persistent_cache_same_request_and_same_content_different_request(self):
        event, body = self.event(), self.body()
        body["eventIds"] = [event]
        self.assertFalse(self.request(body)[1]["cached"])
        self.assertTrue(self.request(body)[1]["cached"])
        second = self.request(self.body([event]))[1]
        self.assertTrue(second["cached"])
        self.assertEqual(len(self.provider.calls), 1)
        other_provider = Provider()
        self.server.practice_analysis = module.PracticeAnalysis(self.store, other_provider)
        self.assertTrue(self.request(self.body([event]))[1]["cached"])
        self.assertEqual(len(other_provider.calls), 0)

    def test_07_cache_checks_current_access_and_content_before_return(self):
        event, body = self.event(), self.body()
        body["eventIds"] = [event]
        self.request(body)
        self.assertEqual(self.request(body, identity=1)[0], 404)
        with self.store.connect() as db:
            row = db.execute("SELECT payload FROM history WHERE event_id=?", (event,)).fetchone()
            payload = json.loads(row[0]); payload["durationSeconds"] = 25
            db.execute("UPDATE history SET payload=? WHERE event_id=?", (module.json_bytes(payload).decode(), event))
        self.assertEqual(self.request(body)[0], 409)
        self.assertEqual(self.request(self.body([event]))[0], 200)
        self.assertEqual(len(self.provider.calls), 2)
        with self.store.connect() as db:
            db.execute("DELETE FROM history WHERE event_id=?", (event,))
        self.assertEqual(self.request(body)[0], 404)

    def test_08_invalid_schema_reference_state_and_numeric_claims_fallback_once(self):
        event = self.event()
        mutations = [
            lambda out, data: {**out, "unexpected": True},
            lambda out, data: {**out, "status": "complete"},
            lambda out, data: {**out, "observations": [{"title": "x", "description": "x", "factIds": ["made-up"]}]},
            lambda out, data: {**out, "strengths": out["observations"]},
            lambda out, data: {**out, "observations": []},
            lambda out, data: {**out, "summary": "你的正确率为99%。"},
            lambda out, data: {**out, "summary": "你已完成30分钟练习。"},
            lambda out, data: {**out, "summary": "大三度属于稳定弱项。"},
            lambda out, data: {**out, "summary": "已经听过本次录音。"},
            lambda out, data: {**out, "limitations": []},
        ]
        for index, change in enumerate(mutations):
            with self.subTest(case=index):
                provider = Provider(change); provider.model = "invalid-case-" + str(index)
                self.server.practice_analysis = module.PracticeAnalysis(self.store, provider, clock=lambda: self.moment)
                # Independent content namespaces retain the per-account quota.
                with self.store.connect() as db:
                    db.execute("DELETE FROM practice_analysis_v2_requests")
                body = self.body([event])
                status, result = self.request(body)
                self.assertEqual(status, 200)
                self.assertEqual(result["generationStatus"], "fallback")
                self.assertEqual(result["output"]["status"], "investment_only")
                self.assertTrue(result["retryAllowed"])
                self.assertFalse(result["cached"])
                self.assertEqual(self.request(body)[1]["generationStatus"], "fallback")
                self.assertEqual(len(provider.calls), 1)
                with self.store.connect() as db:
                    self.assertEqual(db.execute("SELECT count(*) FROM practice_analysis_v2_cache WHERE user_id=?", (self.identities[0]["userId"],)).fetchone()[0], 0)

    def test_09_pending_cannot_be_observation_and_provisional_cannot_be_strength(self):
        event = self.event({"status": "uncertain", "source": "client-reported", "errors": [{"type": "wrong"}]}, mode="follow")
        def wrong(out, data):
            return {**out, "observations": out["pendingReview"]}
        self.server.practice_analysis = module.PracticeAnalysis(self.store, Provider(wrong))
        self.assertEqual(self.request(self.body([event]))[1]["generationStatus"], "fallback")

    def test_10_timeout_unknown_is_not_recharged_even_with_new_request_id(self):
        event = self.event()
        def unknown(out, data):
            raise module.AnalysisError(504, "synthetic private details must not echo", uncertain=True)
        provider = Provider(unknown)
        self.server.practice_analysis = module.PracticeAnalysis(self.store, provider)
        body = self.body([event])
        status, result = self.request(body)
        self.assertEqual(status, 200)
        self.assertFalse(result["retryAllowed"])
        self.assertNotIn("synthetic private", module.json_bytes(result).decode())
        self.request(body)
        self.request(self.body([event]))
        self.assertEqual(len(provider.calls), 1)

    def test_11_lost_pending_after_restart_becomes_unknown_without_second_call(self):
        event = self.event()
        prepared = self.analyzer.input(self.identities[0]["userId"], [event])
        input_sha = module.sha({"owner": self.identities[0]["userId"], "aggregate": prepared["modelInput"], "source": prepared["sourceHash"], "fingerprint": self.analyzer.fingerprint})
        body = self.body([event])
        with self.store.connect() as db:
            db.execute("INSERT INTO practice_analysis_v2_requests VALUES(?,?,?,'pending',NULL,1,?)", (self.identities[0]["userId"], body["requestId"], input_sha, self.moment))
        result = self.request(body)[1]
        self.assertEqual(result["generationStatus"], "fallback")
        self.assertFalse(result["retryAllowed"])
        self.assertEqual(len(self.provider.calls), 0)

    def test_12_latest_200_scope_and_explicit_ids_limit(self):
        ids = [self.event() for _ in range(201)]
        result = self.request(self.body())[1]
        self.assertEqual(result["scope"]["recordCount"], 200)
        self.assertTrue(result["scope"]["hasMore"])
        self.assertTrue(any("200" in value for value in self.provider.calls[0]["coverage"]["limitations"]))
        for invalid in (ids, [ids[0], ids[0]], [[ids[0]]]):
            self.assertEqual(self.request(self.body(invalid))[0], 400)

    def test_13_version_fingerprint_invalidates_cache_and_request(self):
        event, body = self.event(), self.body()
        body["eventIds"] = [event]
        self.request(body)
        self.analyzer.fingerprint["promptHash"] = "new-prompt"
        self.assertEqual(self.request(body)[0], 409)
        self.assertFalse(self.request(self.body([event]))[1]["cached"])
        self.assertEqual(len(self.provider.calls), 2)

    def test_14_rate_limit_counts_provider_attempts_not_content_cache_reads(self):
        for index in range(6):
            event = self.event(duration=20 + index)
            self.assertEqual(self.request(self.body([event]))[0], 200)
        event = self.event(duration=50)
        self.assertEqual(self.request(self.body([event]))[0], 429)
        self.assertEqual(len(self.provider.calls), 6)

    def test_15_concurrency_busy_does_not_reserve_or_invoke_provider(self):
        event = self.event()
        self.analyzer.capacity.acquire(); self.analyzer.capacity.acquire()
        body = self.body([event])
        try:
            self.assertEqual(self.request(body)[0], 429)
            self.assertEqual(len(self.provider.calls), 0)
            with self.store.connect() as db:
                self.assertEqual(db.execute("SELECT count(*) FROM practice_analysis_v2_requests").fetchone()[0], 0)
        finally:
            self.analyzer.capacity.release(); self.analyzer.capacity.release()
        self.assertEqual(self.request(body)[0], 200)

    def test_16_input_byte_budget_is_checked_before_model_call(self):
        event = self.event()
        with patch.object(module, "MAX_INPUT_BYTES", 100):
            self.assertEqual(self.request(self.body([event]))[0], 413)
        with patch.object(module, "MAX_INPUT_TOKEN_BOUND", 100):
            self.assertEqual(self.request(self.body([event]))[0], 413)
        self.assertEqual(len(self.provider.calls), 0)

    def test_17_real_concurrent_same_snapshot_is_one_call_not_unknown_fallback(self):
        event = self.event()
        entered, release = threading.Event(), threading.Event()
        def blocking(out, data):
            entered.set()
            release.wait(5)
            return out
        provider = Provider(blocking)
        self.server.practice_analysis = module.PracticeAnalysis(self.store, provider)
        body, replies = self.body([event]), []
        worker = threading.Thread(target=lambda: replies.append(self.request(body)))
        worker.start()
        try:
            self.assertTrue(entered.wait(3))
            self.assertEqual(self.request(body)[0], 409)
            self.assertEqual(self.request(self.body([event]))[0], 409)
            self.assertEqual(len(provider.calls), 1)
        finally:
            release.set()
            worker.join(5)
        self.assertEqual(replies[0][0], 200)
        self.assertEqual(replies[0][1]["generationStatus"], "completed")
        self.assertTrue(self.request(body)[1]["cached"])

    def test_18_known_fallback_requires_new_explicit_request_for_a_retry(self):
        event = self.event()
        provider = Provider(lambda out, data: {**out, "badField": True})
        self.server.practice_analysis = module.PracticeAnalysis(self.store, provider)
        body = self.body([event])
        first = self.request(body)[1]
        self.assertEqual(first["generationStatus"], "fallback")
        self.assertTrue(first["retryAllowed"])
        provider.change = None
        self.assertEqual(self.request(body)[1]["generationStatus"], "fallback")
        self.assertEqual(len(provider.calls), 1)
        second = self.request(self.body([event]))[1]
        self.assertEqual(second["generationStatus"], "completed")
        self.assertEqual(len(provider.calls), 2)

    def test_19_precise_value_requires_its_cited_fact_not_another_input_fact(self):
        event = self.event({"status": "analysed", "source": "client-reported", "errors": [{"type": "wrong", "noteId": "n" + str(index)} for index in range(4)]}, mode="follow")
        def wrong_citation(out, data):
            return {**out, "observations": [{"title": "当前样本的计时", "description": "当前样本记录时长为30秒。", "factIds": ["wrong-client-count"]}]}
        provider = Provider(wrong_citation)
        self.server.practice_analysis = module.PracticeAnalysis(self.store, provider)
        body = self.body([event])
        result = self.request(body)[1]
        self.assertEqual(result["generationStatus"], "fallback")
        self.assertTrue(result["retryAllowed"])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM practice_analysis_v2_cache").fetchone()[0], 0)
        self.assertEqual(self.request(body)[1]["generationStatus"], "fallback")
        self.assertEqual(len(provider.calls), 1)
        # Both the exact value and its actual cited fact are now present.
        provider.change = lambda out, data: {**out, "observations": [{"title": "计时已有记录", "description": "记录时长为30秒。", "factIds": ["practice-investment"]}]}
        self.assertEqual(self.request(self.body([event]))[1]["generationStatus"], "completed")
        # Summary/limitations may describe the whole selected fact snapshot.
        prepared = self.analyzer.input(self.identities[0]["userId"], [event])["modelInput"]
        legal = valid_output(prepared)
        legal["summary"] = "当前样本记录时长为30秒，包含4项客户端错误标记。"
        module.validate_output(legal, prepared)

    def test_20_timer_only_summary_cannot_silently_upgrade_to_strength_or_progress(self):
        event = self.event()
        provider = Provider(lambda out, data: {**out, "summary": "你的音准已成为稳定强项，演奏能力持续进步。"})
        self.server.practice_analysis = module.PracticeAnalysis(self.store, provider)
        body = self.body([event])
        result = self.request(body)[1]
        self.assertEqual(result["generationStatus"], "fallback")
        self.assertEqual(result["summarySource"], "program")
        self.assertIn("文字分析暂未生成", result["output"]["summary"])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM practice_analysis_v2_cache").fetchone()[0], 0)
        provider.change = None
        repaired = self.request(self.body([event]))[1]
        self.assertEqual(repaired["generationStatus"], "completed")
        self.assertEqual(repaired["summarySource"], "program")
        self.assertEqual(repaired["output"]["summary"], module.LIMITED_SUMMARIES["investment_only"])


class OutputClaimBoundaryTests(unittest.TestCase):
    def test_limited_feedback_allows_negation_future_checks_and_projects_summary(self):
        prepared = synthetic_input()
        for text in (
            "不能据此判断音准是否稳定或技术进步。",
            "这是投入记录，不代表演奏质量或技术改善。",
            "稳定强弱项与进步结论暂不可判定。",
            "待补充演奏分析后再观察强弱项。",
            "下一次复测时观察演奏能力是否进步。",
        ):
            with self.subTest(text=text):
                legal = valid_output(prepared)
                legal["summary"] = "练习投入已有记录，演奏尚未分析。"
                legal["observations"][0]["description"] = text
                legal["suggestions"] = [{"title": "补充可分析记录", "action": text, "successCheck": "后续记录包含可复核的演奏结果。", "factIds": ["synthetic-timer"]}]
                projected = module.validate_output(legal, prepared)
                self.assertEqual(projected["summary"], module.LIMITED_SUMMARIES["investment_only"])
                self.assertEqual(projected["suggestions"], legal["suggestions"])
                self.assertNotEqual(legal["summary"], projected["summary"])
        no_data = {**prepared, "reportStatus": "no_usable_data", "facts": []}
        self.assertEqual(module.validate_output(valid_output(no_data), no_data)["summary"], module.LIMITED_SUMMARIES["no_usable_data"])
        invalid = {**valid_output(no_data), "summary": "你的演奏能力持续进步。"}
        with self.assertRaises(ValueError):
            module.validate_output(invalid, no_data)

    def test_limited_observations_and_suggestions_reject_explicit_capability_upgrades(self):
        prepared = synthetic_input()
        for text in (
            "你的音准已成为稳定强项。",
            "演奏能力持续进步。",
            "你的节奏表现一直稳定。",
            "不能判断技巧强弱，但你的能力已经提升。",
        ):
            for group in ("observations", "suggestions"):
                with self.subTest(text=text, group=group):
                    invalid = valid_output(prepared)
                    if group == "observations":
                        invalid[group][0]["description"] = text
                    else:
                        invalid[group] = [{"title": "练习建议", "action": text, "successCheck": "保留记录。", "factIds": ["synthetic-timer"]}]
                    with self.assertRaises(ValueError):
                        module.validate_output(invalid, prepared)


class ProviderTransportTests(unittest.TestCase):
    def test_json_mode_configured_prompt_complete_check_and_safe_single_call(self):
        input_value = synthetic_input()
        good = valid_output(input_value)
        for finish, content, expected_error in (("stop", json.dumps(good), False), ("length", json.dumps(good), True), ("stop", "", True), ("stop", '{"x":1,"x":2}', True)):
            with self.subTest(finish=finish, empty=not content), tempfile.TemporaryDirectory() as root:
                key = Path(root) / "synthetic-key"
                synthetic_key = "sk-" + "synthetic" * 4
                key.write_text(synthetic_key, encoding="ascii")
                skill_dir = Path(root) / "private-synthetic-rules"
                skill_dir.mkdir()
                (skill_dir / "deepseek-system-prompt.txt").write_text(SYNTHETIC_PROMPT, encoding="utf8")
                for name in ("aggregate-input.schema.json", "output.schema.json"):
                    shutil.copyfile(module.CONTRACTS / name, skill_dir / name)
                provider = module.DeepSeekProvider(key, skill_dir=skill_dir)
                calls = []
                class Response(io.BytesIO):
                    status = 200
                class Opener:
                    def open(self, request, timeout):
                        calls.append(json.loads(request.data))
                        return Response(module.json_bytes({"choices": [{"finish_reason": finish, "message": {"content": content}}]}))
                provider.opener = Opener()
                if expected_error:
                    with self.assertRaises(module.AnalysisError):
                        provider(input_value)
                else:
                    self.assertEqual(provider(input_value), good)
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["messages"][0]["content"], SYNTHETIC_PROMPT)
                self.assertEqual(calls[0]["response_format"], {"type": "json_object"})
                self.assertEqual(calls[0]["thinking"], {"type": "disabled"})
                self.assertLessEqual(calls[0]["max_tokens"], 4096)
                self.assertNotIn(synthetic_key, json.dumps(calls))

    def test_missing_private_configuration_disables_optional_analysis(self):
        with patch.dict(os.environ, {"NOTELITE_PRACTICE_SKILL_DIR": "", "NOTELITE_DEEPSEEK_KEY_FILE": "synthetic-nonexistent-key-file"}):
            self.assertIsNone(module.from_environment(None))
            with self.assertRaises(module.AnalysisError):
                module.DeepSeekProvider("synthetic-key-never-read")

    def test_environment_directory_and_exact_prompt_hash(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            (directory / "deepseek-system-prompt.txt").write_text(SYNTHETIC_PROMPT, encoding="utf8")
            for name in ("aggregate-input.schema.json", "output.schema.json"):
                shutil.copyfile(module.CONTRACTS / name, directory / name)
            with patch.dict(os.environ, {"NOTELITE_PRACTICE_SKILL_DIR": str(directory)}):
                provider = module.DeepSeekProvider("synthetic-key-never-read")
            self.assertEqual(provider.prompt, SYNTHETIC_PROMPT)
            # Use the actual account store, but do not read/call the key file.
            store = accounts.Store(directory / "test-store")
            analyzer = module.PracticeAnalysis(store, provider)
            self.assertEqual(analyzer.fingerprint["promptHash"], module.sha(SYNTHETIC_PROMPT.encode()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
