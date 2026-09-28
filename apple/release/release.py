#!/usr/bin/env python3
"""Build iOS archives on an ephemeral macOS GitHub runner; keep keys out of git."""

import base64
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import zipfile


class ReleaseError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise ReleaseError(message)


def run(args, *, capture=False):
    # Never echo argv: security import/keychain arguments contain passwords.
    result = subprocess.run(args, check=False, capture_output=capture, text=True)
    if result.returncode:
        raise ReleaseError(f"{Path(args[0]).name} failed (exit {result.returncode}).")
    return result.stdout if capture else ""


def settings():
    mode = os.environ.get("RELEASE_MODE", "verify")
    upload = os.environ.get("RELEASE_UPLOAD", "false")
    bundle = os.environ.get("RELEASE_BUNDLE_ID", "")
    team = os.environ.get("RELEASE_TEAM_ID", "")
    version = os.environ.get("RELEASE_VERSION", "")
    build = os.environ.get("RELEASE_BUILD_NUMBER", "")
    require(mode in ("verify", "export"), "Mode must be verify or export.")
    require(upload in ("true", "false"), "Upload must be true or false.")
    require(upload == "false" or mode == "export", "Upload requires export mode.")
    require(re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", bundle), "Invalid bundle ID.")
    require(mode == "verify" or re.fullmatch(r"[A-Z0-9]{10}", team), "Export requires a 10-character Team ID.")
    require(re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version), "Version must have three numeric components.")
    require(re.fullmatch(r"[1-9][0-9]*(?:\.[0-9]+){0,2}", build), "Invalid build number.")
    return mode, upload == "true", bundle, team, version, build


def paths():
    require(sys.platform == "darwin", "This release workflow requires macOS and full Xcode.")
    require(os.environ.get("GITHUB_ACTIONS") == "true", "Use this script on an ephemeral GitHub-hosted runner.")
    temp = Path(os.environ["RUNNER_TEMP"]).resolve()
    return temp / "yinban-release-private", temp / "yinban-release-output"


def prepare():
    settings()
    paths()
    candidates = []
    for app in Path("/Applications").glob("Xcode*.app"):
        info_path = app / "Contents/Info.plist"
        if not info_path.is_file() or re.search(r"beta|rc|preview", str(app.resolve()), re.I):
            continue
        info = plistlib.loads(info_path.read_bytes())
        version = info.get("CFBundleShortVersionString", "")
        if re.fullmatch(r"\d+(?:\.\d+)*", version):
            candidates.append((tuple(map(int, version.split("."))), app.resolve()))
    require(candidates, "No stable Xcode installation found.")
    version, app = max(candidates, key=lambda row: row[0])
    require(version[0] >= 26, "App Store uploads require Xcode 26 or later.")
    developer = str(app / "Contents/Developer")
    os.environ["DEVELOPER_DIR"] = developer
    sdk = run(["xcrun", "--sdk", "iphoneos", "--show-sdk-version"], capture=True).strip()
    require(int(sdk.split(".")[0]) >= 26, "App Store uploads require the iOS 26 SDK or later.")
    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as output:
        output.write(f"DEVELOPER_DIR={developer}\n")
    run(["xcodebuild", "-version"])
    print(f"iOS device SDK: {sdk}")


def validate_profile(profile, bundle, team, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    entitlements = profile.get("Entitlements", {})
    expires = profile.get("ExpirationDate")
    require(isinstance(expires, dt.datetime), "Provisioning profile has no expiration date.")
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=dt.timezone.utc)
    require(expires > now, "Provisioning profile has expired.")
    require(team in profile.get("TeamIdentifier", []), "Profile belongs to another developer team.")
    require(entitlements.get("com.apple.developer.team-identifier") == team,
            "Profile team entitlement does not match the requested team.")
    prefixes = profile.get("ApplicationIdentifierPrefix", [])
    require(entitlements.get("application-identifier") in [f"{prefix}.{bundle}" for prefix in prefixes],
            "Profile must match the exact bundle ID; wildcard profiles are not accepted.")
    require(not entitlements.get("get-task-allow", False), "Development profiles cannot be used for App Store export.")
    require(not profile.get("ProvisionedDevices") and not profile.get("ProvisionsAllDevices"),
            "Use an App Store distribution profile, not Ad Hoc or Enterprise.")
    require("iOS" in profile.get("Platform", []), "Profile is not an iOS profile.")
    require(re.fullmatch(r"[A-Fa-f0-9-]{36}", profile.get("UUID", "")), "Profile UUID is invalid.")
    certificates = profile.get("DeveloperCertificates", [])
    require(certificates, "Profile contains no signing certificates.")
    return {hashlib.sha1(cert).hexdigest().upper(): cert for cert in certificates}


