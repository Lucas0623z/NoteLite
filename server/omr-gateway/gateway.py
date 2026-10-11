#!/usr/bin/env python3
"""Device-scoped HTTPS gateway for the separately installed local OMR service.

No administrator token is returned to clients. TLS and static assets are served
by nginx; this service only listens on loopback. Python standard library only.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
from http.client import HTTPConnection
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import sqlite3
import threading
import time
from urllib.parse import parse_qs, urlsplit
import uuid

from account_auth import AccountResolver, AccountAuthError, COOKIE as ACCOUNT_COOKIE

LOG = logging.getLogger("notelite.gateway")
MAX_UPLOAD = 32 * 1024 * 1024
MAX_XML = 10 * 1024 * 1024
COOKIE = "__Host-notelite-session"
WRITE_METHODS = {"POST", "PUT", "PATCH"}
UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
JOB_ROUTE = re.compile(r"/api/jobs/(" + UUID_PATTERN + r")(?:/(score/(?:musicxml|midi|notes)|notes|original|project/omr|log|score))?$")


class GatewayError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


def stamp(seconds=None):
    return datetime.fromtimestamp(time.time() if seconds is None else seconds, timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def public_origin(value):
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("public-origin 必须是无路径、无凭据的 HTTPS 地址。")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("public-origin 端口无效。") from error
    authority = parsed.netloc.lower()
    if port == 443:
        authority = authority[:-4]
    return "https://" + authority


def canonical_uuid(value):
    if not isinstance(value, str) or not re.fullmatch(UUID_PATTERN, value) or str(uuid.UUID(value)) != value:
        raise GatewayError(400, "标识无效。")
    return value


class Store:
    def __init__(self, root: Path):
        root = root.absolute()
        if root.is_symlink():
            raise ValueError("存储目录不能是符号链接。")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = root / "gateway.sqlite3"
        if self.path.is_symlink():
            raise ValueError("数据库不能是符号链接。")
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS pairs(hash TEXT PRIMARY KEY,owner TEXT NOT NULL,expires REAL NOT NULL,used INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY,owner TEXT NOT NULL,name TEXT NOT NULL,hash TEXT UNIQUE NOT NULL,kind TEXT NOT NULL,csrf TEXT NOT NULL,expires REAL NOT NULL,revoked INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,owner TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS legacy_claims(owner TEXT PRIMARY KEY,user_id TEXT NOT NULL,created REAL NOT NULL,count INTEGER NOT NULL);
            """)
        if os.name == "posix":
            root.chmod(0o700)
            self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        with self.lock:
            connection = sqlite3.connect(self.path, timeout=15)
            connection.row_factory = sqlite3.Row
            try:
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA synchronous=FULL")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def default_owner(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM meta WHERE key='default_owner'").fetchone()
            if row:
                return row[0]
            owner = str(uuid.uuid4())
            db.execute("INSERT INTO meta VALUES('default_owner',?)", (owner,))
            return owner

    def pair(self, owner=None, ttl=600):
        owner = canonical_uuid(owner) if owner else self.default_owner()
        code, expires = secrets.token_urlsafe(32), time.time() + ttl
        with self.connect() as db:
            db.execute("DELETE FROM pairs WHERE expires < ? OR used=1", (time.time(),))
            db.execute("INSERT INTO pairs(hash,owner,expires) VALUES(?,?,?)", (digest(code), owner, expires))
        return {"code": code, "owner": owner, "expiresAt": stamp(expires)}

    def redeem(self, code, name, kind):
        if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_-]{40,128}", code):
            raise GatewayError(401, "配对码无效、已使用或已过期。")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or any(ord(c) < 32 or ord(c) == 127 for c in name):
            raise GatewayError(400, "请填写有效的设备名称。")
        if kind not in {"native", "browser"}:
            raise GatewayError(400, "配对模式无效。")
        token, csrf, device = secrets.token_urlsafe(32), secrets.token_urlsafe(32), str(uuid.uuid4())
        expires = time.time() + (30 if kind == "browser" else 90) * 86400
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            pair = db.execute("SELECT owner FROM pairs WHERE hash=? AND expires>? AND used=0", (digest(code), time.time())).fetchone()
            if not pair:
                raise GatewayError(401, "配对码无效、已使用或已过期。")
            db.execute("UPDATE pairs SET used=1 WHERE hash=?", (digest(code),))
            db.execute("INSERT INTO devices VALUES(?,?,?,?,?,?,?,0)", (device, pair[0], name.strip(), digest(token), kind, csrf, expires))
        return {"deviceId": device, "owner": pair[0], "deviceName": name.strip(), "expiresAt": stamp(expires), "token": token, "csrf": csrf, "kind": kind}

    def device(self, token, kind):
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{40,128}", token):
            raise GatewayError(401, "请先配对此设备。")
        with self.connect() as db:
            row = db.execute("SELECT * FROM devices WHERE hash=? AND kind=? AND expires>? AND revoked=0", (digest(token), kind, time.time())).fetchone()
            if not row:
                raise GatewayError(401, "设备凭据无效或已过期，请重新配对。")
            return dict(row)

    def own(self, job, owner):
        with self.connect() as db:
            row = db.execute("SELECT owner FROM jobs WHERE id=?", (job,)).fetchone()
            if not row or not hmac.compare_digest(row[0], owner):
                raise GatewayError(404, "任务不存在。")

    def register(self, job, owner):
        canonical_uuid(job)
        with self.connect() as db:
            if db.execute("SELECT 1 FROM legacy_claims WHERE owner=?", (owner,)).fetchone():
                raise GatewayError(409, "旧设备资料已迁移，请使用账户重新登录。")
            db.execute("INSERT INTO jobs VALUES(?,?,?)", (job, owner, time.time()))

    def list_ids(self, owner):
        with self.connect() as db:
            return {row[0] for row in db.execute("SELECT id FROM jobs WHERE owner=?", (owner,))}

    def revoke(self, device):
        with self.connect() as db:
            db.execute("UPDATE devices SET revoked=1 WHERE id=?", (device,))


