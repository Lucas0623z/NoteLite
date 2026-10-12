#!/usr/bin/env python3
"""NoteLite account, score sync, practice history and temporary course service.

Standard library only. Bind loopback behind the existing trusted HTTPS nginx.
The OMR ownership and legacy-claim adapters are explicitly fail-closed hooks.
"""
from __future__ import annotations

import argparse
import base64
import binascii
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import hmac
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import struct
import threading
import time
from urllib.parse import parse_qs, urlsplit
import uuid
import wave
import xml.etree.ElementTree as ET
from practice_analysis import AnalysisError, from_environment

PREFIX = "/api/account"
COOKIE = "__Host-notelite-account"
MAX_XML = 10 * 1024 * 1024
MAX_BODY = MAX_XML * 2 + 4096
MAX_CHUNK = 8 * 1024 * 1024
MAX_ANALYSIS = 1024 * 1024
MAX_ANALYSIS_STORAGE = 128 * MAX_ANALYSIS
MAX_REJECT_DRAIN = 64 * 1024
REJECT_DRAIN_SECONDS = 0.25
MAX_PROFILE = 256 * 1024
MAX_AVATAR_CHARACTERS = 196608
MAX_ACCOUNT_EXPORT = 16 * 1024 * 1024
PROFILE_FIELDS = {"displayName", "avatar", "avatarImage", "email", "phone", "selectedCourse", "theme", "options"}
PROFILE_COURSES = {
    "弦乐-小提琴", "弦乐-中提琴", "弦乐-大提琴", "弦乐-低音提琴", "弦乐-竖琴", "打击乐-钢琴",
    "木管-长笛", "木管-单簧管", "木管-巴松管", "木管-双簧管", "铜管-圆号", "铜管-小号",
    "铜管-长号", "铜管-大号", "铜管-上低音号",
}
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
AUDIO_TYPES = {"audio/wav", "audio/mpeg", "audio/ogg", "audio/mp4"}
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
TOKEN = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")
WRITES = {"POST", "PUT", "PATCH", "DELETE"}
HASH_LOCK = threading.BoundedSemaphore(2)
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 17, 8, 1


class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


def now_stamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def uid(value):
    if not isinstance(value, str) or not re.fullmatch(UUID, value):
        raise APIError(400, "标识无效。")
    return value


def text(value, name, maximum=120):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise APIError(400, name + "无效。")
    return value.strip()


def integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise APIError(400, name + "无效。")
    return value


