"""Server-only account resolver. No account or administrator token is logged."""
from datetime import datetime
import hashlib
import hmac
from http.client import HTTPConnection
import json
import re
import socket
import uuid

COOKIE = "__Host-notelite-account"
TOKEN = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")


class AccountAuthError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


class AccountResolver:
    def __init__(self, port, key, origin, timeout=5):
        if not 1 <= port <= 65535 or not TOKEN.fullmatch(key):
            raise ValueError("Account resolver configuration is invalid")
        self.port, self.key, self.origin, self.timeout = port, key, origin, timeout

    def request(self, path, headers, body=None):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=self.timeout)
        try:
            connection.request("POST", path, body, headers)
            response = connection.getresponse()
            raw = response.read(16385)
            if len(raw) > 16384:
                raise AccountAuthError(503, "账户认证服务暂时不可用。")
            # Never propagate service bodies or internal credentials to clients.
            if response.status == 401:
                raise AccountAuthError(401, "登录凭据无效或已过期。")
            if response.status != 200:
                raise AccountAuthError(503, "账户认证服务暂时不可用。")
            try:
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise ValueError()
                return value
            except ValueError:
                raise AccountAuthError(503, "账户认证服务暂时不可用。") from None
        except (OSError, socket.timeout):
            raise AccountAuthError(503, "账户认证服务暂时不可用。") from None
        finally:
            connection.close()

    def resolve(self, token, kind):
        if not isinstance(token, str) or not TOKEN.fullmatch(token) or kind not in {"browser", "native"}:
            raise AccountAuthError(401, "登录凭据无效或已过期。")
        value = self.request("/internal/account/resolve", {
            "Content-Type": "application/json", "X-NoteLite-Internal-Key": self.key,
        }, json.dumps({"token": token, "kind": kind}).encode())
        try:
            owner, session = value["owner"], value["sessionId"]
            if str(uuid.UUID(owner)) != owner or str(uuid.UUID(session)) != session or value["kind"] != kind:
                raise ValueError()
            expires = datetime.fromisoformat(value["expiresAt"]).timestamp()
            csrf_hash = value["csrfHash"]
            if not re.fullmatch(r"[a-f0-9]{64}", csrf_hash):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise AccountAuthError(503, "账户认证服务暂时不可用。") from None
        csrf = hashlib.sha256(("NoteLite-account-CSRF:" + token).encode("ascii")).hexdigest()
        if kind == "browser" and not hmac.compare_digest(hashlib.sha256(csrf.encode()).hexdigest(), csrf_hash):
            raise AccountAuthError(503, "账户认证服务暂时不可用。")
        return {"id": session, "owner": owner, "name": "NoteLite 账户", "expires": expires,
                "kind": kind, "csrf": csrf, "csrf_hash": csrf_hash,
                "account": True, "account_token": token}

    def logout(self, identity):
        headers = {"Host": self.origin[8:], "Content-Type": "application/json"}
        if identity["kind"] == "native":
            headers["Authorization"] = "Bearer " + identity["account_token"]
        else:
            headers.update({"Cookie": COOKIE + "=" + identity["account_token"],
                            "Origin": self.origin, "X-NoteLite-CSRF": identity["csrf"]})
        value = self.request("/api/account/logout", headers)
        if value.get("authenticated") is not False:
            raise AccountAuthError(503, "账户认证服务暂时不可用。")
