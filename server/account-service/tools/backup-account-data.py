#!/usr/bin/env python3
"""Private, offline three-root backup/restore. Never deploys or stops services."""
from __future__ import annotations
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile

ROLES = {"accounts", "gateway", "omr"}
SERVICES = ("notelite-accounts.service", "notelite-gateway.service", "notelite-omr.service")
MAX_MANIFEST = 64 * 1024 * 1024
MAX_FILES = 500000
MAGIC = b"SQLite format 3\x00"


class MigrationError(Exception):
    pass


def ensure_quiesced(quiesced, runner=None):
    if not quiesced:
        raise MigrationError("必须确认所有数据写入已停止，并提供 --quiesced。")
    if sys.platform.startswith("linux"):
        try:
            result = (runner or subprocess.run)(["systemctl", "show", "--property=Id,LoadState,ActiveState", "--no-pager", *SERVICES], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False)
            units = {}
            for block in result.stdout.decode("ascii", errors="strict").strip().split("\n\n"):
                values = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
                if values.get("Id") in units:
                    raise MigrationError("停止状态检查返回重复服务。")
                units[values.get("Id")] = values
        except (OSError, subprocess.SubprocessError, UnicodeError) as error:
            raise MigrationError("无法确认三项服务均已停止。") from error
        if result.returncode != 0 or set(units) != set(SERVICES) or any(units[service].get("LoadState") != "loaded" or units[service].get("ActiveState") != "inactive" for service in SERVICES):
            raise MigrationError("三项服务必须全部处于 inactive，工具不会自动停止服务。")


def safe_path(path):
    path = Path(path)
    if ".." in path.parts:
        raise MigrationError("目录参数不能包含上级路径。")
    path = path.absolute()
    for item in [*reversed(path.parents), path]:
        if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
            raise MigrationError("目录或文件不能使用符号链接或目录联接。")
    return path


def relative_name(name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name or any(ord(c) < 32 or ord(c) == 127 for c in name) or any(part in {"", ".", ".."} for part in name.split("/")):
        raise MigrationError("备份清单含不安全的相对路径。")
    try:
        name.encode("utf8")
    except UnicodeError as error:
        raise MigrationError("备份清单含无效的文件名。") from error
    return name


def private_mode(path, directory=False):
    if os.name == "posix":
        path.chmod(0o700 if directory else 0o600)


def regular_open(path):
    path = safe_path(path)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise MigrationError("数据目录只能包含普通文件和目录。")
    return os.fdopen(descriptor, "rb")


def checksum(path):
    digest, size = hashlib.sha256(), 0
    with regular_open(path) as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def inventory(root):
    root = safe_path(root)
    if not root.is_dir():
        raise MigrationError("数据根目录不存在。")
    files, directories = [], []
    for directory, children, names in os.walk(root, followlinks=False):
        directory = safe_path(directory)
        for child in children:
            path = safe_path(directory / child)
            if not path.is_dir():
                raise MigrationError("数据目录中发现不支持的文件类型。")
            directories.append(relative_name(path.relative_to(root).as_posix()))
        for name in names:
            path = safe_path(directory / name)
            if not stat.S_ISREG(path.stat().st_mode):
                raise MigrationError("数据目录中发现不支持的文件类型。")
            files.append(relative_name(path.relative_to(root).as_posix()))
    return sorted(files), sorted(directories)


def roots_checked(roots, *, sources):
    if set(roots) != ROLES:
        raise MigrationError("必须同时提供 accounts、gateway、omr 三项数据根目录。")
    result = {label: safe_path(path) for label, path in roots.items()}
    values = list(result.values())
    for first in values:
        for second in values:
            if first != second and first.is_relative_to(second) or first == second and values.count(first) > 1:
                raise MigrationError("三个数据目录不能相同或相互包含。")
        if not sources and first.exists() and (not first.is_dir() or any(first.iterdir())):
            raise MigrationError("恢复只接受不存在或完全空的数据目录，禁止覆盖。")
    return result


def check_sqlite(path, required=()):
    with regular_open(path) as stream:
        if stream.read(16) != MAGIC:
            raise MigrationError("数据库格式无效。")
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
            if list(db.execute("PRAGMA quick_check")) != [("ok",)] or list(db.execute("PRAGMA foreign_key_check")):
                raise MigrationError("数据库完整性校验未通过。")
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not set(required) <= tables:
                raise MigrationError("备份数据库缺少必要的账户或归属结构。")
    except sqlite3.Error as error:
        raise MigrationError("数据库无法读取或校验。") from error


def copy_private(source, target, expected=None):
    before = source.stat()
    with regular_open(source) as reader, target.open("xb") as writer:
        shutil.copyfileobj(reader, writer, 1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())
    private_mode(target)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise MigrationError("发现数据在复制期间改变，请停止所有写入后重试。")
    actual = checksum(target)
    if expected is not None and actual != expected:
        raise MigrationError("复制后校验失败，恢复未完成。")
    return actual


def sqlite_snapshot(source, target):
    before = source.stat()
    check_sqlite(source)
    # The backup API includes committed WAL contents, unlike raw database copying.
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=5)) as original:
        with closing(sqlite3.connect(target)) as copied:
            original.backup(copied)
            copied.execute("PRAGMA journal_mode=DELETE")
    private_mode(target)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise MigrationError("数据库在备份期间改变，请重新确认停止所有写入。")
    check_sqlite(target)
    return checksum(target)


