#!/usr/bin/env python3
"""Create and verify a commit-bound corresponding-source notice, never legal approval.

Run `prepare` before XcodeGen. Generated SOURCE-OFFER.json is ignored by Git so
each build refers to its actual commit instead of the previous release. The
release verifier compares this document and all legal resources in the app.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "Lucas0623z/NoteLite"
STATIC_NAMES = ("AGPL-3.0-LICENSE.txt", "AUDIVERISCORE-NOTICE.md", "CORRESPONDING-SOURCE.md", "AUDIVERISCORE-PROVENANCE.json")
SOURCE_OFFER = "SOURCE-OFFER.json"
UPSTREAM_COMMIT = "b02fd4f8e31bf3dee1124bf4956e60fcca7f00a0"
# Hash of the full existing AGPL v3 text after CRLF -> LF normalization. Actual
# installed bytes must still equal the source file, without normalization.
AGPL_TEXT_SHA256 = "76a97c878c9c7a8321bb395c2b44d3fe2f8d81314d219b20138ed0e2dddd5182"
SOURCE_ROOTS = ("apple/AudiverisCore", "apple/NoteLite", "apple/NoteLiteTests", "apple/NoteLiteUITests", "native/audio", "app/src",
                "figma-ui", "practice-web", "apple/scripts", "apple/release", "apple/Legal",
                "apple/NoteWiseModels", "apple/project.yml", ".github/workflows",
                "tools/audiveris-port")


class LegalResourceError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise LegalResourceError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_full_agpl(path):
    require(hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == AGPL_TEXT_SHA256,
            "The unchanged full AGPL v3 license text is required; a URL or excerpt is insufficient.")


def source_inventory(root):
    """List the full translated package, including build recipe and oracle data.

    This sub-inventory is a tamper/provenance check, not a definition that limits
    Corresponding Source. The linked client and its build scripts are offered
    through the complete repository archive at the same commit.
    """
    base = root / "apple/AudiverisCore"
    require(base.is_dir() and not base.is_symlink(), "AudiverisCore source package is missing or linked.")
    paths = sorted(p for p in base.rglob("*") if p.is_file())
    require(all(not p.is_symlink() for p in base.rglob("*")), "Corresponding-source links are forbidden.")
    names = {p.relative_to(base).as_posix() for p in paths}
    required = {"LICENSE", "NOTICE.md", "Package.swift", "Sources/AudiverisCore/Binarization.swift",
                "Sources/AudiverisCore/Image.swift", "Sources/AudiverisCore/Runs.swift",
                "Tests/AudiverisCoreTests/Fixtures/manifest.json"}
    require(required <= names, "Corresponding-source package is incomplete.")
    # SPM build products are not source. Never accidentally publish a runtime
    # inventory or a developer's local paths instead of the versioned package.
    paths = [p for p in paths if not any(part.startswith(".") or part == "__pycache__"
                                       for part in p.relative_to(base).parts)]
    return {p.relative_to(root).as_posix(): {"bytes": p.stat().st_size, "sha256": digest(p)} for p in paths}


def offer(root, commit, repository=REPOSITORY):
    require(isinstance(commit, str) and re.fullmatch(r"[a-f0-9]{40}", commit), "Expected an exact source commit for the license offer.")
    require(repository == REPOSITORY, "Source offer must use the authorized public NoteLite repository.")
    url = "https://github.com/" + repository
    provenance = json.loads((root / "apple/Legal/AUDIVERISCORE-PROVENANCE.json").read_text(encoding="utf-8"))
    require(provenance.get("verifiedUpstreamReference", {}).get("commit") == UPSTREAM_COMMIT,
            "AudiverisCore upstream reference is missing or changed without a provenance update.")
    return {"schemaVersion": 1, "sourceCommit": commit, "repository": url,
            "sourceTreeURL": url + "/tree/" + commit,
            "sourceArchiveURL": url + "/archive/" + commit + ".tar.gz",
            "sourceAvailability": "no charge; public exact-commit repository archive",
            "license": "AGPL-3.0-or-later for Audiveris-derived code; original licenses apply to other portions",
            "correspondingSourceScope": "Complete repository archive includes the translated package, linked Apple client, source inputs and build/installation scripts; the package inventory below does not narrow this scope.",
            "buildInstructionsURL": url + "/blob/" + commit + "/apple/Legal/CORRESPONDING-SOURCE.md",
            "sourceRoots": list(SOURCE_ROOTS),
            "translatedPackageInventory": source_inventory(root),
            "upstreamProvenance": provenance,
            "distributionCompatibility": "not established by this notice; App Store terms, installation information and all rights-holder permissions require separate review"}


def encoded_offer(root, commit, repository=REPOSITORY):
    return (json.dumps(offer(root, commit, repository), ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def verify_packaged(root, resources, commit, repository=REPOSITORY):
    """Check the actual app's resources, independent of simulator or signing tools."""
    source = root / "apple/Legal"
    installed = resources / "Legal"
    require(installed.is_dir() and not installed.is_symlink(), "Actual app Legal resource directory is missing or linked.")
    paths = sorted(installed.rglob("*"))
    require(all(not path.is_symlink() for path in paths), "Actual app legal resource links are forbidden.")
    actual = {p.relative_to(installed).as_posix(): {"bytes": p.stat().st_size, "sha256": digest(p)}
              for p in paths if p.is_file()}
    expected_names = set(STATIC_NAMES) | {SOURCE_OFFER}
    require(set(actual) - {".gitignore"} == expected_names,
            "Actual app legal resources are missing or contain unexpected files.")
    for name in set(actual) - {SOURCE_OFFER}:
        original = source / name
        require(original.is_file() and not original.is_symlink()
                and original.read_bytes() == (installed / name).read_bytes(),
                "Actual app legal notice or full license differs from source: " + name)
    require((installed / "AGPL-3.0-LICENSE.txt").read_bytes() == (root / "apple/AudiverisCore/LICENSE").read_bytes(),
            "Actual app must contain the full unchanged AudiverisCore AGPL license.")
    verify_full_agpl(installed / "AGPL-3.0-LICENSE.txt")
    expected = encoded_offer(root, commit, repository)
    generated = source / SOURCE_OFFER
    require(generated.is_file() and not generated.is_symlink()
            and (installed / SOURCE_OFFER).read_bytes() == generated.read_bytes() == expected,
            "Actual app corresponding-source offer is stale, incomplete or from another commit/source bytes.")
    return {"files": actual, "sourceCommit": commit, "sourceArchiveURL": json.loads(expected)["sourceArchiveURL"],
            "actualAppLicenseBytesVerified": True, "distributionCompatibilityEstablished": False}


