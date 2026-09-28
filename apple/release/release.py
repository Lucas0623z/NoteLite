#!/usr/bin/env python3
"""Build iOS archives on an ephemeral macOS GitHub runner; keep keys out of git."""

import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import secrets
import shlex
import shutil
import subprocess
import sys


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
    project = Path(__file__).resolve().parents[1] / "NoteLite.xcodeproj"
    archive_path = output / "Yinban.xcarchive"
    command = ["xcodebuild", "archive", "-project", str(project), "-scheme", "NoteLite", "-configuration", "Release",
               "-destination", "generic/platform=iOS", "-archivePath", str(archive_path),
               "-derivedDataPath", str(private / "DerivedData"), f"PRODUCT_BUNDLE_IDENTIFIER={bundle}",
               f"MARKETING_VERSION={version}", f"CURRENT_PROJECT_VERSION={build}"]
    try:
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