def backup(roots, destination, *, quiesced=False, runner=None):
    ensure_quiesced(quiesced, runner)
    roots = roots_checked(roots, sources=True)
    destination = safe_path(destination)
    if destination.exists() or any(destination.is_relative_to(root) or root.is_relative_to(destination) for root in roots.values()):
        raise MigrationError("备份目录必须是新的目录，并位于三个数据根目录之外。")
    if not destination.parent.is_dir():
        raise MigrationError("请先准备私密备份父目录。")
    all_files = {label: inventory(root) for label, root in roots.items()}
    check_sqlite(roots["accounts"] / "accounts.sqlite3", {"users", "sessions", "scores", "history"})
    check_sqlite(roots["gateway"] / "gateway.sqlite3", {"jobs", "devices"})
    destination.mkdir(mode=0o700)
    private_mode(destination, True)
    created_identity = (destination.stat().st_dev, destination.stat().st_ino)
    manifest = {"schemaVersion": 1, "createdAt": datetime.now(timezone.utc).isoformat(), "quiesced": True, "roots": sorted(ROLES), "directories": [], "files": []}
    try:
        data = destination / "data"
        data.mkdir(mode=0o700)
        for label in sorted(ROLES):
            copied_root = data / label
            copied_root.mkdir(mode=0o700)
            files, directories = all_files[label]
            sqlite_names = set()
            for name in files:
                with regular_open(roots[label] / name) as stream:
                    if stream.read(16) == MAGIC:
                        sqlite_names.add(name)
            for name in directories:
                (copied_root / name).mkdir(mode=0o700, parents=True, exist_ok=True)
                private_mode(copied_root / name, True)
                manifest["directories"].append({"root": label, "path": name})
            for name in files:
                if any(name == database + suffix for database in sqlite_names for suffix in ("-wal", "-shm", "-journal")):
                    continue  # These are represented by the consistent SQLite snapshot.
                source, target = roots[label] / name, copied_root / name
                size, digest = sqlite_snapshot(source, target) if name in sqlite_names else copy_private(source, target)
                manifest["files"].append({"root": label, "path": name, "size": size, "sha256": digest, "sqlite": name in sqlite_names})
        encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf8")
        if len(encoded) > MAX_MANIFEST or len(manifest["files"]) > MAX_FILES:
            raise MigrationError("备份清单超过当前工具上限。")
        (destination / "MANIFEST.json").write_bytes(encoded)
        (destination / "MANIFEST.sha256").write_bytes((hashlib.sha256(encoded).hexdigest() + "\n").encode("ascii"))
        for file in (destination / "MANIFEST.json", destination / "MANIFEST.sha256"):
            private_mode(file)
        verify_bundle(destination)
    except Exception:
        # This function created the exact new destination itself; never remove
        # a caller's existing backup or any source directory during cleanup.
        if destination.exists() and not destination.is_symlink() and not getattr(destination, "is_junction", lambda: False)() and (destination.stat().st_dev, destination.stat().st_ino) == created_identity:
            shutil.rmtree(destination)
        raise
    return summary(manifest, "backed_up")


