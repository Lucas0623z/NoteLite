#!/usr/bin/env python3
"""Transfer the exact signed build-for-testing products, never test results.

The producer and consumers remain in one GitHub run at one source commit.
test-without-building uses the original xctestrun and its relative placeholders;
no generated plist, executable, environment, signature or test filter is edited.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import plistlib
import posixpath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import unicodedata


ARCHIVE_ROOT = "SimulatorTestProducts"
TARGETS = {"NoteLiteTests", "NoteLiteUITests"}
IDENTITY_FIELDS = ("sourceCommit", "runId", "runAttempt", "toolchain", "sourceInputs")
LEGAL_NAMES = {"AGPL-3.0-LICENSE.txt", "AUDIVERISCORE-NOTICE.md", "CORRESPONDING-SOURCE.md",
               "AUDIVERISCORE-PROVENANCE.json", "SOURCE-OFFER.json"}
MAX_MEMBERS = 100000
MAX_BYTES = 16 * 1024 ** 3
INPUTS = ("practice-web/package-lock.json", "figma-ui/pnpm-lock.yaml", "apple/project.yml",
          "apple/NoteLite/NoteWiseProfiles.json", "apple/NoteWiseModels/MODEL-LOCK.json",
          "apple/NoteWiseModels/DIVIDE-NO-NAN-PATCH.json", "apple/NoteWiseModels/BASIC-PITCH-LICENSE",
          "apple/NoteWiseModels/THIRD-PARTY.txt", "apple/scripts/simulator_test_products.py",
          "apple/scripts/prepare-figma-ui.py", "apple/scripts/prepare-notewise-model.py",
          "apple/scripts/prepare-notewise-profiles.mjs", "apple/scripts/select-xcode.sh",
          "apple/release/legal_resources.py", ".github/workflows/apple-client.yml")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    attributes = path.lstat()
    require(stat.S_ISREG(attributes.st_mode) and not path.is_symlink() and attributes.st_size <= MAX_BYTES,
            "Hash input must be a bounded ordinary file")
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def within(path, root):
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (ValueError, OSError, RuntimeError) as error:
        raise ValueError("Product path escaped its permitted root or is missing") from error
    return path.resolve(strict=True)


def no_link_ancestors(path):
    for candidate in (path, *path.parents):
        require(not candidate.is_symlink(), "An extraction destination ancestor is a symlink")


def tree_inventory(root: Path) -> dict:
    """Full bytes, modes and bounded link targets, without following directory links."""
    require(root.is_dir() and not root.is_symlink(), "Missing ordinary inventory root")
    result = {}
    folded = set()
    total = 0
    for directory, names, files in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in sorted(names + files):
            path = base / name
            relative = path.relative_to(root).as_posix()
            folded_path = unicodedata.normalize("NFC", relative).casefold()
            require(folded_path not in folded, "Case-insensitive product path collision")
            folded.add(folded_path)
            attributes = path.lstat()
            require(not attributes.st_mode & 0o7000, "Privileged product file modes are forbidden")
            if path.is_symlink():
                target = os.readlink(path)
                require(not Path(target).is_absolute() and "\\" not in target and "\0" not in target,
                        "Absolute product links are forbidden")
                within(path, root)
                require(path.name not in LEGAL_NAMES and "Legal" not in path.relative_to(root).parts,
                        "Legal resources cannot be symlinks")
                result[relative] = {"type": "symlink", "target": target,
                                    "mode": stat.S_IMODE(attributes.st_mode)}
            elif stat.S_ISREG(attributes.st_mode):
                total += attributes.st_size
                require(total <= MAX_BYTES, "Product tree is too large")
                result[relative] = {"type": "file", "bytes": attributes.st_size,
                                    "sha256": sha256(path), "mode": stat.S_IMODE(attributes.st_mode)}
            else:
                require(stat.S_ISDIR(attributes.st_mode), "Special product files are forbidden")
        require(len(folded) <= MAX_MEMBERS, "Product tree has too many members")
    return result


def _extract_validated_archive(archive: Path, destination: Path) -> Path:
    """Validate all members first, then extract ordinary files before internal links."""
    no_link_ancestors(destination.absolute())
    require(not destination.exists() or (destination.is_dir() and not any(destination.iterdir())),
            "Extraction destination must be empty")
    destination.mkdir(parents=True, exist_ok=True)
    anchor = destination.resolve(strict=True)
    with tarfile.open(archive, "r:gz") as source:
        entries = source.getmembers()
        require(0 < len(entries) <= MAX_MEMBERS, "Invalid archive member count")
        mapped = {}
        folded = set()
        total = 0
        for member in entries:
            raw = member.name.rstrip("/")
            pieces = PurePosixPath(raw).parts
            require(raw and not raw.startswith("/") and "\\" not in raw and ":" not in raw and "\0" not in raw
                    and all(piece not in (".", "..") for piece in raw.split("/"))
                    and pieces[0] == ARCHIVE_ROOT, "Unsafe archive member path")
            folded_path = unicodedata.normalize("NFC", raw).casefold()
            require(folded_path not in folded, "Duplicate archive path")
            folded.add(folded_path)
            require(member.isdir() or member.isfile() or member.issym() or member.islnk(),
                    "Special archive members are forbidden")
            require(not member.mode & 0o7000 and member.size >= 0, "Invalid archive mode or size")
            total += member.size
            require(total <= MAX_BYTES, "Archive uncompressed size is too large")
            mapped[raw] = member
            if member.issym() or member.islnk():
                target = member.linkname
                require(target and not target.startswith("/") and "\\" not in target and ":" not in target and "\0" not in target,
                        "Absolute or invalid archive link")
                require(PurePosixPath(raw).name not in LEGAL_NAMES and "Legal" not in pieces,
                        "Legal resources cannot be linked")
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(raw), target)
                                             if member.issym() else target)
                require(resolved == ARCHIVE_ROOT or resolved.startswith(ARCHIVE_ROOT + "/"),
                        "Archive link escaped its own root")
        require(ARCHIVE_ROOT in mapped and mapped[ARCHIVE_ROOT].isdir(), "Archive root is missing")
        for name, member in mapped.items():
            for parent in PurePosixPath(name).parents:
                if str(parent) == ".":
                    break
                require(str(parent) not in mapped or mapped[str(parent)].isdir(),
                        "An archive member has a non-directory ancestor")
            if member.islnk():
                require(member.linkname in mapped and mapped[member.linkname].isfile(),
                        "Archive hard link must name an ordinary internal file")
        # Files never pass through an archive-created symlink, even if tar order changes.
        for name, member in sorted(mapped.items(), key=lambda pair: (len(PurePosixPath(pair[0]).parts), pair[0])):
            output = anchor.joinpath(*PurePosixPath(name).parts)
            no_link_ancestors(output.parent)
            require(output.absolute().is_relative_to(anchor), "Archive output escaped destination")
            if member.isdir():
                output.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                output.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as input_stream, output.open("xb") as output_stream:
                    shutil.copyfileobj(input_stream, output_stream, 1024 * 1024)
                require(output.stat().st_size == member.size, "Truncated archive member")
                output.chmod(member.mode)
                os.utime(output, (member.mtime, member.mtime))
        for name, member in mapped.items():
            if not (member.issym() or member.islnk()):
                continue
            output = anchor.joinpath(*PurePosixPath(name).parts)
            no_link_ancestors(output.parent)
            output.parent.mkdir(parents=True, exist_ok=True)
            if member.issym():
                output.symlink_to(member.linkname)
                os.utime(output, (member.mtime, member.mtime), follow_symlinks=False)
            else:
                target = anchor.joinpath(*PurePosixPath(member.linkname).parts)
                within(target, anchor / ARCHIVE_ROOT)
                os.link(target, output)
                os.utime(output, (member.mtime, member.mtime))
        for name, member in mapped.items():
            if member.issym():
                within(anchor.joinpath(*PurePosixPath(name).parts), anchor / ARCHIVE_ROOT)
        for name, member in sorted(mapped.items(), reverse=True):
            if member.isdir():
                output = anchor.joinpath(*PurePosixPath(name).parts)
                output.chmod(member.mode)
                os.utime(output, (member.mtime, member.mtime))
    return anchor / ARCHIVE_ROOT


def safe_extract(archive: Path, destination: Path) -> Path:
    try:
        attributes = archive.lstat()
        require(stat.S_ISREG(attributes.st_mode) and not archive.is_symlink() and attributes.st_size <= MAX_BYTES,
                "Archive input must be a bounded ordinary file")
        return _extract_validated_archive(archive, destination)
    except (tarfile.TarError, OSError) as error:
        raise ValueError("Invalid or unreadable simulator product archive") from error


def _targets(document):
    require(isinstance(document, dict), "xctestrun root must be a dictionary")
    metadata = document.get("__xctestrun_metadata__", {})
    require(isinstance(metadata, dict), "Invalid xctestrun metadata")
    version = metadata.get("FormatVersion", 1)
    require(version in (1, 2), "Unsupported xctestrun format")
    if version == 1:
        require("TestConfigurations" not in document, "Mixed xctestrun formats")
        values = [(name, item) for name, item in document.items() if name != "__xctestrun_metadata__"]
    else:
        configurations = document.get("TestConfigurations")
        require(isinstance(configurations, list) and len(configurations) == 1,
                "Exactly one complete test configuration is required")
        configuration = configurations[0]
        require(isinstance(configuration, dict) and configuration.get("IsEnabled", True) is True,
                "Test configuration is disabled or invalid")
        items = configuration.get("TestTargets")
        require(isinstance(items, list), "Missing test targets")
        values = [(item.get("BlueprintName"), item) for item in items if isinstance(item, dict)]
        require(len(values) == len(items), "Invalid test target")
    require(len(values) == 2 and {name for name, _ in values} == TARGETS,
            "The complete NoteLiteTests and NoteLiteUITests targets are required")
    require(all(isinstance(item, dict) for _, item in values), "Invalid test target dictionary")
    return version, values


def _runtime_path(value, products, platforms, host=None):
    require(isinstance(value, str) and value and "\n" not in value and "\0" not in value
            and "\\" not in value, "Invalid xctestrun runtime path")
    choices = {"__TESTROOT__": products, "__PLATFORMS__": platforms}
    if host is not None:
        choices["__TESTHOST__"] = host
    token, separator, suffix = value.partition("/")
    require(token in choices and (separator or token == "__TESTHOST__"),
            "Nonportable absolute or unrecognized xctestrun runtime path")
    require(all(part not in (".", "..") for part in suffix.split("/")),
            "Escaping xctestrun runtime path")
    root = choices[token]
    output = root / suffix if suffix else root
    within(output, platforms if token == "__PLATFORMS__" else products)
    return output


def validate_xctestrun(document: dict, products: Path, platforms: Path) -> dict:
    """Accept original format 1/2 plists only; never synthesize or alter a plist."""
    version, targets = _targets(document)
    def reject_filters(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ("OnlyTestIdentifiers", "SkipTestIdentifiers", "OnlyTestConfigurations", "SkipTestConfigurations"):
                    require(not item, "Filtered native test runs are forbidden")
                if key in ("IsEnabled",) and item is False:
                    raise ValueError("Disabled native tests are forbidden")
                reject_filters(item)
        elif isinstance(value, list):
            for item in value:
                reject_filters(item)
    reject_filters(document)
    summary = {"formatVersion": version, "targets": []}
    hosts, runners = set(), set()
    for name, target in targets:
        require(target.get("IsUITestBundle", False) is (name == "NoteLiteUITests"),
                "Unexpected native test target type")
        host = _runtime_path(target.get("TestHostPath"), products, platforms)
        require(host.is_dir() and host.suffix == ".app", "Missing test host app")
        bundle = _runtime_path(target.get("TestBundlePath"), products, platforms, host)
        require(bundle.is_dir() and bundle.suffix == ".xctest" and bundle.stem == name,
                "Missing or contradictory test bundle")
        environment = target.get("EnvironmentVariables")
        require(isinstance(environment, dict) and environment.get("NOTELITE_LIVE_ACCOUNT_ACCEPTANCE") == "1",
                "Live account acceptance must be baked into both test targets")
        for key in ("NOTELITE_SIM_SWIFT_PATH", "DYLD_FALLBACK_LIBRARY_PATH"):
            require(environment.get(key, "") == "", "Simulator Swift paths must remain empty")
        path_keys = []
        for key, value in target.items():
            if key.endswith("Path") and key not in ("TestHostPath", "TestBundlePath", "BlueprintPath"):
                _runtime_path(value, products, platforms, host)
                path_keys.append(key)
            elif key.endswith("Paths"):
                require(isinstance(value, list), "Invalid runtime path list")
                for path in value:
                    _runtime_path(path, products, platforms, host)
                path_keys.append(key)
            elif key.endswith("EnvironmentVariables"):
                require(isinstance(value, dict), "Invalid test environment")
                for env_key, env_value in value.items():
                    if env_key in ("DYLD_FRAMEWORK_PATH", "DYLD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES"):
                        require(isinstance(env_value, str), "Invalid dynamic loader environment")
                        for path in env_value.split(":"):
                            if path:
                                _runtime_path(path, products, platforms, host)
        if name == "NoteLiteUITests":
            application = _runtime_path(target.get("UITargetAppPath"), products, platforms, host)
            require(application.is_dir() and application.name == "NoteLite.app", "Missing UI target app")
            hosts.add(application.relative_to(products).as_posix())
            runners.add(host.relative_to(products).as_posix())
        else:
            require(host.name == "NoteLite.app", "Unexpected unit test host")
            hosts.add(host.relative_to(products).as_posix())
        summary["targets"].append({"name": name, "host": host.relative_to(products).as_posix(),
                                   "bundle": bundle.relative_to(products).as_posix(),
                                   "runtimePathKeys": sorted(path_keys),
                                   "environmentKeys": sorted(environment), "liveAccountAcceptance": True})
    require(len(hosts) == len(runners) == 1, "Targets do not share the same actual host")
    summary.update({"hostApp": hosts.pop(), "uiRunnerApp": runners.pop()})
    return summary


def describe_xctestrun(document):
    """Small structural diagnostics, including when validation fails; no environment values."""
    version, targets = _targets(document)
    return {"formatVersion": version, "targets": [
        {"name": name, "keys": sorted(target),
         "environmentKeys": sorted(target.get("EnvironmentVariables", {}))
         if isinstance(target.get("EnvironmentVariables"), dict) else [],
         "liveAccountAcceptance": target.get("EnvironmentVariables", {}).get("NOTELITE_LIVE_ACCOUNT_ACCEPTANCE") == "1"
         if isinstance(target.get("EnvironmentVariables"), dict) else False}
        for name, target in targets]}


def assert_identity(manifest: dict, expected: dict) -> None:
    require(isinstance(manifest, dict) and isinstance(expected, dict), "Invalid product identity")
    for key in IDENTITY_FIELDS:
        require(key in expected and key in manifest and manifest[key] == expected[key],
                "Simulator product identity differs: " + key)


def command(*arguments):
    return subprocess.run(arguments, check=True, capture_output=True, text=True, timeout=120).stdout.strip()


def current_identity(repo):
    commit = command("git", "-C", str(repo), "rev-parse", "HEAD")
    require(re.fullmatch(r"[a-f0-9]{40}", commit) and commit == os.environ.get("GITHUB_SHA"),
            "Expected a clean checkout of the exact GitHub source commit")
    require(os.environ.get("GITHUB_REPOSITORY") == "Lucas0623z/NoteLite", "Unexpected source repository")
    require(not command("git", "-C", str(repo), "diff", "HEAD", "--", *INPUTS), "Source inputs are dirty")
    inputs = {}
    for relative in INPUTS:
        raw = subprocess.run(["git", "-C", str(repo), "show", commit + ":" + relative],
                             check=True, capture_output=True, timeout=60).stdout
        require((repo / relative).read_bytes() == raw, "Source input differs from Git checkout: " + relative)
        inputs[relative] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    developer = os.environ.get("DEVELOPER_DIR")
    require(developer and Path(developer).is_dir(), "Select an exact stable Xcode first")
    toolchain = {"developerDirectory": developer, "xcodebuild": command("xcodebuild", "-version"),
                 "simulatorSDKVersion": command("xcrun", "--sdk", "iphonesimulator", "--show-sdk-version"),
                 "simulatorSDKBuild": command("xcrun", "--sdk", "iphonesimulator", "--show-sdk-build-version"),
                 "simulatorSDKPath": command("xcrun", "--sdk", "iphonesimulator", "--show-sdk-path"),
                 "architecture": platform.machine()}
    require(toolchain["architecture"] == "arm64", "Expected the original arm64 simulator build architecture")
    require(re.fullmatch(r"[0-9]+", os.environ.get("GITHUB_RUN_ID", "")) and
            re.fullmatch(r"[0-9]+", os.environ.get("GITHUB_RUN_ATTEMPT", "")), "Missing current GitHub run identity")
    return {"sourceCommit": commit, "runId": os.environ["GITHUB_RUN_ID"],
            "runAttempt": os.environ["GITHUB_RUN_ATTEMPT"], "toolchain": toolchain, "sourceInputs": inputs}


def verify_resources(repo, products, plan, expected=None):
    app = products / plan["hostApp"]
    runner = products / plan["uiRunnerApp"]
    for signed in (app, runner):
        command("codesign", "--verify", "--strict", str(signed))
    command("python3", "-B", str(repo / "apple/release/legal_resources.py"), "verify", "--resources", str(app))
    for notice in ("MODEL-LOCK.json", "DIVIDE-NO-NAN-PATCH.json", "BASIC-PITCH-LICENSE", "THIRD-PARTY.txt"):
        require((repo / "apple/NoteWiseModels" / notice).read_bytes() == (app / notice).read_bytes(),
                "Actual model provenance differs from the current source: " + notice)
    require((repo / "apple/NoteLite/NoteWiseProfiles.json").read_bytes() == (app / "NoteWiseProfiles.json").read_bytes(),
            "Actual instrument profiles differ from the current source")
    resources = {name: tree_inventory(app / name) for name in ("FigmaUI", "practice", "NoteWiseBasicPitch.mlmodelc")}
    require(all(resources.values()), "Generated UI, practice or model resources are missing")
    if expected is None:
        for name, original in (("FigmaUI", repo / "apple/FigmaUI"), ("practice", repo / "app/res/practice")):
            require(resources[name] == tree_inventory(original), "Actual app differs from its generated resources: " + name)
    else:
        require(resources == expected, "Transferred generated resources differ from the actual producer app")
    return resources


def output(name, value):
    require("\n" not in str(value) and "\r" not in str(value), "Invalid workflow output")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
        stream.write(name + "=" + str(value) + "\n")


def package(repo, archive):
    identity = current_identity(repo)
    derived = Path.home() / "Library/Developer/Xcode/DerivedData"
    candidates = sorted(derived.glob("NoteLite-*/Build/Products/*.xctestrun"))
    require(len(candidates) == 1, "Expected exactly one original NoteLite xctestrun product")
    original = candidates[0]
    products = original.parent
    platforms = Path(identity["toolchain"]["developerDirectory"]) / "Platforms"
    document = plistlib.loads(original.read_bytes())
    print(json.dumps({"originalXctestrunStructure": describe_xctestrun(document)}, indent=2), flush=True)
    plan = validate_xctestrun(document, products, platforms)
    resources = verify_resources(repo, products, plan)
    inventory = tree_inventory(products)
    manifest = {"schemaVersion": 1, **identity, "products": inventory, "xctestrun": original.name,
                "testPlan": plan, "generatedResources": resources}
    no_link_ancestors(archive.parent)
    archive.parent.mkdir(parents=True, exist_ok=True)
    require(not archive.exists() and not archive.is_symlink(), "Refusing to replace a simulator product archive")
    with tempfile.TemporaryDirectory(prefix="notelite-simulator-products-") as folder:
        root = Path(folder) / ARCHIVE_ROOT
        root.mkdir()
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with tarfile.open(archive, "w:gz", dereference=False) as destination:
            destination.add(root, arcname=ARCHIVE_ROOT)
            destination.add(products, arcname=ARCHIVE_ROOT + "/Products", recursive=True)
    output("archive_sha256", sha256(archive))
    # Bounded diagnostics describe actual fields; scheme/environment values are not dumped.
    print(json.dumps({"sourceCommit": identity["sourceCommit"], "xctestrun": original.name,
                      "testPlan": plan, "productFiles": len(inventory)}, indent=2))


def restore(repo, archive, destination, expected_sha):
    require(re.fullmatch(r"[a-f0-9]{64}", expected_sha) and sha256(archive) == expected_sha,
            "Simulator product archive differs from the producer's checksum")
    expected = current_identity(repo)
    root = safe_extract(archive, destination)
    manifest_path = root / "manifest.json"
    require(manifest_path.is_file() and not manifest_path.is_symlink() and manifest_path.stat().st_size <= 20 * 1024 ** 2,
            "Missing or invalid product manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(manifest.get("schemaVersion") == 1, "Unsupported product manifest")
    assert_identity(manifest, expected)
    require({item.name for item in root.iterdir()} == {"Products", "manifest.json"}, "Unexpected product archive roots")
    products = root / "Products"
    require(tree_inventory(products) == manifest.get("products"), "Transferred product bytes, paths or modes differ")
    name = manifest.get("xctestrun")
    require(isinstance(name, str) and Path(name).name == name and name.endswith(".xctestrun"), "Invalid xctestrun name")
    require([p.name for p in products.glob("*.xctestrun")] == [name], "Unexpected additional xctestrun files")
    xctestrun = products / name
    plan = validate_xctestrun(plistlib.loads(xctestrun.read_bytes()), products,
                              Path(expected["toolchain"]["developerDirectory"]) / "Platforms")
    require(plan == manifest.get("testPlan"), "Transferred test plan differs")
    verify_resources(repo, products, plan, manifest.get("generatedResources"))
    evidence = {"sourceCommit": expected["sourceCommit"], "runId": expected["runId"],
                "runAttempt": expected["runAttempt"], "archiveSHA256": expected_sha,
                "toolchain": expected["toolchain"], "testPlan": plan,
                "fullProductInventoryVerified": True, "generatedResourcesVerified": True,
                "hostAndRunnerSignaturesVerified": True, "actualTestResults": "not run by this helper"}
    diagnostics = repo / "apple/Screenshots/native-diagnostics"
    diagnostics.mkdir(parents=True, exist_ok=True)
    (diagnostics / "simulator-product-transfer.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    output("xctestrun_path", xctestrun.resolve())
    print("Same-run signed products and unfiltered original test plan verified; no test result generated.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("package", "restore"))
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--expected-sha256")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    if args.action == "package":
        package(repo, args.archive.absolute())
    else:
        require(args.destination is not None and args.expected_sha256 is not None, "Restore requires destination and producer checksum")
        restore(repo, args.archive.absolute(), args.destination.absolute(), args.expected_sha256)


if __name__ == "__main__":
    main()