def git(root, *args):
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    require(result.returncode == 0, "Cannot verify exact Git source for the legal resources.")
    return result.stdout.strip()


def current_commit(root):
    head = git(root, "rev-parse", "HEAD")
    selected = os.environ.get("GITHUB_SHA", head)
    require(selected == head, "Source offer cannot point to a different checkout commit.")
    require(not git(root, "status", "--porcelain", "--untracked-files=all", "--", *SOURCE_ROOTS),
            "Commit corresponding source before generating distributable legal resources.")
    require(os.environ.get("GITHUB_REPOSITORY", REPOSITORY) == REPOSITORY,
            "This release must offer source from the authorized public NoteLite repository.")
    return selected


def prepare(root=ROOT, check=False):
    commit = current_commit(root)
    license_path = root / "apple/Legal/AGPL-3.0-LICENSE.txt"
    verify_full_agpl(license_path)
    require(license_path.read_bytes() == (root / "apple/AudiverisCore/LICENSE").read_bytes(),
            "Bundled AGPL text must be the full unchanged package license.")
    for name in STATIC_NAMES:
        require((root / "apple/Legal" / name).is_file() and not (root / "apple/Legal" / name).is_symlink(),
                "A static legal resource is missing or linked.")
    data = encoded_offer(root, commit)
    target = root / "apple/Legal" / SOURCE_OFFER
    if check:
        require(target.is_file() and not target.is_symlink() and target.read_bytes() == data,
                "Generated source offer is missing, stale or from different source bytes.")
    else:
        require(not target.is_symlink(), "Generated source offer must not be a link.")
        target.write_bytes(data)
    return commit


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "check", "verify"))
    parser.add_argument("--resources", type=Path, help="Actual .app root on iOS or .app/Contents/Resources on macOS.")
    arguments = parser.parse_args()
    try:
        commit = prepare(check=arguments.command != "prepare")
        if arguments.command == "verify":
            require(arguments.resources is not None, "Specify the actual app resources to verify.")
            verify_packaged(ROOT, arguments.resources, commit)
            print("Verified actual packaged full license, notices and exact-commit corresponding source offer; distribution compatibility remains a separate review.")
        else:
            require(arguments.resources is None, "Resources are only valid for actual app verification.")
            print("Verified exact-commit legal resource source inputs; distribution compatibility is a separate review.")
    except (LegalResourceError, OSError, ValueError) as error:
        parser.exit(1, "Legal resource preparation stopped: " + str(error) + "\n")
