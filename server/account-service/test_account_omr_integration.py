"""Real HTTP/SQLite auth and ownership integration; synthetic OMR transport."""
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import unittest
from urllib.parse import urlsplit
import uuid

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/("omr-gateway" if (HERE.parent/"omr-gateway").is_dir() else "gateway")))
import gateway
from account_auth import AccountResolver
import account_service as account
from omr_bridge import OMRBridge
from integrated_service import IntegratedStore


class OMRHandler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def reply(self,status,value,etag=None):
        raw=json.dumps(value).encode() if isinstance(value,dict) else value
        self.send_response(status);self.send_header("Content-Length",str(len(raw)))
        self.send_header("Content-Type","application/json" if isinstance(value,dict) else "application/vnd.recordare.musicxml+xml")
        if etag:self.send_header("ETag",etag)
        self.end_headers();self.wfile.write(raw)
    def dispatch(self):
        if self.headers.get("Authorization")!="Bearer "+self.server.token:self.reply(401,{});return
        path=urlsplit(self.path).path
        if path=="/api/jobs" and self.command=="POST":
            self.rfile.read(int(self.headers["Content-Length"]));job={"id":self.headers.get("X-NoteLite-Job-Id") or str(uuid.uuid4()),"state":"succeeded","revision":1,"filename":"synthetic.musicxml"}
            self.server.jobs[job["id"]]=job;self.reply(202,job)
        elif path=="/api/jobs":self.reply(200,{"jobs":list(self.server.jobs.values())})
        elif path.startswith("/api/jobs/") and self.command=="DELETE":
            if getattr(self.server,"fail_delete",False): self.reply(503,{});return
            job_id=path.split("/")[3]; absent=self.server.jobs.pop(job_id,None) is None
            self.reply(200,{"id":job_id,"deleted":True,"alreadyAbsent":absent})
        elif path.startswith("/api/jobs/"):
            job=self.server.jobs.get(path.split("/")[3])
            if not job:self.reply(404,{});return
            if path.endswith("musicxml"):self.reply(200,account.SAMPLE_XML.encode(),f'"{job["revision"]}"')
            else:self.reply(200,job)
        else:self.reply(404,{})
    do_GET=do_POST=do_DELETE=dispatch


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=tempfile.TemporaryDirectory();cls.origin="https://notelite.example";cls.key=secrets.token_urlsafe(32)
        cls.gstore=gateway.Store(Path(cls.root.name)/"gateway");cls.upstream=ThreadingHTTPServer(("127.0.0.1",0),OMRHandler)
        cls.upstream.token=secrets.token_urlsafe(32);cls.upstream.jobs={}
        cls.bridge=OMRBridge(cls.gstore,cls.upstream.token,cls.origin,upstream_port=cls.upstream.server_port)
        cls.astore=IntegratedStore(Path(cls.root.name)/"accounts",omr_import=cls.bridge.import_score,legacy_claim=cls.bridge.claim,omr_delete=cls.bridge.delete_owner,omr_fence=cls.bridge.deletion_fence)
        def user_exists(owner):
            with cls.astore.connect() as db:return db.execute("SELECT 1 FROM users WHERE id=?",(owner,)).fetchone() is not None
        cls.bridge.account_user_exists=user_exists
        cls.account_server=account.Server(("127.0.0.1",0),cls.astore,cls.origin,cls.key)
        cls.gateway_server=gateway.Server(("127.0.0.1",0),cls.gstore,cls.origin,cls.upstream.token,upstream_port=cls.upstream.server_port,
                                         account_resolver=AccountResolver(cls.account_server.server_port,cls.key,cls.origin))
        for server in (cls.upstream,cls.account_server,cls.gateway_server):threading.Thread(target=server.serve_forever,daemon=True).start()
        cls.first=cls.astore.register({"username":"first","password":"only synthetic long test password","mode":"native"})
        cls.other=cls.astore.register({"username":"other","password":"only synthetic long test password","mode":"native"})
        cls.second=cls.astore.login({"username":"first","password":"only synthetic long test password","mode":"native"})
    @classmethod
    def tearDownClass(cls):
        for server in (cls.gateway_server,cls.account_server,cls.upstream):server.shutdown();server.server_close()
        cls.root.cleanup()
    def call(self,method,path,body=None,identity=None,headers=None,expected=200,account_api=False):
        fields={"Host":"notelite.example",**(headers or {})}
        if identity:fields["Authorization"]="Bearer "+identity["token"]
        if isinstance(body,dict):body=json.dumps(body).encode();fields["Content-Type"]="application/json"
        connection=HTTPConnection("127.0.0.1",(self.account_server if account_api else self.gateway_server).server_port,timeout=15)
        try:
            connection.request(method,path,body,fields);response=connection.getresponse();raw=response.read()
            self.assertEqual(response.status,expected,"HTTP status mismatch")
            return json.loads(raw) if response.getheader("Content-Type","").startswith("application/json") else raw
        finally:connection.close()
    def upload(self,identity=None,headers=None):return self.call("POST","/api/jobs?filename=synthetic.musicxml",account.SAMPLE_XML.encode(),identity,headers,202)
    def legacy(self,kind="native",owner=None):return self.gstore.redeem(self.gstore.pair(owner or str(uuid.uuid4()))["code"],"Old synthetic device",kind)
    def test_account_deletion_cancels_private_omr_results_and_preserves_other_owner(self):
        user=self.astore.register({"username":"delete_"+uuid.uuid4().hex[:16],"password":"only synthetic long test password","mode":"native"})
        first=self.upload(user);other=self.upload(self.other)
        old=self.legacy();legacy_job=self.upload(old)
        self.call("POST","/api/account/legacy/claim",{"deviceToken":old["token"],"deviceKind":"native"},user,account_api=True)
        self.call("DELETE","/api/account/account",{"password":"only synthetic long test password","confirmation":"DELETE_ACCOUNT"},user,account_api=True)
        self.assertNotIn(first["id"],self.upstream.jobs)
        self.assertNotIn(legacy_job["id"],self.upstream.jobs)
        self.assertIn(other["id"],self.upstream.jobs)
        self.call("GET","/api/jobs/"+other["id"],identity=self.other)
        self.call("GET","/api/jobs",identity=user,expected=401)
        with self.gstore.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs WHERE owner=?",(user["userId"],)).fetchone()[0],0)
            self.assertIsNotNone(db.execute("SELECT 1 FROM deleted_owners WHERE owner=?",(old["owner"],)).fetchone())

    def test_account_delete_sql_rollback_does_not_leave_gateway_owner_frozen(self):
        user=self.astore.register({"username":"rollback_"+uuid.uuid4().hex[:16],"password":"only synthetic long test password","mode":"native"})
        job=self.upload(user)
        with self.astore.connect() as db:
            db.execute("CREATE TRIGGER synthetic_rollback BEFORE DELETE ON users WHEN OLD.id='"+user["userId"]+"' BEGIN SELECT RAISE(ABORT,'synthetic SQL failure'); END")
        try:
            self.call("DELETE","/api/account/account",{"password":"only synthetic long test password","confirmation":"DELETE_ACCOUNT"},user,expected=503,account_api=True)
            # Bridge maps a transaction/fence failure to static retryable 503.
            self.call("GET","/api/account/me",identity=user,account_api=True)
            self.call("GET","/api/jobs/"+job["id"],identity=user)
            self.upload(user)
            with self.gstore.connect() as db:
                self.assertIsNone(db.execute("SELECT 1 FROM deleted_owners WHERE owner=?",(user["userId"],)).fetchone())
        finally:
            with self.astore.connect() as db: db.execute("DROP TRIGGER synthetic_rollback")

    def test_worker_unavailable_retains_cleanup_queue_and_blocked_owner_until_retry(self):
        user=self.astore.register({"username":"retry_"+uuid.uuid4().hex[:16],"password":"only synthetic long test password","mode":"native"})
        job=self.upload(user)
        self.upstream.fail_delete=True
        try:
            result=self.call("DELETE","/api/account/account",{"password":"only synthetic long test password","confirmation":"DELETE_ACCOUNT"},user,expected=202,account_api=True)
            self.assertFalse(result["deleted"])
            self.assertTrue(result["accountDeleted"])
            self.assertIn(job["id"],self.upstream.jobs)
            self.call("GET","/api/jobs",identity=user,expected=401)
            with self.assertRaises(gateway.GatewayError): self.gstore.register(str(uuid.uuid4()),user["userId"])
        finally: self.upstream.fail_delete=False
        self.assertTrue(self.astore.process_deletion(user["userId"]))
        self.assertNotIn(job["id"],self.upstream.jobs)

    def test_01_account_cross_device_job_and_exact_snapshot(self):
        job=self.upload(self.first);self.call("GET","/api/jobs/"+job["id"],identity=self.second)
        self.call("GET","/api/jobs/"+job["id"],identity=self.other,expected=404)
        created=self.call("POST","/api/account/scores",{"title":"Snapshot","jobId":job["id"],"scoreIndex":0,"revision":1},self.first,expected=201,account_api=True)
        self.assertEqual(self.call("GET","/api/account/scores/"+created["id"]+"/musicxml",identity=self.second,account_api=True),account.SAMPLE_XML.encode())
        self.upstream.jobs[job["id"]]["revision"]=2
        self.call("POST","/api/account/scores",{"title":"Stale","jobId":job["id"],"scoreIndex":0,"revision":1},self.first,expected=409,account_api=True)
        self.call("POST","/api/account/scores",{"title":"Wrong owner","jobId":job["id"],"scoreIndex":0,"revision":2},self.other,expected=404,account_api=True)
    def test_02_invalid_account_cookie_cannot_fall_back(self):
        old=self.legacy("browser");cookies=gateway.COOKIE+"="+old["token"]+"; __Host-notelite-account="+secrets.token_urlsafe(32)
        self.call("GET","/api/jobs",headers={"Cookie":cookies},expected=401)
        self.call("GET","/api/jobs",identity=self.first,headers={"Cookie":cookies},expected=401)
    def test_03_browser_account_csrf_profile_and_logout(self):
        login=self.astore.login({"username":"first","password":"only synthetic long test password","mode":"browser"})
        fields={"Cookie":"__Host-notelite-account="+login["token"],"Origin":self.origin}
        self.call("POST","/api/jobs?filename=bad.xml",b"x",headers=fields,expected=403)
        fields["X-NoteLite-CSRF"]=login["csrf"];job=self.upload(headers=fields)
        self.call("GET","/api/jobs/"+job["id"],identity=self.first)
        self.call("GET","/api/jobs",identity=login,expected=401)
        self.call("POST","/api/session/logout",headers=fields)
        self.call("GET","/api/jobs",headers=fields,expected=401)
        self.call("GET","/api/jobs",identity=self.first)
    def test_04_native_dual_proof_claim_revokes_all_old_access(self):
        old=self.legacy();another=self.gstore.redeem(self.gstore.pair(old["owner"])["code"],"Second old device","native")
        unused=self.gstore.pair(old["owner"]);job=self.upload(old)
        payload={"deviceToken":old["token"],"deviceKind":"native"}
        self.call("POST","/api/account/legacy/claim",{**payload,"owner":old["owner"]},self.first,expected=400,account_api=True)
        claim=self.call("POST","/api/account/legacy/claim",payload,self.first,account_api=True);self.assertEqual(claim["migratedJobs"],1)
        self.call("GET","/api/jobs/"+job["id"],identity=self.second)
        self.call("GET","/api/jobs/"+job["id"],identity=self.other,expected=404)
        for value in (old,another):self.call("GET","/api/jobs",identity=value,expected=401)
        with self.assertRaises(gateway.GatewayError):self.gstore.redeem(unused["code"],"Late device","native")
        with self.assertRaises(gateway.GatewayError):self.gstore.register(str(uuid.uuid4()),old["owner"])
    def test_05_legacy_browser_requires_its_own_origin_and_csrf(self):
        old=self.legacy("browser");payload={"deviceToken":old["token"],"deviceKind":"browser","deviceCSRF":old["csrf"]}
        self.call("POST","/api/account/legacy/claim",payload,self.first,expected=403,account_api=True)
        self.call("POST","/api/account/legacy/claim",{**payload,"deviceCSRF":"wrong"},self.first,{"Origin":self.origin},403,True)
        self.call("POST","/api/account/legacy/claim",payload,self.first,{"Origin":self.origin},account_api=True)
    def test_06_account_owner_is_not_eligible_for_legacy_claim(self):
        old=self.legacy(owner=self.first["userId"])
        self.call("POST","/api/account/legacy/claim",{"deviceToken":old["token"],"deviceKind":"native"},self.other,expected=409,account_api=True)
    def test_07_expected_user_and_resolver_failure_are_fail_closed(self):
        self.call("POST","/api/jobs?filename=stale.xml",b"x",self.first,{"X-NoteLite-Expected-User":self.other["userId"]},409)
        old=self.legacy();resolver=self.gateway_server.account_resolver
        self.gateway_server.account_resolver=AccountResolver(self.account_server.server_port,secrets.token_urlsafe(32),self.origin)
        try:
            self.call("GET","/api/jobs",identity=old,expected=503)
            self.call("GET","/api/jobs",identity=self.first,expected=503)
        finally:self.gateway_server.account_resolver=resolver
    def test_08_enrolled_student_receives_later_course_scores_without_new_code(self):
        course=self.call("POST","/api/account/courses",{"title":"Late score delivery"},self.first,expected=201,account_api=True)
        code=self.call("POST","/api/account/courses/"+course["id"]+"/codes",{"maxUses":1},self.first,expected=201,account_api=True)
        joined=self.call("POST","/api/account/course-codes/join",{"code":code["code"]},self.other,account_api=True)
        self.assertEqual(joined["deliveredScores"],[])
        shared=self.call("POST","/api/account/courses/"+course["id"]+"/scores",{"sourceKind":"official","scoreId":"notelite-four-notes-v1"},self.first,expected=201,account_api=True)
        route="/api/account/courses/"+course["id"]
        first=self.call("GET",route,identity=self.other,account_api=True)
        second=self.call("GET",route,identity=self.other,account_api=True)
        self.assertEqual(first["deliveredScores"],second["deliveredScores"])
        self.assertEqual(len(first["deliveredScores"]),1)
        self.assertEqual(first["deliveredScores"][0]["courseScoreId"],shared["id"])


if __name__=="__main__":unittest.main()
