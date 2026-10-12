#!/usr/bin/env python3
"""Independent local Audiveris job API. Python standard library, no practice engine.

Job reservation, bearer authentication and worker design were adapted from
NoteLite bridge/notelite_bridge.py (AGPL-3.0-or-later). MusicXML edits publish an
immutable revision only after the independent original MIDI exporter succeeds.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import logging
import math
import mimetypes
import os
from pathlib import Path, PurePosixPath
import queue
import re
import secrets
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import threading
import time
from urllib.parse import parse_qs, quote, unquote, urlsplit
import uuid
import xml.etree.ElementTree as ET
import zipfile

MAX_UPLOAD = 32 * 1024 * 1024
MAX_XML = 10 * 1024 * 1024
MAX_EDITS = 200
INPUT_TYPES = {".pdf", ".png", ".jpg", ".jpeg", ".musicxml", ".xml", ".mxl"}
LOG = logging.getLogger("notelite.omr")
ORDER = {name: n for n, name in enumerate(("grace", "cue", "chord", "pitch", "unpitched", "rest", "duration", "tie", "instrument", "footnote", "level", "voice", "type", "dot", "accidental", "time-modification", "stem", "notehead", "notehead-text", "staff", "beam", "notations", "lyric", "play", "listen"))}
NOTE_TYPES = {"maxima", "long", "breve", "whole", "half", "quarter", "eighth", "16th", "32nd", "64th", "128th", "256th", "512th", "1024th"}


class APIError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message
        super().__init__(message)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def tag(element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def children(element, name):
    return [child for child in element if tag(child) == name]


def text(element, name, default=""):
    items = children(element, name)
    return items[0].text or default if items else default


def numeric(value, name: str, minimum=0, maximum=1_000_000_000, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= value <= maximum or not math.isfinite(value) or integer and value != int(value):
        raise APIError(400, f"{name} 无效。")
    return int(value) if integer or value == int(value) else value


def filename_extension(filename: str) -> str:
    if not isinstance(filename, str) or not filename or len(filename) > 255 or filename[-1] in ". " or any(c in filename for c in '/\\:') or any(ord(c) < 32 or ord(c) == 127 for c in filename):
        raise APIError(400, "请提供不含目录的文件名。")
    extension = Path(filename).suffix.lower()
    if extension not in INPUT_TYPES:
        raise APIError(415, "支持 PDF、PNG、JPEG、MusicXML 和 MXL。")
    return extension


def safe_xml(data: bytes, *, score=True):
    if not data or len(data) > MAX_XML:
        raise APIError(413, "MusicXML 必须在 10 MiB 以内。")
    try:
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            decoded = data.decode("utf-16")
        elif data.startswith(b"<\x00"):
            decoded = data.decode("utf-16-le")
        elif data.startswith(b"\x00<"):
            decoded = data.decode("utf-16-be")
        else:
            declaration = re.search(br'<\?xml[^>]*encoding\s*=\s*[\'"]([^\'"]+)', data[:300], re.I)
            encoding = declaration.group(1).decode("ascii").lower() if declaration else "utf-8-sig"
            if encoding not in {"utf-8", "utf-8-sig", "ascii", "us-ascii", "iso-8859-1", "latin-1"}:
                raise APIError(400, "请使用 UTF-8 或 UTF-16 MusicXML。")
            decoded = data.decode(encoding)
        if "\x00" in decoded or re.search(r"<!\s*ENTITY\b", decoded, re.I):
            raise APIError(400, "XML 不允许实体声明。")
        for declaration in re.findall(r"<!DOCTYPE\b.*?>", decoded, re.I | re.S):
            if "[" in declaration or "]" in declaration:
                raise APIError(400, "XML 不允许内部 DTD。")
        # ElementTree/Expat does not fetch an external MusicXML SYSTEM DTD.
        root = ET.fromstring(data)
    except (UnicodeError, LookupError, ET.ParseError) as error:
        raise APIError(400, "MusicXML 格式无效。") from error
    if score and tag(root) != "score-partwise":
        raise APIError(415, "目前支持 score-partwise MusicXML。")
    count = 0
    pending = [(root, 0)]
    while pending:
        element, depth = pending.pop()
        count += 1
        if count > 200_000 or depth > 128:
            raise APIError(413, "XML 结构超出解析限制。")
        pending.extend((child, depth + 1) for child in element)
    if score:
        parts = children(root, "part")
        ids = [part.get("id") for part in parts]
        if not parts or len(parts) > 256 or any(not value for value in ids) or len(set(ids)) != len(ids):
            raise APIError(400, "MusicXML 声部 ID 无效。")
    return root


def serialize(root) -> bytes:
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def mxl_scores(path: Path) -> list[tuple[str, bytes]]:
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > 256 or sum(item.file_size for item in entries) > 64 * 1024 * 1024:
                raise APIError(413, "MXL 解压内容超出限制。")
            names = set()
            for item in entries:
                name = item.filename
                parts = PurePosixPath(name).parts
                if not name or name.startswith("/") or "\\" in name or ":" in name or ".." in parts or any(ord(c) < 32 for c in name) or name in names or stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1:
                    raise APIError(400, "MXL 包含不安全或重复的文件路径。")
                names.add(name)
            if "META-INF/container.xml" in names:
                container = archive.getinfo("META-INF/container.xml")
                if container.file_size > 128 * 1024:
                    raise APIError(413, "MXL 容器描述过大。")
                root = safe_xml(archive.read(container), score=False)
                roots = [node.get("full-path") for node in root.iter() if tag(node) == "rootfile" and node.get("full-path")]
                if not roots:
                    raise APIError(400, "MXL 容器没有 MusicXML 入口。")
            else:
                roots = [item.filename for item in entries if not item.is_dir() and item.filename.lower().endswith((".xml", ".musicxml")) and not item.filename.startswith("META-INF/")]
                if len(roots) != 1:
                    raise APIError(400, "MXL 缺少明确的 MusicXML 入口。")
            if len(roots) > 64 or len(set(roots)) != len(roots):
                raise APIError(413, "MXL 乐章入口数量超限或重复。")
            results = []
            for selected in roots:
                if selected not in names or archive.getinfo(selected).is_dir():
                    raise APIError(400, "MXL 的 MusicXML 入口无效。")
                entry = archive.getinfo(selected)
                if entry.file_size > MAX_XML:
                    raise APIError(413, "MXL 中 MusicXML 必须在 10 MiB 以内。")
                with archive.open(entry) as stream:
                    data = stream.read(MAX_XML + 1)
                # Every declared movement is checked, even if it is not selected.
                safe_xml(data)
                results.append((PurePosixPath(selected).stem, data))
            return results
    except (zipfile.BadZipFile, KeyError, OSError, RuntimeError, NotImplementedError) as error:
        raise APIError(400, "MXL 压缩文件无效。") from error


def mxl_xml(path: Path) -> bytes:
    scores = mxl_scores(path)
    if len(scores) != 1:
        raise APIError(400, "这是多乐章 MXL，请通过全部乐章接口读取。")
    return scores[0][1]


def source_xml(path: Path) -> bytes:
    if path.suffix.lower() == ".mxl":
        return mxl_xml(path)
    data = path.read_bytes()
    return serialize(safe_xml(data))


def source_scores(path: Path, name: str | None = None) -> list[tuple[str, bytes]]:
    if path.suffix.lower() == ".mxl":
        scores = mxl_scores(path)
        return [(name or path.stem, scores[0][1])] if len(scores) == 1 else scores
    return [(name or path.stem, source_xml(path))]


def natural_key(path: Path):
    return [int(value) if value.isdigit() else value.lower() for value in re.split(r"([0-9]+)", path.as_posix())]


def validate_input(path: Path, extension: str):
    with path.open("rb") as stream:
        head = stream.read(32)
    if extension in {".xml", ".musicxml", ".mxl"}:
        source_scores(path)
    elif extension == ".pdf" and not head.startswith(b"%PDF-") or extension == ".png" and not head.startswith(b"\x89PNG\r\n\x1a\n") or extension in {".jpg", ".jpeg"} and not head.startswith(b"\xff\xd8\xff"):
        raise APIError(415, "文件内容与扩展名不一致。")
    if extension == ".png" and len(head) >= 24:
        width, height = int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
        if not width or not height or width * height > 100_000_000:
            raise APIError(413, "PNG 尺寸超出限制。")


def argv_setting(name: str, default: list[str]) -> list[str]:
    value = os.environ.get(name)
    args = json.loads(value) if value and value.lstrip().startswith("[") else shlex.split(value) if value else default
    if not isinstance(args, list) or not args or any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in args):
        raise ValueError(f"{name} 必须是命令参数数组或命令前缀。")
    return args


def stop_process_group(process):
    """Stop the entire private engine group, including descendants after parent exit."""
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        elif process.poll() is None:
            process.terminate()
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass
    # The leader can exit before descendants. Always kill the group on POSIX.
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        elif process.poll() is None:
            process.kill()
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired as error:
        raise APIError(503, "识谱子进程尚未结束，请稍后重试清理。") from error


class JobCancellation:
    def __init__(self):
        self.event = threading.Event()
        self.lock = threading.RLock()
        self.process = None

    def check(self):
        if self.event.is_set():
            raise APIError(410, "任务已取消。")

    def attach(self, process):
        with self.lock:
            self.process = process
            if self.event.is_set():
                stop_process_group(process)
                self.check()

    def detach(self, process):
        with self.lock:
            if self.process is process:
                self.process = None

    def cancel(self):
        self.event.set()
        with self.lock:
            if self.process is not None:
                stop_process_group(self.process)


def run_command(command, cwd: Path, log: Path, timeout: float, title: str, cancellation=None):
    if cancellation:
        cancellation.check()
    with log.open("ab") as output:
        output.write(f"\n[{now()}] {title}\n".encode())
        output.flush()
        try:
            process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, shell=False, start_new_session=os.name == "posix")
        except OSError as error:
            raise APIError(503, f"{title}尚未安装或不能启动。") from error
        try:
            if cancellation:
                cancellation.attach(process)
            deadline = time.monotonic() + timeout
            while True:
                if cancellation:
                    cancellation.check()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                try:
                    code = process.wait(timeout=min(.2, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
        except subprocess.TimeoutExpired as error:
            stop_process_group(process)
            raise APIError(504, f"{title}超时；请查看任务日志。") from error
        except BaseException:
            stop_process_group(process)
            raise
        finally:
            # A successful leader may leave descendants; no engine group is
            # allowed to keep writing after the command has returned.
            stop_process_group(process)
            if cancellation:
                cancellation.detach(process)
        if cancellation:
            cancellation.check()
        if code != 0:
            raise APIError(422, f"{title}返回 {code}；请查看任务日志。")


def warnings_from(log: Path):
    if not log.is_file():
        return []
    with log.open("rb") as stream:
        stream.seek(max(0, log.stat().st_size - 1024 * 1024))
        lines = stream.read().decode("utf8", errors="replace").splitlines()
    return list(dict.fromkeys(line[:700] for line in lines if re.search(r"\bWARN(?:ING)?\b|\bERROR\b|\bSEVERE\b", line, re.I)))[-60:]


def note_listing(data: bytes):
    root = safe_xml(data)
    names = {node.get("id"): text(node, "part-name", node.get("id", "")) for part_list in children(root, "part-list") for node in children(part_list, "score-part")}
    parts, notes = [], []
    for part in children(root, "part"):
        part_id, divisions, ordinal = part.get("id"), 1, 0
        parts.append({"id": part_id, "name": names.get(part_id, part_id)})
        for mi, measure in enumerate(children(part, "measure")):
            ni = 0
            for item in measure:
                if tag(item) == "attributes":
                    try:
                        divisions = float(text(item, "divisions", divisions))
                    except (TypeError, ValueError):
                        raise APIError(400, "MusicXML divisions 无效。") from None
                    if not math.isfinite(divisions) or divisions <= 0:
                        raise APIError(400, "MusicXML divisions 无效。")
                if tag(item) != "note":
                    continue
                pitches = children(item, "pitch")
                pitch = None
                if pitches:
                    p = pitches[0]
                    try:
                        pitch = {"step": text(p, "step"), "alter": float(text(p, "alter", "0")), "octave": int(text(p, "octave"))}
                    except ValueError:
                        raise APIError(400, "MusicXML 音高无效。") from None
                try:
                    duration = float(text(item, "duration", "0"))
                except ValueError:
                    raise APIError(400, "MusicXML duration 无效。") from None
                if not math.isfinite(duration) or duration < 0 or pitch and not math.isfinite(pitch["alter"]):
                    raise APIError(400, "MusicXML 音符数值无效。")
                notes.append({"partId": part_id, "measureIndex": mi, "noteIndex": ni, "measure": measure.get("number", str(mi + 1)), "sourceNoteId": f"{part_id}:{ordinal}", "divisions": divisions, "duration": duration, "type": text(item, "type"), "dot": len(children(item, "dot")), "rest": bool(children(item, "rest")), "pitch": pitch, "voice": text(item, "voice", "1"), "staff": text(item, "staff", "1"), "chord": bool(children(item, "chord")), "grace": bool(children(item, "grace")), "ties": [node.get("type") for node in children(item, "tie")]})
                ni += 1
                ordinal += 1
    return {"parts": parts, "notes": notes}


def apply_edits(data: bytes, edits: list) -> bytes:
    if not isinstance(edits, list) or not 1 <= len(edits) <= MAX_EDITS:
        raise APIError(400, "请提供 1 到 200 项音符修改。")
    root = safe_xml(data)
    targets, seen = [], set()
    parts = {part.get("id"): part for part in children(root, "part")}
    # Resolve all indices against the same pre-edit XML, including deletions.
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) - {"partId", "measureIndex", "noteIndex", "pitch", "step", "alter", "octave", "duration", "type", "dot", "rest", "delete"}:
            raise APIError(400, "音符修改字段无效。")
        if not isinstance(edit.get("partId"), str):
            raise APIError(400, "partId 必须是声部标识。")
        key = (edit.get("partId"), numeric(edit.get("measureIndex"), "measureIndex", integer=True), numeric(edit.get("noteIndex"), "noteIndex", integer=True))
        if key in seen or key[0] not in parts:
            raise APIError(400, "音符定位重复或声部不存在。")
        seen.add(key)
        try:
            measure = children(parts[key[0]], "measure")[key[1]]
            note = children(measure, "note")[key[2]]
        except IndexError:
            raise APIError(400, "音符位置不存在。") from None
        targets.append((measure, note, edit))
    for measure, note, edit in targets:
        ns = note.tag[:-4] if note.tag.endswith("note") else ""
        def remove(name):
            for element in children(note, name):
                note.remove(element)
        def set_value(name, value=None):
            remove(name)
            element = ET.Element(ns + name)
            element.text = str(value) if value is not None else None
            order = ORDER.get(name, 100)
            insertion = next((i for i, child in enumerate(note) if ORDER.get(tag(child), 100) > order), len(note))
            note.insert(insertion, element)
            return element
        for field in ("rest", "delete"):
            if field in edit and not isinstance(edit[field], bool):
                raise APIError(400, f"{field} 必须是布尔值。")
        if edit.get("delete"):
            note_children = children(measure, "note")
            position = note_children.index(note)
            # If the base of a chord is deleted, its first surviving tone becomes base.
            if not children(note, "chord") and position + 1 < len(note_children) and children(note_children[position + 1], "chord"):
                following = note_children[position + 1]
                for element in children(following, "chord"):
                    following.remove(element)
            measure.remove(note)
            continue
        pitch = edit.get("pitch")
        if pitch is not None and not isinstance(pitch, dict):
            raise APIError(400, "pitch 必须包含 step、alter、octave。")
        if pitch is None and any(field in edit for field in ("step", "alter", "octave")):
            pitch = {field: edit[field] for field in ("step", "alter", "octave") if field in edit}
        if edit.get("rest"):
            if pitch is not None:
                raise APIError(400, "休止符不能同时指定音高。")
            for name in ("pitch", "unpitched", "accidental", "tie"):
                remove(name)
            for notation in children(note, "notations"):
                for tied in children(notation, "tied"):
                    notation.remove(tied)
            set_value("rest")
        elif pitch is not None or edit.get("rest") is False and children(note, "rest"):
            current = children(note, "pitch")
            old = current[0] if current else ET.Element(ns + "pitch")
            pitch = pitch or {}
            if set(pitch) - {"step", "alter", "octave"}:
                raise APIError(400, "pitch 字段无效。")
            step = pitch.get("step", text(old, "step"))
            alter = numeric(pitch.get("alter", float(text(old, "alter", "0"))), "alter", -2, 2, integer=True)
            octave = numeric(pitch.get("octave", int(text(old, "octave", "4"))), "octave", -1, 9, integer=True)
            if not isinstance(step, str) or len(step) != 1 or step not in "CDEFGAB":
                raise APIError(400, "step 必须是 C、D、E、F、G、A、B。")
            midi = (octave + 1) * 12 + {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[step] + alter
            if not 0 <= midi <= 127:
                raise APIError(400, "音高超出 MIDI 范围。")
            remove("rest")
            remove("unpitched")
            remove("accidental")
            node = set_value("pitch")
            for name, value in (("step", step), ("alter", alter), ("octave", octave)):
                if name != "alter" or value != 0:
                    ET.SubElement(node, ns + name).text = str(value)
        if "duration" in edit:
            set_value("duration", numeric(edit["duration"], "duration", .000001))
        if "type" in edit:
            if not isinstance(edit["type"], str) or edit["type"] not in NOTE_TYPES:
                raise APIError(400, "音符时值 type 无效。")
            set_value("type", edit["type"])
        if "dot" in edit:
            count = numeric(edit["dot"], "dot", 0, 4, integer=True)
            remove("dot")
            for _ in range(count):
                element = ET.Element(ns + "dot")
                insertion = next((i for i, child in enumerate(note) if ORDER.get(tag(child), 100) > ORDER["dot"]), len(note))
                note.insert(insertion, element)
    result = serialize(root)
    note_listing(result)
    return result


def validate_midi(path: Path):
    with path.open("rb") as stream:
        head = stream.read(14)
        if len(head) != 14 or not head.startswith(b"MThd\x00\x00\x00\x06") or not 0 < int.from_bytes(head[10:12], "big") <= 512:
            raise APIError(422, "MIDI 转换器没有生成有效 MIDI。")
        for _ in range(int.from_bytes(head[10:12], "big")):
            header = stream.read(8)
            if len(header) != 8 or not header.startswith(b"MTrk"):
                raise APIError(422, "MIDI 音轨无效。")
            length = int.from_bytes(header[4:], "big")
            if length > 32 * 1024 * 1024 or len(stream.read(length)) != length:
                raise APIError(422, "MIDI 音轨数据无效。")
        if stream.read(1):
            raise APIError(422, "MIDI 文件末尾无效。")


class JobService:
    def __init__(self, storage: Path, token: str, *, engine_command=None, midi_command=None, timeout=900, midi_timeout=120, queue_size=4, max_jobs=100):
        if len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
            raise ValueError("Bearer token 至少应有 32 个无空白 ASCII 字符。")
        storage.mkdir(mode=0o700, parents=True, exist_ok=True)
        if storage.is_symlink():
            raise ValueError("任务存储不能是符号链接。")
        self.storage, self.token = storage.resolve(), token
        self.engine_command = engine_command or argv_setting("OMR_ENGINE_COMMAND", ["/usr/local/bin/audiveris-omr"])
        self.midi_command = midi_command or argv_setting("OMR_MIDI_COMMAND", ["/usr/local/bin/omr-midi"])
        self.timeout, self.midi_timeout, self.max_jobs = timeout, midi_timeout, max_jobs
        self.lock = threading.RLock()
        self.jobs, self.job_locks, self.cancellations = {}, {}, {}
        self.uploading = set()
        self.pending = queue.Queue()
        self.slots = threading.BoundedSemaphore(queue_size + 1)
        self.reserved = 0
        self.stopping = threading.Event()
        self.midi_lock = threading.Lock()
        self._load()
        self.worker = threading.Thread(target=self._work, daemon=True, name="audiveris-worker")
        self.worker.start()

    def directory(self, job_id):
        try:
            if str(uuid.UUID(job_id)) != job_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise APIError(404, "任务不存在。") from None
        path = self.storage / job_id
        if path.is_symlink() or path.resolve().parent != self.storage:
            raise APIError(404, "任务目录无效。")
        return path

    def file(self, job_id, relative):
        root = self.directory(job_id)
        if not isinstance(relative, str) or "\\" in relative or PurePosixPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts:
            raise APIError(404, "任务文件无效。")
        path = root / relative
        if not path.resolve().is_relative_to(root) or any(item.is_symlink() for item in (path, *path.parents) if item != root.parent):
            raise APIError(404, "任务文件无效。")
        return path

    def _save(self, job):
        root = self.directory(job["id"])
        temp = root / (".metadata-" + uuid.uuid4().hex)
        try:
            with temp.open("xb") as stream:
                stream.write(json.dumps(job, ensure_ascii=False, allow_nan=False).encode("utf8"))
                stream.flush()
                os.fsync(stream.fileno())
            temp.replace(root / "job.json")
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                LOG.warning("未能清理临时元数据；原修订仍可读取。")

    def _load(self):
        for directory in self.storage.iterdir():
            try:
                if not directory.is_dir() or directory.is_symlink() or self.directory(directory.name) != directory:
                    continue
                path = directory / "job.json"
                if path.is_symlink() or path.stat().st_size > 1024 * 1024:
                    continue
                job = json.loads(path.read_text(encoding="utf8"))
                if job["id"] != directory.name or job["state"] not in {"queued", "running", "succeeded", "failed"} or not isinstance(job.get("scores", []), list):
                    continue
                filename_extension(job["filename"])
                self.file(job["id"], job["input"])
                for score in job.get("scores", []):
                    for key in ("musicxml", "midi"):
                        self.file(job["id"], score[key])
                if job["state"] in {"queued", "running"}:
                    job.update(state="failed", error="服务重启中断了识谱；原始文件已保留。", updatedAt=now())
                    self._save(job)
                self.jobs[job["id"]], self.job_locks[job["id"]] = job, threading.Lock()
                self.cancellations[job["id"]] = JobCancellation()
            except (OSError, ValueError, KeyError, TypeError, APIError):
                LOG.warning("跳过无效任务元数据 %s", directory.name)

    def public(self, job):
        prefix = f'/api/jobs/{job["id"]}'
        scores = [{"id": str(index), "index": index, "name": score["name"], "musicxml": f"{prefix}/score/musicxml?score={index}", "midi": f"{prefix}/score/midi?score={index}", "noteCount": score["noteCount"]} for index, score in enumerate(job.get("scores", []))]
        artifacts = {"original": prefix + "/original", "log": prefix + "/log"}
        if scores:
            artifacts.update(musicxml=prefix + "/score/musicxml", midi=prefix + "/score/midi")
        if job.get("project"):
            artifacts["omr"] = prefix + "/project/omr"
        source_type = Path(job["filename"]).suffix.lower().lstrip(".")
        return {key: copy.deepcopy(job.get(key)) for key in ("id", "filename", "createdAt", "updatedAt", "state", "revision", "warnings", "error")} | {"status": job["state"], "scores": scores, "artifacts": artifacts, "sourceType": source_type, "recognitionMode": "import" if source_type in {"xml", "musicxml", "mxl"} else "audiveris"}

    def get(self, job_id):
        self.directory(job_id)
        with self.lock:
            if job_id not in self.jobs:
                raise APIError(404, "任务不存在。")
            return self.public(self.jobs[job_id])

    def delete(self, job_id):
        # Called only by the private authenticated loopback handler. Public
        # account ownership is checked under the gateway's SQLite transaction.
        directory = self.directory(job_id)
        with self.lock:
            job, mutex, cancellation = self.jobs.get(job_id), self.job_locks.get(job_id), self.cancellations.get(job_id)
            if job is None:
                if job_id in self.uploading:
                    raise APIError(503, "上传正在结束，请稍后重试清理。")
                existed = directory.exists()
                if existed:
                    try:
                        shutil.rmtree(directory)
                    except OSError as error:
                        raise APIError(503, "任务文件尚未全部删除，请稍后重试清理。") from error
                return {"id": job_id, "deleted": True, "alreadyAbsent": not existed}
        cancellation.cancel()
        if not mutex.acquire(timeout=15):
            raise APIError(503, "任务正在结束，请稍后重试清理。")
        try:
            with self.lock:
                # Never remove a different registration or a redirected path.
                if self.cancellations.get(job_id) is not cancellation or self.job_locks.get(job_id) is not mutex:
                    if job_id not in self.jobs and not directory.exists():
                        return {"id": job_id, "deleted": True, "alreadyAbsent": True}
                    raise APIError(409, "任务标识已改变，请重新确认清理。")
                directory = self.directory(job_id)
                if directory.exists():
                    try:
                        shutil.rmtree(directory)
                    except OSError as error:
                        raise APIError(503, "任务文件尚未全部删除，请稍后重试清理。") from error
                self.jobs.pop(job_id, None)
                self.job_locks.pop(job_id, None)
                self.cancellations.pop(job_id, None)
            return {"id": job_id, "deleted": True, "alreadyAbsent": False}
        finally:
            mutex.release()

    def submit(self, filename, stream, length, job_id=None):
        extension = filename_extension(filename)
        if not 0 < length <= MAX_UPLOAD:
            raise APIError(413, "上传文件必须在 32 MiB 以内。")
        job_id = str(uuid.uuid4()) if job_id is None else job_id
        directory = self.directory(job_id)
        with self.lock:
            if job_id in self.jobs or job_id in self.uploading or directory.exists():
                raise APIError(409, "任务标识已存在。")
            if self.stopping.is_set() or len(self.jobs) + self.reserved >= self.max_jobs or not self.slots.acquire(blocking=False):
                raise APIError(503, "识谱队列或任务存储已满，请稍后重试。")
            self.reserved += 1
            self.uploading.add(job_id)
        committed, created = False, False
        try:
            directory.mkdir(mode=0o700)
            created = True
            source = directory / ("input" + extension)
            with source.open("xb") as target:
                remaining = length
                while remaining:
                    chunk = stream.read(min(64 * 1024, remaining))
                    if not chunk:
                        raise APIError(400, "上传提前结束。")
                    target.write(chunk)
                    remaining -= len(chunk)
            validate_input(source, extension)
            job = {"id": job_id, "filename": filename, "input": source.name, "state": "queued", "createdAt": now(), "updatedAt": now(), "revision": 0, "scores": [], "project": None, "warnings": [], "error": None}
            self._save(job)
            with self.lock:
                self.jobs[job_id], self.job_locks[job_id] = job, threading.Lock()
                self.cancellations[job_id] = JobCancellation()
                self.reserved -= 1
                committed = True
                response = self.public(job)
                self.pending.put(job_id)
            return response
        finally:
            with self.lock:
                self.uploading.discard(job_id)
            if not committed:
                try:
                    if created and directory.is_dir() and not directory.is_symlink() and directory.resolve().parent == self.storage:
                        shutil.rmtree(directory)
                except OSError:
                    LOG.exception("不能清理拒绝的上传 %s", job_id)
                with self.lock:
                    self.reserved -= 1
                    self.slots.release()

    def _revision(self, job, xml_scores):
        cancellation = self.cancellations[job["id"]]
        cancellation.check()
        root = self.directory(job["id"])
        revisions = self.file(job["id"], "revisions")
        revisions.mkdir(exist_ok=True)
        number = job["revision"] + 1
        while (revisions / f"{number:08d}").exists():
            number += 1
        stage = revisions / (".pending-" + uuid.uuid4().hex)
        stage.mkdir(mode=0o700)
        try:
            scores = []
            for index, (name, data) in enumerate(xml_scores):
                listing = note_listing(data)
                xml_path = stage / f"score-{index:03d}.musicxml"
                midi_path = stage / f"score-{index:03d}.mid"
                xml_path.write_bytes(serialize(safe_xml(data)))
                while not self.midi_lock.acquire(timeout=.2):
                    cancellation.check()
                try:
                    run_command([*self.midi_command, str(xml_path), str(midi_path)], root, root / "engine.log", self.midi_timeout, "MIDI转换", cancellation)
                finally:
                    self.midi_lock.release()
                validate_midi(midi_path)
                relative = f"revisions/{number:08d}"
                scores.append({"name": name, "musicxml": relative + "/" + xml_path.name, "midi": relative + "/" + midi_path.name, "noteCount": len(listing["notes"]), "xmlSha256": hashlib.sha256(xml_path.read_bytes()).hexdigest(), "midiSha256": hashlib.sha256(midi_path.read_bytes()).hexdigest()})
            cancellation.check()
            stage.rename(revisions / f"{number:08d}")
            updated = copy.deepcopy(job)
            updated.update(revision=number, scores=scores, state="succeeded", error=None, updatedAt=now(), warnings=warnings_from(root / "engine.log"))
            self._save(updated)
            with self.lock:
                self.jobs[job["id"]] = updated
            return updated
        finally:
            # An orphaned complete revision after a metadata failure is harmless;
            # readers follow only the atomically committed job.json pointer.
            if stage.exists() and not stage.is_symlink() and stage.resolve().parent == revisions.resolve():
                try:
                    shutil.rmtree(stage)
                except OSError:
                    LOG.warning("未能清理失败的待发布修订；原修订仍可读取。")

    def _work(self):
        while True:
            job_id = self.pending.get()
            if job_id is None:
                self.pending.task_done()
                return
            with self.lock:
                mutex = self.job_locks.get(job_id)
            if mutex is None:
                self.slots.release(); self.pending.task_done(); continue
            with mutex:
                with self.lock:
                    job = self.jobs.get(job_id)
                    cancellation = self.cancellations.get(job_id)
                if job is None or cancellation is None or cancellation.event.is_set():
                    self.slots.release(); self.pending.task_done(); continue
                try:
                    cancellation.check()
                    if self.stopping.is_set():
                        raise APIError(503, "服务已停止；原始文件已保留。")
                    with self.lock:
                        job.update(state="running", updatedAt=now())
                        self._save(job)
                    source = self.file(job_id, job["input"])
                    root = self.directory(job_id)
                    if source.suffix in {".musicxml", ".xml", ".mxl"}:
                        xml_scores = source_scores(source, Path(job["filename"]).stem)
                    else:
                        output = self.file(job_id, "out")
                        output.mkdir()
                        run_command([*self.engine_command, "-save", "-swap", "-output", str(output), "--", str(source)], root, root / "engine.log", self.timeout, "NoteLite识谱", cancellation)
                        candidates = [path for path in sorted(output.rglob("*"), key=natural_key) if path.is_file() and not path.is_symlink() and path.suffix.lower() in {".mxl", ".xml", ".musicxml"} and path.resolve().is_relative_to(output)]
                        # Audiveris may emit both compressed and plain exports.
                        unique = {}
                        for path in candidates:
                            unique.setdefault(path.stem, path)
                        if not unique:
                            raise APIError(422, "没有生成 MusicXML，请检查原谱与识谱日志。")
                        if len(unique) > 64:
                            raise APIError(413, "导出乐章数量超出限制。")
                        xml_scores = [score for path in unique.values() for score in source_scores(path)]
                        if len(xml_scores) > 64:
                            raise APIError(413, "导出乐章数量超出限制。")
                        projects = [path for path in sorted(output.rglob("*.omr")) if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(output)]
                        job["project"] = projects[0].relative_to(root).as_posix() if projects else None
                    self._revision(job, xml_scores)
                except Exception as error:
                    if cancellation.event.is_set():
                        continue
                    LOG.exception("任务失败 %s", job_id)
                    with self.lock:
                        job.update(state="failed", error=error.message if isinstance(error, APIError) else "识谱处理失败，请查看任务日志。", updatedAt=now(), warnings=warnings_from(self.directory(job_id) / "engine.log"))
                        try:
                            self._save(job)
                        except OSError:
                            LOG.exception("不能保存失败任务 %s", job_id)
                finally:
                    self.slots.release()
                    self.pending.task_done()

    def _ready(self, job_id, index):
        self.directory(job_id)
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise APIError(404, "任务不存在。")
            if self.cancellations[job_id].event.is_set():
                raise APIError(410, "任务已取消。")
            if job["state"] != "succeeded":
                raise APIError(409, "识谱尚未完成。")
            if not 0 <= index < len(job["scores"]):
                raise APIError(404, "乐章不存在。")
            return job

    def notes(self, job_id, index=0):
        job = self._ready(job_id, index)
        data = self.file(job_id, job["scores"][index]["musicxml"]).read_bytes()
        return {"jobId": job_id, "revision": job["revision"], "score": index} | note_listing(data)

    def edit(self, job_id, *, index=0, data=None, edits=None, revision=None):
        self.directory(job_id)
        with self.lock:
            mutex = self.job_locks.get(job_id)
        if mutex is None:
            raise APIError(404, "任务不存在。")
        if not mutex.acquire(blocking=False):
            raise APIError(409, "任务正在识谱或保存，请稍后重试。")
        try:
            job = self._ready(job_id, index)
            if revision is not None and numeric(revision, "revision", integer=True) != job["revision"]:
                raise APIError(409, "乐谱已更新，请重新读取后修改。")
            scores = [(score["name"], self.file(job_id, score["musicxml"]).read_bytes()) for score in job["scores"]]
            replacement = serialize(safe_xml(data)) if data is not None else apply_edits(scores[index][1], edits)
            scores[index] = (scores[index][0], replacement)
            updated = self._revision(job, scores)
            return self.public(updated)
        finally:
            mutex.release()

    def artifact(self, job_id, kind, index=0):
        self.directory(job_id)
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise APIError(404, "任务不存在。")
            if kind in {"musicxml", "midi"}:
                self._ready(job_id, index)
                relative = job["scores"][index][kind]
                name = f"score-{index}.{ 'musicxml' if kind == 'musicxml' else 'mid'}"
            elif kind == "original":
                relative, name = job["input"], job["filename"]
            elif kind == "omr" and job.get("project"):
                relative, name = job["project"], "project.omr"
            elif kind == "log":
                relative, name = "engine.log", "recognition.log"
            else:
                raise APIError(404, "文件不存在。")
            path = self.file(job_id, relative)
            try:
                stream = path.open("rb")
            except OSError:
                raise APIError(404, "文件不存在。") from None
            return stream, name, job["revision"]

    def close(self):
        self.stopping.set()
        self.pending.put(None)
        self.worker.join(self.timeout + self.midi_timeout + 5)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, service: JobService, web: Path | None = None):
        if address[0] != "127.0.0.1":
            raise ValueError("OMR 服务只允许监听 127.0.0.1。")
        self.service, self.web = service, web.resolve() if web else None
        self.connections = threading.BoundedSemaphore(16)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.connections.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n")
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.connections.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.connections.release()


class Handler(BaseHTTPRequestHandler):
    server_version, sys_version = "NoteLiteOMR/1", ""
    def setup(self):
        super().setup()
        self.connection.settimeout(60)

    def log_message(self, *_):
        LOG.info("HTTP %s", self.client_address[0])

    def json(self, status, value):
        payload = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if status == 401:
            self.send_header("WWW-Authenticate", 'Bearer realm="NoteLiteOMR"')
        if status == 503:
            self.send_header("Retry-After", "5")
        self.end_headers()
        self.wfile.write(payload)

    def body_length(self, limit):
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Encoding"):
            raise APIError(400, "请使用带 Content-Length 的原始请求体。")
        if not lengths:
            raise APIError(411, "需要 Content-Length。")
        if len(lengths) != 1 or not re.fullmatch(r"[0-9]+", lengths[0]):
            raise APIError(400, "Content-Length 无效。")
        length = int(lengths[0])
        if not 0 < length <= limit:
            raise APIError(413, "请求体超出大小限制。")
        return length

    def body(self, limit):
        length = self.body_length(limit)
        data = self.rfile.read(length)
        if len(data) != length:
            raise APIError(400, "请求体提前结束。")
        return data

    def send_file(self, stream, name, revision, mime=None):
        with stream:
            self.send_response(200)
            self.send_header("Content-Type", mime or mimetypes.guess_type(name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(os.fstat(stream.fileno()).st_size))
            self.send_header("Content-Disposition", "inline; filename*=UTF-8''" + quote(name, safe=""))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("ETag", f'"{revision}"')
            self.end_headers()
            shutil.copyfileobj(stream, self.wfile, 64 * 1024)

    def dispatch(self):
        target = urlsplit(self.path)
        host = urlsplit("http://" + self.headers.get("Host", ""))
        if host.hostname not in {"127.0.0.1", "localhost"}:
            raise APIError(403, "服务仅允许本机访问。")
        origin = self.headers.get("Origin")
        if origin:
            source = urlsplit(origin)
            if source.scheme not in {"http", "https"} or source.hostname != host.hostname or source.port != host.port:
                raise APIError(403, "请求来源无效。")
        service = self.server.service
        query = parse_qs(target.query, keep_blank_values=True)
        if any(len(values) != 1 for values in query.values()):
            raise APIError(400, "重复的查询参数。")
        if self.command == "GET" and target.path == "/api/health":
            self.json(200, {"status": "ok", "service": "notelite-omr", "engine": "Audiveris", "engineVersion": "5.11.0", "authentication": "bearer", "maxUploadBytes": MAX_UPLOAD, "maxXmlBytes": MAX_XML, "queued": service.pending.qsize()})
            return
        if not target.path.startswith("/api/") and self.command == "GET" and self.server.web:
            relative = unquote(target.path).lstrip("/") or "index.html"
            parts = PurePosixPath(relative).parts
            path = self.server.web / relative
            if ".." in parts or "\\" in relative or not path.resolve().is_relative_to(self.server.web) or any(part.startswith(".") for part in parts) or path.is_symlink() or not path.is_file():
                raise APIError(404, "页面不存在。")
            self.send_file(path.open("rb"), path.name, 0)
            return
        supplied = self.headers.get_all("Authorization", [])
        provided = supplied[0].encode("utf8") if len(supplied) == 1 else b""
        if not hmac.compare_digest(provided, ("Bearer " + service.token).encode("ascii")):
            raise APIError(401, "需要有效的访问令牌。")
        if target.path == "/api/jobs" and self.command == "POST":
            if set(query) != {"filename"}:
                raise APIError(400, "请提供 filename 参数。")
            requested = self.headers.get_all("X-NoteLite-Job-Id", [])
            if len(requested) > 1:
                raise APIError(400, "任务标识字段重复。")
            self.json(202, service.submit(query["filename"][0], self.rfile, self.body_length(MAX_UPLOAD), requested[0] if requested else None))
            return
        if target.path == "/api/jobs" and self.command == "GET":
            with service.lock:
                self.json(200, {"jobs": [service.public(job) for job in sorted(service.jobs.values(), key=lambda job: job["createdAt"], reverse=True)]})
            return
        match = re.fullmatch(r"/api/jobs/([^/]+)(?:/(score/(?:musicxml|midi|notes)|notes|original|project/omr|log|score))?", target.path)
        if not match:
            raise APIError(404, "接口不存在。")
        job_id, action = match.groups()
        service.directory(job_id)
        if set(query) - {"score"}:
            raise APIError(400, "查询参数无效。")
        try:
            index = int(query.get("score", ["0"])[0])
            if index < 0:
                raise ValueError()
        except ValueError:
            raise APIError(400, "score 索引无效。") from None
        if self.command == "GET" and action is None:
            self.json(200, service.get(job_id))
        elif self.command == "DELETE" and action is None and not query:
            self.json(200, service.delete(job_id))
        elif self.command == "GET" and action in {"notes", "score/notes"}:
            self.json(200, service.notes(job_id, index))
        elif self.command == "GET" and action in {"score/musicxml", "score/midi", "original", "project/omr", "log"}:
            kind = {"score/musicxml": "musicxml", "score/midi": "midi", "project/omr": "omr"}.get(action, action)
            stream, name, revision = service.artifact(job_id, kind, index)
            mime = {"musicxml": "application/vnd.recordare.musicxml+xml", "midi": "audio/midi", "log": "text/plain; charset=utf-8"}.get(kind)
            self.send_file(stream, name, revision, mime)
        elif self.command == "PUT" and action == "score":
            value = self.headers.get("If-Match")
            if value is not None:
                if not re.fullmatch(r'"?[0-9]+"?', value):
                    raise APIError(400, "If-Match 修订号无效。")
                value = int(value.strip('"'))
            self.json(200, service.edit(job_id, index=index, data=self.body(MAX_XML), revision=value))
        elif self.command == "PATCH" and action in {"notes", "score/notes"}:
            try:
                value = json.loads(self.body(128 * 1024).decode("utf8"))
            except (ValueError, UnicodeError):
                raise APIError(400, "修改请求不是有效 JSON。") from None
            if not isinstance(value, dict):
                raise APIError(400, "修改请求必须是 JSON 对象。")
            edits = value.get("edits")
            if edits is None:
                edits = [{key: item for key, item in value.items() if key not in {"revision", "score"}}]
            index = numeric(value.get("score", index), "score", integer=True)
            self.json(200, service.edit(job_id, index=index, edits=edits, revision=value.get("revision")))
        else:
            raise APIError(405, "请求方法无效。")

    def handle_request(self):
        try:
            self.dispatch()
        except APIError as error:
            self.json(error.status, {"error": error.message})
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            self.close_connection = True
        except (ValueError, UnicodeError):
            self.json(400, {"error": "请求格式无效。"})
        except Exception:
            LOG.exception("HTTP 请求失败")
            self.json(500, {"error": "服务器处理失败，已保留原有文件。"})
    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = handle_request


def token_from(path: Path) -> str:
    configured = os.environ.get("OMR_TOKEN")
    if configured:
        return configured
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("令牌文件不能是符号链接。")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.stat().st_size > 4096 or os.name == "posix" and path.stat().st_mode & 0o077:
            raise ValueError("令牌文件必须限制为 0600 权限。")
        return path.read_text(encoding="ascii").strip()
    with os.fdopen(descriptor, "w", encoding="ascii") as stream:
        value = secrets.token_urlsafe(32)
        stream.write(value + "\n")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", "--bind", dest="host", choices=["127.0.0.1"], default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--storage", type=Path, default=Path(os.environ.get("OMR_STORAGE", "/var/lib/audiveris/jobs")))
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--web", type=Path, default=Path(__file__).resolve().parent / "web")
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("OMR_JOB_TIMEOUT", "900")))
    parser.add_argument("--midi-timeout", type=float, default=120)
    parser.add_argument("--omr", help="Audiveris wrapper executable; command arguments can instead use OMR_ENGINE_COMMAND JSON")
    parser.add_argument("--midi", help="MIDI converter wrapper executable; command arguments can instead use OMR_MIDI_COMMAND JSON")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535 or not math.isfinite(args.timeout) or args.timeout <= 0 or not math.isfinite(args.midi_timeout) or args.midi_timeout <= 0:
        parser.error("端口或超时无效。")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token_path = args.token_file or args.storage.parent / "api-token"
    service = JobService(args.storage, token_from(token_path), timeout=args.timeout, midi_timeout=args.midi_timeout, engine_command=[args.omr] if args.omr else None, midi_command=[args.midi] if args.midi else None)
    server = Server((args.host, args.port), service, args.web)
    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    LOG.info("独立 OMR 服务监听 127.0.0.1:%d；访问令牌由受限文件保存，不输出令牌。", args.port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        service.close()


if __name__ == "__main__":
    main()