def decode_secret(value, path, name):
    require(value, f"Missing GitHub secret: {name}.")
    try:
        data = base64.b64decode("".join(value.split()), validate=True)
    except (ValueError, TypeError):
        raise ReleaseError(f"{name} must contain valid base64.") from None
    require(data, f"{name} is empty.")
    path.write_bytes(data)
    path.chmod(0o600)


def cleanup():
    private, _ = paths()
    state_file = private / "state.json"
    if state_file.is_file():
        state = json.loads(state_file.read_text(encoding="utf-8"))
        # Paths come only from this script on the same ephemeral runner.
        for profile in state.get("profiles", []):
            Path(profile).unlink(missing_ok=True)
        if state.get("keychains") is not None:
            subprocess.run(["security", "list-keychains", "-d", "user", "-s", *state["keychains"]],
                           check=False, capture_output=True)
        if state.get("keychain"):
            subprocess.run(["security", "delete-keychain", state["keychain"]], check=False, capture_output=True)
    if private.exists():
        shutil.rmtree(private)


def install_signing(private, bundle, team, credentials):
    p12 = private / "distribution.p12"
    profile_path = private / "app.mobileprovision"
    decode_secret(credentials["IOS_DISTRIBUTION_P12_BASE64"], p12, "IOS_DISTRIBUTION_P12_BASE64")
    decode_secret(credentials["IOS_APP_STORE_PROFILE_BASE64"], profile_path, "IOS_APP_STORE_PROFILE_BASE64")
    require(credentials["IOS_DISTRIBUTION_P12_PASSWORD"], "Missing IOS_DISTRIBUTION_P12_PASSWORD secret.")
    profile = plistlib.loads(run(["security", "cms", "-D", "-i", str(profile_path)], capture=True).encode())
    certificates = validate_profile(profile, bundle, team)
    keychain = private / "signing.keychain-db"
    keychain_password = secrets.token_urlsafe(32)
    original_keychains = shlex.split(run(["security", "list-keychains", "-d", "user"], capture=True))
    installed_profile = Path.home() / "Library/Developer/Xcode/UserData/Provisioning Profiles" / f"{profile['UUID']}.mobileprovision"
    require(not installed_profile.exists(), "A profile with this UUID already exists; use a clean hosted runner.")
    state = {"keychain": str(keychain), "keychains": original_keychains, "profiles": [str(installed_profile)]}
    (private / "state.json").write_text(json.dumps(state), encoding="utf-8")
    run(["security", "create-keychain", "-p", keychain_password, str(keychain)], capture=True)
    run(["security", "set-keychain-settings", "-lut", "21600", str(keychain)], capture=True)
    run(["security", "unlock-keychain", "-p", keychain_password, str(keychain)], capture=True)
    run(["security", "import", str(p12), "-P", credentials["IOS_DISTRIBUTION_P12_PASSWORD"],
         "-t", "cert", "-f", "pkcs12", "-k", str(keychain), "-T", "/usr/bin/codesign", "-T", "/usr/bin/security"], capture=True)
    run(["security", "set-key-partition-list", "-S", "apple-tool:,apple:,codesign:", "-k", keychain_password, str(keychain)], capture=True)
    run(["security", "list-keychains", "-d", "user", "-s", str(keychain), *original_keychains], capture=True)
    identities = run(["security", "find-identity", "-v", "-p", "codesigning", str(keychain)], capture=True)
    matching = [(fingerprint, name) for fingerprint, name in re.findall(r'([0-9A-F]{40}) "([^"]+)"', identities)
                if fingerprint in certificates and (name.startswith("Apple Distribution:") or name.startswith("iPhone Distribution:"))]
    require(len(matching) == 1, "P12 must contain exactly one valid distribution identity included in the provisioning profile.")
    fingerprint, _ = matching[0]
    certificate = private / "distribution.cer"
    certificate.write_bytes(certificates[fingerprint])
    subject = run(["openssl", "x509", "-inform", "DER", "-in", str(certificate), "-noout", "-subject", "-nameopt", "RFC2253"], capture=True)
    require(re.search(r"(?:^|,)OU=" + re.escape(team) + r"(?:,|$)", subject.strip().removeprefix("subject=")),
            "Distribution certificate belongs to another developer team.")
    run(["openssl", "x509", "-inform", "DER", "-in", str(certificate), "-noout", "-checkend", "0"], capture=True)
    installed_profile.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(profile_path, installed_profile)
    return profile["UUID"], fingerprint


