"""Offline restoration drill with disposable databases/assets, never production."""
import hashlib
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

import account_service as accounts
import practice_analysis
import test_account_service as fixtures
from test_account_omr_integration import gateway
from test_practice_analysis import Provider

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("offline_migration", HERE / "tools/backup-account-data.py")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def inactive(*args, **kwargs):
    output = "\n\n".join("Id=" + service + "\nLoadState=loaded\nActiveState=inactive" for service in migration.SERVICES) + "\n"
    return SimpleNamespace(returncode=0, stdout=output.encode("ascii"))


class AccountMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_temp = tempfile.TemporaryDirectory()
        cls.source = Path(cls.source_temp.name)
        cls.roots = {label: cls.source / label for label in migration.ROLES}
        cls.moment = 1791766800.0
        cls.store = accounts.Store(cls.roots["accounts"], clock=lambda: cls.moment, disk_reserve=0)
        cls.identity = cls.store.register({"username": "offline_fixture", "password": "only synthetic migration password", "mode": "native"})
        cls.teacher = cls.store.register({"username": "offline_teacher", "password": "only synthetic teacher password", "mode": "native"})
        cls.owner = cls.identity["userId"]
        cls.profile = cls.store.update_profile(cls.owner, {"requestId": str(uuid.uuid4()), "changes": {"displayName": "迁移练琴者", "theme": "dark", "options": {"音效": False}}}, '"profile-0"')
        cls.score = cls.store.create_score(cls.owner, {"title": "原曲名称", "musicxml": accounts.SAMPLE_XML})
        cls.event = cls.event_body(cls.score["id"], "personal", "strict")
        analysis = json.loads((HERE / "fixtures/notewise-v2.json").read_text(encoding="utf8"))
        analysis["takeId"] = analysis["eventId"] = cls.event["eventId"]
        analysis["sourceScoreSha256"] = hashlib.sha256(accounts.SAMPLE_XML.encode()).hexdigest()
        cls.event["analysis"] = analysis
        cls.store.add_history(cls.owner, cls.event)
        cls.store.update_score(cls.owner, cls.score["id"], {"title": "改谱后的名称", "musicxml": accounts.SAMPLE_XML.replace("<step>F</step>", "<step>G</step>")}, cls.score["etag"])
        analyzer = practice_analysis.PracticeAnalysis(cls.store, Provider(), clock=lambda: cls.moment)
        cls.report_id = str(uuid.uuid4())
        cls.report = analyzer.analyse(cls.owner, cls.report_id, [cls.event["eventId"]])
        # Existing explicit classroom submission is backed up; ordinary personal
        # recordings are not uploaded or invented by this fixture.
        course = cls.store.create_course(cls.teacher["userId"], {"title": "Migration classroom"})
        course_score = cls.store.add_course_score(cls.teacher["userId"], course["id"], {"sourceKind": "official", "scoreId": "notelite-four-notes-v1"})
        code = cls.store.create_code(cls.teacher["userId"], course["id"], {})
        cls.store.join_course(cls.owner, {"code": code["code"]})
        assignment = cls.store.create_assignment(cls.teacher["userId"], course["id"], {"title": "Submitted lesson", "courseScoreId": course_score["id"]})
        homework = cls.event_body("notelite-four-notes-v1", "official", "free")
        cls.store.add_history(cls.owner, homework)
        cls.audio = fixtures.AccountHTTPTests.tiny_wav(None)
        upload = cls.store.create_upload(cls.owner, {"assignmentId": assignment["id"], "size": len(cls.audio), "mime": "audio/wav", "sha256": hashlib.sha256(cls.audio).hexdigest()})
        cls.store.append_upload(cls.owner, upload["uploadId"], 0, cls.audio)
        cls.store.complete_upload(cls.owner, upload["uploadId"])
        cls.submission = cls.store.submit(cls.owner, assignment["id"], {"eventId": homework["eventId"], "uploadId": upload["uploadId"]})
        (cls.roots["accounts"] / "internal-key").write_bytes(b"synthetic-private-internal-key-not-production")
        private = cls.roots["accounts"] / "practice-record-analysis"
        private.mkdir()
        (private / "private-fixture.txt").write_bytes(b"synthetic operator asset, not a real user prompt")
        cls.gstore = gateway.Store(cls.roots["gateway"])
        cls.job_id = str(uuid.uuid4())
        cls.gstore.register(cls.job_id, cls.owner)
        cls.roots["omr"].mkdir()
        (cls.roots["omr"] / "access-token").write_bytes(b"synthetic-private-worker-token-not-production")
        job = cls.roots["omr"] / "jobs" / cls.job_id
        job.mkdir(parents=True)
        (job / "original.pdf").write_bytes(b"%PDF-1.4\nSynthetic offline fixture only\n")
        (job / "score.musicxml").write_text(accounts.SAMPLE_XML, encoding="utf8")
        (job / "score.mid").write_bytes(b"MThd\x00\x00\x00\x06\x00\x00\x00\x01\x01\xe0MTrk\x00\x00\x00\x04\x00\xff\x2f\x00")
        (job / "job.json").write_text(json.dumps({"id": cls.job_id, "state": "succeeded", "revision": 1, "filename": "original.pdf", "input": "original.pdf", "scores": [{"name": "Fixture", "noteCount": 4, "musicxml": "score.musicxml", "midi": "score.mid"}]}), encoding="utf8")
        cls.baseline = cls.source / "private-backup"
        migration.backup(cls.roots, cls.baseline, quiesced=True, runner=inactive)

    @classmethod
    def event_body(cls, score, kind, mode):
        return {"eventId": str(uuid.uuid4()), "sourceKind": kind, "scoreId": score, "mode": mode, "durationSeconds": 30, "startedAt": accounts.now_stamp(cls.moment - 60), "endedAt": accounts.now_stamp(cls.moment - 30)}

    @classmethod
    def tearDownClass(cls):
        cls.source_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / "bundle"
        shutil.copytree(self.baseline, self.bundle)
        self.targets = {label: self.root / ("restored-" + label) for label in migration.ROLES}

    def rehash_manifest(self, transform):
        path = self.bundle / "MANIFEST.json"
        manifest = json.loads(path.read_bytes())
        transform(manifest)
        raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        path.write_bytes(raw)
        (self.bundle / "MANIFEST.sha256").write_bytes((hashlib.sha256(raw).hexdigest() + "\n").encode("ascii"))

    def assert_rejected_before_target_writes(self):
        with self.assertRaises((migration.MigrationError, OSError)):
            migration.restore(self.bundle, self.targets, quiesced=True, runner=inactive)
        self.assertTrue(all(not path.exists() for path in self.targets.values()))
        self.assertEqual(list(self.root.glob(".notelite-restore-*")), [])

    def test_new_stores_read_same_uuid_names_snapshots_versions_cache_assets_and_classroom_audio(self):
        result = migration.restore(self.bundle, self.targets, quiesced=True, runner=inactive)
        self.assertEqual(result["status"], "restored")
        reopened = accounts.Store(self.targets["accounts"], clock=lambda: self.moment, disk_reserve=0)
        identity = reopened.login({"username": "offline_fixture", "password": "only synthetic migration password", "mode": "native"})
        self.assertEqual(identity["userId"], self.owner)
        self.assertEqual(reopened.read_profile(self.owner), self.profile)
        metadata, current_xml = reopened.read_score(self.owner, self.score["id"])
        self.assertEqual(metadata["title"], "改谱后的名称")
        self.assertEqual(metadata["revision"], 2)
        self.assertNotEqual(current_xml, accounts.SAMPLE_XML)
        self.assertEqual(reopened.history_xml(self.owner, self.event["eventId"])[0], accounts.SAMPLE_XML)
        version = reopened.read_history_analysis(self.owner, self.event["eventId"], 1)
        self.assertEqual(version["analysis"]["eventId"], self.event["eventId"])
        analyzer = practice_analysis.PracticeAnalysis(reopened, Provider(), clock=lambda: self.moment)
        replay = analyzer.analyse(self.owner, self.report_id, [self.event["eventId"]])
        self.assertEqual(replay["output"], self.report["output"])
        self.assertTrue(replay["cached"])
        self.assertEqual(len(analyzer.provider.calls), 0)
        restored_gateway = gateway.Store(self.targets["gateway"])
        restored_gateway.own(self.job_id, self.owner)
        with self.assertRaises(gateway.GatewayError):
            restored_gateway.own(self.job_id, self.teacher["userId"])
        original = self.targets["omr"] / "jobs" / self.job_id / "original.pdf"
        self.assertEqual(original.read_bytes(), (self.roots["omr"] / "jobs" / self.job_id / "original.pdf").read_bytes())
        self.assertEqual(json.loads((original.parent / "job.json").read_text())["id"], self.job_id)
        path, _, size = reopened.submission_audio(self.teacher["userId"], self.submission["id"])
        self.assertEqual(path.read_bytes(), self.audio)
        self.assertEqual(size, len(self.audio))
        for label, name in (("accounts", "internal-key"), ("omr", "access-token")):
            self.assertEqual((self.targets[label] / name).read_bytes(), (self.roots[label] / name).read_bytes())

    def test_quiesced_is_required_and_linux_checks_actual_three_inactive_services(self):
        with self.assertRaises(migration.MigrationError):
            migration.backup(self.roots, self.root / "new", runner=inactive)
        self.assertFalse((self.root / "new").exists())
        commands = []
        def stopped(command, **kwargs):
            commands.append(command)
            return inactive()
        with patch.object(migration.sys, "platform", "linux"):
            migration.ensure_quiesced(True, stopped)
            self.assertEqual(commands[0], ["systemctl", "show", "--property=Id,LoadState,ActiveState", "--no-pager", *migration.SERVICES])
            good = inactive().stdout
            for result in (SimpleNamespace(returncode=0, stdout=good.replace(b"ActiveState=inactive", b"ActiveState=active", 1)), SimpleNamespace(returncode=1, stdout=good), SimpleNamespace(returncode=0, stdout=good.replace(b"LoadState=loaded", b"LoadState=not-found", 1)), SimpleNamespace(returncode=0, stdout=good.split(b"\n\n", 1)[0])):
                with self.assertRaises(migration.MigrationError):
                    migration.ensure_quiesced(True, lambda *a, **k: result)
            with self.assertRaises(migration.MigrationError):
                migration.ensure_quiesced(True, lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("systemctl", 10)))

    def test_manifest_damage_or_missing_file_refuses_before_any_restoration_write(self):
        (self.bundle / "MANIFEST.json").write_bytes((self.bundle / "MANIFEST.json").read_bytes() + b" ")
        self.assert_rejected_before_target_writes()
        shutil.copy2(self.baseline / "MANIFEST.json", self.bundle / "MANIFEST.json")
        (self.bundle / "data/accounts/internal-key").unlink()
        self.assert_rejected_before_target_writes()

    def test_changed_data_or_extra_file_refuses_before_any_restoration_write(self):
        key = self.bundle / "data/accounts/internal-key"
        key.write_bytes(b"changed fixture")
        self.assert_rejected_before_target_writes()
        shutil.copy2(self.baseline / "data/accounts/internal-key", key)
        (self.bundle / "unexpected-private-file").write_bytes(b"extra")
        self.assert_rejected_before_target_writes()

    def test_traversal_absolute_backslash_and_drive_names_are_rejected_even_if_manifest_rehashed(self):
        for bad in ("../escape", "/absolute", "a/../../escape", "a\\escape", "C:/escape", "./escape", "a//escape"):
            shutil.copy2(self.baseline / "MANIFEST.json", self.bundle / "MANIFEST.json")
            self.rehash_manifest(lambda value: value["files"][0].update(path=bad))
            with self.subTest(path=bad):
                self.assert_rejected_before_target_writes()
        self.assertFalse((self.root / "escape").exists())

    def test_malformed_duplicate_and_colliding_manifest_rows_are_rejected(self):
        changes = [lambda v: v["files"].append(dict(v["files"][0])), lambda v: v["files"][0].update(root=[]), lambda v: v["files"][0].update(size=True), lambda v: v.update(schemaVersion=True)]
        for change in changes:
            shutil.copy2(self.baseline / "MANIFEST.json", self.bundle / "MANIFEST.json")
            self.rehash_manifest(change)
            self.assert_rejected_before_target_writes()

    def test_nonempty_or_overlapping_targets_cannot_be_overwritten(self):
        destination = self.targets["accounts"]
        destination.mkdir()
        existing = destination / "do-not-touch.txt"
        existing.write_bytes(b"existing unrelated data")
        with self.assertRaises(migration.MigrationError):
            migration.restore(self.bundle, self.targets, quiesced=True, runner=inactive)
        self.assertEqual(existing.read_bytes(), b"existing unrelated data")
        self.assertFalse(self.targets["gateway"].exists())
        with self.assertRaises(migration.MigrationError):
            migration.restore(self.bundle, {"accounts": self.root / "nested", "gateway": self.root / "nested/gateway", "omr": self.root / "other"}, quiesced=True, runner=inactive)

    def test_empty_targets_are_supported_and_backup_cannot_be_its_own_source(self):
        for path in self.targets.values():
            path.mkdir()
        self.assertEqual(migration.restore(self.bundle, self.targets, quiesced=True, runner=inactive)["status"], "restored")
        with self.assertRaises(migration.MigrationError):
            migration.backup(self.roots, self.roots["accounts"] / "nested-backup", quiesced=True, runner=inactive)
        with self.assertRaises(migration.MigrationError):
            migration.backup(self.roots, self.baseline, quiesced=True, runner=inactive)
        self.assertTrue((self.baseline / "MANIFEST.json").exists())

    def test_sqlite_backup_keeps_committed_wal_rows_without_copying_wal_sidecars(self):
        path = self.roots["gateway"] / "fixture.sqlite3"
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE fixture(value TEXT)")
            connection.execute("INSERT INTO fixture VALUES('committed WAL data')")
            connection.commit()
            self.assertTrue(Path(str(path) + "-wal").exists())
            output = self.root / "wal-backup"
            migration.backup(self.roots, output, quiesced=True, runner=inactive)
            with closing(sqlite3.connect(output / "data/gateway/fixture.sqlite3")) as db:
                self.assertEqual(db.execute("SELECT value FROM fixture").fetchone()[0], "committed WAL data")
            self.assertFalse((output / "data/gateway/fixture.sqlite3-wal").exists())
        finally:
            connection.close()
            path.unlink(missing_ok=True)

    def test_symlink_source_bundle_and_target_are_rejected(self):
        link = self.root / "link"
        try:
            link.symlink_to(self.roots["accounts"], target_is_directory=True)
        except OSError:
            # Windows runners commonly lack CreateSymbolicLink privilege.
            # Still execute the rejection branches with a narrow filesystem mock.
            original = migration.Path.is_symlink
            with patch.object(migration.Path, "is_symlink", lambda path: path == self.roots["accounts"] or original(path)):
                with self.assertRaises(migration.MigrationError):
                    migration.backup(self.roots, self.root / "symlink-backup", quiesced=True, runner=inactive)
            return
        with self.assertRaises(migration.MigrationError):
            migration.backup({**self.roots, "accounts": link}, self.root / "symlink-backup", quiesced=True, runner=inactive)
        link.unlink()
        (self.bundle / "data/accounts/extra-link").symlink_to(self.roots["accounts"] / "internal-key")
        self.assert_rejected_before_target_writes()
        (self.bundle / "data/accounts/extra-link").unlink()
        self.targets["accounts"].symlink_to(self.roots["accounts"], target_is_directory=True)
        with self.assertRaises(migration.MigrationError):
            migration.restore(self.bundle, self.targets, quiesced=True, runner=inactive)

    def test_cli_verify_reports_counts_and_never_outputs_private_content(self):
        result = subprocess.run([sys.executable, str(HERE / "tools/backup-account-data.py"), "verify", "--bundle", str(self.bundle)], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "verified")
        for secret in ("synthetic-private", "migration password", self.owner, "迁移练琴者", "practice-record-analysis"):
            self.assertNotIn(secret, result.stdout + result.stderr)

    @unittest.skipUnless(sys.platform.startswith("linux"), "POSIX permission assertion runs on Linux CI; Windows privacy needs operator ACLs")
    def test_private_backup_and_restored_directory_permissions(self):
        migration.restore(self.bundle, self.targets, quiesced=True, runner=inactive)
        for root in [self.bundle, *self.targets.values()]:
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
            for path in root.rglob("*"):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o600)


if __name__ == "__main__":
    unittest.main()
