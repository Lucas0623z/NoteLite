#!/usr/bin/env python3
"""Offline cloud-client packaging gates. Never read signing keys or deploy services."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import subprocess
import sys
import zipfile

REPO = Path(__file__).resolve().parents[2]
MAX_FILE = 512 * 1024 * 1024
MAX_TOTAL = 4 * 1024 * 1024 * 1024
FORBIDDEN_DIRS = {".git", ".svn", "node_modules", "src", "sources", "server", "private", "credentials",
                  "secrets", "user-data", "userdata", "recordings", "takes", "practice-history", "jobs",
                  "__pycache__", "test-output", "fixtures", "tessdata", "omrresources", "embeddedruntime"}
DEBUG_SUFFIXES = {".map", ".pdb", ".dSYM", ".xcresult", ".xctest", ".log"}
PRIVATE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".dpapi", ".sqlite", ".sqlite3", ".db", ".secret"}
SOURCE_SUFFIXES = {".ts", ".tsx", ".swift", ".java", ".class", ".jar", ".py", ".pyc", ".cpp", ".h", ".mm",
                   ".mjs", ".cjs", ".ps1", ".sh", ".c", ".o", ".obj", ".a", ".xcconfig", ".pbxproj"}
USER_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".mp4", ".pdf", ".omr", ".mxl", ".mid"}
WEB_SUFFIXES = {".html", ".js", ".css", ".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".avif",
                ".ico", ".woff", ".woff2", ".ttf", ".otf", ".txt", ".json", ".musicxml"}
DEBUG_MARKERS = (b"--uitesting-figma", b"noteLiteDiagnostics", b"NOTELITE_UI_TEST_SCORE", b"/@vite/client")
OMR_MARKERS = (b"JNI_CreateJavaVM", b"JNI_OnLoad_jnitesseract", b"JNI_OnLoad_jnileptonica", b"com/notelite/omr/EmbeddedOmrEngine")
SECRET_PATTERNS = (
    rb"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----",
    rb"\bsk-[A-Za-z0-9_-]{24,}\b",
    rb"(?i)[\"'](?:accessToken|apiKey|api_key|upstream_token|internal_key|deviceToken)[\"']\s*:\s*[\"'][A-Za-z0-9_+/=-]{24,}[\"']",
    rb"(?i)Bearer [A-Za-z0-9_-]{32,}(?![A-Za-z0-9_-])",
)


class GateError(Exception):
    pass


def require(value, message):
    if not value:
        raise GateError(message)


def safe_name(name):
    parts = name.split("/")
    require(name and "\\" not in name and not PurePosixPath(name).is_absolute()
            and all(p not in {"", ".", ".."} and not any(ord(c) < 32 or c in '<>:"|?*' for c in p)
                    and not p.endswith((" ", ".")) for p in parts), "Unsafe release path.")
    reserved = {"con", "prn", "aux", "nul", "clock$", "conin$", "conout$"}
    reserved.update(x + y for x in ("com", "lpt") for y in "123456789¹²³")
    require(all(p.split(".", 1)[0].casefold() not in reserved for p in parts), "Reserved release path.")


def policy(name, *, allow_maps=False):
    safe_name(name)
    path = PurePosixPath(name)
    folded = [p.casefold() for p in path.parts]
    # Fail before opening any forbidden private/user file. Values never enter reports.
    require(not any(p in FORBIDDEN_DIRS or p.endswith((".dsym", ".xcresult", ".xctest")) for p in folded),
            "Forbidden source, server, debug or user-data path: " + name)
    require(not path.name.casefold().startswith(".env") and path.suffix.lower() not in PRIVATE_SUFFIXES,
            "Private credential/database path: " + name)
    require(path.suffix.lower() not in SOURCE_SUFFIXES, "Source or Java OMR payload is forbidden: " + name)
    require(path.suffix.lower() not in USER_SUFFIXES and (path.suffix.lower() not in {".xml", ".musicxml"}
            or name in {"practice/demo.musicxml", "demo.musicxml"}), "User recording/score payload is forbidden: " + name)
    require(not re.search(r"(?:jnitesseract|jnileptonica|omr-midi|audiveris-omr|access-token|account-token|pairing-code)", name, re.I),
            "Server engine or credential payload is forbidden: " + name)
    debug = path.suffix.lower() in {s.lower() for s in DEBUG_SUFFIXES}
    require(allow_maps and path.suffix.lower() == ".map" or not debug, "Debug artifact is forbidden: " + name)
    require(path.suffix.lower() not in {".zip", ".tar", ".gz", ".7z"}, "Nested opaque archive is forbidden: " + name)


def scan_content(name, data):
    require(not any(marker in data for marker in DEBUG_MARKERS), "Development/test marker in release file: " + name)
    require(not any(marker in data for marker in OMR_MARKERS), "Embedded server OMR engine in release file: " + name)
    require(not any(re.search(pattern, data) for pattern in SECRET_PATTERNS), "Credential-shaped content in release file: " + name)
    if PurePosixPath(name).suffix.lower() in {".js", ".css", ".html"}:
        require(not re.search(rb"[#@]\s*sourceMappingURL\s*=", data), "Sourcemap reference in release file: " + name)


def audit_tree(root, *, allow_maps=False):
    root = root.resolve()
    require(root.is_dir(), "Release input must be a directory.")
    files, folded, total = {}, set(), 0
    # No traversal through symlinks/junctions; a release must contain its own files.
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink() and not (hasattr(path, "is_junction") and path.is_junction()),
                "Links are not accepted in this cloud-client release format.")
        name = path.relative_to(root).as_posix()
        if path.is_dir():
            policy(name + "/directory-placeholder")
            continue
        require(path.is_file(), "Unsupported release file type.")
        policy(name, allow_maps=allow_maps)
        require(name.casefold() not in folded, "Case-insensitive duplicate release path.")
        folded.add(name.casefold())
        size = path.stat().st_size
        total += size
        require(size <= MAX_FILE and total <= MAX_TOTAL, "Release payload exceeds size limits.")
        if allow_maps and path.suffix.lower() == ".map":
            continue
        data = path.read_bytes()
        scan_content(name, data)
        files[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": size}
    require(files, "Release payload is empty.")
    return files


def notices_for_figma(node_modules):
    pending = [(name, node_modules.parent) for name in ("react", "react-dom", "opensheetmusicdisplay")]
    seen, notices = set(), []
    while pending:
        name, parent = pending.pop()
        require(re.fullmatch(r"(?:@[a-z0-9_.-]+/)?[a-z0-9_.-]+", name), "Invalid dependency name.")
        # Follow Node's ancestor node_modules lookup from the real package path.
        # pnpm stores transitive dependencies beside each resolved package.
        parent = parent.resolve()
        directory = next((ancestor / "node_modules" / name for ancestor in (parent, *parent.parents)
                          if (ancestor / "node_modules" / name / "package.json").is_file()), None)
        require(directory is not None, "Missing installed runtime dependency: " + name)
        directory = directory.resolve()
        if directory in seen:
            continue
        seen.add(directory)
        metadata = json.loads((directory / "package.json").read_text(encoding="utf8"))
        license_text = None
        for candidate in ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENSE-MIT", "LICENSE-MIT.txt", "LICENSE.markdown", "license", "license.md", "COPYING"):
            if (directory / candidate).is_file():
                license_text = (directory / candidate).read_text(encoding="utf8")
                break
        if license_text is None and name in {"fft.js", "isarray"}:
            marker = "#### LICENSE" if name == "fft.js" else "## License"
            readme = (directory / "README.md").read_text(encoding="utf8")
            if marker in readme:
                license_text = readme.split(marker, 1)[1]
        require(license_text and len(license_text.strip()) > 50, "Missing runtime dependency license: " + name)
        notices.append(f"--- {name} {metadata['version']} ({metadata.get('license', 'see notice')}) ---\n{license_text}\n")
        pending.extend((dependency, directory) for dependency in metadata.get("dependencies", {}))
    return "NoteLite Figma client runtime dependencies\n\n" + "\n".join(sorted(notices))


def prepare(figma_dist, practice, output, *, repo=REPO):
    # Build outputs are consumed exactly; this does not edit either UI or build config.
    figma_files = audit_tree(figma_dist, allow_maps=True)
    practice_files = audit_tree(practice, allow_maps=True)
    require(all(PurePosixPath(name).suffix.lower() in WEB_SUFFIXES for name in {*figma_files, *practice_files}),
            "Prepared web resources contain a non-web payload.")
    require("index.html" in figma_files and "index.html" in practice_files and "THIRD-PARTY.txt" in practice_files,
            "Both built UIs and the Windows practice notices are required.")
    require(not output.exists(), "Choose a new output directory; existing data is never overwritten.")
    license_text = (repo / "LICENSE").read_text(encoding="utf8")
    figma_notices = notices_for_figma(repo / "figma-ui/node_modules")
    output.mkdir(parents=True)
    for prefix, source, files in (("FigmaUI", figma_dist, figma_files), ("practice", practice, practice_files)):
        for name in files:
            target = output / prefix / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, target)
    (output / "LICENSE.txt").write_text(license_text, encoding="utf8")
    (output / "FigmaUI/THIRD-PARTY.txt").write_text(figma_notices, encoding="utf8")
    inventory = audit_tree(output)
    manifest = {"schemaVersion": 1, "scope": "cloud-client web resources; not an installable or signed native application",
                "serverOMRIncluded": False, "signed": False, "readyForDistribution": False, "files": inventory}
    (output / "RELEASE-MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf8")
    return manifest


def verify_inventory(root, *, web=False):
    inventory = audit_tree(root)
    manifest_path = root / "RELEASE-MANIFEST.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf8"))
        actual = {name: value for name, value in inventory.items() if name != "RELEASE-MANIFEST.json"}
        require(manifest.get("files") == actual and manifest.get("serverOMRIncluded") is False,
                "Release files changed or were added after preparation.")
    require(any(PurePosixPath(name).name in {"LICENSE", "LICENSE.txt"} for name in inventory), "Retain the application license.")
    require(any(PurePosixPath(name).name == "THIRD-PARTY.txt" for name in inventory), "Retain third-party notices.")
    if web:
        require(manifest_path.is_file() and "FigmaUI/index.html" in inventory and "practice/index.html" in inventory,
                "Use prepare for web resource candidates.")
    return inventory


def command(args, *, messages=False):
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    result = subprocess.run(args, capture_output=True, text=True, **options)
    require(result.returncode == 0, "Platform signature verification failed.")
    return result.stdout + result.stderr if messages else result.stdout


def verify_signature(root, platform, publisher):
    require(publisher and len(publisher) <= 160, "An expected signing team/publisher is required.")
    if platform in {"ios", "macos"}:
        require(sys.platform == "darwin", "Apple signatures must be verified on macOS with codesign.")
        require(root.suffix == ".app", "Apple release input must be the final signed .app.")
        info = root / ("Contents/Info.plist" if platform == "macos" else "Info.plist")
        plist = plistlib.loads(info.read_bytes())
        require(isinstance(plist.get("CFBundleExecutable"), str) and "/" not in plist["CFBundleExecutable"], "Invalid native executable name.")
        safe_name(plist["CFBundleExecutable"])
        executable = root / ("Contents/MacOS" if platform == "macos" else "") / plist["CFBundleExecutable"]
        require(executable.is_file(), "Native application executable is missing.")
        command(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(root)])
        description = command(["codesign", "-d", "--verbose=4", str(root)], messages=True)
        require(re.search(r"^TeamIdentifier=" + re.escape(publisher) + r"$", description, re.M), "Unexpected Apple signing team.")
        require("Signature=adhoc" not in description, "Ad hoc signatures are not distribution signing.")
        authority = "Authority=Developer ID Application:" if platform == "macos" else "Authority=Apple Distribution:"
        require(authority in description, "A platform distribution signing identity is required.")
        entitlements = command(["codesign", "-d", "--entitlements", ":-", str(root)], messages=True)
        start = entitlements.find("<?xml")
        end = entitlements.find("</plist>", start)
        require(start >= 0 and end >= 0, "Signed application entitlements could not be verified.")
        values = plistlib.loads(entitlements[start:end + len("</plist>")].encode())
        require(not values.get("get-task-allow") and not values.get("com.apple.security.get-task-allow"), "Development/debug signing cannot be released.")
        if platform == "macos":
            require(re.search(r"flags=[^\n]*\([^\n]*\bruntime\b", description), "macOS requires hardened runtime signing.")
            command(["spctl", "--assess", "--type", "execute", "--verbose=2", str(root)])
        else:
            require("iPhoneSimulator" not in plist.get("CFBundleSupportedPlatforms", []), "Simulator builds cannot be released.")
            profile = plistlib.loads(command(["security", "cms", "-D", "-i", str(root / "embedded.mobileprovision")]).encode())
            require(not profile.get("ProvisionedDevices") and not profile.get("ProvisionsAllDevices")
                    and not profile.get("Entitlements", {}).get("get-task-allow"), "iOS requires App Store distribution provisioning.")
            expires = profile.get("ExpirationDate")
            require(isinstance(expires, datetime), "Provisioning expiration is unavailable.")
            expires = expires.replace(tzinfo=timezone.utc) if expires.tzinfo is None else expires
            require(expires > datetime.now(timezone.utc) and publisher in profile.get("TeamIdentifier", [])
                    and "iOS" in profile.get("Platform", []), "Provisioning is expired or belongs to another team/platform.")
            app_id = profile.get("Entitlements", {}).get("application-identifier")
            require(app_id == values.get("application-identifier") and app_id in
                    [prefix + "." + plist["CFBundleIdentifier"] for prefix in profile.get("ApplicationIdentifierPrefix", [])],
                    "Provisioning does not match the exact signed application.")
        return {"platform": platform, "verified": True, "publisher": publisher}
    require(platform == "windows" and os.name == "nt", "Windows signatures must be verified on Windows.")
    binaries = sorted(p for p in root.rglob("*") if p.suffix.lower() in {".exe", ".dll", ".msi"})
    require(any(p.suffix.lower() == ".exe" for p in binaries), "A resource folder is not a Windows application.")
    for binary in binaries:
        quoted = str(binary).replace("'", "''")
        script = "$s=Get-AuthenticodeSignature -LiteralPath '" + quoted + "';@{status=$s.Status.ToString();publisher=$s.SignerCertificate.Subject;timestamp=($null -ne $s.TimeStamperCertificate)}|ConvertTo-Json -Compress"
        value = json.loads(command(["powershell", "-NoProfile", "-NonInteractive", "-Command", script]))
        require(value.get("status") == "Valid" and value.get("publisher") == publisher and value.get("timestamp") is True,
                "Windows executable/library requires a valid timestamped signature from the expected publisher.")
    return {"platform": platform, "verified": True, "publisher": publisher, "signedBinaries": len(binaries)}


def package(root, output, platform, publisher=None):
    inventory = verify_inventory(root, web=platform == "web-candidate")
    signature = {"verified": False}
    if platform != "web-candidate":
        signature = verify_signature(root, platform, publisher)
    report_path = output.with_suffix(output.suffix + ".report.json")
    require(not output.exists() and not report_path.exists() and not output.resolve().is_relative_to(root.resolve()), "Choose a new archive outside the release input.")
    output.parent.mkdir(parents=True, exist_ok=True)
    prefix = "Payload/" + root.name if platform == "ios" else root.name
    created = False
    try:
        archive = zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED)
        created = True
        with archive:
            for name in inventory:
                archive.write(root / name, prefix + "/" + name)
        # Re-read the actual archive; compare every payload byte to the audited source.
        with zipfile.ZipFile(output) as archive:
            require(len(archive.infolist()) == len(inventory), "Archive file count changed.")
            for name, expected in inventory.items():
                data = archive.read(prefix + "/" + name)
                require(len(data) == expected["bytes"] and hashlib.sha256(data).hexdigest() == expected["sha256"], "Archive byte verification failed.")
        report = {"status": "passed", "platform": platform, "scope": "native signature and packaged bytes" if signature["verified"] else "web resources only",
                  "signature": signature, "readyForDistribution": signature["verified"], "serverOMRIncluded": False,
                  "archiveSha256": hashlib.sha256(output.read_bytes()).hexdigest(), "fileCount": len(inventory)}
        with report_path.open("x", encoding="utf8") as file:
            file.write(json.dumps(report, indent=2) + "\n")
        return report
    except Exception:
        if created:
            output.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    stage = commands.add_parser("prepare")
    stage.add_argument("--figma-dist", type=Path, default=REPO / "figma-ui/dist")
    stage.add_argument("--practice", type=Path, default=REPO / "app/res/practice")
    stage.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--input", type=Path, required=True)
    pack = commands.add_parser("package")
    pack.add_argument("--input", type=Path, required=True)
    pack.add_argument("--output", type=Path, required=True)
    pack.add_argument("--platform", choices=["web-candidate", "ios", "macos", "windows"], required=True)
    pack.add_argument("--publisher")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare(args.figma_dist, args.practice, args.output)
            print(json.dumps({"status": "passed", "fileCount": len(result["files"]), "signed": False, "readyForDistribution": False}))
        elif args.command == "verify":
            print(json.dumps({"status": "passed", "fileCount": len(verify_inventory(args.input)), "signatureChecked": False, "readyForDistribution": False}))
        else:
            print(json.dumps(package(args.input, args.output, args.platform, args.publisher)))
    except (GateError, OSError, ValueError, KeyError) as error:
        print("Release gate rejected: " + str(error), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