NATIVE_ENGINE_ENTRIES = (
    "JNI_CreateJavaVM", "JNI_OnLoad_jnijavacpp", "JNI_OnLoad_jnileptonica",
    "JNI_OnLoad_jnitesseract", "loadfunctions",
)
REQUIRED_ENGINE_RESOURCES = {
    "build-inventory.json", "runtime/lib/modules", "tessdata/eng.traineddata",
    "assets/basic-classifier.zip", "assets/Bravura.otf", "assets/FinaleJazzText.otf",
    "licenses/fonts/provenance.json", "licenses/fonts/FONT-NOTICES.txt",
    "licenses/fonts/Bravura-LICENSE.txt", "licenses/fonts/Leland-LICENSE.txt",
    "licenses/fonts/MakeMusic-OFL.txt",
}
REQUIRED_ENGINE_CLASSES = {
    "com/notelite/omr/EmbeddedOmrEngine.class",
    "org/apache/pdfbox/rendering/PDFRenderer.class",
    "org/bytedeco/javacpp/Loader.class",
    "org/bytedeco/tesseract/global/tesseract.class",
    "org/bytedeco/leptonica/global/leptonica.class",
}
PRACTICE_SOURCE = Path(__file__).resolve().parents[2] / "app/res/practice"


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def contained_file(root, relative):
    require(isinstance(relative, str) and relative and "\\" not in relative,
            "Invalid embedded resource path.")
    name = PurePosixPath(relative)
    require(not name.is_absolute() and ".." not in name.parts and ":" not in relative,
            "Embedded resource path escapes its directory.")
    result = (root / relative).resolve()
    require(result.is_relative_to(root.resolve()) and result.is_file(),
            f"Missing or escaped embedded file: {relative}.")
    return result


def verify_resource_inventory(root, resources):
    require(isinstance(resources, list) and resources, "Embedded resource inventory is empty.")
    names = set()
    for entry in resources:
        require(isinstance(entry, dict), "Invalid embedded resource inventory entry.")
        name = entry.get("path")
        path = contained_file(root, name)
        require(name.casefold() not in names, "Duplicate embedded resource inventory path.")
        names.add(name.casefold())
        require(isinstance(entry.get("sha256"), str) and re.fullmatch(r"[a-f0-9]{64}", entry["sha256"]),
                f"Invalid embedded resource checksum: {name}.")
        require(type(entry.get("bytes")) is int and path.stat().st_size == entry["bytes"]
                and digest(path) == entry["sha256"], f"Embedded resource differs from composition: {name}.")
    expected = {entry["path"] for entry in resources}
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    require(actual == expected, "Embedded resource files do not match the complete composition inventory.")
    require(REQUIRED_ENGINE_RESOURCES <= expected, "The composition omits required engine resources or font notices.")
    return expected