def fields(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise APIError(400, "请求字段无效或缺少必要字段。")


def profile_json(value):
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf8")) > MAX_PROFILE:
            raise APIError(413, "个人设置超过 256 KiB 大小限制。")
        return encoded
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise APIError(400, "个人设置须为有效的 JSON 数据。") from error


def profile_changes(value):
    fields(value, PROFILE_FIELDS)
    profile_json(value)
    for key, maximum in (("displayName", 80), ("email", 254), ("phone", 40)):
        if key in value and (not isinstance(value[key], str) or len(value[key]) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value[key])):
            raise APIError(400, "个人设置的文字字段无效。")
    for key, choices in (("avatar", {"mascot", "portrait", "custom"}), ("theme", {"light", "dark"})):
        if key in value and (not isinstance(value[key], str) or value[key] not in choices):
            raise APIError(400, "个人设置的选项无效。")
    if "selectedCourse" in value and value["selectedCourse"] is not None and (not isinstance(value["selectedCourse"], str) or value["selectedCourse"] not in PROFILE_COURSES):
        raise APIError(400, "所选课程无效。")
    if "options" in value:
        options = value["options"]
        if not isinstance(options, dict) or len(options) > 200:
            raise APIError(400, "个人设置的开关数量无效。")
        for key, enabled in options.items():
            if not isinstance(key, str) or not 1 <= len(key) <= 80 or key in {"__proto__", "prototype", "constructor"} or any(ord(c) < 32 or ord(c) == 127 for c in key) or not isinstance(enabled, bool):
                raise APIError(400, "个人设置的开关无效。")
    if "avatarImage" in value and value["avatarImage"] is not None:
        image = value["avatarImage"]
        if not isinstance(image, str) or len(image) > MAX_AVATAR_CHARACTERS:
            raise APIError(413 if isinstance(image, str) else 400, "头像图片超过大小限制或格式无效。")
        match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})", image)
        if not match:
            raise APIError(400, "头像须为 PNG、JPEG 或 WebP 图片。")
        try:
            data = base64.b64decode(match[2], validate=True)
        except (ValueError, binascii.Error) as error:
            raise APIError(400, "头像图片编码无效。") from error
        valid = (match[1] == "png" and data.startswith(b"\x89PNG\r\n\x1a\n")) or (match[1] == "jpeg" and data.startswith(b"\xff\xd8\xff")) or (match[1] == "webp" and len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP")
        if not valid:
            raise APIError(400, "头像图片内容与格式不一致。")
    return value


def analysis_json(value):
    """Canonical UTF-8 bytes are bounded before storage and after normalization."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False)
        size = len(encoded.encode("utf8"))
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise APIError(400, "演奏分析须为有效的 JSON 数据。") from error
    if size > MAX_ANALYSIS:
        raise APIError(413, "演奏分析超过 1 MiB 大小限制。")
    return encoded


def is_performance_v2(value):
    return isinstance(value, dict) and value.get("schemaVersion") in (2, "2", "2.0")


def token_hash(value):
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        raise APIError(401, "登录凭据无效或已过期。")
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def code_hash(value):
    if not isinstance(value, str) or not re.fullmatch("[" + CODE_ALPHABET + "]{6}", value.strip().upper()):
        raise APIError(404, "课堂代码无效、已过期或不可使用。")
    return hashlib.sha256(value.strip().upper().encode("ascii")).hexdigest()


def csrf_value(token):
    return hashlib.sha256(("NoteLite-account-CSRF:" + token).encode("ascii")).hexdigest()


def password_bytes(value, *, creating=True):
    # No MFA is configured: OWASP recommends at least 15 characters.
    minimum = 15 if creating else 1
    requirement = "新密码须为 15 至 256 个字符。" if creating else "请输入当前密码（最多 256 个字符）。"
    if not isinstance(value, str) or not minimum <= len(value) <= 256:
        raise APIError(400, requirement)
    try:
        raw = value.encode("utf8")
    except UnicodeError as error:
        raise APIError(400, "密码须为有效文字。") from error
    if len(raw) > 1024:
        raise APIError(400, requirement)
    return raw


def password_hash(value, salt=None, *, creating=True):
    raw = password_bytes(value, creating=creating)
    salt = secrets.token_bytes(16) if salt is None else bytes.fromhex(salt)
    with HASH_LOCK:
        hashed = hashlib.scrypt(raw, salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=192 * 1024 * 1024, dklen=32)
    return salt.hex(), hashed.hex()


def username(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,31}", value):
        raise APIError(400, "用户名须为 3 至 32 位字母、数字、点、下划线或连字符。")
    return value.lower()


def validate_xml(value):
    if not isinstance(value, str):
        raise APIError(400, "MusicXML 须为文字。")
    try:
        size = len(value.encode("utf8"))
    except UnicodeError as error:
        raise APIError(400, "MusicXML 须为有效文字。") from error
    if not 1 <= size <= MAX_XML:
        raise APIError(413, "MusicXML 超过大小限制。")
    # MusicXML exports commonly include an external public DOCTYPE. Preserve it
    # in the stored bytes, but strip it for parsing; never fetch the external DTD.
    # Internal subsets and entity declarations remain forbidden.
    parsed_value = value
    if re.search(r"<!\s*ENTITY", value, re.I):
        raise APIError(400, "MusicXML 不允许实体声明。")
    doctypes = list(re.finditer(r"<!\s*DOCTYPE", value, re.I))
    if doctypes:
        external = re.compile(r'''<!\s*DOCTYPE\s+score-partwise\s+(?:PUBLIC\s+(?:"[^"<>\[\]]+"|'[^'<>\[\]]+')\s+(?:"[^"<>\[\]]+"|'[^'<>\[\]]+')|SYSTEM\s+(?:"[^"<>\[\]]+"|'[^'<>\[\]]+'))\s*>''', re.I)
        matches = list(external.finditer(value))
        if len(doctypes) != 1 or len(matches) != 1 or doctypes[0].start() != matches[0].start():
            raise APIError(400, "MusicXML 不允许内部 DTD。")
        parsed_value = value[:matches[0].start()] + value[matches[0].end():]
    try:
        root = ET.fromstring(parsed_value)
    except (ET.ParseError, ValueError) as error:
        raise APIError(400, "MusicXML 无法解析。") from error
    local = lambda node: node.tag.rsplit("}", 1)[-1] if isinstance(node.tag, str) else ""
    if local(root) != "score-partwise" or not any(local(node) == "part-list" for node in root) or not any(local(node) == "part" for node in root):
        raise APIError(400, "请提供包含声部的 score-partwise MusicXML。")
    return value


SAMPLE_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0"><work><work-title>NoteLite 四音练习</work-title></work><part-list><score-part id="P1"><part-name>Piano</part-name><score-instrument id="I1"><instrument-name>Piano</instrument-name></score-instrument></score-part></part-list><part id="P1"><measure number="1"><attributes><divisions>1</divisions><key><fifths>0</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes><direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>80</per-minute></metronome></direction-type><sound tempo="80"/></direction><note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note><note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note><note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note><note><pitch><step>F</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note></measure></part></score-partwise>'''


class Store:
    def __init__(self, root, *, clock=time.time, omr_import=None, legacy_claim=None, omr_delete=None, omr_fence=None,
                 max_recording=100 * 1024 * 1024, recording_quota=1024 ** 3, disk_reserve=256 * 1024 * 1024):
        root = Path(root).absolute()
        if root.is_symlink():
            raise ValueError("存储目录不能为符号链接。")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = root / "accounts.sqlite3"
        if self.path.is_symlink():
            raise ValueError("数据库不能为符号链接。")
        self.lock, self.clock = threading.RLock(), clock
        self.owner_context = ContextVar("notelite-account-request-owner", default=None)
        self.deletion_lock = threading.Lock()
        self.omr_import, self.legacy_claim, self.omr_delete, self.omr_fence = omr_import, legacy_claim, omr_delete, omr_fence
        self.recordings = root / "recordings"
        if self.recordings.is_symlink():
            raise ValueError("录音目录不能为符号链接。")
        self.recordings.mkdir(mode=0o700, exist_ok=True)
        self.max_recording, self.recording_quota, self.disk_reserve = max_recording, recording_quota, disk_reserve
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,username TEXT UNIQUE NOT NULL,salt TEXT NOT NULL,password_hash TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS account_deletions(user_id TEXT PRIMARY KEY,recordings TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),kind TEXT NOT NULL,name TEXT NOT NULL,token_hash TEXT UNIQUE NOT NULL,csrf_hash TEXT NOT NULL,expires REAL NOT NULL,revoked INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS user_sessions ON sessions(user_id);
            CREATE TABLE IF NOT EXISTS profiles(user_id TEXT PRIMARY KEY REFERENCES users(id),preferences TEXT NOT NULL,revision INTEGER NOT NULL,updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS profile_requests(user_id TEXT NOT NULL REFERENCES users(id),request_id TEXT NOT NULL,payload_hash TEXT NOT NULL,result TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(user_id,request_id));
            CREATE TABLE IF NOT EXISTS catalog(id TEXT PRIMARY KEY,title TEXT NOT NULL,composer TEXT NOT NULL,license TEXT NOT NULL,source TEXT NOT NULL,xml TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS scores(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),title TEXT NOT NULL,xml TEXT NOT NULL,revision INTEGER NOT NULL,updated REAL NOT NULL,job_id TEXT,score_index INTEGER,omr_revision INTEGER);
            CREATE INDEX IF NOT EXISTS user_scores ON scores(user_id);
            CREATE TABLE IF NOT EXISTS score_requests(user_id TEXT NOT NULL REFERENCES users(id),request_id TEXT NOT NULL,payload_hash TEXT NOT NULL,score_id TEXT NOT NULL REFERENCES scores(id),PRIMARY KEY(user_id,request_id));
            CREATE TABLE IF NOT EXISTS history(user_id TEXT NOT NULL REFERENCES users(id),event_id TEXT NOT NULL,payload TEXT NOT NULL,created REAL NOT NULL,score_xml TEXT,score_sha256 TEXT,score_revision INTEGER,PRIMARY KEY(user_id,event_id));
            CREATE TABLE IF NOT EXISTS history_analysis_versions(user_id TEXT NOT NULL,event_id TEXT NOT NULL,version INTEGER NOT NULL,parent_version INTEGER NOT NULL,request_id TEXT NOT NULL,source_hash TEXT NOT NULL,analysis_hash TEXT NOT NULL,payload TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(user_id,event_id,version),UNIQUE(user_id,event_id,request_id),FOREIGN KEY(user_id,event_id) REFERENCES history(user_id,event_id));
            CREATE TABLE IF NOT EXISTS courses(id TEXT PRIMARY KEY,creator TEXT NOT NULL REFERENCES users(id),title TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS course_scores(id TEXT PRIMARY KEY,course_id TEXT NOT NULL REFERENCES courses(id),title TEXT NOT NULL,xml TEXT NOT NULL,source_kind TEXT NOT NULL,source_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS codes(hash TEXT PRIMARY KEY,course_id TEXT NOT NULL REFERENCES courses(id),expires REAL NOT NULL,max_uses INTEGER NOT NULL,uses INTEGER NOT NULL DEFAULT 0,revoked INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS memberships(course_id TEXT NOT NULL REFERENCES courses(id),user_id TEXT NOT NULL REFERENCES users(id),joined REAL NOT NULL,PRIMARY KEY(course_id,user_id));
            CREATE TABLE IF NOT EXISTS course_deliveries(course_id TEXT NOT NULL REFERENCES courses(id),user_id TEXT NOT NULL REFERENCES users(id),course_score_id TEXT NOT NULL REFERENCES course_scores(id),score_id TEXT NOT NULL REFERENCES scores(id),PRIMARY KEY(course_id,user_id,course_score_id));
            CREATE TABLE IF NOT EXISTS assignments(id TEXT PRIMARY KEY,course_id TEXT NOT NULL REFERENCES courses(id),course_score_id TEXT NOT NULL REFERENCES course_scores(id),title TEXT NOT NULL,due REAL,requirements TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS uploads(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),assignment_id TEXT NOT NULL REFERENCES assignments(id),size INTEGER NOT NULL,offset INTEGER NOT NULL,mime TEXT NOT NULL,sha256 TEXT NOT NULL,complete INTEGER NOT NULL DEFAULT 0,expires REAL NOT NULL,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS submissions(id TEXT PRIMARY KEY,assignment_id TEXT NOT NULL REFERENCES assignments(id),user_id TEXT NOT NULL REFERENCES users(id),event_id TEXT NOT NULL,upload_id TEXT REFERENCES uploads(id),analysis TEXT NOT NULL,created REAL NOT NULL,UNIQUE(assignment_id,user_id,event_id),FOREIGN KEY(user_id,event_id) REFERENCES history(user_id,event_id));
            ''')
            columns = {r[1] for r in db.execute("PRAGMA table_info(history)")}
            for column, kind in (("score_xml", "TEXT"), ("score_sha256", "TEXT"), ("score_revision", "INTEGER")):
                if column not in columns:
                    db.execute("ALTER TABLE history ADD COLUMN " + column + " " + kind)
            submission_columns = {r[1] for r in db.execute("PRAGMA table_info(submissions)")}
            for column, kind in (("analysis_version", "INTEGER"), ("analysis_hash", "TEXT"), ("source_hash", "TEXT")):
                if column not in submission_columns:
                    db.execute("ALTER TABLE submissions ADD COLUMN " + column + " " + kind)
            db.execute("INSERT OR IGNORE INTO catalog VALUES(?,?,?,?,?,?)", ("notelite-four-notes-v1", "NoteLite 四音练习", "NoteLite", "CC0-1.0", "NoteLite 自编练习（C4 D4 E4 F4）", SAMPLE_XML))
        if os.name == "posix":
            root.chmod(0o700)
            self.recordings.chmod(0o700)
            self.path.chmod(0o600)
        # Unknown users get the same scrypt work as existing users.
        self.dummy_salt, self.dummy_hash = password_hash(secrets.token_urlsafe(24))

    @contextmanager
    def connect(self):
        with self.lock:
            db = sqlite3.connect(self.path, timeout=15)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA secure_delete=ON")
            try:
                if self.owner_context.get() is not None:
                    self.require_active_user(db, self.owner_context.get())
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

    @staticmethod
    def require_active_user(db, user_id):
        if not db.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
            raise APIError(401, "账户已注销，请重新读取登录状态。")

    @contextmanager
    def owner_scope(self, user_id):
        token = self.owner_context.set(user_id)
        try:
            yield
        finally:
            self.owner_context.reset(token)

    @staticmethod
    def default_preferences():
        return {"displayName": "名字", "avatar": "mascot", "avatarImage": None, "email": "", "phone": "", "selectedCourse": None, "theme": "light", "options": {}}

    def profile_meta(self, db, user_id):
        self.require_active_user(db, user_id)
        row = db.execute("SELECT * FROM profiles WHERE user_id=?", (user_id,)).fetchone()
        revision = row["revision"] if row else 0
        updated = row["updated"] if row else db.execute("SELECT created FROM users WHERE id=?", (user_id,)).fetchone()[0]
        return {"userId": user_id, "revision": revision, "etag": f'"profile-{revision}"', "updatedAt": now_stamp(updated), "preferences": json.loads(row["preferences"]) if row else self.default_preferences()}

    def read_profile(self, user_id):
        with self.connect() as db:
            return self.profile_meta(db, user_id)

    def update_profile(self, user_id, data, etag):
        fields(data, {"requestId", "changes"}, {"requestId", "changes"})
        request_id = uid(data["requestId"])
        changes = profile_changes(data["changes"])
        digest = hashlib.sha256(profile_json(changes).encode("utf8")).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.require_active_user(db, user_id)
            old = db.execute("SELECT * FROM profile_requests WHERE user_id=? AND request_id=?", (user_id, request_id)).fetchone()
            if old:
                if not hmac.compare_digest(old["payload_hash"], digest):
                    raise APIError(409, "个人设置保存标识已用于其他内容。")
                # A lost response can be replayed with its original, now stale
                # precondition. It returns the original result and writes nothing.
                return json.loads(old["result"])
            current = self.profile_meta(db, user_id)
            if etag != current["etag"]:
                raise APIError(412, "另一台设备已修改个人设置，请重新读取后合并。")
            merged = {**current["preferences"], **changes}
            if "options" in changes:
                merged["options"] = {**current["preferences"]["options"], **changes["options"]}
            preferences = profile_json(profile_changes(merged))
            db.execute("INSERT INTO profiles VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET preferences=excluded.preferences,revision=excluded.revision,updated=excluded.updated", (user_id, preferences, current["revision"] + 1, self.clock()))
            result = self.profile_meta(db, user_id)
            db.execute("INSERT INTO profile_requests VALUES(?,?,?,?,?)", (user_id, request_id, digest, json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False), self.clock()))
            return result

    def export_account(self, user_id):
        # This is a bounded owner-only user export, not an importable database
        # backup. Never include authentication secrets or another pupil's data.
        with self.connect() as db:
            db.execute("BEGIN")
            self.require_active_user(db, user_id)
            user = db.execute("SELECT id,username,created FROM users WHERE id=?", (user_id,)).fetchone()
            value = {"schemaVersion": 1, "exportedAt": now_stamp(self.clock()), "user": {"id": user["id"], "username": user["username"], "createdAt": now_stamp(user["created"])}, "profile": self.profile_meta(db, user_id), "recordings": "Local practice recordings remain on their original device; explicitly submitted classroom recordings are metadata only."}
            used = len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf8"))
            def rows(name, query, args=(user_id,), transform=None):
                nonlocal used
                result = []
                for row in db.execute(query, args):
                    item = transform(row) if transform else dict(row)
                    used += len(json.dumps(item, ensure_ascii=False, allow_nan=False).encode("utf8")) + 2
                    if used > MAX_ACCOUNT_EXPORT:
                        raise APIError(413, "完整数据导出超过 16 MiB，请分别导出曲谱与练习记录。")
                    result.append(item)
                value[name] = result
                used += len(name) + 8
            rows("profileRequests", "SELECT request_id,payload_hash,result,created FROM profile_requests WHERE user_id=? ORDER BY created,request_id", transform=lambda r: {"requestId": r["request_id"], "payloadHash": r["payload_hash"], "result": json.loads(r["result"]), "createdAt": now_stamp(r["created"])})
            rows("scores", "SELECT * FROM scores WHERE user_id=? ORDER BY id", transform=lambda r: {**self.score_meta(r), "musicxml": r["xml"]})
            rows("history", "SELECT * FROM history WHERE user_id=? ORDER BY created,event_id", transform=lambda r: {"event": self.history_meta(db, r), "musicxml": r["score_xml"], "scoreSha256": r["score_sha256"], "scoreRevision": r["score_revision"]})
            rows("historyAnalyses", "SELECT event_id,version,parent_version,request_id,source_hash,analysis_hash,payload,created FROM history_analysis_versions WHERE user_id=? ORDER BY event_id,version", transform=lambda r: {**{k: r[k] for k in r.keys() if k != "payload"}, "analysis": json.loads(r["payload"])})
            rows("classrooms", "SELECT c.id,c.title,c.creator,c.created,CASE WHEN c.creator=? THEN 'teacher' ELSE 'student' END AS role FROM courses c WHERE c.creator=? OR EXISTS(SELECT 1 FROM memberships m WHERE m.course_id=c.id AND m.user_id=?) ORDER BY c.id", (user_id, user_id, user_id))
            rows("courseDeliveries", "SELECT course_id,course_score_id,score_id FROM course_deliveries WHERE user_id=?")
            rows("submissions", "SELECT id,assignment_id,event_id,upload_id,analysis,analysis_version,analysis_hash,source_hash,created FROM submissions WHERE user_id=?", transform=lambda r: {**{k: r[k] for k in r.keys() if k != "analysis"}, "analysis": json.loads(r["analysis"])})
            rows("classroomRecordingMetadata", "SELECT id,assignment_id,size,offset,mime,sha256,complete,expires,created FROM uploads WHERE user_id=?")
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table, label in (("practice_analysis_v2_requests", "practiceAnalysisRequests"), ("practice_analysis_v2_cache", "practiceAnalysisCache")):
                if table in tables:
                    rows(label, "SELECT * FROM " + table + " WHERE user_id=?", transform=lambda r: {**{k: r[k] for k in r.keys() if k not in {"user_id", "result"}}, "result": json.loads(r["result"]) if r["result"] else None})
            if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf8")) > MAX_ACCOUNT_EXPORT:
                raise APIError(413, "完整数据导出超过 16 MiB，请分别导出曲谱与练习记录。")
            return value

    def install_analysis_guards(self, db):
        # Old schema versions intentionally lacked a foreign key. Guard both
        # INSERT and UPDATE so a delayed provider response cannot resurrect data.
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("practice_analysis_v2_requests", "practice_analysis_v2_cache", "practice_analysis_requests", "practice_analysis_cache"):
            if table in tables:
                for action in ("INSERT", "UPDATE"):
                    db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_active_{action.lower()} BEFORE {action} ON {table} WHEN NOT EXISTS(SELECT 1 FROM users WHERE id=NEW.user_id) BEGIN SELECT RAISE(ABORT,'account_unavailable'); END")

    def request_deletion(self, user_id, session_id, data):
        fields(data, {"password", "confirmation"}, {"password", "confirmation"})
        if data["confirmation"] != "DELETE_ACCOUNT":
            raise APIError(400, "请再次确认永久注销账户。")
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not row:
                raise APIError(401, "账户已注销。")
        _, candidate = password_hash(data["password"], row["salt"], creating=False)
        if not hmac.compare_digest(candidate, row["password_hash"]):
            raise APIError(403, "当前密码不正确，账户未注销。")
        # The gateway writer transaction is uncommitted until the account
        # transaction commits. A failed account SQL operation rolls back both
        # the owner fence and personal-data deletion, keeping the account usable.
        with self.lock:
            try:
                with self.omr_fence(user_id) if self.omr_fence is not None else nullcontext():
                    with self.connect() as db:
                        db.execute("BEGIN IMMEDIATE")
                        current = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
                        session = db.execute("SELECT 1 FROM sessions WHERE id=? AND user_id=? AND revoked=0 AND expires>?", (session_id, user_id, self.clock())).fetchone()
                        if not current or not session or current["password_hash"] != row["password_hash"]:
                            raise APIError(401, "登录状态已改变，请重新确认注销。")
                        self.install_analysis_guards(db)
                        owned_class = "SELECT id FROM courses WHERE creator=?"
                        class_assignments = "SELECT a.id FROM assignments a JOIN courses c ON c.id=a.course_id WHERE c.creator=?"
                        recordings = [r[0] for r in db.execute(f"SELECT id FROM uploads WHERE user_id=? OR assignment_id IN ({class_assignments})", (user_id, user_id))]
                        db.execute(f"DELETE FROM submissions WHERE user_id=? OR assignment_id IN ({class_assignments})", (user_id, user_id))
                        db.execute(f"DELETE FROM uploads WHERE user_id=? OR assignment_id IN ({class_assignments})", (user_id, user_id))
                        db.execute(f"DELETE FROM assignments WHERE course_id IN ({owned_class})", (user_id,))
                        db.execute(f"DELETE FROM codes WHERE course_id IN ({owned_class})", (user_id,))
                        db.execute(f"DELETE FROM course_deliveries WHERE user_id=? OR course_id IN ({owned_class})", (user_id, user_id))
                        db.execute(f"DELETE FROM memberships WHERE user_id=? OR course_id IN ({owned_class})", (user_id, user_id))
                        db.execute(f"DELETE FROM course_scores WHERE course_id IN ({owned_class})", (user_id,))
                        db.execute("DELETE FROM courses WHERE creator=?", (user_id,))
                        db.execute("DELETE FROM history_analysis_versions WHERE user_id=?", (user_id,))
                        db.execute("DELETE FROM history WHERE user_id=?", (user_id,))
                        db.execute("DELETE FROM score_requests WHERE user_id=?", (user_id,))
                        db.execute("DELETE FROM scores WHERE user_id=?", (user_id,))
                        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                        for table in ("practice_analysis_v2_requests", "practice_analysis_v2_cache", "practice_analysis_requests", "practice_analysis_cache"):
                            if table in tables:
                                db.execute("DELETE FROM " + table + " WHERE user_id=?", (user_id,))
                        db.execute("DELETE FROM profile_requests WHERE user_id=?", (user_id,))
                        db.execute("DELETE FROM profiles WHERE user_id=?", (user_id,))
                        db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
                        # Only opaque IDs remain while filesystem/OMR cancellation retries.
                        # The actual username, password hash and account record are deleted.
                        db.execute("INSERT INTO account_deletions VALUES(?,?,?)", (user_id, json.dumps(recordings), self.clock()))
                        db.execute("DELETE FROM users WHERE id=?", (user_id,))
            except Exception:
                # A gateway commit can fail after the account commit. The opaque
                # cleanup queue is already durable: report pending and retry;
                # never restore or silently disable an existing account.
                with self.owner_scope(None), self.connect() as db:
                    committed = not db.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone() and db.execute("SELECT 1 FROM account_deletions WHERE user_id=?", (user_id,)).fetchone()
                if not committed:
                    raise
        with self.owner_scope(None):
            complete = self.process_deletion(user_id)
        return {"authenticated": False, "accountDeleted": True, "deletionRequested": True,
                "deleted": complete, "status": "completed" if complete else "pending"}

    def process_deletion(self, user_id):
        # Persisted queue means an unavailable OMR worker or an open Windows
        # recording cannot turn account deletion into a false completion.
        if not self.deletion_lock.acquire(blocking=False):
            return False
        try:
            with self.connect() as db:
                request = db.execute("SELECT recordings FROM account_deletions WHERE user_id=?", (uid(user_id),)).fetchone()
            if not request:
                return True
            try:
                for recording in json.loads(request[0]):
                    self.recording_path(recording).unlink(missing_ok=True)
                if self.omr_delete is not None:
                    self.omr_delete(user_id)
                elif self.omr_import is not None or self.legacy_claim is not None:
                    raise APIError(503, "识谱删除适配器尚未配置。")
                with self.connect() as db:
                    db.execute("DELETE FROM account_deletions WHERE user_id=?", (user_id,))
                return True
            except (APIError, OSError, ValueError):
                return False
        finally:
            self.deletion_lock.release()

    def process_deletions(self):
        with self.connect() as db:
            users = [r[0] for r in db.execute("SELECT user_id FROM account_deletions ORDER BY created LIMIT 100")]
        for user_id in users:
            self.process_deletion(user_id)

    def register(self, data):
        fields(data, {"username", "password", "mode", "deviceName"}, {"username", "password"})
        name = username(data["username"])
        self.session_options(data)
        salt, hashed = password_hash(data["password"])
        user_id = str(uuid.uuid4())
        with self.connect() as db:
            try:
                db.execute("INSERT INTO users VALUES(?,?,?,?,?)", (user_id, name, salt, hashed, self.clock()))
            except sqlite3.IntegrityError as error:
                raise APIError(409, "用户名已被使用。") from error
            return self.new_session(db, user_id, name, data)

    def session_options(self, data):
        kind = data.get("mode", "browser")
        if not isinstance(kind, str) or kind not in {"browser", "native"}:
            raise APIError(400, "登录模式无效。")
        name = text(data.get("deviceName", "NoteLite"), "设备名称", 80)
        return kind, name

    def login(self, data):
        fields(data, {"username", "password", "mode", "deviceName"}, {"username", "password"})
        name = username(data["username"])
        self.session_options(data)
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE username=?", (name,)).fetchone()
        _, candidate = password_hash(data["password"], row["salt"] if row else self.dummy_salt, creating=False)
        if not hmac.compare_digest(candidate, row["password_hash"] if row else self.dummy_hash) or not row:
            raise APIError(401, "用户名或密码不正确。")
        with self.connect() as db:
            return self.new_session(db, row["id"], name, data)

    def new_session(self, db, user_id, name, data):
        self.require_active_user(db, user_id)
        kind, device_name = self.session_options(data)
        token, session_id = secrets.token_urlsafe(32), str(uuid.uuid4())
        csrf = csrf_value(token)
        moment = self.clock()
        expires = moment + (30 if kind == "browser" else 90) * 86400
        # Expired sessions are purged. Bound active devices without silently revoking.
        db.execute("DELETE FROM sessions WHERE expires<=? OR revoked=1", (moment,))
        if db.execute("SELECT count(*) FROM sessions WHERE user_id=?", (user_id,)).fetchone()[0] >= 32:
            raise APIError(409, "已达 32 台登录设备，请先退出其他设备。")
        db.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?,?,0,?)", (session_id, user_id, kind, device_name, token_hash(token), token_hash(csrf), expires, moment))
        return {"authenticated": True, "userId": user_id, "username": name, "sessionId": session_id, "deviceName": device_name, "expiresAt": now_stamp(expires), "kind": kind, "token": token, "csrf": csrf}

    def authenticate(self, token, kind):
        hashed = token_hash(token)
        with self.connect() as db:
            row = db.execute("SELECT s.*,u.username FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.kind=? AND s.expires>? AND s.revoked=0", (hashed, kind, self.clock())).fetchone()
        if not row:
            raise APIError(401, "登录凭据无效或已过期。")
        return dict(row)

    def identity(self, session, csrf=None):
        value = {"authenticated": True, "userId": session["user_id"], "username": session["username"], "sessionId": session["id"], "deviceName": session["name"], "expiresAt": now_stamp(session["expires"]), "kind": session["kind"]}
        if csrf is not None:
            value["csrf"] = csrf
        return value

    def session_list(self, user_id):
        with self.connect() as db:
            return [{"sessionId": row["id"], "deviceName": row["name"], "kind": row["kind"], "createdAt": now_stamp(row["created"]), "expiresAt": now_stamp(row["expires"])} for row in db.execute("SELECT * FROM sessions WHERE user_id=? AND expires>? AND revoked=0 ORDER BY created", (user_id, self.clock()))]

    def revoke(self, user_id, session_id):
        with self.connect() as db:
            cursor = db.execute("UPDATE sessions SET revoked=1 WHERE id=? AND user_id=?", (uid(session_id), user_id))
            if cursor.rowcount != 1:
                raise APIError(404, "设备不存在。")

    def score_meta(self, row):
        value = {"id": row["id"], "title": row["title"], "revision": row["revision"], "updatedAt": now_stamp(row["updated"]), "etag": '"' + row["id"] + ':' + str(row["revision"]) + '"'}
        if row["job_id"] is not None:
            value["omr"] = {"jobId": row["job_id"], "scoreIndex": row["score_index"], "revision": row["omr_revision"]}
        return value

    def get_score(self, db, user_id, score_id):
        row = db.execute("SELECT * FROM scores WHERE id=? AND user_id=?", (uid(score_id), user_id)).fetchone()
        if not row:
            raise APIError(404, "个人曲谱不存在。")
        return row

    def quota(self, db, user_id, additional):
        row = db.execute("SELECT count(*),coalesce(sum(length(CAST(xml AS BLOB))),0) FROM scores WHERE user_id=?", (user_id,)).fetchone()
        if row[0] >= 1000 or row[1] + additional > 100 * 1024 * 1024:
            raise APIError(413, "个人曲谱达到存储限额。")

    def insert_score(self, db, user_id, title, xml, omr=None):
        self.quota(db, user_id, len(xml.encode("utf8")))
        score_id = str(uuid.uuid4())
        omr = omr or (None, None, None)
        db.execute("INSERT INTO scores VALUES(?,?,?,?,?,?,?,?,?)", (score_id, user_id, title, xml, 1, self.clock(), *omr))
        return self.score_meta(self.get_score(db, user_id, score_id))

    def create_score(self, user_id, data):
        fields(data, {"title", "musicxml", "jobId", "scoreIndex", "revision", "requestId"}, {"title"})
        title = text(data["title"], "曲谱名称")
        request_id = uid(data["requestId"]) if "requestId" in data else None
        request_hash = hashlib.sha256(json.dumps({k: v for k, v in data.items() if k != "requestId"}, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf8")).hexdigest()
        if request_id:
            with self.connect() as db:
                old = self.existing_score_request(db, user_id, request_id, request_hash)
                if old:
                    return {**old, "duplicate": True}
        omr = None
        if "jobId" in data:
            if "musicxml" in data or not {"scoreIndex", "revision"} <= set(data):
                raise APIError(400, "识谱导入字段无效。")
            omr = (uid(data["jobId"]), integer(data["scoreIndex"], "谱序号", 0, 10000), integer(data["revision"], "识谱版本", 1, 2 ** 31 - 1))
            if self.omr_import is None:
                raise APIError(503, "识谱所有权校验尚未配置，无法关联任务。")
            # Hook must verify account UUID owns job and returns XML of exactly this revision.
            xml = validate_xml(self.omr_import(user_id, *omr))
        else:
            if "scoreIndex" in data or "revision" in data or "musicxml" not in data:
                raise APIError(400, "请提供 MusicXML 或完整识谱任务引用。")
            xml = validate_xml(data["musicxml"])
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if request_id:
                old = self.existing_score_request(db, user_id, request_id, request_hash)
                if old:
                    return {**old, "duplicate": True}
            result = self.insert_score(db, user_id, title, xml, omr)
            if request_id:
                db.execute("INSERT INTO score_requests VALUES(?,?,?,?)", (user_id, request_id, request_hash, result["id"]))
            return {**result, "duplicate": False}

    def existing_score_request(self, db, user_id, request_id, request_hash):
        row = db.execute("SELECT * FROM score_requests WHERE user_id=? AND request_id=?", (user_id, request_id)).fetchone()
        if row:
            if not hmac.compare_digest(row["payload_hash"], request_hash):
                raise APIError(409, "曲谱创建标识已用于其他内容。")
            return self.score_meta(self.get_score(db, user_id, row["score_id"]))
        return None

    def list_scores(self, user_id):
        with self.connect() as db:
            return [self.score_meta(row) for row in db.execute("SELECT * FROM scores WHERE user_id=? ORDER BY updated DESC,id", (user_id,))]

    def read_score(self, user_id, score_id):
        with self.connect() as db:
            row = self.get_score(db, user_id, score_id)
            return self.score_meta(row), row["xml"]

    def update_score(self, user_id, score_id, data, etag):
        fields(data, {"title", "musicxml"}, {"musicxml"})
        xml = validate_xml(data["musicxml"])
        title = text(data["title"], "曲谱名称") if "title" in data else None
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.get_score(db, user_id, score_id)
            if etag != self.score_meta(row)["etag"]:
                raise APIError(409, "另一台设备已修改，请重新读取曲谱后合并。")
            total = db.execute("SELECT coalesce(sum(length(CAST(xml AS BLOB))),0) FROM scores WHERE user_id=? AND id<>?", (user_id, score_id)).fetchone()[0]
            if total + len(xml.encode("utf8")) > 100 * 1024 * 1024:
                raise APIError(413, "个人曲谱达到存储限额。")
            db.execute("UPDATE scores SET title=?,xml=?,revision=revision+1,updated=? WHERE id=? AND user_id=?", (title or row["title"], xml, self.clock(), score_id, user_id))
            return self.score_meta(self.get_score(db, user_id, score_id))

    def catalog(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT id,title,composer,license,source FROM catalog ORDER BY id")]

    def official_xml(self, score_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM catalog WHERE id=?", (score_id,)).fetchone()
            if not row:
                raise APIError(404, "官方曲谱不存在。")
            return row["xml"]

    def add_history(self, user_id, data):
        fields(data, {"eventId", "sourceKind", "scoreId", "scoreRevision", "mode", "durationSeconds", "startedAt", "endedAt", "analysis"}, {"eventId", "sourceKind", "scoreId", "mode", "durationSeconds", "startedAt", "endedAt"})
        uid(data["eventId"])
        if not isinstance(data["mode"], str) or not isinstance(data["sourceKind"], str) or data["mode"] not in {"free", "strict", "follow", "playback"} or data["sourceKind"] not in {"official", "personal"}:
            raise APIError(400, "练习类型无效。")
        text(data["scoreId"], "练习曲谱标识", 80)
        duration = data["durationSeconds"]
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or not 0 <= duration <= 86400:
            raise APIError(400, "练习时长无效。")
        for key in ("startedAt", "endedAt"):
            if not isinstance(data[key], str) or len(data[key]) > 40:
                raise APIError(400, "练习时间无效。")
        try:
            start, end = (datetime.fromisoformat(data[key].replace("Z", "+00:00")) for key in ("startedAt", "endedAt"))
            if start.tzinfo is None or end.tzinfo is None or end < start or (end - start).total_seconds() > 86400 or end.timestamp() > self.clock() + 300 or duration > (end - start).total_seconds() + 2:
                raise ValueError()
        except (ValueError, TypeError, OverflowError) as error:
            raise APIError(400, "练习时间或时长不一致。") from error
        original_analysis = data.get("analysis")
        analysis_json(original_analysis)
        if "scoreRevision" in data:
            integer(data["scoreRevision"], "练习曲谱版本", 1, 2 ** 31 - 1)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM history WHERE user_id=? AND event_id=?", (user_id, data["eventId"])).fetchone()
            if existing:
                if is_performance_v2(original_analysis):
                    self.check_history_snapshot(existing)
                analysis = self.analysis_payload(original_analysis, existing["score_xml"], existing["score_sha256"], existing["score_revision"], data["mode"], data["eventId"])
                self.check_analysis_mode(analysis, data["mode"])
                data = {**data, "analysis": analysis}
                canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
                old = json.loads(existing["payload"])
                old.pop("scoreSha256", None)
                if "scoreRevision" not in data:
                    old.pop("scoreRevision", None)
                if json.dumps(old, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) != canonical:
                    raise APIError(409, "练习事件标识已用于其他内容。")
                return {"event": self.history_meta(db, existing), "duplicate": True, "scoreValidated": False}
            if data["sourceKind"] == "personal":
                score = self.get_score(db, user_id, data["scoreId"])
                revision, xml = score["revision"], score["xml"]
            else:
                score = db.execute("SELECT * FROM catalog WHERE id=?", (data["scoreId"],)).fetchone()
                if not score:
                    raise APIError(404, "官方曲谱不存在。")
                revision, xml = 1, score["xml"]
            if data.get("scoreRevision", revision) != revision:
                raise APIError(409, "练习曲谱版本已改变，请同步曲谱再保存记录。")
            if db.execute("SELECT count(*) FROM history WHERE user_id=?", (user_id,)).fetchone()[0] >= 20000:
                raise APIError(413, "练习历史达到当前存储限额。")
            # Keep the exact practiced score, independent of later multi-device edits.
            history_bytes = db.execute("SELECT coalesce(sum(length(CAST(score_xml AS BLOB))),0) FROM history WHERE user_id=?", (user_id,)).fetchone()[0]
            if history_bytes + len(xml.encode("utf8")) > 100 * 1024 * 1024:
                raise APIError(413, "练习曲谱快照达到当前存储限额。")
            sha = hashlib.sha256(xml.encode("utf8")).hexdigest()
            analysis = self.analysis_payload(original_analysis, xml, sha, revision, data["mode"], data["eventId"])
            self.check_analysis_mode(analysis, data["mode"])
            data = {**data, "analysis": analysis, "scoreRevision": revision, "scoreSha256": sha}
            canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            db.execute("INSERT INTO history(user_id,event_id,payload,created,score_xml,score_sha256,score_revision) VALUES(?,?,?,?,?,?,?)", (user_id, data["eventId"], canonical, self.clock(), xml, sha, revision))
            history = self.get_history(db, user_id, data["eventId"])
            if is_performance_v2(analysis):
                self.insert_analysis_version(db, history, analysis, 0, data["eventId"], sha)
            # Stored timing is client-reported. Never invent pitch accuracy or evaluation.
            return {"event": self.history_meta(db, history), "duplicate": False, "scoreValidated": False}

    def list_history(self, user_id, limit=100, before=None):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM history WHERE user_id=? ORDER BY created DESC,event_id DESC LIMIT ?", (user_id, limit)) if before is None else db.execute("SELECT * FROM history WHERE user_id=? AND (created<? OR (created=? AND event_id<?)) ORDER BY created DESC,event_id DESC LIMIT ?", (user_id, before[0], before[0], before[1], limit))
            rows = list(rows)
            return {"events": [{**self.history_meta(db, row), "receivedAt": now_stamp(row["created"]), "scoreValidated": False} for row in rows], "nextCursor": f'{rows[-1]["created"]}:{rows[-1]["event_id"]}' if len(rows) == limit else None}

    def get_history(self, db, user_id, event_id):
        row = db.execute("SELECT * FROM history WHERE user_id=? AND event_id=?", (user_id, uid(event_id))).fetchone()
        if not row:
            raise APIError(404, "练习记录不存在。")
        return row

    def check_history_snapshot(self, row):
        xml, digest = row["score_xml"], row["score_sha256"]
        if not isinstance(xml, str) or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise APIError(503, "此历史记录未保存可核对的原谱快照。")
        if not hmac.compare_digest(hashlib.sha256(xml.encode("utf8")).hexdigest(), digest):
            raise APIError(503, "练习原谱快照完整性校验未通过。")
        return xml, digest, row["score_revision"]

    def check_analysis_mode(self, analysis, mode):
        if mode in {"free", "playback"} and analysis.get("status") != "unanalysed":
            raise APIError(400, "自由计时和播放记录不能包含音准分析。")

    def history_meta(self, db, row):
        result = json.loads(row["payload"])
        latest = db.execute("SELECT * FROM history_analysis_versions WHERE user_id=? AND event_id=? ORDER BY version DESC LIMIT 1", (row["user_id"], row["event_id"])).fetchone()
        if latest:
            self.check_history_snapshot(row)
            self.check_analysis_version(row, latest)
            result.update({"analysis": json.loads(latest["payload"]), "analysisVersion": latest["version"],
                           "analysisHash": latest["analysis_hash"], "snapshotValidatedByServer": True})
        return result

    def check_analysis_version(self, history, row):
        try:
            raw = row["payload"].encode("utf8")
            intact = len(raw) <= MAX_ANALYSIS and hmac.compare_digest(hashlib.sha256(raw).hexdigest(), row["analysis_hash"])
            intact = intact and hmac.compare_digest(row["source_hash"], history["score_sha256"])
        except (TypeError, UnicodeError):
            intact = False
        if not intact:
            raise APIError(503, "演奏分析版本完整性校验未通过。")

    def analysis_version_meta(self, row, *, include_payload=True):
        result = {"version": row["version"], "parentVersion": row["parent_version"],
                  "requestId": row["request_id"], "sourceHash": row["source_hash"],
                  "analysisHash": row["analysis_hash"], "createdAt": now_stamp(row["created"]),
                  "snapshotValidatedByServer": True}
        if include_payload:
            result["analysis"] = json.loads(row["payload"])
        return result

    def insert_analysis_version(self, db, history, analysis, parent, request_id, source_hash):
        canonical = analysis_json(analysis)
        if parent >= 64:
            raise APIError(413, "这条练习的分析版本达到当前存储限额。")
        total = db.execute("SELECT coalesce(sum(length(CAST(payload AS BLOB))),0) FROM history_analysis_versions WHERE user_id=?", (history["user_id"],)).fetchone()[0]
        if total + len(canonical.encode("utf8")) > MAX_ANALYSIS_STORAGE:
            raise APIError(413, "演奏分析达到当前存储限额。")
        digest = hashlib.sha256(canonical.encode("utf8")).hexdigest()
        version = parent + 1
        db.execute("INSERT INTO history_analysis_versions VALUES(?,?,?,?,?,?,?,?,?)", (history["user_id"], history["event_id"], version, parent, request_id, source_hash, digest, canonical, self.clock()))
        return db.execute("SELECT * FROM history_analysis_versions WHERE user_id=? AND event_id=? AND version=?", (history["user_id"], history["event_id"], version)).fetchone()

    def add_history_analysis(self, user_id, event_id, data):
        fields(data, {"requestId", "parentVersion", "sourceHash", "analysis"}, {"requestId", "parentVersion", "sourceHash", "analysis"})
        request_id = uid(data["requestId"])
        parent = integer(data["parentVersion"], "父分析版本", 0, 2 ** 31 - 1)
        source_hash = data["sourceHash"]
        if not isinstance(source_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", source_hash):
            raise APIError(400, "原谱快照校验值无效。")
        analysis_json(data["analysis"])
        if not is_performance_v2(data["analysis"]):
            raise APIError(400, "复核分析须使用 V2 演奏记录。")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            history = self.get_history(db, user_id, event_id)
            xml, sha, revision = self.check_history_snapshot(history)
            if not hmac.compare_digest(source_hash, sha):
                raise APIError(409, "分析引用的原谱快照与这条练习不一致。")
            event = json.loads(history["payload"])
            analysis = self.analysis_payload(data["analysis"], xml, sha, revision, event["mode"], event_id)
            self.check_analysis_mode(analysis, event["mode"])
            canonical = analysis_json(analysis)
            old = db.execute("SELECT * FROM history_analysis_versions WHERE user_id=? AND event_id=? AND request_id=?", (user_id, event_id, request_id)).fetchone()
            if old:
                self.check_analysis_version(history, old)
                if old["parent_version"] != parent or old["source_hash"] != source_hash or old["payload"] != canonical:
                    raise APIError(409, "分析请求标识已用于其他内容。")
                return {**self.analysis_version_meta(old), "duplicate": True}
            latest = db.execute("SELECT coalesce(max(version),0) FROM history_analysis_versions WHERE user_id=? AND event_id=?", (user_id, event_id)).fetchone()[0]
            if parent != latest:
                raise APIError(409, "另一台设备已保存更新的分析，请重新读取后复核。")
            row = self.insert_analysis_version(db, history, analysis, parent, request_id, source_hash)
            return {**self.analysis_version_meta(row), "duplicate": False}

    def list_history_analyses(self, user_id, event_id):
        with self.connect() as db:
            history = self.get_history(db, user_id, event_id)
            self.check_history_snapshot(history)
            rows = list(db.execute("SELECT * FROM history_analysis_versions WHERE user_id=? AND event_id=? ORDER BY version DESC", (user_id, event_id)))
            for row in rows:
                self.check_analysis_version(history, row)
            return {"analyses": [self.analysis_version_meta(row, include_payload=False) for row in rows],
                    "latestVersion": rows[0]["version"] if rows else 0}

    def read_history_analysis(self, user_id, event_id, version):
        integer(version, "分析版本", 1, 2 ** 31 - 1)
        with self.connect() as db:
            history = self.get_history(db, user_id, event_id)
            self.check_history_snapshot(history)
            row = db.execute("SELECT * FROM history_analysis_versions WHERE user_id=? AND event_id=? AND version=?", (user_id, event_id, version)).fetchone()
            if not row:
                raise APIError(404, "分析版本不存在。")
            self.check_analysis_version(history, row)
            return self.analysis_version_meta(row)

    def history_xml(self, user_id, event_id):
        with self.connect() as db:
            row = db.execute("SELECT score_xml,score_sha256 FROM history WHERE user_id=? AND event_id=?", (user_id, uid(event_id))).fetchone()
            if not row:
                raise APIError(404, "练习记录不存在。")
            if row["score_xml"] is None:
                raise APIError(503, "此历史记录未保存当时的曲谱快照。")
            return row["score_xml"], row["score_sha256"]

    def get_course(self, db, user_id, course_id, creator=False):
        row = db.execute("SELECT * FROM courses WHERE id=?", (uid(course_id),)).fetchone()
        if not row or (creator and row["creator"] != user_id) or (not creator and row["creator"] != user_id and not db.execute("SELECT 1 FROM memberships WHERE course_id=? AND user_id=?", (course_id, user_id)).fetchone()):
            raise APIError(404, "课程不存在。")
        return row

    def course_detail(self, db, user_id, course_id):
        row = self.get_course(db, user_id, course_id)
        creator = row["creator"] == user_id
        teacher = db.execute("SELECT username FROM users WHERE id=?", (row["creator"],)).fetchone()[0]
        result = {"id": row["id"], "title": row["title"], "teacher": teacher, "role": "teacher" if creator else "student", "createdAt": now_stamp(row["created"]), "sharedScores": [{"id": r["id"], "title": r["title"]} for r in db.execute("SELECT id,title FROM course_scores WHERE course_id=? ORDER BY id", (course_id,))], "sharingScope": "只向本课堂老师共享已提交作业的录音和错音；个人练习历史不自动共享。"}
        result["deliveredScores"] = [self.score_meta(r) for r in db.execute("SELECT s.* FROM scores s JOIN course_deliveries d ON d.score_id=s.id WHERE d.course_id=? AND d.user_id=? ORDER BY s.id", (course_id, user_id))]
        if creator:
            result["memberCount"] = db.execute("SELECT count(*) FROM memberships WHERE course_id=?", (course_id,)).fetchone()[0]
        return result

    def create_course(self, user_id, data):
        fields(data, {"title"}, {"title"})
        title, course_id = text(data["title"], "课程名称", 40), str(uuid.uuid4())
        with self.connect() as db:
            if db.execute("SELECT count(*) FROM courses WHERE creator=?", (user_id,)).fetchone()[0] >= 100:
                raise APIError(413, "课程达到当前数量限额。")
            db.execute("INSERT INTO courses VALUES(?,?,?,?)", (course_id, user_id, title, self.clock()))
            return self.course_detail(db, user_id, course_id)

    def list_courses(self, user_id):
        with self.connect() as db:
            rows = db.execute("SELECT c.id FROM courses c LEFT JOIN memberships m ON m.course_id=c.id AND m.user_id=? WHERE c.creator=? OR m.user_id=? ORDER BY c.created DESC,c.id", (user_id, user_id, user_id))
            return [self.course_detail(db, user_id, row[0]) for row in rows]

    def add_course_score(self, user_id, course_id, data):
        fields(data, {"sourceKind", "scoreId"}, {"sourceKind", "scoreId"})
        with self.connect() as db:
            self.get_course(db, user_id, course_id, True)
            if data["sourceKind"] == "personal":
                score = self.get_score(db, user_id, data["scoreId"])
            elif data["sourceKind"] == "official":
                score = db.execute("SELECT * FROM catalog WHERE id=?", (data["scoreId"],)).fetchone()
                if not score:
                    raise APIError(404, "官方曲谱不存在。")
            else:
                raise APIError(400, "曲谱来源无效。")
            if db.execute("SELECT count(*) FROM course_scores WHERE course_id=?", (course_id,)).fetchone()[0] >= 30:
                raise APIError(413, "课程曲谱达到当前数量限额。")
            score_id = str(uuid.uuid4())
            # Snapshot, never expose the creator's private score ID/OMR job to members.
            db.execute("INSERT INTO course_scores VALUES(?,?,?,?,?,?)", (score_id, course_id, score["title"], score["xml"], data["sourceKind"], data["scoreId"]))
            return {"id": score_id, "title": score["title"], "snapshot": True}

    def create_code(self, user_id, course_id, data):
        fields(data, {"ttlSeconds", "maxUses"})
        ttl = integer(data.get("ttlSeconds", 86400), "代码有效期", 60, 7 * 86400)
        uses = integer(data.get("maxUses", 50), "代码次数", 1, 500)
        with self.connect() as db:
            self.get_course(db, user_id, course_id, True)
            db.execute("DELETE FROM codes WHERE expires<=?", (self.clock(),))
            if db.execute("SELECT count(*) FROM codes WHERE course_id=? AND revoked=0", (course_id,)).fetchone()[0] >= 20:
                raise APIError(413, "课程有效代码达到当前数量限额。")
            expires = self.clock() + ttl
            for _ in range(8):
                code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
                try:
                    db.execute("INSERT INTO codes VALUES(?,?,?,?,0,0,?)", (code_hash(code), course_id, expires, uses, self.clock()))
                    break
                except sqlite3.IntegrityError:
                    continue
            else:
                raise APIError(503, "暂时无法生成课堂代码。")
            return {"code": code, "codeId": code_hash(code), "courseId": course_id, "expiresAt": now_stamp(expires), "maxUses": uses, "purpose": "join-classroom"}

    def revoke_code(self, user_id, course_id, code_id):
        if not re.fullmatch(r"[0-9a-f]{64}", code_id):
            raise APIError(404, "代码不存在。")
        with self.connect() as db:
            self.get_course(db, user_id, course_id, True)
            if db.execute("UPDATE codes SET revoked=1 WHERE hash=? AND course_id=?", (code_id, course_id)).rowcount != 1:
                raise APIError(404, "代码不存在。")

    def join_course(self, user_id, data):
        fields(data, {"code"}, {"code"})
        hashed = code_hash(data["code"])
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            code = db.execute("SELECT * FROM codes WHERE hash=? AND expires>? AND revoked=0", (hashed, self.clock())).fetchone()
            if not code:
                raise APIError(404, "课程代码无效、已过期或已撤销。")
            course_id = code["course_id"]
            joined = db.execute("SELECT 1 FROM memberships WHERE course_id=? AND user_id=?", (course_id, user_id)).fetchone()
            if not joined:
                if code["uses"] >= code["max_uses"]:
                    raise APIError(409, "课程代码使用次数已用完。")
                db.execute("INSERT INTO memberships VALUES(?,?,?)", (course_id, user_id, self.clock()))
                db.execute("UPDATE codes SET uses=uses+1 WHERE hash=?", (hashed,))
            for score in db.execute("SELECT * FROM course_scores WHERE course_id=? ORDER BY id", (course_id,)):
                if not db.execute("SELECT 1 FROM course_deliveries WHERE course_id=? AND user_id=? AND course_score_id=?", (course_id, user_id, score["id"])).fetchone():
                    delivered = self.insert_score(db, user_id, score["title"], score["xml"])
                    db.execute("INSERT INTO course_deliveries VALUES(?,?,?,?)", (course_id, user_id, score["id"], delivered["id"]))
            return {**self.course_detail(db, user_id, course_id), "alreadyJoined": bool(joined), "historySharedWithCreator": False}

    def preview_code(self, data):
        fields(data, {"code"}, {"code"})
        with self.connect() as db:
            row = db.execute("SELECT c.id,c.title,u.username,d.expires FROM codes d JOIN courses c ON c.id=d.course_id JOIN users u ON u.id=c.creator WHERE d.hash=? AND d.expires>? AND d.revoked=0 AND d.uses<d.max_uses", (code_hash(data["code"]), self.clock())).fetchone()
            if not row:
                raise APIError(404, "课堂代码无效、已过期或不可使用。")
            return {"courseId": row["id"], "title": row["title"], "teacher": row["username"], "expiresAt": now_stamp(row["expires"]), "sharingScope": "只向本课堂老师共享已提交作业的录音和错音；个人练习历史不自动共享。"}

    def leave_course(self, user_id, course_id):
        with self.connect() as db:
            self.get_course(db, user_id, course_id)
            if db.execute("DELETE FROM memberships WHERE course_id=? AND user_id=?", (course_id, user_id)).rowcount != 1:
                raise APIError(400, "课程老师不能退出自己的课堂。")
        return {"left": True, "retainedSubmittedWork": True}

    def roster(self, user_id, course_id):
        with self.connect() as db:
            self.get_course(db, user_id, course_id, True)
            return [{"userId": r["id"], "username": r["username"], "joinedAt": now_stamp(r["joined"])} for r in db.execute("SELECT u.id,u.username,m.joined FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.course_id=? ORDER BY m.joined,u.id", (course_id,))]

    def assignment(self, db, user_id, assignment_id, *, student=False):
        row = db.execute("SELECT a.*,c.creator FROM assignments a JOIN courses c ON c.id=a.course_id WHERE a.id=?", (uid(assignment_id),)).fetchone()
        if not row:
            raise APIError(404, "作业不存在。")
        self.get_course(db, user_id, row["course_id"])
        if student and row["creator"] == user_id:
            raise APIError(403, "此操作仅供课堂学生使用。")
        return row

    def assignment_meta(self, row):
        return {"id": row["id"], "courseId": row["course_id"], "courseScoreId": row["course_score_id"], "title": row["title"], "dueAt": now_stamp(row["due"]) if row["due"] is not None else None, "requirements": row["requirements"], "createdAt": now_stamp(row["created"])}

    def create_assignment(self, user_id, course_id, data):
        fields(data, {"title", "courseScoreId", "dueAt", "requirements"}, {"title", "courseScoreId"})
        title, source, due = text(data["title"], "作业名称"), uid(data["courseScoreId"]), None
        requirements = text(data["requirements"], "作业要求", 2000) if data.get("requirements") else ""
        if data.get("dueAt") is not None:
            try:
                date = datetime.fromisoformat(data["dueAt"].replace("Z", "+00:00"))
                if date.tzinfo is None:
                    raise ValueError()
                due = date.timestamp()
                if not self.clock() < due <= self.clock() + 366 * 86400:
                    raise ValueError()
            except (ValueError, TypeError, AttributeError, OverflowError) as error:
                raise APIError(400, "作业截止时间无效。") from error
        assignment_id = str(uuid.uuid4())
        with self.connect() as db:
            self.get_course(db, user_id, course_id, True)
            if not db.execute("SELECT 1 FROM course_scores WHERE id=? AND course_id=?", (source, course_id)).fetchone():
                raise APIError(404, "课堂曲谱不存在。")
            if db.execute("SELECT count(*) FROM assignments WHERE course_id=?", (course_id,)).fetchone()[0] >= 500:
                raise APIError(413, "课堂作业达到当前数量限额。")
            db.execute("INSERT INTO assignments VALUES(?,?,?,?,?,?,?)", (assignment_id, course_id, source, title, due, requirements, self.clock()))
            return self.assignment_meta(self.assignment(db, user_id, assignment_id))

    def list_assignments(self, user_id, course_id):
        with self.connect() as db:
            self.get_course(db, user_id, course_id)
            return [self.assignment_meta(row) for row in db.execute("SELECT * FROM assignments WHERE course_id=? ORDER BY created DESC,id", (course_id,))]

    def recording_path(self, upload_id):
        target = self.recordings / (uid(upload_id) + ".audio")
        if target.is_symlink() or target.parent.resolve() != self.recordings.resolve():
            raise APIError(500, "录音存储不可用。")
        return target

    def upload_meta(self, row):
        return {"uploadId": row["id"], "assignmentId": row["assignment_id"], "size": row["size"], "offset": row["offset"], "mime": row["mime"], "complete": bool(row["complete"]), "expiresAt": now_stamp(row["expires"])}

    def get_upload(self, db, user_id, upload_id):
        row = db.execute("SELECT * FROM uploads WHERE id=? AND user_id=?", (uid(upload_id), user_id)).fetchone()
        if not row or (not row["complete"] and row["expires"] <= self.clock()):
            raise APIError(404, "录音上传不存在或已过期。")
        return row

    def create_upload(self, user_id, data):
        fields(data, {"assignmentId", "size", "mime", "sha256"}, {"assignmentId", "size", "mime", "sha256"})
        size = integer(data["size"], "录音大小", 12, self.max_recording)
        if not isinstance(data["mime"], str) or data["mime"] not in AUDIO_TYPES or not isinstance(data["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", data["sha256"]):
            raise APIError(400, "录音类型或校验值无效。")
        upload_id = str(uuid.uuid4())
        with self.connect() as db:
            self.assignment(db, user_id, data["assignmentId"], student=True)
            for old in list(db.execute("SELECT id FROM uploads WHERE complete=0 AND expires<=?", (self.clock(),))):
                self.recording_path(old[0]).unlink(missing_ok=True)
                db.execute("DELETE FROM uploads WHERE id=?", (old[0],))
            reserved = db.execute("SELECT coalesce(sum(size),0) FROM uploads WHERE user_id=?", (user_id,)).fetchone()[0]
            if reserved + size > self.recording_quota:
                raise APIError(413, "课堂录音达到个人存储限额。")
            if shutil.disk_usage(self.recordings).free < size + self.disk_reserve:
                raise APIError(507, "服务器暂时没有足够录音空间。")
            path = self.recording_path(upload_id)
            with path.open("xb"):
                pass
            if os.name == "posix":
                path.chmod(0o600)
            moment = self.clock()
            try:
                db.execute("INSERT INTO uploads VALUES(?,?,?,?,?,?,?,0,?,?)", (upload_id, user_id, data["assignmentId"], size, 0, data["mime"], data["sha256"], moment + 7 * 86400, moment))
            except Exception:
                path.unlink(missing_ok=True)
                raise
            return self.upload_meta(self.get_upload(db, user_id, upload_id))

    def append_upload(self, user_id, upload_id, offset, raw):
        if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_CHUNK:
            raise APIError(413, "录音分块须为 1 至 8 MiB。")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.get_upload(db, user_id, upload_id)
            self.assignment(db, user_id, row["assignment_id"], student=True)
            if row["complete"] or offset != row["offset"]:
                raise APIError(409, "录音上传位置已改变，请重新读取上传状态。")
            if offset + len(raw) > row["size"]:
                raise APIError(413, "录音分块超过声明的总大小。")
            if shutil.disk_usage(self.recordings).free < len(raw) + self.disk_reserve:
                raise APIError(507, "服务器暂时没有足够录音空间。")
            with self.recording_path(upload_id).open("r+b") as output:
                if output.seek(0, 2) < offset:
                    raise APIError(500, "录音存储状态异常。")
                output.truncate(offset)
                output.seek(offset)
                try:
                    output.write(raw)
                    output.flush()
                    os.fsync(output.fileno())
                    db.execute("UPDATE uploads SET offset=? WHERE id=?", (offset + len(raw), upload_id))
                except Exception:
                    output.truncate(offset)
                    raise
            return self.upload_meta(self.get_upload(db, user_id, upload_id))

    def complete_upload(self, user_id, upload_id):
        with self.connect() as db:
            row = self.get_upload(db, user_id, upload_id)
            self.assignment(db, user_id, row["assignment_id"], student=True)
            if row["complete"]:
                return self.upload_meta(row)
            if row["offset"] != row["size"]:
                raise APIError(409, "录音尚未上传完整。")
            sha = hashlib.sha256()
            path = self.recording_path(upload_id)
            with path.open("rb") as recording:
                head = recording.read(64)
                sha.update(head)
                while chunk := recording.read(1024 * 1024):
                    sha.update(chunk)
            wav_valid = False
            if row["mime"] == "audio/wav":
                try:
                    with wave.open(str(path), "rb") as wav:
                        wav_valid = wav.getnchannels() in {1, 2} and wav.getsampwidth() in {1, 2, 3, 4} and 8000 <= wav.getframerate() <= 192000 and wav.getnframes() > 0
                        expected = wav.getnframes() * wav.getnchannels() * wav.getsampwidth()
                        consumed = 0
                        while chunk := wav.readframes(65536):
                            consumed += len(chunk)
                        wav_valid = wav_valid and consumed == expected
                except (wave.Error, EOFError, RuntimeError, struct.error):
                    wav_valid = False
            valid = {
                "audio/wav": wav_valid and len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WAVE" and struct.unpack("<I", head[4:8])[0] + 8 == row["size"],
                "audio/mpeg": head.startswith(b"ID3") or (len(head) > 4 and head[0] == 255 and head[1] & 224 == 224 and head[1] & 6 != 0 and head[2] & 240 not in {0, 240} and head[2] & 12 != 12),
                "audio/ogg": head.startswith(b"OggS\x00") and (b"OpusHead" in head or b"vorbis" in head),
                "audio/mp4": len(head) >= 12 and head[4:8] == b"ftyp" and head[8:12] in {b"M4A ", b"isom", b"mp42", b"M4B ", b"qt  "},
            }[row["mime"]]
            if not valid or not hmac.compare_digest(sha.hexdigest(), row["sha256"]) or path.stat().st_size != row["size"]:
                raise APIError(400, "录音格式或完整性校验未通过。")
            db.execute("UPDATE uploads SET complete=1 WHERE id=?", (upload_id,))
            return self.upload_meta(self.get_upload(db, user_id, upload_id))

    def analysis_payload(self, value, score_xml=None, score_sha=None, score_revision=None, mode=None, event_id=None):
        if value is None:
            return {"status": "unanalysed", "source": "none", "errors": None, "verifiedByServer": False}
        analysis_json(value)
        if is_performance_v2(value):
            if not isinstance(score_xml, str) or not isinstance(score_sha, str):
                raise APIError(503, "V2 演奏分析需要当时的原谱快照。")
            if event_id is not None and value.get("takeId") != event_id:
                raise APIError(422, "演奏分析的录制标识与这条练习不一致。")
            from performance_analysis import normalize_performance
            try:
                normalized = normalize_performance(value, score_xml, score_sha, score_revision, mode)
            except ValueError as error:
                raise APIError(422, "演奏分析与原谱快照或练习模式不一致，请重新同步后检查记录。") from error
            result = {**normalized, "verifiedByServer": False}
            analysis_json(result)
            return result
        fields(value, {"status", "source", "errors"}, {"status", "source", "errors"})
        if not isinstance(value["status"], str) or value["status"] not in {"uncertain", "analysed"} or value["source"] != "client-reported" or not isinstance(value["errors"], list) or len(value["errors"]) > 5000:
            raise APIError(400, "错音结果须注明客户端来源或保留未分析状态。")
        for error in value["errors"]:
            fields(error, {"type", "noteId", "measure", "expectedMidi", "playedMidi", "cents", "confidence"}, {"type"})
            if not isinstance(error["type"], str) or error["type"] not in {"wrong", "missed", "extra", "rhythm", "uncertain"}:
                raise APIError(400, "错音类型无效。")
            if "noteId" in error:
                text(error["noteId"], "音符标识", 160)
            if "measure" in error:
                integer(error["measure"], "小节", 0, 100000)
            for key in ("expectedMidi", "playedMidi", "cents", "confidence"):
                if key in error and error[key] is not None:
                    val = error[key]
                    high = 127 if key.endswith("Midi") else 1 if key == "confidence" else 1200
                    low = -1200 if key == "cents" else 0
                    if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val) or not low <= val <= high:
                        raise APIError(400, "错音数据无效。")
        return {**value, "verifiedByServer": False}

    def submit(self, user_id, assignment_id, data):
        fields(data, {"eventId", "uploadId", "analysis", "analysisVersion"}, {"eventId"})
        event_id = uid(data["eventId"])
        if "analysisVersion" in data:
            integer(data["analysisVersion"], "提交分析版本", 1, 2 ** 31 - 1)
        analysis_json(data.get("analysis"))
        upload_id = uid(data["uploadId"]) if data.get("uploadId") else None
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            assignment = self.assignment(db, user_id, assignment_id, student=True)
            history = self.get_history(db, user_id, event_id)
            event = json.loads(history["payload"])
            old = db.execute("SELECT * FROM submissions WHERE assignment_id=? AND user_id=? AND event_id=?", (assignment_id, user_id, event_id)).fetchone()
            requested_version = data.get("analysisVersion")
            version_row = None
            if requested_version is not None:
                version_row = db.execute("SELECT * FROM history_analysis_versions WHERE user_id=? AND event_id=? AND version=?", (user_id, event_id, requested_version)).fetchone()
                if not version_row:
                    raise APIError(404, "提交分析版本不存在。")
            elif "analysis" not in data and old:
                # A retry after a later owner-only review remains pinned to the
                # originally submitted version instead of implicitly sharing it.
                if old["analysis_version"] is not None:
                    version_row = db.execute("SELECT * FROM history_analysis_versions WHERE user_id=? AND event_id=? AND version=?", (user_id, event_id, old["analysis_version"])).fetchone()
                    if not version_row:
                        raise APIError(503, "已提交的分析版本不可用。")
            elif "analysis" not in data or is_performance_v2(data.get("analysis")):
                version_row = db.execute("SELECT * FROM history_analysis_versions WHERE user_id=? AND event_id=? ORDER BY version DESC LIMIT 1", (user_id, event_id)).fetchone()
            if version_row:
                self.check_history_snapshot(history)
                self.check_analysis_version(history, version_row)
                analysis = json.loads(version_row["payload"])
                if "analysis" in data:
                    supplied = self.analysis_payload(data["analysis"], history["score_xml"], history["score_sha256"], history["score_revision"], event["mode"], event_id)
                    if analysis_json(supplied) != version_row["payload"]:
                        raise APIError(409, "提交分析内容与指定版本不一致。")
                canonical = version_row["payload"]
            elif "analysis" in data:
                analysis = self.analysis_payload(data["analysis"], history["score_xml"], history["score_sha256"], history["score_revision"], event["mode"], event_id)
                canonical = analysis_json(analysis)
            elif old:
                analysis = json.loads(old["analysis"])
                canonical = old["analysis"]
            else:
                analysis = event.get("analysis", self.analysis_payload(None))
                canonical = analysis_json(analysis)
            submitted_version = version_row["version"] if version_row else None
            submitted_hash = version_row["analysis_hash"] if version_row else None
            source_hash = history["score_sha256"]
            source = db.execute("SELECT * FROM course_scores WHERE id=?", (assignment["course_score_id"],)).fetchone()
            matched = event["sourceKind"] == "official" and source["source_kind"] == "official" and event["scoreId"] == source["source_id"]
            if event["sourceKind"] == "personal":
                matched = bool(db.execute("SELECT 1 FROM course_deliveries WHERE course_id=? AND user_id=? AND course_score_id=? AND score_id=?", (assignment["course_id"], user_id, assignment["course_score_id"], event["scoreId"])).fetchone())
            if not matched:
                raise APIError(400, "练习记录不属于这份课堂作业曲谱。")
            self.check_analysis_mode(analysis, event["mode"])
            if upload_id:
                upload = self.get_upload(db, user_id, upload_id)
                if not upload["complete"] or upload["assignment_id"] != assignment_id:
                    raise APIError(400, "录音尚未完成或不属于这份作业。")
                if db.execute("SELECT 1 FROM submissions WHERE upload_id=? AND (assignment_id<>? OR user_id<>? OR event_id<>?)", (upload_id, assignment_id, user_id, event_id)).fetchone():
                    raise APIError(409, "录音已用于其他提交。")
            if old:
                if old["upload_id"] != upload_id or old["analysis"] != canonical or old["analysis_version"] != submitted_version:
                    raise APIError(409, "这条练习已提交其他内容。")
                return {**self.submission_meta(db, old), "duplicate": True}
            submission_id = str(uuid.uuid4())
            db.execute("INSERT INTO submissions(id,assignment_id,user_id,event_id,upload_id,analysis,created,analysis_version,analysis_hash,source_hash) VALUES(?,?,?,?,?,?,?,?,?,?)", (submission_id, assignment_id, user_id, event_id, upload_id, canonical, self.clock(), submitted_version, submitted_hash, source_hash))
            return {**self.submission_meta(db, db.execute("SELECT * FROM submissions WHERE id=?", (submission_id,)).fetchone()), "duplicate": False}

    def submission_meta(self, db, row):
        history = self.get_history(db, row["user_id"], row["event_id"])
        event = json.loads(history["payload"])
        analysis = json.loads(row["analysis"])
        if row["analysis_version"] is not None:
            self.check_history_snapshot(history)
            pinned = db.execute("SELECT * FROM history_analysis_versions WHERE user_id=? AND event_id=? AND version=?", (row["user_id"], row["event_id"], row["analysis_version"])).fetchone()
            if not pinned or row["analysis"] != pinned["payload"] or row["analysis_hash"] != pinned["analysis_hash"] or row["source_hash"] != pinned["source_hash"]:
                raise APIError(503, "已提交的分析快照完整性校验未通过。")
            self.check_analysis_version(history, pinned)
            event.update({"analysis": analysis, "analysisVersion": row["analysis_version"],
                          "analysisHash": row["analysis_hash"], "snapshotValidatedByServer": True})
        assignment = db.execute("SELECT due FROM assignments WHERE id=?", (row["assignment_id"],)).fetchone()
        return {"id": row["id"], "assignmentId": row["assignment_id"], "student": db.execute("SELECT username FROM users WHERE id=?", (row["user_id"],)).fetchone()[0], "event": event, "audioAvailable": row["upload_id"] is not None, "analysis": analysis, "analysisVersion": row["analysis_version"], "analysisHash": row["analysis_hash"], "sourceHash": row["source_hash"], "submittedAt": now_stamp(row["created"]), "late": assignment["due"] is not None and row["created"] > assignment["due"]}

    def list_submissions(self, user_id, assignment_id):
        with self.connect() as db:
            assignment = self.assignment(db, user_id, assignment_id)
            rows = db.execute("SELECT * FROM submissions WHERE assignment_id=? ORDER BY created DESC,id", (assignment_id,)) if assignment["creator"] == user_id else db.execute("SELECT * FROM submissions WHERE assignment_id=? AND user_id=? ORDER BY created DESC,id", (assignment_id, user_id))
            return [self.submission_meta(db, row) for row in rows]

    def submission_audio(self, user_id, submission_id):
        with self.connect() as db:
            row = self.visible_submission(db, user_id, submission_id)
            if not row["upload_id"]:
                raise APIError(404, "作业录音不存在。")
            upload = db.execute("SELECT * FROM uploads WHERE id=? AND complete=1", (row["upload_id"],)).fetchone()
            if not upload:
                raise APIError(404, "作业录音不存在。")
            return self.recording_path(upload["id"]), upload["mime"], upload["size"]

    def visible_submission(self, db, user_id, submission_id):
        row = db.execute("SELECT s.*,c.creator FROM submissions s JOIN assignments a ON a.id=s.assignment_id JOIN courses c ON c.id=a.course_id WHERE s.id=?", (uid(submission_id),)).fetchone()
        if not row or user_id not in {row["user_id"], row["creator"]}:
            raise APIError(404, "作业记录不存在。")
        return row

    def submission_xml(self, user_id, submission_id):
        with self.connect() as db:
            row = self.visible_submission(db, user_id, submission_id)
            history = db.execute("SELECT score_xml,score_sha256 FROM history WHERE user_id=? AND event_id=?", (row["user_id"], row["event_id"])).fetchone()
            if not history or history["score_xml"] is None:
                raise APIError(503, "作业原谱快照不可用。")
            return history["score_xml"], history["score_sha256"]


class RateLimit:
    def __init__(self, clock=time.monotonic):
        self.clock, self.lock, self.buckets = clock, threading.Lock(), {}

    def check(self, key, limit, window):
        moment = self.clock()
        with self.lock:
            if len(self.buckets) >= 8192:
                self.buckets = {k: v for k, v in self.buckets.items() if v and v[-1] > moment - 3600}
                if key not in self.buckets and len(self.buckets) >= 8192:
                    raise APIError(429, "请求过于频繁，请稍后重试。")
            values = [v for v in self.buckets.get(key, []) if v > moment - window]
            if len(values) >= limit:
                raise APIError(429, "请求过于频繁，请稍后重试。")
            values.append(moment)
            self.buckets[key] = values


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, store, origin, internal_key=None):
        if address[0] != "127.0.0.1":
            raise ValueError("服务必须只监听 127.0.0.1。")
        parsed = urlsplit(origin)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("必须配置无路径的 HTTPS public-origin。")
        self.origin, self.authority, self.store = origin.rstrip("/"), parsed.netloc.lower(), store
        self.practice_analysis = from_environment(store)
        with store.connect() as db:
            store.install_analysis_guards(db)
        self.internal_key = internal_key
        if internal_key is not None:
            token_hash(internal_key)
        self.limiter, self.capacity = RateLimit(), threading.BoundedSemaphore(16)
        super().__init__(address, Handler)
        self.deletion_stop = threading.Event()
        self.deletion_thread = threading.Thread(target=self.retry_deletions, daemon=True)
        self.deletion_thread.start()

    def retry_deletions(self):
        while not self.deletion_stop.is_set():
            try:
                self.store.process_deletions()
            except (sqlite3.Error, OSError, APIError):
                pass
            self.deletion_stop.wait(15)

    def server_close(self):
        self.deletion_stop.set()
        super().server_close()
        self.deletion_thread.join(timeout=1)

    def process_request(self, request, address):
        if not self.capacity.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
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
    server_version, sys_version = "NoteLiteAccount/1", ""

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, *_):
        # No URL, usernames, body, password, cookies, bearer or course code logs.
        pass

    def respond(self, status, value, extra=(), content_type="application/json; charset=utf-8"):
        data = value.encode("utf8") if isinstance(value, str) else json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if self.close_connection:
            self.send_header("Connection", "close")
        if status in {429, 503}:
            self.send_header("Retry-After", "60" if status == 429 else "5")
        for key, value in extra:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def body(self, maximum=MAX_BODY):
        if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Encoding"):
            raise APIError(400, "请提供原始 JSON 请求体。")
        values = self.headers.get_all("Content-Length", [])
        if len(values) != 1 or not re.fullmatch(r"[0-9]{1,10}", values[0]):
            raise APIError(411, "需要准确的 Content-Length。")
        size = int(values[0])
        if not 0 < size <= maximum:
            raise APIError(413, "请求超过大小限制。")
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise APIError(415, "请求须使用 application/json。")
        self._body_started = True
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise APIError(400, "请求体未完整传输。")
        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate field")
                result[key] = value
            return result
        try:
            value = json.loads(raw.decode("utf8"), object_pairs_hook=unique_pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError, UnicodeError, RecursionError) as error:
            raise APIError(400, "JSON 无效。") from error
        if not isinstance(value, dict):
            raise APIError(400, "请求须为 JSON 对象。")
        return value

    def validate_origin(self):
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0].lower() not in {self.server.authority, f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}:
            raise APIError(403, "请求地址无效。")
        origins = self.headers.get_all("Origin", [])
        if len(origins) > 1 or origins and origins[0] != self.server.origin or self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise APIError(403, "请求来源无效。")

    def identity(self):
        authorizations = self.headers.get_all("Authorization", [])
        if authorizations:
            if len(authorizations) != 1 or not authorizations[0].startswith("Bearer "):
                raise APIError(401, "登录凭据无效。")
            return self.server.store.authenticate(authorizations[0][7:], "native")
        cookies = self.headers.get_all("Cookie", [])
        if len(cookies) != 1:
            raise APIError(401, "请先登录。")
        try:
            cookie = SimpleCookie()
            cookie.load(cookies[0])
            token = cookie[COOKIE].value if COOKIE in cookie else ""
        except CookieError:
            token = ""
        identity = self.server.store.authenticate(token, "browser")
        identity["request_csrf"] = csrf_value(token)
        if self.command in WRITES:
            csrf = self.headers.get_all("X-NoteLite-CSRF", [])
            if self.headers.get("Origin") != self.server.origin or len(csrf) != 1:
                raise APIError(403, "保存前请重新加载登录状态。")
            try:
                valid = hmac.compare_digest(token_hash(csrf[0]), identity["csrf_hash"])
            except APIError:
                valid = False
            if not valid:
                raise APIError(403, "保存前请重新加载登录状态。")
        return identity

    def login_response(self, value):
        headers = []
        if value["kind"] == "browser":
            headers.append(("Set-Cookie", COOKIE + "=" + value.pop("token") + "; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=2592000"))
        else:
            value.pop("csrf")
        self.respond(201, value, headers)

    def internal(self, path):
        # nginx MUST deny /internal/. Header is server-only, never a client token.
        keys = self.headers.get_all("X-NoteLite-Internal-Key", [])
        if self.command != "POST" or not self.server.internal_key or len(keys) != 1 or not hmac.compare_digest(keys[0], self.server.internal_key):
            raise APIError(404, "接口不存在。")
        data = self.body(4096)
        if path == "/internal/account/resolve":
            fields(data, {"token", "kind"}, {"token", "kind"})
            if not isinstance(data["kind"], str) or data["kind"] not in {"browser", "native"}:
                raise APIError(401, "登录凭据无效。")
            session = self.server.store.authenticate(data["token"], data["kind"])
            self.respond(200, {"owner": session["user_id"], "sessionId": session["id"], "kind": session["kind"], "csrfHash": session["csrf_hash"], "expiresAt": now_stamp(session["expires"])})
            return
        raise APIError(404, "接口不存在。")

    def dispatch(self):
        self.validate_origin()
        target = urlsplit(self.path)
        if target.scheme or target.netloc or target.fragment or "%" in target.path or "\\" in target.path:
            raise APIError(404, "接口不存在。")
        query = parse_qs(target.query, keep_blank_values=True)
        if any(len(v) != 1 for v in query.values()):
            raise APIError(400, "查询参数重复。")
        path = target.path
        if path.startswith("/internal/") and not query:
            return self.internal(path)
        if not path.startswith(PREFIX + "/"):
            raise APIError(404, "接口不存在。")
        route = path[len(PREFIX):]
        source = self.headers.get("X-Real-IP", self.client_address[0])[:128]
        if route == "/health" and self.command == "GET" and not query:
            self.respond(200, {"status": "ok", "authentication": "account-scoped", "listeningConnected": False, "omrOwnershipHook": self.server.store.omr_import is not None})
            return
        if route in {"/register", "/login"} and self.command == "POST" and not query:
            self.server.limiter.check((route, source), 6 if route == "/register" else 12, 3600 if route == "/register" else 60)
            data = self.body(4096)
            if data.get("mode", "browser") == "browser" and self.headers.get("Origin") != self.server.origin:
                raise APIError(403, "请在应用的 HTTPS 页面登录。")
            if route == "/login":
                self.server.limiter.check(("login-name", source, str(data.get("username", "")).lower()[:32]), 10, 900)
            self.login_response(self.server.store.register(data) if route == "/register" else self.server.store.login(data))
            return
        session = self.identity()
        with self.server.store.owner_scope(session["user_id"]):
            return self.protected_dispatch(route, query, session, source)

    def protected_dispatch(self, route, query, session, source):
        user_id, store = session["user_id"], self.server.store
        with store.connect():
            pass  # Recheck a previously authenticated request after deletion.
        expected = self.headers.get_all("X-NoteLite-Expected-User", [])
        if expected:
            if len(expected) != 1:
                raise APIError(400, "账户一致性字段重复。")
            if not hmac.compare_digest(expected[0], user_id):
                raise APIError(409, "登录账户已改变，请重新载入后操作。")
        self.server.limiter.check(("user", user_id), 120, 60)
        if route == "/practice-analysis" and self.command == "POST" and not query:
            data = self.body(16384)
            fields(data, {"requestId", "eventIds"}, {"requestId"})
            if self.server.practice_analysis is None:
                raise APIError(503, "AI 分析服务尚未配置。")
            try:
                self.respond(200, self.server.practice_analysis.analyse(user_id, data["requestId"], data.get("eventIds")))
            except AnalysisError as error:
                raise APIError(error.status, error.message) from None
            return
        if self.command == "GET" and route == "/me" and not query:
            self.respond(200, store.identity(session, session.get("request_csrf")))
            return
        if route == "/profile" and not query:
            if self.command == "GET":
                result = store.read_profile(user_id)
                self.respond(200, result, [("ETag", result["etag"])])
                return
            if self.command == "PUT":
                etags = self.headers.get_all("If-Match", [])
                if len(etags) != 1 or not etags[0] or len(etags[0]) > 80:
                    raise APIError(428, "保存必须提供 If-Match 个人设置版本。")
                result = store.update_profile(user_id, self.body(MAX_PROFILE), etags[0])
                self.respond(200, result, [("ETag", result["etag"])])
                return
        if route == "/account/export" and self.command == "GET" and not query:
            self.server.limiter.check(("account-export", user_id), 6, 3600)
            self.respond(200, store.export_account(user_id), [("Content-Disposition", 'attachment; filename="notelite-account.json"')])
            return
        if self.command == "GET" and route == "/sessions" and not query:
            self.respond(200, {"sessions": store.session_list(user_id)})
            return
        if self.command == "DELETE" and route == "/account" and not query:
            self.server.limiter.check(("account-delete", user_id), 6, 3600)
            self.server.limiter.check(("account-delete-ip", source), 20, 3600)
            result = store.request_deletion(user_id, session["id"], self.body(4096))
            self.respond(200 if result["deleted"] else 202, result, [("Set-Cookie", COOKIE + "=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0")])
            return
        if self.command == "POST" and route == "/logout" and not query:
            store.revoke(user_id, session["id"])
            self.respond(200, {"authenticated": False}, [("Set-Cookie", COOKIE + "=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0")])
            return
        match = re.fullmatch(r"/sessions/(" + UUID + ")", route)
        if match and self.command == "DELETE" and not query:
            store.revoke(user_id, match[1])
            self.respond(200, {"revoked": True})
            return
        if self.command == "GET" and route == "/catalog" and not query:
            self.respond(200, {"scores": store.catalog()})
            return
        match = re.fullmatch(r"/catalog/([A-Za-z0-9_-]{1,80})/musicxml", route)
        if match and self.command == "GET" and not query:
            self.respond(200, store.official_xml(match[1]), content_type="application/vnd.recordare.musicxml+xml; charset=utf-8")
            return
        if route == "/scores" and not query:
            if self.command == "GET":
                self.respond(200, {"scores": store.list_scores(user_id)})
                return
            if self.command == "POST":
                result = store.create_score(user_id, self.body())
                self.respond(200 if result["duplicate"] else 201, result)
                return
        match = re.fullmatch(r"/scores/(" + UUID + r")(?:/(musicxml))?", route)
        if match and not query:
            if self.command == "GET":
                metadata, xml = store.read_score(user_id, match[1])
                self.respond(200, xml if match[2] else metadata, [("ETag", metadata["etag"])], "application/vnd.recordare.musicxml+xml; charset=utf-8" if match[2] else "application/json; charset=utf-8")
                return
            if self.command == "PUT" and not match[2]:
                etags = self.headers.get_all("If-Match", [])
                if len(etags) != 1:
                    raise APIError(428, "保存必须提供 If-Match 曲谱版本。")
                result = store.update_score(user_id, match[1], self.body(), etags[0])
                self.respond(200, result, [("ETag", result["etag"])])
                return
        if route == "/history":
            if self.command == "POST" and not query:
                result = store.add_history(user_id, self.body(1024 * 1024 + 4096))
                self.respond(200 if result["duplicate"] else 201, result)
                return
            if self.command == "GET" and not set(query) - {"limit", "cursor"}:
                try:
                    limit = int(query.get("limit", ["100"])[0])
                    integer(limit, "查询条数", 1, 200)
                    before = None
                    if "cursor" in query:
                        moment, event_id = query["cursor"][0].split(":", 1)
                        moment = float(moment)
                        if not math.isfinite(moment) or moment < 0:
                            raise ValueError()
                        before = (moment, uid(event_id))
                except ValueError as error:
                    raise APIError(400, "历史分页参数无效。") from error
                self.respond(200, store.list_history(user_id, limit, before))
                return
        match = re.fullmatch(r"/history/(" + UUID + r")/musicxml", route)
        if match and self.command == "GET" and not query:
            xml, sha = store.history_xml(user_id, match[1])
            self.respond(200, xml, [("ETag", '"' + sha + '"')], "application/vnd.recordare.musicxml+xml; charset=utf-8")
            return
        match = re.fullmatch(r"/history/(" + UUID + r")/analyses(?:/([1-9][0-9]{0,9}))?", route)
        if match and not query:
            if self.command == "GET":
                result = store.read_history_analysis(user_id, match[1], int(match[2])) if match[2] else store.list_history_analyses(user_id, match[1])
                self.respond(200, result)
                return
            if self.command == "POST" and not match[2]:
                result = store.add_history_analysis(user_id, match[1], self.body(MAX_ANALYSIS + 4096))
                self.respond(200 if result["duplicate"] else 201, result)
                return
        if route == "/courses" and not query:
            if self.command == "POST":
                self.respond(201, store.create_course(user_id, self.body(4096)))
                return
            if self.command == "GET":
                self.respond(200, {"courses": store.list_courses(user_id)})
                return
        if route in {"/course-codes/join", "/course-codes/preview"} and self.command == "POST" and not query:
            # Six-character UI code has 30 bits. Both limits apply to preview and
            # join together; neither endpoint may become an unlimited oracle.
            self.server.limiter.check(("course-code", user_id), 6, 60)
            self.server.limiter.check(("course-code-ip", source), 20, 60)
            data = self.body(4096)
            self.respond(200, store.join_course(user_id, data) if route.endswith("/join") else store.preview_code(data))
            return
        match = re.fullmatch(r"/courses/(" + UUID + r")/(membership|roster|assignments)", route)
        if match and not query:
            if match[2] == "membership" and self.command == "DELETE":
                self.respond(200, store.leave_course(user_id, match[1]))
                return
            if match[2] == "roster" and self.command == "GET":
                self.respond(200, {"students": store.roster(user_id, match[1])})
                return
            if match[2] == "assignments" and self.command == "GET":
                self.respond(200, {"assignments": store.list_assignments(user_id, match[1])})
                return
            if match[2] == "assignments" and self.command == "POST":
                self.respond(201, store.create_assignment(user_id, match[1], self.body(8192)))
                return
        match = re.fullmatch(r"/assignments/(" + UUID + r")/submissions", route)
        if match and not query:
            if self.command == "GET":
                self.respond(200, {"submissions": store.list_submissions(user_id, match[1])})
                return
            if self.command == "POST":
                result = store.submit(user_id, match[1], self.body(1024 * 1024 + 4096))
                self.respond(200 if result["duplicate"] else 201, result)
                return
        if route == "/uploads" and self.command == "POST" and not query:
            self.respond(201, store.create_upload(user_id, self.body(4096)))
            return
        match = re.fullmatch(r"/uploads/(" + UUID + r")(?:/(complete))?", route)
        if match and not query:
            if self.command == "GET" and not match[2]:
                with store.connect() as db:
                    row = store.get_upload(db, user_id, match[1])
                    store.assignment(db, user_id, row["assignment_id"], student=True)
                    result = store.upload_meta(row)
                self.respond(200, result)
                return
            if self.command == "POST" and match[2] == "complete":
                self.respond(200, store.complete_upload(user_id, match[1]))
                return
            if self.command == "PUT" and not match[2]:
                offsets = self.headers.get_all("Upload-Offset", [])
                if len(offsets) != 1 or not re.fullmatch(r"[0-9]{1,12}", offsets[0]):
                    raise APIError(400, "录音分块须提供 Upload-Offset。")
                self.respond(200, store.append_upload(user_id, match[1], int(offsets[0]), self.raw_audio()))
                return
        match = re.fullmatch(r"/submissions/(" + UUID + r")(?:/(audio|musicxml))?", route)
        if match and self.command == "GET" and not query:
            if not match[2]:
                with store.connect() as db:
                    value = store.submission_meta(db, store.visible_submission(db, user_id, match[1]))
                self.respond(200, value)
                return
            if match[2] == "musicxml":
                xml, sha = store.submission_xml(user_id, match[1])
                self.respond(200, xml, [("ETag", '"' + sha + '"')], "application/vnd.recordare.musicxml+xml; charset=utf-8")
                return
            path, mime, size = store.submission_audio(user_id, match[1])
            ranges = self.headers.get_all("Range", [])
            start, end, status = 0, size - 1, 200
            if ranges:
                if len(ranges) != 1:
                    raise APIError(416, "录音读取范围无效。")
                span = re.fullmatch(r"bytes=([0-9]*)-([0-9]*)", ranges[0])
                if not span or not (span[1] or span[2]):
                    raise APIError(416, "录音读取范围无效。")
                if span[1]:
                    start, end = int(span[1]), min(size - 1, int(span[2])) if span[2] else size - 1
                else:
                    start = max(0, size - int(span[2]))
                if start > end or start >= size:
                    raise APIError(416, "录音读取范围无效。")
                status = 206
            with path.open("rb") as recording:
                self.send_response(status)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(end - start + 1))
                self.send_header("Accept-Ranges", "bytes")
                if status == 206:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Content-Disposition", 'attachment; filename="homework-recording.' + {"audio/wav": "wav", "audio/mpeg": "mp3", "audio/ogg": "ogg", "audio/mp4": "m4a"}[mime] + '"')
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                recording.seek(start)
                remaining = end - start + 1
                while remaining and (chunk := recording.read(min(64 * 1024, remaining))):
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            return
        match = re.fullmatch(r"/courses/(" + UUID + r")(?:/(scores|codes)(?:/([0-9a-f]{64}))?)?", route)
        if match and not query:
            if self.command == "GET" and not match[2]:
                with store.connect() as db:
                    result = store.course_detail(db, user_id, match[1])
                self.respond(200, result)
                return
            if self.command == "POST" and match[2] in {"scores", "codes"} and not match[3]:
                data = self.body(4096)
                self.respond(201, store.add_course_score(user_id, match[1], data) if match[2] == "scores" else store.create_code(user_id, match[1], data))
                return
            if self.command == "DELETE" and match[2] == "codes" and match[3]:
                store.revoke_code(user_id, match[1], match[3])
                self.respond(200, {"revoked": True})
                return
        if route == "/legacy/claim" and self.command == "POST" and not query:
            data = self.body(4096)
            fields(data, {"deviceToken", "deviceKind", "deviceCSRF"}, {"deviceToken", "deviceKind"})
            if store.legacy_claim is None:
                raise APIError(503, "双重认证迁移适配器尚未配置。")
            if not isinstance(data["deviceKind"], str) or data["deviceKind"] not in {"native", "browser"}:
                raise APIError(400, "旧设备凭据类型无效。")
            token_hash(data["deviceToken"])
            # Adapter verifies BOTH existing device + account, CSRF for browser,
            # migrates jobs atomically, revokes/rotates old principals, audits counts.
            # Keep the account lock across migration; deletion cannot commit
            # between active-owner validation and the gateway ownership transfer.
            with store.connect():
                result = store.legacy_claim(user_id, data, self.headers.get("Origin"))
            self.respond(200, result)
            return
        raise APIError(404, "接口不存在。")

    def raw_audio(self):
        if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Encoding"):
            raise APIError(400, "请提供原始二进制录音分块。")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,10}", lengths[0]):
            raise APIError(411, "需要准确的 Content-Length。")
        size = int(lengths[0])
        if not 1 <= size <= MAX_CHUNK:
            raise APIError(413, "录音分块须为 1 至 8 MiB。")
        if self.headers.get("Content-Type") != "application/octet-stream":
            raise APIError(415, "录音分块须为 application/octet-stream。")
        self._body_started = True
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise APIError(400, "录音分块未完整传输。")
        return raw

    def discard_rejected_body(self):
        # Closing with a small unread request body can reset TCP and hide the
        # error response (RFC 9112 section 9.6). Never parse or authorize it.
        if getattr(self, "_body_started", False) or self.headers.get("Transfer-Encoding") or self.headers.get("Expect"):
            return 0
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,10}", lengths[0]):
            return 0
        remaining = size = int(lengths[0])
        if not 0 < size <= MAX_REJECT_DRAIN:
            return 0
        self._body_started = True
        deadline, previous_timeout = time.monotonic() + REJECT_DRAIN_SECONDS, self.connection.gettimeout()
        try:
            while remaining:
                available = deadline - time.monotonic()
                if available <= 0:
                    break
                self.connection.settimeout(available)
                chunk = self.rfile.read1(remaining)
                if not chunk:
                    break
                remaining -= len(chunk)
        except (OSError, ValueError):
            pass
        finally:
            self.connection.settimeout(previous_timeout)
        return size - remaining

    def handle_api(self):
        self._body_started = False
        try:
            self.dispatch()
        except APIError as error:
            self.close_connection = True
            self.discard_rejected_body()
            self.respond(error.status, {"error": error.message})
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception:
            # Never echo upstream exception, body, password or private path.
            self.close_connection = True
            self.respond(500, {"error": "服务暂时无法完成请求。"})

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = handle_api


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--port", type=int, default=8771)
    parser.add_argument("--public-origin", required=True)
    parser.add_argument("--internal-key-file")
    parser.add_argument("--max-recording-mb", type=int, default=100)
    parser.add_argument("--recording-quota-mb", type=int, default=1024)
    parser.add_argument("--disk-reserve-mb", type=int, default=256)
    args = parser.parse_args()
    key = Path(args.internal_key_file).read_text(encoding="ascii").strip() if args.internal_key_file else None
    if not 1 <= args.max_recording_mb <= 1024 or not args.max_recording_mb <= args.recording_quota_mb <= 102400 or not 64 <= args.disk_reserve_mb <= 102400:
        parser.error("录音限额无效。")
    server = Server(("127.0.0.1", args.port), Store(args.root, max_recording=args.max_recording_mb * 1024 ** 2, recording_quota=args.recording_quota_mb * 1024 ** 2, disk_reserve=args.disk_reserve_mb * 1024 ** 2), args.public_origin, key)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
