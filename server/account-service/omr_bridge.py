"""Private OMR import and dual-proof legacy migration hooks.

Only service processes read the administrator credential. XML is snapshotted
from a single immutable revision; caller-supplied ownership is never accepted.
"""
from contextlib import contextmanager
import hashlib
import hmac
import json
import sqlite3
from http.client import HTTPConnection
import socket
import time

from account_service import APIError, MAX_XML, uid


class OMRBridge:
    def __init__(self, gateway_store, upstream_token, origin, *, upstream_port=8765, account_user_exists=None):
        self.store, self.token, self.origin = gateway_store, upstream_token, origin
        self.port, self.account_user_exists = upstream_port, account_user_exists

    def check_owner(self, db, owner):
        try:
            self.store.check_owner(db, owner)
        except Exception as error:
            status = 410 if getattr(error, "status", None) == 410 else 503
            raise APIError(status, "识谱账户已注销或所有者验证暂不可用。") from None

    def import_score(self, user, job, index, revision):
        uid(user);uid(job)
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index <= 63:
            raise APIError(400, "乐章索引无效。")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise APIError(400, "修订号无效。")
        with self.store.connect() as db:
            self.check_owner(db, user)
            row = db.execute("SELECT owner FROM jobs WHERE id=?", (job,)).fetchone()
            if not row or not hmac.compare_digest(row[0], user):
                raise APIError(404, "任务不存在。")
        connection = HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            connection.request("GET", f"/api/jobs/{job}/score/musicxml?score={index}", headers={
                "Host": f"127.0.0.1:{self.port}", "Authorization": "Bearer " + self.token,
            })
            response = connection.getresponse()
            if response.status in {404, 409}:
                raise APIError(response.status, "任务不存在或结果尚未就绪。")
            if response.status != 200:
                raise APIError(503, "识谱结果暂时不可用。")
            # The module opens an immutable revision under its metadata lock.
            # Comparing that stream's ETag avoids metadata/file races.
            if response.getheader("ETag") != f'"{revision}"':
                raise APIError(409, "谱面版本已变化，请刷新后重新保存到谱库。")
            raw = response.read(MAX_XML + 1)
            if len(raw) > MAX_XML:
                raise APIError(413, "识谱结果超过大小限制。")
            try:
                return raw.decode("utf8")
            except UnicodeError:
                raise APIError(503, "识谱结果暂时不可用。") from None
        except (OSError, socket.timeout):
            raise APIError(503, "识谱结果暂时不可用。") from None
        finally:
            connection.close()

    @contextmanager
    def deletion_fence(self, user):
        uid(user)
        try:
            with self.store.deletion_fence(user):
                yield
        except APIError:
            raise
        except Exception:
            # Gateway/SQLite errors expose only a static retry message, never
            # credentials, job paths or upstream process output.
            raise APIError(503, "识谱服务正在保存，请稍后重试注销。") from None

    def delete_owner(self, user):
        uid(user)
        try:
            jobs = self.store.delete_owner(user)
            for job in jobs:
                uid(job)
                # Recheck ownership under the durable tombstone. A UUID cannot
                # become a new account's job between the list and deletion.
                with self.store.connect() as db:
                    row = db.execute("SELECT owner FROM jobs WHERE id=?", (job,)).fetchone()
                    if not row or not hmac.compare_digest(row[0], user):
                        raise APIError(503, "识谱资料清理待重试。")
                    connection = HTTPConnection("127.0.0.1", self.port, timeout=30)
                    try:
                        connection.request("DELETE", f"/api/jobs/{job}", headers={
                            "Host": f"127.0.0.1:{self.port}", "Authorization": "Bearer " + self.token,
                        })
                        response = connection.getresponse()
                        raw = response.read(4097)
                        if response.status != 200 or len(raw) > 4096:
                            raise APIError(503, "识谱资料清理待重试。")
                        result = json.loads(raw)
                        if not isinstance(result, dict) or result.get("id") != job or result.get("deleted") is not True:
                            raise APIError(503, "识谱资料清理待重试。")
                    finally:
                        connection.close()
            self.store.finish_delete_owner(user)
        except APIError:
            raise
        except Exception:
            raise APIError(503, "识谱资料清理待重试。") from None

    def claim(self, user, data, origin):
        uid(user)
        token, kind = data.get("deviceToken"), data.get("deviceKind")
        try:
            identity = self.store.device(token, kind)
        except Exception:
            # Store exceptions have safe static text; don't propagate tokens.
            raise APIError(401, "旧设备凭据无效或已过期。") from None
        owner = identity["owner"]
        if kind == "browser":
            csrf = data.get("deviceCSRF")
            if origin != self.origin or not isinstance(csrf, str) or not hmac.compare_digest(csrf.encode(), identity["csrf"].encode()):
                raise APIError(403, "请在原设备的 HTTPS 页面确认迁移。")
        elif kind != "native":
            raise APIError(401, "旧设备凭据类型无效。")
        if self.account_user_exists is None:
            raise APIError(503, "迁移所有者验证尚未配置。")
        if self.account_user_exists(owner):
            raise APIError(409, "账户谱库不能通过旧设备迁移。")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.check_owner(db, user)
            self.check_owner(db, owner)
            # Recheck validity in the same transaction as the ownership change.
            row = db.execute("SELECT owner FROM devices WHERE id=? AND hash=? AND kind=? AND expires>? AND revoked=0",
                             (identity["id"], hashlib.sha256(token.encode("ascii")).hexdigest(), kind, time.time())).fetchone()
            if not row or not hmac.compare_digest(row[0], owner):
                raise APIError(401, "旧设备凭据无效或已过期。")
            if db.execute("SELECT 1 FROM legacy_claims WHERE owner=?", (owner,)).fetchone():
                raise APIError(409, "旧资料已迁移，请重新载入账户谱库。")
            count = db.execute("SELECT COUNT(*) FROM jobs WHERE owner=?", (owner,)).fetchone()[0]
            db.execute("UPDATE jobs SET owner=? WHERE owner=?", (user, owner))
            db.execute("UPDATE devices SET revoked=1 WHERE owner=?", (owner,))
            db.execute("UPDATE pairs SET used=1 WHERE owner=?", (owner,))
            db.execute("INSERT INTO legacy_claims VALUES(?,?,?,?)", (owner, user, time.time(), count))
        return {"userId": user, "migratedJobs": count, "previousDeviceAccessRevoked": True}