def embedded_build():
    """Resolve only a verified device composition; there is no baseline fallback."""
    raw = os.environ.get("RELEASE_EMBEDDED_BUILD", "")
    require(raw.strip(), "RELEASE_EMBEDDED_BUILD must name a complete iphoneos engine build.")
    build = Path(raw).resolve()
    require(build.is_dir(), "The embedded build directory does not exist.")
    evidence = build / "evidence"
    location = contained_file(evidence, "project-location.txt").read_text(encoding="utf-8").strip()
    project_directory = Path(location)
    require(project_directory.is_absolute(), "The generated project location must be absolute.")
    project_directory = project_directory.resolve()
    require(project_directory.is_relative_to(build), "The generated project must belong to this embedded build.")
    project = project_directory / "NoteLite.xcodeproj"
    require(project.is_dir(), "The generated embedded Xcode project is missing.")
    for name in ("embedded-project.json", "native-libraries.xcconfig"):
        generated = name if name.endswith(".json") else "Generated/" + name
        require(contained_file(evidence, name).read_bytes() == contained_file(project_directory, generated).read_bytes(),
                f"Generated embedded configuration differs from its evidence: {name}.")
    spec = json.loads((evidence / "embedded-project.json").read_text(encoding="utf-8"))
    target = spec["targets"]["NoteLite"]
    options = target["settings"]["base"]
    require("EMBEDDED_OMR_RUNTIME" in shlex.split(options.get("SWIFT_ACTIVE_COMPILATION_CONDITIONS", "")),
            "The embedded project does not enable the production engine.")
    require(target.get("configFiles", {}).get("Release") == "Generated/native-libraries.xcconfig",
            "The Release target does not use the composed native libraries.")
    bridge = contained_file(project_directory, "EmbeddedRuntime/EmbeddedJVM.h")
    contained_file(project_directory, "EmbeddedRuntime/EmbeddedJVM.mm")
    contained_file(project_directory, "Generated/native-symbols.c")
    require(Path(options.get("SWIFT_OBJC_BRIDGING_HEADER", "")).resolve() == bridge,
            "The embedded project uses an unexpected JNI bridge header.")
    inventory_file = contained_file(evidence, "app-inventory.json")
    inventory = json.loads(inventory_file.read_text(encoding="utf-8"))
    require(inventory.get("sdk") == "iphoneos" and inventory.get("architecture") == "arm64"
            and inventory.get("embeddedRuntimeEnabled") is True
            and set(inventory.get("deviceFamilies", [])) == {1, 2},
            "Release requires a complete iphoneos/arm64 composition for iPhone and iPad.")
    resources = project_directory / "Generated/OMRResources"
    names = verify_resource_inventory(resources, inventory.get("resources"))
    native = json.loads((resources / "build-inventory.json").read_text(encoding="utf-8"))
    require(native.get("sdk") == "iphoneos" and native.get("architecture") == "arm64",
            "The engine's native inventory belongs to another platform.")
    archives = native.get("nativeArchives", [])
    require(archives, "The composition has no native archive provenance.")
    archive_paths = set()
    for entry in archives:
        path = Path(entry["path"])
        require(path.is_absolute() and path.is_file() and path.suffix == ".a",
                "A composed native archive is unavailable; retain the downloaded dependencies.")
        require(digest(path) == entry["sha256"], "A native archive changed after composition.")
        require(path.as_posix() not in archive_paths, "Duplicate native archive provenance.")
        archive_paths.add(path.as_posix())
    config = {}
    for line in (evidence / "native-libraries.xcconfig").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            config[key.strip()] = value.strip()
    flags = shlex.split(config.get("OTHER_LDFLAGS", ""))
    linked_archives = {token.removeprefix("-Wl,-force_load,") for token in flags if token.endswith(".a")}
    require(config.get("ARCHS") == "arm64" and linked_archives == archive_paths,
            "The native link configuration does not match its archive provenance.")
    headers = [Path(token) for token in shlex.split(config.get("HEADER_SEARCH_PATHS", "")) if token != "$(inherited)"]
    require(headers and all(path.is_absolute() and path.is_dir() for path in headers)
            and any((path / "jni.h").is_file() for path in headers)
            and any((path / "jni_md.h").is_file() for path in headers), "The target JNI headers are missing.")
    missing_classes = set(REQUIRED_ENGINE_CLASSES)
    for name in sorted(names):
        if name.startswith("java/") and name.endswith(".jar"):
            try:
                with zipfile.ZipFile(resources / name) as jar:
                    missing_classes.difference_update(jar.namelist())
            except zipfile.BadZipFile:
                raise ReleaseError(f"Invalid embedded Java archive: {name}.") from None
    require(not missing_classes, "The embedded Java bundle lacks the engine, PDFBox, or OCR APIs.")
    settings_output = json.loads(run([
        "xcodebuild", "-project", str(project), "-scheme", "NoteLite", "-configuration", "Release",
        "-destination", "generic/platform=iOS", "-showBuildSettings", "-json",
    ], capture=True))
    app_settings = [item["buildSettings"] for item in settings_output if item.get("target") == "NoteLite"]
    require(len(app_settings) == 1, "Cannot resolve the embedded application's Release build settings.")
    effective = app_settings[0]
    require("EMBEDDED_OMR_RUNTIME" in shlex.split(effective.get("SWIFT_ACTIVE_COMPILATION_CONDITIONS", ""))
            and effective.get("PLATFORM_NAME") == "iphoneos"
            and shlex.split(effective.get("ARCHS", "")) == ["arm64"],
            "Effective Release settings disable the engine or target a different platform.")
    require(linked_archives <= {token.removeprefix("-Wl,-force_load,")
                               for token in shlex.split(effective.get("OTHER_LDFLAGS", ""))},
            "Effective Release settings lost composed native libraries.")
    require(effective.get("STRIP_INSTALLED_PRODUCT") == "NO" and effective.get("COPY_PHASE_STRIP") == "NO",
            "Embedded Release builds must preserve native exports required by JNI and FFM lookup.")
    return {"project": project, "resources": inventory["resources"], "inventorySHA256": digest(inventory_file)}


