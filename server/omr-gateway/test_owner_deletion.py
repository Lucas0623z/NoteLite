"""Actual HTTP and cross-instance SQLite races, using synthetic private jobs."""
import concurrent.futures
from pathlib import Path
import threading
import time
import uuid
import unittest

import gateway
import test_gateway


class OwnerDeletionTests(unittest.TestCase):
    setUp = test_gateway.GatewayTests.setUp
    tearDown = test_gateway.GatewayTests.tearDown
    request = test_gateway.GatewayTests.request
    pair = test_gateway.GatewayTests.pair
    create = test_gateway.GatewayTests.create

    def test_account_transaction_failure_rolls_back_owner_and_legacy_fence(self):
        old, _ = self.pair(str(uuid.uuid4()))
        user = str(uuid.uuid4())
        owned = self.create(old)
        with self.store.connect() as db:
            db.execute("INSERT INTO legacy_claims VALUES(?,?,?,0)", (old["owner"],user,time.time()))
        with self.assertRaisesRegex(RuntimeError, "synthetic account commit failure"):
            with self.store.deletion_fence(user) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM deleted_owners").fetchone()[0], 2)
                raise RuntimeError("synthetic account commit failure")
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM deleted_owners").fetchone()[0], 0)
        with self.store.owner_operation(user): pass
        self.store.own(owned["id"], old["owner"])

    def test_uncommitted_fence_blocks_late_writer_until_account_rollback(self):
        owner = str(uuid.uuid4())
        other_process = gateway.Store(Path(self.temp.name))
        attempted, written = threading.Event(), threading.Event()
        job = str(uuid.uuid4())
        def write():
            attempted.set()
            with other_process.owner_operation(owner) as db:
                other_process.register(job, owner, db)
            written.set()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            with self.assertRaisesRegex(RuntimeError, "rollback account deletion"):
                with self.store.deletion_fence(owner):
                    late = pool.submit(write)
                    self.assertTrue(attempted.wait(3))
                    self.assertFalse(written.wait(.1), "uncommitted tombstone must retain the writer reservation")
                    raise RuntimeError("rollback account deletion")
            late.result(5)
        self.assertEqual(self.store.list_ids(owner), {job})

    def test_committed_fence_rejects_late_writer_and_retains_no_new_job(self):
        owner = str(uuid.uuid4())
        other_process = gateway.Store(Path(self.temp.name))
        attempted, completed = threading.Event(), threading.Event()
        job = str(uuid.uuid4())
        def write():
            attempted.set()
            try:
                with other_process.owner_operation(owner) as db:
                    other_process.register(job, owner, db)
            finally:
                completed.set()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            with self.store.deletion_fence(owner):
                late = pool.submit(write)
                self.assertTrue(attempted.wait(3))
                self.assertFalse(completed.wait(.1))
            with self.assertRaises(gateway.GatewayError) as failure:
                late.result(5)
        self.assertEqual(failure.exception.status, 410)
        with self.store.connect() as db:
            self.assertFalse(db.execute("SELECT 1 FROM jobs WHERE id=?", (job,)).fetchone())

    def test_pairing_and_direct_registration_reserve_owner_before_their_first_write(self):
        # Pause immediately after the owner check. Deletion in a separately
        # opened SQLite Store must wait even before INSERT has started.
        for action in ("pair", "register"):
            with self.subTest(action=action):
                owner = str(uuid.uuid4())
                other_process = gateway.Store(Path(self.temp.name))
                checked, release, frozen = threading.Event(), threading.Event(), threading.Event()
                original = self.store.check_owner
                def paused_check(db, candidate):
                    original(db, candidate)
                    checked.set()
                    if not release.wait(5): raise AssertionError("synthetic owner check remained paused")
                self.store.check_owner = paused_check
                def freeze():
                    other_process.freeze_owner(owner)
                    frozen.set()
                try:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                        write = pool.submit(self.store.pair, owner) if action == "pair" else pool.submit(self.store.register, str(uuid.uuid4()), owner)
                        self.assertTrue(checked.wait(3))
                        deletion = pool.submit(freeze)
                        try: self.assertFalse(frozen.wait(.1), "deletion passed a checked owner before its metadata write")
                        finally: release.set()
                        write.result(5)
                        deletion.result(5)
                finally:
                    release.set()
                    self.store.check_owner = original
                other_process.finish_delete_owner(owner)
                with self.store.connect() as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM pairs WHERE owner=?", (owner,)).fetchone()[0], 0)
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs WHERE owner=?", (owner,)).fetchone()[0], 0)

    def test_freeze_drains_accepted_upload_then_blocks_cached_owner_and_preserves_other_owner(self):
        first, _ = self.pair(str(uuid.uuid4()))
        other, _ = self.pair(str(uuid.uuid4()))
        second_job = self.create(other)
        self.upstream.upload_entered, self.upstream.upload_release = threading.Event(), threading.Event()
        another_process_store = gateway.Store(Path(self.temp.name))
        finished = threading.Event()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            upload = pool.submit(self.create, first)
            self.assertTrue(self.upstream.upload_entered.wait(3))
            def freeze():
                ids = another_process_store.delete_owner(first["owner"])
                finished.set()
                return ids
            deletion = pool.submit(freeze)
            self.assertFalse(finished.wait(.1), "freeze must wait for an accepted upstream write")
            self.upstream.upload_release.set()
            accepted = upload.result(5)
            self.assertEqual(deletion.result(5), [accepted["id"]])
        with self.assertRaises(gateway.GatewayError) as failure:
            with self.store.owner_operation(first["owner"]):
                self.fail("cached authenticated owner bypassed durable tombstone")
        self.assertEqual(failure.exception.status, 410)
        self.assertEqual(self.request("POST", "/api/jobs?filename=late.xml", b"x", {"Authorization":"Bearer "+first["token"]})[0], 410)
        another_process_store.finish_delete_owner(first["owner"])
        another_process_store.finish_delete_owner(first["owner"])
        self.store.own(second_job["id"], other["owner"])
        self.assertEqual(self.store.list_ids(other["owner"]), {second_job["id"]})
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs WHERE owner=?",(first["owner"],)).fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM devices WHERE owner=?",(first["owner"],)).fetchone()[0],0)
        self.assertEqual(another_process_store.delete_owner(first["owner"]), [])

    def test_lost_upload_response_retains_owned_job_id_for_actual_cleanup(self):
        first, _ = self.pair(str(uuid.uuid4()))
        self.upstream.lose_upload_response = True
        status, _, _ = self.request("POST", "/api/jobs?filename=synthetic.xml", b"<score-partwise/>", {"Authorization":"Bearer "+first["token"]})
        self.assertEqual(status, 502)
        owned = self.store.delete_owner(first["owner"])
        self.assertEqual(len(owned),1)
        self.assertIn(owned[0],self.upstream.jobs)
        self.assertEqual(self.upstream.received[-1][2]["X-NoteLite-Job-Id"],owned[0])

    def test_deleted_legacy_migration_owner_cannot_receive_late_upload_or_new_pairing(self):
        old, _ = self.pair(str(uuid.uuid4()))
        user = str(uuid.uuid4())
        with self.store.connect() as db:
            db.execute("INSERT INTO legacy_claims VALUES(?,?,?,0)",(old["owner"],user,time.time()))
            db.execute("UPDATE devices SET revoked=1 WHERE owner=?",(old["owner"],))
        self.store.delete_owner(user)
        self.store.finish_delete_owner(user)
        for owner in (old["owner"],user):
            with self.assertRaises(gateway.GatewayError):
                with self.store.owner_operation(owner): pass
            with self.assertRaises(gateway.GatewayError): self.store.pair(owner)

    def test_cleanup_is_not_a_public_unauthed_or_other_owner_delete_route(self):
        first, _ = self.pair(str(uuid.uuid4()))
        second, _ = self.pair(str(uuid.uuid4()))
        job = self.create(first)
        path = "/api/jobs/"+job["id"]
        self.assertEqual(self.request("DELETE",path)[0],401)
        self.assertEqual(self.request("DELETE",path,headers={"Authorization":"Bearer "+second["token"]})[0],404)
        self.assertEqual(self.request("DELETE",path,headers={"Authorization":"Bearer "+first["token"]})[0],405)
        self.assertIn(job["id"],self.upstream.jobs)


if __name__ == "__main__": unittest.main()