class RateLimit:
    def __init__(self):
        self.lock = threading.Lock()
        self.buckets = {}

    def check(self, key, limit, window=60):
        moment = time.monotonic()
        with self.lock:
            if len(self.buckets) > 4096:
                self.buckets = {name: values for name, values in self.buckets.items() if values and values[-1] > moment - window}
            values = [value for value in self.buckets.get(key, []) if value > moment - window]
            if len(values) >= limit:
                raise GatewayError(429, "请求过于频繁，请稍后重试。")
            values.append(moment)
            self.buckets[key] = values


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, store, origin, upstream_token, *, upstream_port=8765, upstream_timeout=180, account_resolver=None):
        self.store, self.origin, self.upstream_token = store, public_origin(origin), upstream_token
        self.authority = urlsplit(self.origin).netloc
        self.upstream_port, self.upstream_timeout = upstream_port, upstream_timeout
        self.account_resolver = account_resolver
        self.limiter = RateLimit()
        self.capacity = threading.BoundedSemaphore(16)
        super().__init__(address, Handler)

    def process_request(self, request, address):
        if not self.capacity.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nRetry-After: 5\r\nConnection: close\r\n\r\n")
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.capacity.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.capacity.release()


class Handler(BaseHTTPRequestHandler):
    server_version, sys_version = "NoteLiteGateway/1", ""

    def setup(self):
        super().setup()
        self.connection.settimeout(60)

    def log_message(self, *_):
        # No query strings, file names, cookies, Authorization or pairing codes.
        LOG.info("%s %s", self.command, urlsplit(self.path).path)

    def json(self, status, value, extra=()):
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf8")
        self.response_started = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if status in {429, 503}:
            self.send_header("Retry-After", "60" if status == 429 else "5")
        for name, value in extra:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def read_body(self, limit):
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Encoding"):
            raise GatewayError(400, "请使用原始请求体。")
        if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,12}", lengths[0]):
            raise GatewayError(411 if not lengths else 400, "需要准确的 Content-Length。")
        length = int(lengths[0])
        if not 0 < length <= limit:
            raise GatewayError(413, "请求体超过大小限制。")
        data = self.rfile.read(length)
        if len(data) != length:
            raise GatewayError(400, "请求体提前结束。")
        return data

    def read_json(self, limit):
        try:
            value = json.loads(self.read_body(limit).decode("utf8"))
        except (ValueError, UnicodeError) as error:
            raise GatewayError(400, "请求不是有效 JSON。") from error
        if not isinstance(value, dict):
            raise GatewayError(400, "请求必须是 JSON 对象。")
        return value

    def validate_origin(self):
        hosts = self.headers.get_all("Host", [])
        accepted = {self.server.authority, f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if len(hosts) != 1 or hosts[0].lower() not in accepted:
            raise GatewayError(403, "服务地址无效。")
        origins = self.headers.get_all("Origin", [])
        if len(origins) > 1 or origins and origins[0] != self.server.origin:
            raise GatewayError(403, "请求来源无效。")
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise GatewayError(403, "请求来源无效。")

    def identity(self):
        values = self.headers.get_all("Authorization", [])
        if values:
            if len(values) != 1 or not values[0].startswith("Bearer "):
                raise GatewayError(401, "设备凭据无效。")
            # Conflicting browser/native principals are not a fallback channel.
            for raw_cookie in self.headers.get_all("Cookie", []):
                try:
                    cookie = SimpleCookie();cookie.load(raw_cookie)
                    if ACCOUNT_COOKIE in cookie:
                        raise GatewayError(401, "登录凭据冲突，请重新载入登录状态。")
                except CookieError:
                    raise GatewayError(401, "登录凭据无效。") from None
            token = values[0][7:]
            if self.server.account_resolver:
                try:
                    return self.server.account_resolver.resolve(token, "native")
                except AccountAuthError as error:
                    if error.status != 401:
                        raise GatewayError(error.status, error.message) from None
            return self.server.store.device(token, "native")
        cookies = self.headers.get_all("Cookie", [])
        if len(cookies) != 1:
            raise GatewayError(401, "请先配对此设备。")
        try:
            cookie = SimpleCookie()
            cookie.load(cookies[0])
            # An account cookie is authoritative, including when it has expired.
            # Never silently return to a previously paired device's score library.
            if ACCOUNT_COOKIE in cookie:
                if not self.server.account_resolver:
                    raise GatewayError(503, "账户认证服务暂时不可用。")
                try:
                    identity = self.server.account_resolver.resolve(cookie[ACCOUNT_COOKIE].value, "browser")
                except AccountAuthError as error:
                    raise GatewayError(error.status, error.message) from None
                self.check_browser_csrf(identity)
                return identity
            token = cookie[COOKIE].value if COOKIE in cookie else ""
        except CookieError:
            token = ""
        identity = self.server.store.device(token, "browser")
        self.check_browser_csrf(identity)
        return identity

    def check_browser_csrf(self, identity):
        if self.command in WRITE_METHODS:
            csrf = self.headers.get_all("X-NoteLite-CSRF", [])
            if self.headers.get("Origin") != self.server.origin or len(csrf) != 1 or not hmac.compare_digest(csrf[0].encode(), identity["csrf"].encode()):
                raise GatewayError(403, "请重新加载页面后保存。")

    def upstream(self, body=None, extra=None):
        connection = HTTPConnection("127.0.0.1", self.server.upstream_port, timeout=self.server.upstream_timeout)
        headers = {"Host": f"127.0.0.1:{self.server.upstream_port}", "Authorization": "Bearer " + self.server.upstream_token, "Accept": self.headers.get("Accept", "application/json")}
        if body is not None:
            headers["Content-Length"] = str(len(body))
            headers["Content-Type"] = self.headers.get("Content-Type", "application/octet-stream")
        if extra:
            headers.update(extra)
        try:
            connection.request(self.command, self.path, body, headers)
            response = connection.getresponse()
            return connection, response
        except (OSError, socket.timeout) as error:
            connection.close()
            raise GatewayError(502, "识谱服务暂时无法访问，请稍后重试。") from error

    def json_upstream(self, body=None, extra=None):
        connection, response = self.upstream(body, extra)
        try:
            data = response.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise GatewayError(502, "服务响应过大。")
            if response.status not in {200, 202}:
                try:
                    message = json.loads(data)["error"]
                except (ValueError, KeyError, TypeError):
                    message = "识谱服务请求失败。"
                # Never send internal token, even if a future upstream echoes it.
                message = str(message).replace(self.server.upstream_token, "[内部凭据已隐藏]")
                raise GatewayError(response.status if 400 <= response.status < 600 else 502, message)
            try:
                value = json.loads(data)
            except ValueError as error:
                raise GatewayError(502, "识谱服务返回无效数据。") from error
            def redact(item):
                if isinstance(item, str):
                    return item.replace(self.server.upstream_token, "[内部凭据已隐藏]")
                if isinstance(item, list):
                    return [redact(child) for child in item]
                if isinstance(item, dict):
                    return {redact(key): redact(child) for key, child in item.items()}
                return item
            return response.status, redact(value)
        finally:
            connection.close()

    def proxy_file(self):
        connection, response = self.upstream()
        try:
            if response.status != 200:
                data = response.read(65536)
                try:
                    message = str(json.loads(data)["error"]).replace(self.server.upstream_token, "[内部凭据已隐藏]")
                except (ValueError, KeyError, TypeError):
                    message = "结果暂时不可用。"
                raise GatewayError(response.status if 400 <= response.status < 600 else 502, message)
            length = response.getheader("Content-Length")
            if not length or not length.isdigit() or int(length) > 64 * 1024 * 1024:
                raise GatewayError(502, "结果文件大小无效。")
            self.response_started = True
            self.send_response(200)
            for name in ("Content-Type", "Content-Length", "Content-Disposition", "ETag"):
                value = response.getheader(name)
                if value and "\r" not in value and "\n" not in value:
                    self.send_header(name, value)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
        finally:
            connection.close()

    def dispatch(self):
        self.validate_origin()
        target = urlsplit(self.path)
        if target.scheme or target.netloc or target.fragment or "%" in target.path or "\\" in target.path:
            raise GatewayError(404, "接口不存在。")
        query = parse_qs(target.query, keep_blank_values=True)
        if any(len(values) != 1 for values in query.values()):
            raise GatewayError(400, "重复的查询参数。")
        if self.command == "GET" and target.path == "/api/health" and not query:
            status, value = self.json_upstream()
            value["gateway"] = "device-scoped"
            value["authentication"] = "account-or-legacy-device" if self.server.account_resolver else "device-or-session"
            self.json(status, value)
            return
        if self.command == "POST" and target.path == "/api/pair" and not query:
            # nginx overwrites X-Real-IP; direct access is loopback only.
            source = self.headers.get("X-Real-IP", self.client_address[0])[:128]
            self.server.limiter.check(("pair", source), 6)
            data = self.read_json(4096)
            if set(data) - {"code", "deviceName", "mode"}:
                raise GatewayError(400, "配对字段无效。")
            kind = data.get("mode", "browser")
            if kind == "browser" and self.headers.get("Origin") != self.server.origin:
                raise GatewayError(403, "请在应用的 HTTPS 页面完成配对。")
            device = self.server.store.redeem(data.get("code"), data.get("deviceName"), kind)
            result = {key: device[key] for key in ("deviceId", "owner", "deviceName", "expiresAt")}
            headers = []
            if kind == "native":
                result["token"] = device["token"]
            else:
                result["csrf"] = device["csrf"]
                headers.append(("Set-Cookie", COOKIE + "=" + device["token"] + "; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=2592000"))
            self.json(201, result, headers)
            return
        identity = self.identity()
        expected = self.headers.get_all("X-NoteLite-Expected-User", [])
        if expected:
            if len(expected) != 1:
                raise GatewayError(400, "账户一致性字段重复。")
            if not hmac.compare_digest(expected[0].encode(), identity["owner"].encode()):
                raise GatewayError(409, "登录账户已改变，请重新载入后操作。")
        self.server.limiter.check(("device", identity["id"]), 120)
        if self.command == "GET" and target.path == "/api/session" and not query:
            result = {"authenticated": True, "deviceId": identity["id"], "owner": identity["owner"], "deviceName": identity["name"], "expiresAt": stamp(identity["expires"])}
            if identity["kind"] == "browser":
                result["csrf"] = identity["csrf"]
            self.json(200, result)
            return
        if self.command == "POST" and target.path == "/api/session/logout" and not query:
            cookie = COOKIE
            if identity.get("account"):
                try:
                    self.server.account_resolver.logout(identity)
                except AccountAuthError as error:
                    raise GatewayError(error.status, error.message) from None
                cookie = ACCOUNT_COOKIE
            else:
                self.server.store.revoke(identity["id"])
            self.json(200, {"authenticated": False}, [("Set-Cookie", cookie + "=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0")])
            return
        if target.path == "/api/jobs":
            if self.command == "GET" and not query:
                _, value = self.json_upstream()
                ids = self.server.store.list_ids(identity["owner"])
                self.json(200, {"jobs": [job for job in value.get("jobs", []) if job.get("id") in ids]})
                return
            if self.command == "POST" and set(query) == {"filename"}:
                self.server.limiter.check(("upload", identity["owner"]), 12)
                status, value = self.json_upstream(self.read_body(MAX_UPLOAD))
                try:
                    self.server.store.register(value["id"], identity["owner"])
                except (KeyError, GatewayError, sqlite3.Error) as error:
                    # A received-but-unregistered job remains private to the administrator.
                    raise GatewayError(502, "任务已接收但未能登记，请联系管理员，避免重复上传。") from error
                self.json(status, value)
                return
            raise GatewayError(400 if self.command in {"GET", "POST"} else 405, "请求方法或参数无效。")
        match = JOB_ROUTE.fullmatch(target.path)
        if not match or set(query) - {"score"}:
            raise GatewayError(404, "接口不存在。")
        job, action = match.groups()
        self.server.store.own(job, identity["owner"])
        if query and (not re.fullmatch(r"[0-9]{1,2}", query["score"][0]) or int(query["score"][0]) > 63):
            raise GatewayError(400, "乐章索引无效。")
        if self.command == "GET":
            if action in {None, "notes", "score/notes"}:
                status, value = self.json_upstream()
                self.json(status, value)
            elif action in {"score/musicxml", "score/midi", "original", "project/omr", "log"}:
                self.proxy_file()
            else:
                raise GatewayError(405, "请求方法无效。")
            return
        if self.command == "PATCH" and action in {"notes", "score/notes"}:
            data = self.read_json(128 * 1024)
            if not isinstance(data.get("revision"), int) or isinstance(data["revision"], bool) or data["revision"] < 1:
                raise GatewayError(400, "保存修改必须提供有效修订号。")
            status, value = self.json_upstream(json.dumps(data, ensure_ascii=False).encode("utf8"))
            self.json(status, value)
            return
        if self.command == "PUT" and action == "score":
            revisions = self.headers.get_all("If-Match", [])
            if len(revisions) != 1 or not re.fullmatch(r'"?[1-9][0-9]*"?', revisions[0]):
                raise GatewayError(400, "保存修改必须提供 If-Match 修订号。")
            status, value = self.json_upstream(self.read_body(MAX_XML), {"If-Match": revisions[0]})
            self.json(status, value)
            return
        raise GatewayError(405, "请求方法无效。")

    def handle_request(self):
        self.response_started = False
        try:
            self.dispatch()
        except GatewayError as error:
            self.close_connection = True
            self.json(error.status, {"error": error.message})
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            self.close_connection = True
        except Exception:
            LOG.exception("网关请求失败（未记录凭据或请求体）")
            self.close_connection = True
            if not self.response_started:
                self.json(500, {"error": "网关处理失败，请稍后重试。"})

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = handle_request


def private_json(path, value):
    path = Path(path).absolute()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf8") as output:
        json.dump(value, output, ensure_ascii=False)
        output.write("\n")
    if os.name == "posix":
        path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description="NoteLite 的独立设备网关，不会修改 OMR 引擎。")
    parser.add_argument("--storage", type=Path, default=Path("/var/lib/notelite-gateway"))
    parser.add_argument("--public-origin", default="https://124.221.211.156")
    commands = parser.add_subparsers(dest="command", required=True)
    pair = commands.add_parser("pair", help="创建一次性配对文件，终端不输出配对码")
    pair.add_argument("--output", type=Path, required=True)
    pair.add_argument("--owner")
    pair.add_argument("--ttl", type=int, default=600)
    serve = commands.add_parser("serve")
    serve.add_argument("--host", choices=["127.0.0.1"], default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8770)
    serve.add_argument("--upstream-port", type=int, default=8765)
    serve.add_argument("--upstream-timeout", type=int, default=180)
    serve.add_argument("--upstream-token-file", type=Path, default=Path("/var/lib/audiveris/access-token"))
    serve.add_argument("--account-port", type=int, default=8771)
    serve.add_argument("--account-key-file", type=Path)
    args = parser.parse_args()
    origin = public_origin(args.public_origin)
    store = Store(args.storage)
    if args.command == "pair":
        if not 60 <= args.ttl <= 3600:
            parser.error("配对码期限应为 60 至 3600 秒。")
        result = store.pair(args.owner, args.ttl)
        result["origin"] = origin
        private_json(args.output, result)
        print("PAIRING_FILE_CREATED", args.output.absolute(), "expires", result["expiresAt"])
        return
    if not 1 <= args.port <= 65535 or not 1 <= args.upstream_port <= 65535 or not 10 <= args.upstream_timeout <= 1800:
        parser.error("端口或超时无效。")
    token_path = args.upstream_token_file
    if token_path.is_symlink():
        parser.error("内部凭据文件不能是符号链接。")
    token = token_path.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
        parser.error("内部凭据文件格式无效。")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    resolver = None
    if args.account_key_file:
        if args.account_key_file.is_symlink():
            parser.error("账户内部凭据文件不能是符号链接。")
        resolver = AccountResolver(args.account_port, args.account_key_file.read_text(encoding="ascii").strip(), origin)
    server = Server((args.host, args.port), store, origin, token, upstream_port=args.upstream_port, upstream_timeout=args.upstream_timeout, account_resolver=resolver)
    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    LOG.info("网关就绪 %s:%s; public origin %s", args.host, args.port, origin)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