def verify_preset_bindings(app, symbols, report_file):
    """Compare bundled API declarations with this executable's actual exports."""
    jars = sorted(path for path in (app / "OMRResources/java").glob("*.jar")
                  if path.name.startswith(("leptonica-", "tesseract-")))
    require(len(jars) == 2 and {jar.name.split("-")[0] for jar in jars} == {"leptonica", "tesseract"},
            "Expected one bundled Leptonica and one Tesseract API JAR.")
    auditor = Path(__file__).resolve().parents[2] / "tools/audiveris-port/verify-jni-bindings.py"
    spec = importlib.util.spec_from_file_location("notelite_jni_bindings", auditor)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.audit(jars, set(re.findall(r"\b_?(Java_[A-Za-z0-9_]+)$", symbols, re.M)))
    report = {"jars": [{"name": jar.name, "sha256": digest(jar)} for jar in jars],
              "linked": result, "passed": result["passed"]}
    report_file.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    require(report["passed"], "The executable lacks native preset bindings; see " + report_file.name + ".")
    return report


def verify_embedded_archive(app, composition, output, *, report_name="embedded-archive-inventory.json"):
    """Check the actual archived app before export, validation or upload."""
    verify_resource_inventory(app / "OMRResources", composition["resources"])
    practice_files = sorted(path for path in PRACTICE_SOURCE.rglob("*") if path.is_file())
    require(practice_files, "Build the bundled practice resources before archiving.")
    for original in practice_files:
        relative = original.relative_to(PRACTICE_SOURCE).as_posix()
        installed = contained_file(app / "practice", relative)
        require(digest(installed) == digest(original),
                f"Archived practice resource differs from its source: {relative}.")
    assets = contained_file(app, "Assets.car")
    require(assets.stat().st_size > 0, "The archived asset catalog is empty.")
    info = plistlib.loads((app / "Info.plist").read_bytes())
    require(set(info.get("UIDeviceFamily", [])) == {1, 2}, "The archive must support iPhone and iPad.")
    binary = contained_file(app, info["CFBundleExecutable"])
    run(["xcrun", "lipo", str(binary), "-verify_arch", "arm64"])
    commands = run(["xcrun", "vtool", "-show-build", str(binary)], capture=True)
    require(re.search(r"\bplatform\s+IOS\b", commands) and "IOSSIMULATOR" not in commands,
            "The archived executable is not an iOS device binary.")
    symbols = run(["xcrun", "nm", "-gU", str(binary)], capture=True)
    require(all(re.search(r"\b_" + re.escape(name) + r"$", symbols, re.M) for name in NATIVE_ENGINE_ENTRIES),
            "The archived executable lacks required embedded JNI entry points.")
    binding_report = verify_preset_bindings(app, symbols,
        output / (Path(report_name).stem.removesuffix("-inventory") + "-jni-bindings.json"))
    report = {"sdk": "iphoneos", "architecture": "arm64", "embeddedRuntimeEnabled": True,
              "bundleIdentifier": info.get("CFBundleIdentifier"),
              "version": info.get("CFBundleShortVersionString"), "build": info.get("CFBundleVersion"),
              "compositionInventorySHA256": composition["inventorySHA256"],
              "practiceResourceCount": len(practice_files), "assetCatalogSHA256": digest(assets),
              "nativePresetBindings": binding_report,
              "nativeEntryPoints": list(NATIVE_ENGINE_ENTRIES), "resources": composition["resources"]}
    (output / report_name).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def verify_exported_ipa(ipa, composition, private, output, archived_info):
    """Validate the actual exported Payload before permitting an upload."""
    extracted = private / "export-verification"
    require(not extracted.exists(), "IPA verification directory already exists; use a fresh release job.")
    extracted.mkdir()
    try:
        with zipfile.ZipFile(ipa) as archive:
            names = set()
            for entry in archive.infolist():
                name = PurePosixPath(entry.filename)
                require(entry.filename and "\\" not in entry.filename and ":" not in entry.filename
                        and not name.is_absolute() and ".." not in name.parts,
                        "Exported IPA contains an invalid ZIP path.")
                require((entry.external_attr >> 16) & 0o170000 != 0o120000,
                        "Exported IPA contains a symbolic link; its contents cannot be verified safely.")
                require(name.as_posix().casefold() not in names, "Exported IPA contains duplicate ZIP paths.")
                names.add(name.as_posix().casefold())
            archive.extractall(extracted)
    except zipfile.BadZipFile:
        raise ReleaseError("The exported IPA is not a valid ZIP archive.") from None
    apps = [path for path in (extracted / "Payload").glob("*.app") if path.is_dir()]
    require(len(apps) == 1, "Exported IPA must contain exactly one Payload application.")
    info = plistlib.loads(contained_file(apps[0], "Info.plist").read_bytes())
    for key in ("CFBundleIdentifier", "CFBundleShortVersionString", "CFBundleVersion"):
        require(info.get(key) == archived_info.get(key), "Exported IPA identity/version differs from its archive.")
    verify_embedded_archive(apps[0], composition, output, report_name="embedded-ipa-inventory.json")


