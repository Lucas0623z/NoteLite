#!/usr/bin/env python3
"""Inspect a Windows distribution without extracting or executing its contents.

Usage: python tools/verify-windows-practice-package.py --zip app.zip --output report.json
The repository is the independent reference for current resources, pinned models,
corresponding source and the freshly built native binaries. Readiness markers are
checked as recorded execution evidence; this is not a new acoustic accuracy test.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import csv
from datetime import datetime, timezone
from email.parser import BytesParser
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import struct
import sys
import tarfile
import zipfile


CREPE_ONNX_SHA = "17240ed1474039cd026f761ad9e4036ebb9565724ae690cd048104fb1e592d4e"
COMPONENTS = ("basic-pitch", "pyin", "crepe", "aubio", "partitura", "parangonar", "nakamura")
NAKAMURA_STAGES = ("SprToFmt3x", "Fmt3xToHmm", "ScorePerfmMatcher", "ErrorDetection", "RealignmentMOHMM", "MatchToCorresp")
HELPERS = ("analyze.py", "mono_analysis.py", "crepe_onnx.py", "score_tools.py", "pitch_refinement.py", "runtime_smoke.py", "onset_evidence.py")


def sha_stream(stream):
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


def sha_file(path):
    with path.open("rb") as stream:
        return sha_stream(stream)


def canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def unsafe_windows_path(name):
    parts = name.rstrip("/").split("/")
    devices = {"CON", "PRN", "AUX", "NUL", "CLOCK$", "CONIN$", "CONOUT$"}
    devices.update(prefix + number for prefix in ("COM", "LPT") for number in "123456789¹²³")
    return (not name or "\\" in name or PurePosixPath(name).is_absolute()
            or any(not part or part in (".", "..") or part.endswith((" ", "."))
                   or any(char in '<>:"|?*' or ord(char) < 32 for char in part)
                   or part.split(".", 1)[0].upper() in devices for part in parts))


class Audit:
    def __init__(self, archive, repo, cache=None):
        self.repo = repo
        self.archive = archive
        self.cache = cache or repo / "local-analysis/cache"
        self.checks = []
        self.report = {
            "schemaVersion": 1, "generatedUtc": datetime.now(timezone.utc).isoformat(),
            "archive": str(archive), "repository": str(repo), "referenceCache": str(self.cache), "checks": self.checks,
            "scope": "Read-only ZIP/JAR integrity and packaged integration evidence; no binary execution or acoustic accuracy claim.",
        }

    def check(self, name, passed, details):
        self.checks.append({"name": name, "passed": bool(passed), "details": details})

    def compare(self, z, packaged, local, name=None):
        detail = {"path": packaged, "reference": str(local)}
        if packaged not in z.NameToInfo or not local.is_file():
            detail.update({"packaged": packaged in z.NameToInfo, "referenceExists": local.is_file()})
            self.check(name or packaged, False, detail)
            return
        with z.open(packaged) as stream:
            actual = sha_stream(stream)
        expected = sha_file(local)
        detail.update({"sha256": actual, "expectedSha256": expected})
        self.check(name or packaged, actual == expected, detail)

    def require(self, z, paths, label):
        missing = [p for p in paths if p not in z.NameToInfo or z.getinfo(p).file_size == 0]
        self.check(label, not missing, {"requiredCount": len(paths), "missingOrEmpty": missing})

    def json_member(self, z, path, label):
        try:
            value = json.loads(z.read(path))
            if not isinstance(value, dict):
                raise ValueError("Expected a JSON object")
            return value
        except (KeyError, ValueError, OSError) as exc:
            self.check(label, False, {"path": path, "error": str(exc)})
            return {}

    def pe(self, z, path):
        try:
            with z.open(path) as stream:
                header = stream.read(4096)
            offset = struct.unpack_from("<I", header, 0x3C)[0]
            machine = struct.unpack_from("<H", header, offset + 4)[0]
            passed = header[:2] == b"MZ" and header[offset:offset + 4] == b"PE\0\0" and machine == 0x8664
            self.check("windows-x64:" + path, passed, {"machine": hex(machine)})
        except (KeyError, ValueError, struct.error) as exc:
            self.check("windows-x64:" + path, False, {"error": str(exc)})

    def no_private_data(self, names, label, package_prefix=""):
        # Wheel regression fixtures and trained inference weights are legitimate
        # dependencies. Project work/cache, user takes and training corpora are not.
        bad = []
        project_media = []
        forbidden = {"work", ".git", "test-output", "test_output", "training-data", "training_data", "trainingdata", "windows-performances", "recorded-engine-quality", "practice-history", "takes"}
        for name in names:
            parts = PurePosixPath(name).parts
            folded = [p.casefold() for p in parts]
            if any(p in forbidden for p in folded):
                bad.append(name)
                continue
            relative = name.removeprefix(package_prefix)
            dependency = "/site-packages/" in relative or relative.startswith("python/site-packages/")
            if not dependency and any(p in {"cache", "datasets", "training", "train"} for p in folded):
                bad.append(name)
            if not dependency and PurePosixPath(name).suffix.lower() in {".wav", ".mp3", ".flac", ".ogg", ".npy", ".npz"}:
                project_media.append(name)
        self.check(label, not bad and not project_media, {
            "forbiddenPaths": bad, "unexpectedProjectAudioOrArrays": project_media,
            "policy": "Wheel regression fixtures and inference weights allowed; project work, user recordings and training corpora rejected.",
        })

    def sources(self, z, runtime):
        trees = (("local-analysis/vendor/aubio", "sources/local-analysis/vendor/aubio"),
                 ("local-analysis/vendor/nakamura", "sources/local-analysis/vendor/nakamura"),
                 ("native/audio", "sources/native/audio"))
        count = 0
        failed = []
        for local_tree, packed_tree in trees:
            for local in sorted((self.repo / local_tree).rglob("*")):
                if not local.is_file():
                    continue
                relative = local.relative_to(self.repo / local_tree)
                if any(p in {"build", "test-output", "work", "cache", "__pycache__"} for p in relative.parts) or local.suffix == ".pyc":
                    continue
                path = runtime + packed_tree + "/" + relative.as_posix()
                count += 1
                if path not in z.NameToInfo:
                    failed.append({"path": path, "reason": "missing corresponding source"})
                else:
                    with z.open(path) as stream:
                        actual = sha_stream(stream)
                    if actual != sha_file(local):
                        failed.append({"path": path, "reason": "source differs from current repository"})
        self.check("complete-corresponding-native-sources", count > 0 and not failed, {"checkedFiles": count, "mismatches": failed})
        self.compare(z, runtime + "sources/tools/build-local-audio.ps1", self.repo / "tools/build-local-audio.ps1", "corresponding-build-entry")

    def dependencies(self, z, runtime, lock):
        site = runtime + "python/site-packages/"
        installed = {}
        # Vendored setuptools libraries have their own nested dist-info. Only
        # distributions directly installed in this site-packages root satisfy
        # the pinned environment, rather than a differently versioned vendor.
        metadata_names = [p for p in z.namelist() if p.startswith(site)
                          and len(PurePosixPath(p[len(site):]).parts) == 2
                          and p.endswith(".dist-info/METADATA")]
        for path in metadata_names:
            metadata = BytesParser().parsebytes(z.read(path), headersonly=True)
            installed[canonical(metadata.get("Name", ""))] = {"version": metadata.get("Version"), "metadata": path}
        mismatches = []
        for package in lock["packages"]:
            name = canonical(package["name"])
            if name == "pretty-midi":
                path = site + "pretty_midi/__init__.py"
                expected = package["version"]
                body = z.read(path).decode("utf8") if path in z.NameToInfo else ""
                if not re.search(r"__version__\s*=\s*['\"]" + re.escape(expected) + r"['\"]", body):
                    mismatches.append({"name": name, "expected": expected, "reason": "sdist package version missing or mismatched"})
            elif installed.get(name, {}).get("version") != package["version"]:
                mismatches.append({"name": name, "expected": package["version"], "actual": installed.get(name)})
        self.check("pinned-python-dependencies", not mismatches, {"lockedPackages": len(lock["packages"]), "mismatches": mismatches})
        record_failures = []
        reference_failures = []
        reference_archives = []
        record_count = 0
        skipped = 0
        for package in lock["packages"]:
            name = canonical(package["name"])
            reference = self.cache / package["filename"]
            if not reference.is_file():
                reference_failures.append({"name": name, "path": str(reference), "reason": "independent pinned archive missing"})
                continue
            reference_sha = sha_file(reference)
            if reference_sha != package["sha256"]:
                reference_failures.append({"name": name, "path": str(reference), "reason": "independent archive SHA-256 mismatch", "sha256": reference_sha, "expectedSha256": package["sha256"]})
                continue
            reference_archives.append({"name": name, "filename": package["filename"], "sha256": reference_sha})
            if name == "pretty-midi":
                # Compare the complete extracted package and license against
                # the independently checksum-pinned sdist, not its version text.
                with tarfile.open(reference) as source:
                    for member in source.getmembers():
                        parts = PurePosixPath(member.name).parts
                        if not member.isfile() or len(parts) < 2:
                            continue
                        if len(parts) == 2 and parts[1] == "LICENSE.txt":
                            path = site + "pretty_midi/LICENSE.txt"
                        elif parts[1] == "pretty_midi" and not member.name.lower().endswith(".sf2"):
                            path = site + PurePosixPath(*parts[1:]).as_posix()
                        else:
                            continue
                        record_count += 1
                        if path not in z.NameToInfo:
                            record_failures.append({"name": name, "path": path, "reason": "pinned sdist file missing"})
                            continue
                        with source.extractfile(member) as stream:
                            expected_hex = sha_stream(stream)
                        with z.open(path) as stream:
                            actual_hex = sha_stream(stream)
                        if actual_hex != expected_hex:
                            record_failures.append({"name": name, "path": path, "reason": "pinned sdist SHA-256 mismatch"})
                continue
            with zipfile.ZipFile(reference) as original_wheel:
                originals = [p for p in original_wheel.namelist() if len(PurePosixPath(p).parts) == 2 and p.endswith(".dist-info/RECORD")]
                if len(originals) != 1:
                    reference_failures.append({"name": name, "reason": "pinned wheel has no unique root RECORD"})
                    continue
                original_record = original_wheel.read(originals[0])
            record = site + originals[0]
            if record not in z.NameToInfo or z.read(record) != original_record:
                record_failures.append({"name": name, "path": record, "reason": "packaged RECORD differs from independently pinned original wheel"})
            # A truncated or rewritten ZIP RECORD cannot shrink this checklist.
            for relative, digest, size in csv.reader(io.StringIO(original_record.decode("utf8"))):
                if name == "onnx" and relative.startswith(("onnx/backend/test/", "onnx/test/")):
                    skipped += 1
                    continue
                base = site
                if ".data/" in relative:
                    _, category, relative = relative.split("/", 2)
                    if category == "scripts":
                        skipped += 1
                        continue
                    if category == "data":
                        base = runtime + "python/"
                    elif category not in ("purelib", "platlib"):
                        record_failures.append({"name": name, "reason": "unknown wheel relocation", "category": category})
                        continue
                path = base + relative
                record_count += 1
                if path not in z.NameToInfo:
                    record_failures.append({"name": name, "path": path, "reason": "wheel file missing"})
                    continue
                if size and z.getinfo(path).file_size != int(size):
                    record_failures.append({"name": name, "path": path, "reason": "wheel file size mismatch"})
                if digest:
                    algorithm, expected_hash = digest.split("=", 1)
                    if algorithm != "sha256":
                        record_failures.append({"name": name, "path": path, "reason": "unsupported RECORD digest"})
                        continue
                    with z.open(path) as stream:
                        actual_hex = sha_stream(stream)
                    actual_hash = base64.urlsafe_b64encode(bytes.fromhex(actual_hex)).decode("ascii").rstrip("=")
                    if actual_hash != expected_hash.rstrip("="):
                        record_failures.append({"name": name, "path": path, "reason": "wheel RECORD SHA-256 mismatch"})
        self.check("independently-pinned-dependency-reference-archives", not reference_failures, {"archives": reference_archives, "failures": reference_failures})
        self.check("complete-python-wheel-records", not record_failures and not reference_failures, {"checkedFiles": record_count, "intentionalExcludedFiles": skipped, "exclusions": "unused wheel entry-point scripts and ONNX conformance corpus, as in the installer", "reference": "Original RECORD or sdist from independently SHA-256 pinned cache archives", "failures": record_failures})
        self.require(z, [site + p for p in (
            "partitura/__init__.py", "parangonar/__init__.py", "lxml/etree.cp311-win_amd64.pyd",
            "lark/__init__.py", "xmlschema/__init__.py", "elementpath/__init__.py", "mido/__init__.py",
            "librosa/core/pitch.py", "onnxruntime/capi/onnxruntime_pybind11_state.pyd",
            "onnxruntime/capi/onnxruntime.dll", "numpy/__init__.py", "scipy/__init__.py",
        )], "partitura-and-detector-runtime-files")
        license_missing = []
        for package in ("basic-pitch", "partitura", "parangonar", "librosa", "onnxruntime"):
            info = installed.get(package)
            directory = info["metadata"].rsplit("/", 1)[0] + "/" if info else ""
            matches = [p for p in z.namelist() if directory and p.startswith(directory) and re.search(r"(?:license|copying)", p.rsplit("/", 1)[-1], re.I)]
            if not matches:
                # ONNX Runtime's wheel keeps its license in the import package.
                matches = [p for p in z.namelist() if p.startswith(site + package.replace("-", "_") + "/") and re.search(r"(?:license|copying)", p.rsplit("/", 1)[-1], re.I)]
            if not matches:
                license_missing.append(package)
        self.check("python-engine-license-texts", not license_missing, {"missing": license_missing})

    def runtime(self, z, prefix):
        home = prefix + "tools/local-analysis/"
        lock_path = self.repo / "local-analysis/windows-lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf8"))
        manifest = self.json_member(z, home + "runtime-manifest.json", "runtime-manifest-json")
        ready = self.json_member(z, home + "runtime-ready.json", "runtime-ready-json")
        expected = {
            "engine": "basic-pitch", "version": "0.4.0", "python": lock["python"]["version"], "runtime": "onnx",
            "modelSha256": lock["modelSha256"], "crepeModelSha256": CREPE_ONNX_SHA,
            "lockSha256": sha_file(lock_path), "partitura": "1.9.0", "parangonar": "3.3.3", "librosa": "0.10.2.post1",
            "engines": ["basic-pitch", "pyin", "crepe", "aubio"], "alignmentBaselines": ["parangonar", "nakamura"],
        }
        mismatches = [{"document": label, "field": key, "expected": value, "actual": document.get(key)}
                      for label, document in (("manifest", manifest), ("ready", ready)) for key, value in expected.items() if document.get(key) != value]
        self.check("runtime-manifest-and-lock", not mismatches, {"mismatches": mismatches})
        proof = ready.get("smoke", {})
        weak = []
        for component in COMPONENTS:
            item = proof.get(component, {})
            valid = item.get("passed") is True
            if component in ("basic-pitch", "pyin", "crepe", "aubio"):
                valid = valid and item.get("midi") == 69 and item.get("rawNotesPreserved") is True and item.get("postprocessing") == "waveform-onset-evidence-v1"
                valid = valid and isinstance(item.get("duration"), (int, float)) and item["duration"] > 1
                valid = valid and isinstance(item.get("cents"), (int, float)) and abs(item["cents"] - 25) <= 15
            elif component == "partitura":
                valid = valid and item.get("notes") == 3
            else:
                valid = valid and item.get("pairs") == 3 and bool(item.get("algorithm"))
            if not valid:
                weak.append(component)
        self.check("seven-actual-runtime-readiness-proofs", not weak, {"components": proof, "missingOrInsufficient": weak, "scope": "Stored actual smoke evidence, not fresh execution."})
        models = []
        for name, expected_sha in (("basic-pitch.onnx", lock["modelSha256"]), ("crepe-tiny.onnx", CREPE_ONNX_SHA)):
            path = home + "models/" + name
            actual = None
            if path in z.NameToInfo:
                with z.open(path) as stream:
                    actual = sha_stream(stream)
            models.append({"path": path, "sha256": actual, "expectedSha256": expected_sha})
        self.check("pinned-inference-model-sha256", all(m["sha256"] == m["expectedSha256"] for m in models), {"models": models, "modelCount": 2, "note": "pYIN, aubio and native MPM/YIN are algorithms without learned model weights."})
        actual_models = sorted(p[len(home + "models/"):] for p in z.namelist() if p.startswith(home + "models/") and not p.endswith("/"))
        self.check("served-inference-model-inventory", actual_models == ["basic-pitch.onnx", "crepe-tiny.onnx"], {"actual": actual_models, "expected": ["basic-pitch.onnx", "crepe-tiny.onnx"]})
        self.require(z, [home + p for p in ("python/python.exe", "python/python311.dll", "python/python311.zip", "python/python311._pth", "python/LICENSE.txt", "THIRD-PARTY.txt")], "embedded-python-and-notices")
        self.pe(z, home + "python/python.exe")
        pth_path = home + "python/python311._pth"
        pth = z.read(pth_path).decode("utf8") if pth_path in z.NameToInfo else ""
        self.check("isolated-embedded-python-path", pth.splitlines() == ["python311.zip", ".", "site-packages", "import site"], {"lines": pth.splitlines()})
        for helper in HELPERS:
            self.compare(z, home + helper, self.repo / "local-analysis" / helper, "current-helper:" + helper)
        self.dependencies(z, home, lock)
        native = [(prefix + "bin/NoteLiteAudio.exe", self.repo / "native/audio/build/NoteLiteAudio.exe"),
                  (home + "native/AubioMono.exe", self.repo / "native/audio/build/analysis-tools/AubioMono.exe")]
        native += [(home + "native/nakamura/" + stage + ".exe", self.repo / "native/audio/build/analysis-tools/nakamura" / (stage + ".exe")) for stage in NAKAMURA_STAGES]
        native += [(home + "native/nakamura/libwinpthread-1.dll", self.repo / "native/audio/build/analysis-tools/nakamura/libwinpthread-1.dll")]
        for packaged, reference in native:
            self.pe(z, packaged)
            self.compare(z, packaged, reference, "fresh-native-sha256:" + packaged)
        self.sources(z, home)
        licenses = {
            "licenses/CREPE-MIT.txt": "local-analysis/vendor/crepe/LICENSE",
            "licenses/aubio-GPL3.txt": "local-analysis/vendor/aubio/COPYING",
            "licenses/Nakamura-MIT.txt": "local-analysis/vendor/nakamura/LICENCE.txt",
        }
        for packaged, reference in licenses.items():
            self.compare(z, home + packaged, self.repo / reference, "license:" + packaged)
        for local in sorted((self.repo / "native/audio/vendor/gcc-runtime").iterdir()):
            if local.is_file():
                self.compare(z, home + "licenses/GCC-Runtime/" + local.name, local, "gcc-runtime-license:" + local.name)
        self.compare(z, prefix + "licenses/local-audio/THIRD_PARTY_NOTICES.md", self.repo / "native/audio/THIRD_PARTY_NOTICES.md", "native-third-party-notices")
        self.compare(z, prefix + "licenses/local-audio/miniaudio/LICENSE", self.repo / "native/audio/vendor/miniaudio/LICENSE", "miniaudio-license")
        self.require(z, [home + "python/site-packages/pretty_midi/LICENSE.txt"], "pretty-midi-upstream-license")
        self.check("unused-soundfont-absent", not any(p.lower().endswith(".sf2") for p in z.namelist()), {})

    def run(self):
        self.report.update({"archiveSha256": sha_file(self.archive), "archiveBytes": self.archive.stat().st_size})
        with zipfile.ZipFile(self.archive) as z:
            names = z.namelist()
            self.report.update({"entries": len(names), "uncompressedBytes": sum(x.file_size for x in z.infolist())})
            bad_crc = z.testzip()
            self.check("zip-crc", bad_crc is None, {"firstBadEntry": bad_crc})
            windows_keys = ("/".join(part.rstrip(" .").casefold() for part in x.rstrip("/").split("/")) for x in names)
            duplicates = [p for p, n in Counter(windows_keys).items() if n > 1]
            unsafe = [p for p in names if unsafe_windows_path(p)]
            self.check("safe-unique-windows-paths", not duplicates and not unsafe, {"duplicates": duplicates, "unsafe": unsafe})
            jars = [p for p in names if p.endswith("lib/notelite.jar")]
            if len(jars) != 1:
                raise ValueError("Expected exactly one lib/notelite.jar, found " + str(jars))
            app_jar = jars[0]
            prefix = app_jar[:-len("lib/notelite.jar")]
            self.report["distributionPrefix"] = prefix
            self.require(z, [prefix + "bin/PracticeStudio.bat", app_jar], "windows-application-entry")
            with zipfile.ZipFile(io.BytesIO(z.read(app_jar))) as jar:
                self.check("application-jar-crc", jar.testzip() is None, {"path": app_jar})
                resources = self.repo / "app/res/practice"
                compared = 0
                for local in sorted(resources.rglob("*")):
                    if local.is_file():
                        compared += 1
                        packaged = "res/practice/" + local.relative_to(resources).as_posix()
                        self.compare(jar, packaged, local, "current-embedded-practice-resource:" + local.relative_to(resources).as_posix())
                self.check("embedded-practice-resources-present", compared > 0, {"compared": compared})
                stale = [p for p in jar.namelist() if p.startswith("res/practice/") and not p.endswith("/") and not (resources / p.removeprefix("res/practice/")).is_file()]
                self.check("no-stale-embedded-practice-resources", not stale, {"stale": stale})
                self.no_private_data(jar.namelist(), "no-project-work-or-training-data-in-application-jar")
                self.require(jar, ["res/basic-classifier.zip"], "existing-local-omr-classifier")
            self.runtime(z, prefix)
            self.no_private_data(names, "no-project-work-or-training-data-in-distribution", prefix + "tools/local-analysis/")
        return self.finish()

    def finish(self):
        self.report["passed"] = bool(self.checks) and all(c["passed"] for c in self.checks)
        self.report["passedChecks"] = sum(c["passed"] for c in self.checks)
        self.report["failedChecks"] = [c["name"] for c in self.checks if not c["passed"]]
        return self.report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", nargs="?", type=Path, help="Windows ZIP (or use --zip)")
    parser.add_argument("--zip", dest="zip_path", type=Path)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--cache", type=Path, help="Independent pinned dependency archive cache (default: repository/local-analysis/cache)")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    archive = args.zip_path or args.archive
    if archive is None or args.zip_path is not None and args.archive is not None:
        parser.error("Provide one Windows ZIP path, using a positional argument or --zip")
    if args.output.resolve() == archive.resolve():
        parser.error("The JSON report must not overwrite the input ZIP")
    audit = Audit(archive.resolve(), args.repo.resolve(), args.cache.resolve() if args.cache else None)
    try:
        report = audit.run()
    except Exception as exc:
        audit.check("audit-completed", False, {"error": type(exc).__name__ + ": " + str(exc)})
        report = audit.finish()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"passed": report["passed"], "passedChecks": report["passedChecks"], "failedChecks": report["failedChecks"], "report": str(args.output.resolve())}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