def verify_bundle(bundle):
    bundle = safe_path(bundle)
    actual_files, actual_directories = inventory(bundle)
    with regular_open(bundle / "MANIFEST.json") as stream:
        encoded = stream.read(MAX_MANIFEST + 1)
    if len(encoded) > MAX_MANIFEST:
        raise MigrationError("备份清单过大。")
    with regular_open(bundle / "MANIFEST.sha256") as stream:
        digest = stream.read(66)
    if digest != (hashlib.sha256(encoded).hexdigest() + "\n").encode("ascii"):
        raise MigrationError("备份清单校验失败。")
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate")
            result[key] = value
        return result
    try:
        value = json.loads(encoded, object_pairs_hook=unique_pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise MigrationError("备份清单格式无效。") from error
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "createdAt", "quiesced", "roots", "directories", "files"} or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1 or not isinstance(value["createdAt"], str) or len(value["createdAt"]) > 40 or value["quiesced"] is not True or value["roots"] != sorted(ROLES) or not isinstance(value["files"], list) or not isinstance(value["directories"], list) or len(value["files"]) > MAX_FILES or len(value["directories"]) > MAX_FILES:
        raise MigrationError("备份清单结构无效。")
    expected_files, expected_dirs, identities = {"MANIFEST.json", "MANIFEST.sha256"}, {"data", *("data/" + label for label in ROLES)}, set()
    for row in value["directories"]:
        if not isinstance(row, dict) or set(row) != {"root", "path"} or not isinstance(row["root"], str) or row["root"] not in ROLES:
            raise MigrationError("目录清单格式无效。")
        name = "data/" + row["root"] + "/" + relative_name(row["path"])
        if name.casefold() in identities:
            raise MigrationError("备份清单含重复路径。")
        identities.add(name.casefold())
        expected_dirs.add(name)
    for row in value["files"]:
        if not isinstance(row, dict) or set(row) != {"root", "path", "size", "sha256", "sqlite"} or not isinstance(row["root"], str) or row["root"] not in ROLES or type(row["size"]) is not int or row["size"] < 0 or type(row["sqlite"]) is not bool or not isinstance(row["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
            raise MigrationError("文件清单格式无效。")
        name = "data/" + row["root"] + "/" + relative_name(row["path"])
        identity = name.casefold()
        if identity in identities or name in expected_dirs:
            raise MigrationError("备份清单含重复或冲突路径。")
        identities.add(identity)
        expected_files.add(name)
        if checksum(bundle / name) != (row["size"], row["sha256"]):
            raise MigrationError("备份文件校验失败。")
        if row["sqlite"]:
            check_sqlite(bundle / name)
    if set(actual_files) != expected_files or set(actual_directories) != expected_dirs:
        raise MigrationError("备份内容与清单不一致。")
    check_sqlite(bundle / "data/accounts/accounts.sqlite3", {"users", "sessions", "scores", "history"})
    check_sqlite(bundle / "data/gateway/gateway.sqlite3", {"jobs", "devices"})
    return value


def restore(bundle, roots, *, quiesced=False, runner=None):
    ensure_quiesced(quiesced, runner)
    bundle = safe_path(bundle)
    roots = roots_checked(roots, sources=False)
    if any(root.is_relative_to(bundle) or bundle.is_relative_to(root) for root in roots.values()):
        raise MigrationError("恢复目标不能位于备份中或包含备份。")
    for root in roots.values():
        if not root.parent.is_dir():
            raise MigrationError("请先准备恢复目标的父目录。")
    manifest = verify_bundle(bundle)  # Full three-root validation BEFORE any writes.
    stages, installed = {}, set()
    try:
        for label, root in roots.items():
            stage = Path(tempfile.mkdtemp(prefix=".notelite-restore-", dir=root.parent))
            private_mode(stage, True)
            stages[label] = stage
            for row in manifest["directories"]:
                if row["root"] == label:
                    (stage / row["path"]).mkdir(mode=0o700, parents=True, exist_ok=True)
                    private_mode(stage / row["path"], True)
            for row in manifest["files"]:
                if row["root"] == label:
                    copy_private(bundle / "data" / label / row["path"], stage / row["path"], (row["size"], row["sha256"]))
        # Recheck destination emptiness after staging; writes use exclusive files
        # and rename can replace only an empty directory, never a live library.
        roots_checked(roots, sources=False)
        for label, root in roots.items():
            if root.exists():
                root.rmdir()
            stages[label].rename(root)
            installed.add(label)
            private_mode(root, True)
    finally:
        for label, stage in stages.items():
            if label not in installed and stage.exists() and stage.parent == roots[label].parent:
                shutil.rmtree(stage)
    return summary(manifest, "restored")


def summary(manifest, status):
    return {"status": status, "roots": len(ROLES), "files": len(manifest["files"]), "bytes": sum(row["size"] for row in manifest["files"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("backup", "verify", "restore"))
    parser.add_argument("--bundle", type=Path, required=True)
    for role in sorted(ROLES):
        parser.add_argument("--" + role + "-root", type=Path)
    parser.add_argument("--quiesced", action="store_true", help="Confirm no writers; Linux additionally checks all three systemd services inactive")
    args = parser.parse_args()
    roots = {role: getattr(args, role + "_root") for role in ROLES}
    try:
        if args.operation == "verify":
            result = summary(verify_bundle(args.bundle), "verified")
        elif any(path is None for path in roots.values()):
            raise MigrationError("备份与恢复必须提供三个数据根目录。")
        elif args.operation == "backup":
            result = backup(roots, args.bundle, quiesced=args.quiesced)
        else:
            result = restore(args.bundle, roots, quiesced=args.quiesced)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (MigrationError, OSError, sqlite3.Error) as error:
        message = str(error) if isinstance(error, MigrationError) else "文件或数据库操作未完成，请保持服务停止并检查私密备份。"
        print(json.dumps({"status": "failed", "error": message}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