def archive():
    mode, upload, bundle, team, version, build = settings()
    private, output = paths()
    require(not private.exists() and not output.exists(), "Release output already exists; start a new hosted runner job.")
    private.mkdir(mode=0o700)
    output.mkdir()
    secret_names = ("IOS_DISTRIBUTION_P12_BASE64", "IOS_DISTRIBUTION_P12_PASSWORD", "IOS_APP_STORE_PROFILE_BASE64",
                    "ASC_API_KEY_ID", "ASC_API_ISSUER_ID", "ASC_API_PRIVATE_KEY_BASE64")
    # Remove secrets from the environment inherited by Xcode and other subprocesses.
    credentials = {name: os.environ.pop(name, "") for name in secret_names}
    archive_path = output / "Yinban.xcarchive"
    try:
        composition = embedded_build()
        command = ["xcodebuild", "archive", "-project", str(composition["project"]), "-scheme", "NoteLite", "-configuration", "Release",
                   "-destination", "generic/platform=iOS", "-archivePath", str(archive_path),
                   "-derivedDataPath", str(private / "DerivedData"), f"PRODUCT_BUNDLE_IDENTIFIER={bundle}",
                   f"MARKETING_VERSION={version}", f"CURRENT_PROJECT_VERSION={build}"]
        if upload:
            require(re.fullmatch(r"[A-Z0-9]{10}", credentials["ASC_API_KEY_ID"]), "Missing or invalid ASC_API_KEY_ID.")
            require(re.fullmatch(r"[a-fA-F0-9-]{36}", credentials["ASC_API_ISSUER_ID"]), "Missing or invalid ASC_API_ISSUER_ID.")
            decode_secret(credentials["ASC_API_PRIVATE_KEY_BASE64"], private / "api-key.p8", "ASC_API_PRIVATE_KEY_BASE64")
            run(["openssl", "pkey", "-in", str(private / "api-key.p8"), "-noout"], capture=True)
        if mode == "export":
            profile_uuid, fingerprint = install_signing(private, bundle, team, credentials)
            command += ["CODE_SIGN_STYLE=Manual", f"DEVELOPMENT_TEAM={team}",
                        f"PROVISIONING_PROFILE_SPECIFIER={profile_uuid}", f"CODE_SIGN_IDENTITY={fingerprint}"]
        else:
            command += ["CODE_SIGNING_ALLOWED=NO", "CODE_SIGNING_REQUIRED=NO", "CODE_SIGN_IDENTITY="]
        run(command)
        apps = list((archive_path / "Products/Applications").glob("*.app"))
        require(len(apps) == 1, "Archive must contain exactly one application.")
        info = plistlib.loads((apps[0] / "Info.plist").read_bytes())
        require(info.get("CFBundleIdentifier") == bundle, "Archived bundle ID does not match.")
        require(info.get("CFBundleShortVersionString") == version and str(info.get("CFBundleVersion")) == build,
                "Archived version/build does not match the requested version/build.")
        require("iPhoneOS" in info.get("CFBundleSupportedPlatforms", []), "Archive is not an iOS device build.")
        sdk_match = re.fullmatch(r"iphoneos(\d+)(?:\.\d+)*", info.get("DTSDKName", ""))
        require(sdk_match and int(sdk_match[1]) >= 26, "Archive was not built with the iOS 26 SDK or later.")
        verify_embedded_archive(apps[0], composition, output)
        if mode == "export":
            run(["codesign", "--verify", "--deep", "--strict", str(apps[0])])
            options = {"method": "app-store-connect", "destination": "export", "teamID": team,
                       "signingStyle": "manual", "signingCertificate": fingerprint,
                       "provisioningProfiles": {bundle: profile_uuid}, "manageAppVersionAndBuildNumber": False,
                       "stripSwiftSymbols": True, "uploadSymbols": True}
            export_options = private / "ExportOptions.plist"
            export_options.write_bytes(plistlib.dumps(options))
            run(["xcodebuild", "-exportArchive", "-archivePath", str(archive_path),
                 "-exportPath", str(output / "export"), "-exportOptionsPlist", str(export_options)])
            ipas = list((output / "export").glob("*.ipa"))
            require(len(ipas) == 1, "Export did not produce exactly one IPA.")
            verify_exported_ipa(ipas[0], composition, private, output, info)
            if upload:
                keys = private / "private_keys"
                keys.mkdir(mode=0o700)
                (private / "api-key.p8").rename(keys / f"AuthKey_{credentials['ASC_API_KEY_ID']}.p8")
                os.environ["API_PRIVATE_KEYS_DIR"] = str(keys)
                auth = ["--apiKey", credentials["ASC_API_KEY_ID"], "--apiIssuer", credentials["ASC_API_ISSUER_ID"]]
                run(["xcrun", "altool", "--validate-app", "-f", str(ipas[0]), "-t", "ios", *auth])
                run(["xcrun", "altool", "--upload-app", "-f", str(ipas[0]), "-t", "ios", *auth])
                print("Upload accepted. Wait for Apple's processing, then select the build in App Store Connect.")
        run(["ditto", "-c", "-k", "--keepParent", str(archive_path), str(output / "Yinban.xcarchive.zip")])
        print(f"Completed {mode}: version {version}, build {build}.")
    finally:
        cleanup()


if __name__ == "__main__":
    try:
        require(len(sys.argv) == 2 and sys.argv[1] in ("prepare", "archive", "cleanup"),
                "Usage: release.py prepare|archive|cleanup")
        {"prepare": prepare, "archive": archive, "cleanup": cleanup}[sys.argv[1]]()
    except (ReleaseError, OSError, ValueError, KeyError) as error:
        print(f"Release stopped: {error}", file=sys.stderr)
        sys.exit(1)
