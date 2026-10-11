#!/usr/bin/env python3
"""Release the native cloud-OMR client after real, exact-commit Apple acceptance.

Signing/profile/keychain handling is shared with the existing audited release
helper. This client bundles Figma UI and local NoteWise only; it never downloads
an embedded OMR/JDK composition and never submits a public App Store release.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import subprocess
import sys
import zipfile

import release

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = "com.lucas0623z.yinban"
TEAM = "G74YSFJX76"
BRAND = "黑白键AI-你的陪练搭子"
WORKFLOW = ".github/workflows/apple-client.yml"
PLATFORMS = {
    "macOS": ("native-clients", "apple-client-test-results"),
    "iPhone": ("iPhone interface", "apple-client-test-results-iPhone"),
    "iPad": ("iPad interface", "apple-client-test-results-iPad"),
}
CORE_TESTS = {
    "FigmaShellUITests/testBundledFigmaScorePersistenceNativeFilePanelsAndPractice",
    "FigmaShellUITests/testNewInteractionsLocalPitchTempoPersistenceAndExport",
}
DIRECTION_TEST = "FigmaShellUITests/testNativeScoreAndPracticeDirectionRestore"
MAC_TESTS = {"FigmaShellUITests/testMacFigmaLandscapeContentWindow", "FigmaShellUITests/testMacFigmaPortraitContentWindow"}
NOTEWISE_TESTS = {
    "NoteWiseTests/testMIDIReleaseVelocityZeroAndRunningStatusKeepCompleteEvents",
    "NoteWiseTests/testSplitMIDIStreamPreservesNoteOffWithoutInventingNotesFromSysex",
    "NoteWiseTests/testActualSharedMPMYINWrapperDetectsA4AndReliableSilenceRelease",
    "NoteWiseTests/testSilenceDoesNotInventCorrectNotesAndStopReleaseIsNotNatural",
    "NoteWiseRecordedTranscriptionTests/testActualBundledCoreMLTranscribesChordAndLaterRepeatedPitch",
    "NoteWiseRecordedTranscriptionTests/testActualBundledCoreMLSilenceDoesNotBecomeCorrectNotes",
    "NoteWiseRecordedTranscriptionTests/testSwiftDecoderMatchesPinnedOfficialPythonReference",
    "NoteWiseRecordedTranscriptionTests/testInvalidActivationAndCancellationAreRejected",
}
MAX_ZIP_FILE = 1024 * 1024 * 1024
MAX_ZIP_TOTAL = 4 * 1024 * 1024 * 1024


def settings():
    values = release.settings()
    mode, upload, bundle, team, _, _ = values
    release.require(bundle == BUNDLE and team == TEAM, "Cloud release must retain the registered bundle ID and team.")
    if mode == "export":
        release.require(os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "Signed export requires manual workflow dispatch.")
        release.require(os.environ.get("GITHUB_REF", "").startswith("refs/heads/"), "Export must use a repository branch commit.")
    return values


def exact_sha(value):
    release.require(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{40}", value), "Expected a full source commit SHA.")
    return value


def validate_native_run(run, jobs, source_sha):
    exact_sha(source_sha)
    release.require(run.get("path") == WORKFLOW and run.get("status") == "completed"
                    and run.get("conclusion") == "success", "Apple client acceptance must be completed and successful.")
    release.require(run.get("head_sha") == source_sha, "Apple acceptance must test the exact release commit.")
    release.require(type(run.get("run_attempt")) is int and run["run_attempt"] > 0, "Acceptance run attempt is missing.")
    required = {job for job, _ in PLATFORMS.values()}
    for name in required:
        matching = [j for j in jobs if j.get("name") == name]
        release.require(len(matching) == 1 and matching[0].get("status") == "completed"
                        and matching[0].get("conclusion") == "success"
                        and matching[0].get("head_sha") == source_sha
                        and matching[0].get("run_attempt") == run["run_attempt"],
                        "All three current-attempt native Apple jobs must pass: " + name)


def test_outcomes(value):
    """Read Xcode's test-case leaves, never a parent suite's green status."""
    result = {}

    def walk(node, ancestry=()):
        if isinstance(node, list):
            for child in node:
                walk(child, ancestry)
        elif isinstance(node, dict):
            context = ancestry + tuple(str(node[k]) for k in ("name", "nodeIdentifier") if k in node)
            if node.get("nodeType") == "Test Case":
                name = str(node.get("name", "")).removesuffix("()")
                identifier = str(node.get("nodeIdentifier", "")).removesuffix("()")
                if "/test" in identifier:
                    components = identifier.split("/")
                    key = "/".join(components[-2:])
                else:
                    suite = next((s for s in reversed(ancestry) if s in {"FigmaShellUITests", "NoteWiseTests", "NoteWiseRecordedTranscriptionTests", "ReleaseFeatureTests", "AccountDeletionNativeTests"}), None)
                    key = (suite + "/" + name) if suite and name.startswith("test") else None
                if key:
                    release.require(key not in result, "Duplicate native test result; release requires one actual result per test.")
                    result[key] = node.get("result")
            for key, child in node.items():
                if isinstance(child, (dict, list)):
                    walk(child, context)

    walk(value)
    release.require(result, "Xcode acceptance contains no recognized actual test-case results.")
    return result


def required_tests(platform):
    release.require(platform in PLATFORMS, "Unknown Apple acceptance platform.")
    required = CORE_TESTS | NOTEWISE_TESTS | (MAC_TESTS if platform == "macOS" else {DIRECTION_TEST})
    # Any added NoteWise inference regression in this exact source must also pass.
    source = (ROOT / "apple/NoteLiteTests/NoteWiseTests.swift").read_text(encoding="utf-8")
    required |= {"NoteWiseTests/" + name for name in re.findall(r"\bfunc\s+(test[A-Za-z0-9_]+)\s*\(", source)}
    source = (ROOT / "apple/NoteLiteTests/ReleaseFeatureTests.swift").read_text(encoding="utf-8")
    required |= {"ReleaseFeatureTests/" + name for name in re.findall(r"\bfunc\s+(test[A-Za-z0-9_]+)\s*\(", source)}
    source = (ROOT / "apple/NoteLiteTests/AccountDeletionNativeTests.swift").read_text(encoding="utf-8")
    required |= {"AccountDeletionNativeTests/" + name for name in re.findall(r"\bfunc\s+(test[A-Za-z0-9_]+)\s*\(", source)}
    return required


def validate_test_results(platform, value, summary):
    outcomes = test_outcomes(value)
    release.require(summary.get("result") == "Passed" and summary.get("failedTests") == 0
                    and summary.get("passedTests", 0) > 0, "The actual Xcode test bundle did not pass.")
    required = required_tests(platform)
    release.require(all(outcomes.get(name) == "Passed" for name in required),
                    "A required core, interaction, direction or NoteWise test is missing, skipped or failed: " + platform)
    return {"platform": platform, "requiredTests": sorted(required), "actualResults": {n: outcomes[n] for n in sorted(required)},
            "actualPassedTests": summary["passedTests"], "actualFailedTests": summary["failedTests"]}


def safe_unzip(source, destination):
    release.require(not destination.exists(), "Use a fresh ZIP verification directory.")
    with zipfile.ZipFile(source) as archive:
        names, total = set(), 0
        for entry in archive.infolist():
            name = PurePosixPath(entry.filename)
            release.require(entry.filename and "\\" not in entry.filename and ":" not in entry.filename
                            and not name.is_absolute() and ".." not in name.parts
                            and not any(ord(c) < 32 for c in entry.filename), "Unsafe artifact ZIP path.")
            release.require(name.as_posix().casefold() not in names, "Duplicate artifact ZIP path.")
            names.add(name.as_posix().casefold())
            release.require((entry.external_attr >> 16) & 0o170000 != 0o120000, "Artifact symbolic links are forbidden.")
            total += entry.file_size
            release.require(entry.file_size <= MAX_ZIP_FILE and total <= MAX_ZIP_TOTAL, "Artifact ZIP exceeds release size limits.")
        destination.mkdir(mode=0o700)
        archive.extractall(destination)


def gh_json(endpoint):
    return json.loads(release.run(["gh", "api", endpoint], capture=True))


def acceptance():
    settings()
    private, output = release.paths()
    source_sha = exact_sha(os.environ.get("GITHUB_SHA"))
    release.require(release.run(["git", "rev-parse", "HEAD"], capture=True).strip() == source_sha,
                    "Working checkout differs from the release commit.")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    identifier = os.environ.get("RELEASE_ACCEPTANCE_RUN", "")
    release.require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository), "Invalid acceptance repository.")
    release.require(re.fullmatch(r"[1-9][0-9]*", identifier), "Specify the successful exact-commit Apple client workflow run ID.")
    run = gh_json(f"repos/{repository}/actions/runs/{identifier}")
    release.require(str(run.get("id")) == identifier and run.get("head_repository", {}).get("full_name") == repository,
                    "Acceptance must belong to this repository.")
    jobs = gh_json(f"repos/{repository}/actions/runs/{identifier}/attempts/{run.get('run_attempt')}/jobs?per_page=100")
    release.require(jobs.get("total_count", 0) <= 100, "Unexpected acceptance job count.")
    validate_native_run(run, jobs.get("jobs", []), source_sha)
    artifacts = gh_json(f"repos/{repository}/actions/runs/{identifier}/artifacts?per_page=100")
    release.require(artifacts.get("total_count", 0) <= 100, "Unexpected acceptance artifact count.")
    proof = Path(os.environ["RUNNER_TEMP"]) / "notelite-native-acceptance"
    release.require(not proof.exists(), "Acceptance output already exists; use a fresh runner.")
    proof.mkdir(mode=0o700)
    reports = []
    for platform, (_, artifact_name) in PLATFORMS.items():
        matches = [a for a in artifacts.get("artifacts", []) if a.get("name") == artifact_name]
        release.require(len(matches) == 1 and not matches[0].get("expired"), "Missing unexpired native acceptance artifact: " + platform)
        artifact = matches[0]
        release.require(artifact.get("workflow_run", {}).get("head_sha") == source_sha
                        and artifact.get("created_at", "") >= run.get("run_started_at", "~"),
                        "Acceptance artifact is from another commit or a previous attempt.")
        expected = artifact.get("digest", "")
        release.require(re.fullmatch(r"sha256:[a-f0-9]{64}", expected), "Acceptance artifact has no GitHub SHA256 provenance.")
        downloaded = proof / (platform + ".zip")
        with downloaded.open("wb") as stream:
            response = subprocess.run(["gh", "api", f"repos/{repository}/actions/artifacts/{artifact['id']}/zip"], stdout=stream, stderr=subprocess.PIPE)
        release.require(response.returncode == 0 and release.digest(downloaded) == expected.split(":")[1],
                        "Downloaded native acceptance artifact failed its GitHub checksum.")
        extracted = proof / platform
        safe_unzip(downloaded, extracted)
        results = list(extracted.rglob("TestResults-" + platform + ".xcresult"))
        release.require(len(results) == 1 and results[0].is_dir(), "Actual platform XCResult is missing or ambiguous.")
        summary = json.loads(release.run(["xcrun", "xcresulttool", "get", "test-results", "summary", "--path", str(results[0])], capture=True))
        tests = json.loads(release.run(["xcrun", "xcresulttool", "get", "test-results", "tests", "--path", str(results[0])], capture=True))
        reports.append({**validate_test_results(platform, tests, summary), "artifactId": artifact["id"], "artifactSHA256": expected.split(":")[1]})
    evidence = {"status": "passed", "sourceCommit": source_sha, "workflow": WORKFLOW,
                "runId": int(identifier), "runAttempt": run["run_attempt"], "runURL": run["html_url"],
                "actualNativeAcceptance": reports, "scope": "iPhone/iPad simulators and macOS with a native virtual test display"}
    path = Path(os.environ["RUNNER_TEMP"]) / "notelite-cloud-acceptance.json"
    path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print("Verified actual core, interaction, orientation and NoteWise test results for all three Apple platforms.")


def acceptance_evidence():
    path = Path(os.environ["RUNNER_TEMP"]) / "notelite-cloud-acceptance.json"
    release.require(path.is_file() and not path.is_symlink(), "Run native acceptance verification before archiving.")
    evidence = json.loads(path.read_text(encoding="utf-8"))
    release.require(evidence.get("status") == "passed" and evidence.get("sourceCommit") == exact_sha(os.environ.get("GITHUB_SHA"))
                    and evidence.get("workflow") == WORKFLOW
                    and {e.get("platform") for e in evidence.get("actualNativeAcceptance", [])} == set(PLATFORMS),
                    "Release acceptance evidence is incomplete or from another commit.")
    return evidence


def resource_inventory(root):
    release.require(root.is_dir() and not root.is_symlink(), "Required bundled resource directory is missing.")
    files = {}
    for path in sorted(root.rglob("*")):
        release.require(not path.is_symlink(), "Bundled resource links are forbidden.")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = {"bytes": path.stat().st_size, "sha256": release.digest(path)}
    release.require(files, "Required bundled resources are empty.")
    return files


def verify_resources(app):
    resource_gate_spec = importlib.util.spec_from_file_location("cloud_resource_gate", ROOT / "packaging/cloud-client-release/release.py")
    resource_gate = importlib.util.module_from_spec(resource_gate_spec)
    resource_gate_spec.loader.exec_module(resource_gate)
    reports = {}
    for name, source in (("FigmaUI", ROOT / "apple/FigmaUI"), ("practice", ROOT / "app/res/practice")):
        expected, actual = resource_inventory(source), resource_inventory(app / name)
        release.require(expected == actual, "Archived " + name + " resources differ from the actual production build.")
        for relative in actual:
            try:
                resource_gate.policy(name + "/" + relative)
                resource_gate.scan_content(name + "/" + relative, (app / name / relative).read_bytes())
            except resource_gate.GateError as error:
                raise release.ReleaseError(str(error)) from None
        reports[name] = actual
    for name in ("MODEL-LOCK.json", "THIRD-PARTY.txt", "BASIC-PITCH-LICENSE"):
        original = release.contained_file(ROOT / "apple/NoteWiseModels", name)
        actual = release.contained_file(app, name)
        release.require(release.digest(original) == release.digest(actual), "NoteWise model lock or license differs from its source.")
    original_profiles = release.contained_file(ROOT / "apple/NoteLite", "NoteWiseProfiles.json")
    actual_profiles = release.contained_file(app, "NoteWiseProfiles.json")
    release.require(release.digest(original_profiles) == release.digest(actual_profiles),
                    "Actual packaged NoteWise instrument profiles differ from the verified shared resolver.")
    reports["NoteWiseProfiles.json"] = {"bytes": actual_profiles.stat().st_size, "sha256": release.digest(actual_profiles)}
    reports["NoteWiseBasicPitch.mlmodelc"] = resource_inventory(app / "NoteWiseBasicPitch.mlmodelc")
    for path in app.rglob("*"):
        name = path.relative_to(app).as_posix()
        folded = {p.casefold() for p in path.relative_to(app).parts}
        release.require(not path.is_symlink() and not folded & {"omrresources", "tessdata", "runtime", "embeddedruntime", "private", "skills", "recordings", "fixtures", "__pycache__"}
                        and path.suffix.lower() not in {".jar", ".jmod", ".class", ".p12", ".pfx", ".pem", ".key", ".sqlite", ".sqlite3", ".db", ".log", ".map", ".xctest", ".xcresult"},
                        "Unexpected engine, private, source-map or test payload in the native client: " + name)
    return reports


def code_signature(app, private, expected_profile, expected_fingerprint):
    release.run(["codesign", "--verify", "--deep", "--strict", str(app)], capture=True)
    description = subprocess.run(["codesign", "-d", "--verbose=4", str(app)], capture_output=True, text=True)
    release.require(description.returncode == 0 and re.search(r"^TeamIdentifier=" + TEAM + r"$", description.stderr + description.stdout, re.M),
                    "Actual code signature belongs to another team.")
    entitlements = plistlib.loads(release.run(["codesign", "-d", "--entitlements", ":-", str(app)], capture=True).encode())
    profile = plistlib.loads(release.run(["security", "cms", "-D", "-i", str(release.contained_file(app, "embedded.mobileprovision"))], capture=True).encode())
    certificates = release.validate_profile(profile, BUNDLE, TEAM)
    release.require(profile["UUID"] == expected_profile and expected_fingerprint in certificates,
                    "Actual embedded distribution profile differs from the validated signing profile.")
    release.require(entitlements.get("application-identifier") == profile["Entitlements"]["application-identifier"]
                    and entitlements.get("com.apple.developer.team-identifier") == TEAM
                    and not entitlements.get("get-task-allow", False), "Actual signed app entitlements do not match distribution identity.")
    certificate_prefix = private / ("archive-signer-" if app.parent.name == "Applications" else "ipa-signer-")
    release.run(["codesign", "-d", "--extract-certificates", str(certificate_prefix), str(app)], capture=True)
    certificate = Path(str(certificate_prefix) + "0")
    release.require(certificate.is_file() and hashlib.sha1(certificate.read_bytes()).hexdigest().upper() == expected_fingerprint,
                    "Actual app was signed with another certificate.")
    return {"signatureVerified": True, "team": TEAM, "bundleIdentifier": BUNDLE, "distributionProfileValidated": True}


def verify_app(app, private, version, build, *, signing=None):
    info = plistlib.loads(release.contained_file(app, "Info.plist").read_bytes())
    release.require(info.get("CFBundleIdentifier") == BUNDLE and info.get("CFBundleDisplayName") == BRAND
                    and info.get("CFBundleShortVersionString") == version and str(info.get("CFBundleVersion")) == build,
                    "Actual app identity, display name, version or build differs from the requested release.")
    release.require(set(info.get("UIDeviceFamily", [])) == {1, 2} and "iPhoneOS" in info.get("CFBundleSupportedPlatforms", []),
                    "Archive must be an actual iPhone/iPad device build.")
    sdk = re.fullmatch(r"iphoneos(\d+)(?:\.\d+)*", info.get("DTSDKName", ""))
    release.require(sdk and int(sdk[1]) >= 26, "Archive requires the iOS 26 device SDK or later.")
    binary = release.contained_file(app, info["CFBundleExecutable"])
    release.run(["xcrun", "lipo", str(binary), "-verify_arch", "arm64"], capture=True)
    commands = release.run(["xcrun", "vtool", "-show-build", str(binary)], capture=True)
    release.require(re.search(r"\bplatform\s+IOS\b", commands) and "IOSSIMULATOR" not in commands, "Archive executable is not an iOS device binary.")
    symbols = release.run(["xcrun", "nm", "-gU", str(binary)], capture=True)
    release.require(not any(marker in symbols for marker in ("JNI_CreateJavaVM", "JNI_OnLoad_jnitesseract", "JNI_OnLoad_jnileptonica", "CGVirtualDisplay", "NoteWiseTestProbe")),
                    "App includes server OMR, private display infrastructure or a test-only audio probe.")
    resources = verify_resources(app)
    signature = code_signature(app, private, *signing) if signing else {"signatureVerified": False}
    return {"bundleIdentifier": BUNDLE, "displayName": BRAND, "version": version, "build": build,
            "deviceFamilies": [1, 2], "sdk": info["DTSDKName"], "architecture": "arm64", "executableSHA256": release.digest(binary),
            "resources": resources, "embeddedOMR": False, "bundledLocalNoteWise": True, **signature}


def archive():
    mode, upload, bundle, team, version, build = settings()
    private, output = release.paths()
    evidence = acceptance_evidence()
    release.require(not private.exists() and not output.exists(), "Use a fresh hosted runner for a release archive.")
    private.mkdir(mode=0o700); output.mkdir()
    credentials = {name: os.environ.pop(name, "") for name in ("IOS_DISTRIBUTION_P12_BASE64", "IOS_DISTRIBUTION_P12_PASSWORD", "IOS_APP_STORE_PROFILE_BASE64", "ASC_API_KEY_ID", "ASC_API_ISSUER_ID", "ASC_API_PRIVATE_KEY_BASE64")}
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        os.environ.pop(name, None)
    try:
        project = ROOT / "apple/NoteLite.xcodeproj"
        release.require(project.is_dir(), "Generate the standard cloud-client Xcode project first.")
        # The shared instrument resolver and original model are checked again
        # immediately before Xcode; neither silently rewrites a stale profile.
        release.run(["node", str(ROOT / "apple/scripts/prepare-notewise-profiles.mjs")], capture=True)
        release.run([sys.executable, str(ROOT / "apple/scripts/prepare-notewise-model.py")], capture=True)
        release.run([sys.executable, str(ROOT / "apple/scripts/prepare-release-features.py"), "--check"], capture=True)
        archive_path = private / "NoteLite-cloud.xcarchive"
        command = ["xcodebuild", "archive", "-project", str(project), "-scheme", "NoteLite", "-configuration", "Release",
                   "-destination", "generic/platform=iOS", "-archivePath", str(archive_path), "-derivedDataPath", str(private / "DerivedData"),
                   f"PRODUCT_BUNDLE_IDENTIFIER={bundle}", f"DEVELOPMENT_TEAM={team}", f"MARKETING_VERSION={version}", f"CURRENT_PROJECT_VERSION={build}"]
        signing = None
        if upload:
            release.require(re.fullmatch(r"[A-Z0-9]{10}", credentials["ASC_API_KEY_ID"]), "Missing or invalid ASC_API_KEY_ID.")
            release.require(re.fullmatch(r"[a-fA-F0-9-]{36}", credentials["ASC_API_ISSUER_ID"]), "Missing or invalid ASC_API_ISSUER_ID.")
            release.decode_secret(credentials["ASC_API_PRIVATE_KEY_BASE64"], private / "api-key.p8", "ASC_API_PRIVATE_KEY_BASE64")
            release.run(["openssl", "pkey", "-in", str(private / "api-key.p8"), "-noout"], capture=True)
        if mode == "export":
            signing = release.install_signing(private, bundle, team, credentials)
            command += ["CODE_SIGN_STYLE=Manual", f"PROVISIONING_PROFILE_SPECIFIER={signing[0]}", f"CODE_SIGN_IDENTITY={signing[1]}"]
        else:
            command += ["CODE_SIGNING_ALLOWED=NO", "CODE_SIGNING_REQUIRED=NO", "CODE_SIGN_IDENTITY="]
        release.run(command, capture=True)
        apps = list((archive_path / "Products/Applications").glob("*.app"))
        release.require(len(apps) == 1, "Archive must contain exactly one application.")
        actual = verify_app(apps[0], private, version, build, signing=signing)
        report = {"status": "passed", "mode": mode, "publishedToAppStore": False, "uploadedToAppStoreConnect": False,
                  "sourceCommit": exact_sha(os.environ.get("GITHUB_SHA")), "projectSpecificationSHA256": release.digest(ROOT / "apple/project.yml"),
                  "acceptance": evidence, "actualArchive": actual}
        if signing:
            options = {"method": "app-store-connect", "destination": "export", "teamID": team, "signingStyle": "manual",
                       "signingCertificate": signing[1], "provisioningProfiles": {bundle: signing[0]},
                       "manageAppVersionAndBuildNumber": False, "stripSwiftSymbols": True, "uploadSymbols": False}
            export_options = private / "ExportOptions.plist"; export_options.write_bytes(plistlib.dumps(options))
            exports = private / "export"
            release.run(["xcodebuild", "-exportArchive", "-archivePath", str(archive_path), "-exportPath", str(exports), "-exportOptionsPlist", str(export_options)], capture=True)
            ipas = list(exports.glob("*.ipa")); release.require(len(ipas) == 1, "Signed export must produce exactly one IPA.")
            extracted = private / "ipa-verification"; safe_unzip(ipas[0], extracted)
            exported_apps = list((extracted / "Payload").glob("*.app"))
            release.require(len(exported_apps) == 1, "Exported IPA must contain exactly one Payload app.")
            report["actualIPA"] = verify_app(exported_apps[0], private, version, build, signing=signing)
            package = output / (BRAND + ".ipa"); shutil.copy2(ipas[0], package)
        else:
            package = output / (BRAND + "-iOS-device-unsigned.xcarchive.zip")
            release.run(["ditto", "-c", "-k", "--keepParent", str(archive_path), str(package)], capture=True)
        report["package"] = {"name": package.name, "bytes": package.stat().st_size, "sha256": release.digest(package)}
        if upload:
            keys = private / "private_keys"; keys.mkdir(mode=0o700)
            (private / "api-key.p8").rename(keys / ("AuthKey_" + credentials["ASC_API_KEY_ID"] + ".p8"))
            os.environ["API_PRIVATE_KEYS_DIR"] = str(keys)
            auth = ["--apiKey", credentials["ASC_API_KEY_ID"], "--apiIssuer", credentials["ASC_API_ISSUER_ID"]]
            # Apple receives only the actual verified signed IPA. This command
            # cannot submit review, release publicly or enable external testers.
            release.run(["xcrun", "altool", "--validate-app", "-f", str(package), "-t", "ios", *auth], capture=True)
            release.run(["xcrun", "altool", "--upload-app", "-f", str(package), "-t", "ios", *auth], capture=True)
            report["uploadedToAppStoreConnect"] = True
            report["testFlightProcessingVerified"] = False
        (output / "cloud-release-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (output / "SHA256SUMS.txt").write_text(report["package"]["sha256"] + "  " + package.name + "\n", encoding="utf-8")
        print("Verified " + mode + " package for " + BRAND + ("; Apple accepted the upload for processing." if upload else ".") + " Public App Store release was not submitted.")
    finally:
        release.cleanup()


def prepare():
    settings()
    release.prepare()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "acceptance", "archive", "cleanup"))
    arguments = parser.parse_args()
    try:
        {"prepare": prepare, "acceptance": acceptance, "archive": archive, "cleanup": release.cleanup}[arguments.command]()
    except (release.ReleaseError, OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        # Static gate errors only: never print Xcode/security/provider output or credentials.
        print("Cloud release stopped: " + str(error), file=sys.stderr)
        sys.exit(1)
