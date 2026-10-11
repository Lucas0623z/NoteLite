"""Private cancel/delete races with actual OS processes and temporary synthetic files.

These tests do not claim actual Audiveris recognition or use user-owned jobs.
The descendant-group test runs on the production POSIX platform.
"""
import concurrent.futures
from http.client import HTTPConnection
import io
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import uuid

import server

TOKEN="synthetic-deletion-test-"+"a"*40
XML=b'<score-partwise><part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list><part id="P1"><measure><attributes><divisions>1</divisions></attributes><note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note></measure></part></score-partwise>'
# Complete 1x1 grayscale PNG with IHDR/IDAT/IEND and valid chunk CRCs.
# The production input guard must run unchanged before the process race test.
PNG=bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108000000003a7e9b550000000a49444154789c63f80f0001010100b138f6140000000049454e44ae426082')


def wait_for(predicate, timeout=5):
    deadline=time.monotonic()+timeout
    while not predicate():
        if time.monotonic()>deadline: raise AssertionError("Synthetic process condition did not arrive")
        time.sleep(.01)


class DeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.script=self.root/"synthetic-process.py"
        self.script.write_text('''import os,sys,time,subprocess,signal
from pathlib import Path
root=Path.cwd()
if "child" in sys.argv:
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    (root/"child.pid").write_text(str(os.getpid()))
    while True:
        root.mkdir(exist_ok=True)
        (root/"late-child-write").write_text("synthetic")
        time.sleep(.02)
if "parent" in sys.argv:
    subprocess.Popen([sys.executable,__file__,"child"],cwd=root)
    (root/"parent.pid").write_text(str(os.getpid()))
else:
    (root/"midi-ready").write_text(str(os.getpid()))
while True: time.sleep(.05)
''',encoding="utf8")
        self.service=server.JobService(self.root/"jobs",TOKEN,engine_command=[sys.executable,str(self.script),"parent"],midi_command=[sys.executable,str(self.script)],timeout=20,midi_timeout=20,queue_size=4)
    def tearDown(self):
        for identity in list(self.service.jobs):
            self.service.delete(identity)
        self.service.close()
        self.temp.cleanup()
    def submit(self,data=XML,extension="musicxml",job_id=None):
        return self.service.submit("synthetic."+extension,io.BytesIO(data),len(data),job_id)
    def test_process_group_fixture_passes_real_png_input_validation_on_every_platform(self):
        path=self.root/"valid-fixture.png";path.write_bytes(PNG)
        server.validate_input(path,".png")
        self.assertEqual((int.from_bytes(PNG[16:20],"big"),int.from_bytes(PNG[20:24],"big")),(1,1))
    def test_running_converter_is_stopped_before_directory_delete_and_retry_is_idempotent(self):
        job=self.submit();folder=self.service.directory(job["id"])
        wait_for(lambda:(folder/"midi-ready").is_file())
        start=time.monotonic();result=self.service.delete(job["id"])
        self.assertTrue(result["deleted"]);self.assertFalse(folder.exists())
        self.assertLess(time.monotonic()-start,8)
        time.sleep(.2);self.assertFalse(folder.exists(),"writer recreated a deleted job")
        self.assertTrue(self.service.delete(job["id"])["alreadyAbsent"])
        self.assertTrue(self.service.worker.is_alive())
    def test_queued_delete_does_not_kill_another_job_or_break_worker_capacity(self):
        active=self.submit();active_folder=self.service.directory(active["id"])
        wait_for(lambda:(active_folder/"midi-ready").is_file())
        queued=self.submit();queued_folder=self.service.directory(queued["id"])
        self.service.delete(queued["id"])
        self.assertTrue(active_folder.exists());self.assertEqual(self.service.get(active["id"])["state"],"running")
        self.service.delete(active["id"])
        self.service.pending.join()
        self.assertFalse(queued_folder.exists());self.assertTrue(self.service.worker.is_alive())
        next_job=self.submit();self.service.delete(next_job["id"]);self.service.pending.join()
    @unittest.skipUnless(os.name=="posix","production POSIX process-group cancellation")
    def test_actual_process_group_kills_descendant_after_leader_exit_and_prevents_recreation(self):
        job=self.submit(PNG,"png");folder=self.service.directory(job["id"])
        wait_for(lambda:(folder/"child.pid").is_file() and (folder/"child.pid").read_text().strip().isdigit())
        child=int((folder/"child.pid").read_text())
        self.service.delete(job["id"])
        def child_is_stopped():
            path=Path(f"/proc/{child}/stat")
            return not path.exists() or path.read_text().split()[2] in {"Z","X"}
        wait_for(child_is_stopped)
        time.sleep(.2);self.assertFalse(folder.exists())
    def test_requested_private_uuid_collision_never_deletes_existing_upload(self):
        identity=str(uuid.uuid4());job=self.submit(job_id=identity);folder=self.service.directory(identity)
        with self.assertRaises(server.APIError) as failure:self.submit(job_id=identity)
        self.assertEqual(failure.exception.status,409);self.assertTrue((folder/"input.musicxml").is_file())
        self.assertEqual(job["id"],identity)
        for invalid in ("../outside",identity.upper(),"not-a-uuid"):
            with self.assertRaises(server.APIError):self.service.delete(invalid)
        self.assertTrue(folder.exists())
    def test_inflight_upload_cannot_be_reported_deleted_before_it_commits(self):
        identity=str(uuid.uuid4());entered,release=threading.Event(),threading.Event()
        class PausedStream:
            def read(self, amount):
                entered.set();release.wait(5);return XML
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            upload=pool.submit(self.service.submit,"synthetic.musicxml",PausedStream(),len(XML),identity)
            self.assertTrue(entered.wait(3))
            try:
                with self.assertRaises(server.APIError) as failure:self.service.delete(identity)
                self.assertEqual(failure.exception.status,503)
            finally:release.set()
            self.assertEqual(upload.result(5)["id"],identity)
        self.assertTrue(self.service.delete(identity)["deleted"])
        self.assertFalse(self.service.directory(identity).exists())
    def test_known_uuid_orphan_without_active_writer_is_actually_deleted(self):
        identity=str(uuid.uuid4());folder=self.service.directory(identity);folder.mkdir();(folder/"partial-input.png").write_bytes(b"synthetic abandoned upload")
        self.assertFalse(self.service.delete(identity)["alreadyAbsent"]);self.assertFalse(folder.exists());self.assertTrue(self.service.delete(identity)["alreadyAbsent"])
    def test_loopback_delete_requires_private_bearer_and_cannot_delete_action_or_query_route(self):
        job=self.submit();http=server.Server(("127.0.0.1",0),self.service)
        threading.Thread(target=http.serve_forever,daemon=True).start()
        def request(path,token=None):
            connection=HTTPConnection("127.0.0.1",http.server_port,timeout=5)
            try:
                connection.request("DELETE",path,headers={} if token is None else {"Authorization":"Bearer "+token})
                response=connection.getresponse();response.read();return response.status
            finally:connection.close()
        try:
            path="/api/jobs/"+job["id"]
            self.assertEqual(request(path),401);self.assertEqual(request(path,"device-token"),401)
            self.assertEqual(request(path+"/original",TOKEN),405)
            self.assertEqual(request(path+"?score=0",TOKEN),405)
            self.assertTrue(self.service.directory(job["id"]).exists())
            self.assertEqual(request(path,TOKEN),200);self.assertEqual(request(path,TOKEN),200)
        finally:http.shutdown();http.server_close()


if __name__=="__main__":unittest.main()
