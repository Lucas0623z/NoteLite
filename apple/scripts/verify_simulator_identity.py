#!/usr/bin/env python3
"""Verify the installed simulator host's signature and embedded Keychain identity.

Xcode's simulator link uses __TEXT,__entitlements, which need not be present
in the signature entitlement blob. Read the actual installed Mach-O, not a
DerivedData xcent or a configured build setting. Mach-O structures follow:
https://github.com/apple-oss-distributions/xnu/blob/main/EXTERNAL_HEADERS/mach-o/loader.h
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import struct
import subprocess
import tempfile


class IdentityError(ValueError):
    pass


def macho_evidence(data):
    if len(data) < 32 or len(data) > 200 * 1024 * 1024:
        raise IdentityError("Invalid installed Mach-O size")
    magic = bytes(data[:4])
    order = {b"\xcf\xfa\xed\xfe": "<", b"\xfe\xed\xfa\xcf": ">"}.get(magic)
    if order is None:
        raise IdentityError("Expected a thin 64-bit simulator Mach-O")
    _, cpu, _, file_type, commands, command_bytes, _, _ = struct.unpack_from(order + "8I", data)
    if cpu not in (0x01000007, 0x0100000C) or file_type not in (2, 6):
        raise IdentityError("Unsupported simulator architecture or file type")
    end = 32 + command_bytes
    if not 0 < commands <= 4096 or end > len(data):
        raise IdentityError("Invalid Mach-O load commands")
    offset = 32
    entitlements = []
    der_entitlements = []
    dependencies = []
    for _ in range(commands):
        if offset + 8 > end:
            raise IdentityError("Truncated Mach-O command")
        command, size = struct.unpack_from(order + "2I", data, offset)
        if size < 8 or size % 8 or offset + size > end:
            raise IdentityError("Invalid Mach-O command bounds")
        if command == 0x19:  # LC_SEGMENT_64, segment_command_64 + section_64
            if size < 72:
                raise IdentityError("Truncated segment")
            segment = data[offset + 8:offset + 24].split(b"\0", 1)[0]
            file_offset, file_size = struct.unpack_from(order + "2Q", data, offset + 40)
            sections = struct.unpack_from(order + "I", data, offset + 64)[0]
            if sections > 4096 or size != 72 + 80 * sections or file_offset + file_size > len(data):
                raise IdentityError("Invalid segment bounds")
            for index in range(sections):
                section = offset + 72 + index * 80
                name = data[section:section + 16].split(b"\0", 1)[0]
                owner = data[section + 16:section + 32].split(b"\0", 1)[0]
                if name not in (b"__entitlements", b"__ents_der"):
                    continue
                if owner != b"__TEXT" or segment != b"__TEXT":
                    raise IdentityError("Entitlement section is outside __TEXT")
                length = struct.unpack_from(order + "Q", data, section + 40)[0]
                start = struct.unpack_from(order + "I", data, section + 48)[0]
                flags = struct.unpack_from(order + "I", data, section + 64)[0]
                if (not 0 < length <= 1024 * 1024 or start < end or flags & 0xFF
                        or start < file_offset or start + length > file_offset + file_size):
                    raise IdentityError("Invalid entitlement section bounds")
                payload = data[start:start + length]
                if name == b"__ents_der":
                    der_entitlements.append(payload)
                    continue
                try:
                    value = plistlib.loads(payload)
                except (ValueError, plistlib.InvalidFileException) as error:
                    raise IdentityError("Invalid actual embedded entitlement plist") from error
                if not isinstance(value, dict) or not value:
                    raise IdentityError("Empty actual embedded entitlement plist")
                entitlements.append((value, hashlib.sha256(payload).hexdigest(), payload))
        elif command in (0xC, 0x80000018, 0x8000001F, 0x20, 0x80000023):
            if size < 24:
                raise IdentityError("Truncated linked dylib command")
            start = struct.unpack_from(order + "I", data, offset + 8)[0]
            if not 24 <= start < size:
                raise IdentityError("Invalid linked dylib name offset")
            name_bytes = data[offset + start:offset + size]
            if b"\0" not in name_bytes:
                raise IdentityError("Unterminated linked dylib name")
            dependencies.append(name_bytes.split(b"\0", 1)[0].decode("utf8"))
        offset += size
    if offset != end or len(entitlements) > 1 or len(der_entitlements) > 1:
        raise IdentityError("Extra command bytes or duplicate entitlement section")
    return {"entitlements": entitlements, "derEntitlements": der_entitlements,
            "dependencies": dependencies, "fileType": file_type,
            "sha256": hashlib.sha256(data).hexdigest()}


def validate_identity(value, identifier):
    if not isinstance(value, dict) or value.get("application-identifier") != identifier:
        raise IdentityError("Actual simulator lacks the expected private application identity")
    groups = value.get("keychain-access-groups", [])
    if not isinstance(groups, list) or groups not in ([], [identifier]):
        raise IdentityError("Unexpected actual Keychain sharing group")
    if value.get("com.apple.security.application-groups"):
        raise IdentityError("Unexpected actual application sharing group")
    team = value.get("com.apple.developer.team-identifier")
    if team is not None and team != identifier.split(".", 1)[0]:
        raise IdentityError("Contradictory actual team identity")


def ordinary_file(path, root):
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise IdentityError("Installed code path escaped its own app") from error
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 200 * 1024 * 1024:
        raise IdentityError("Installed code is missing or not an ordinary file")
    return path.read_bytes()


def inspect_installed_app(bundle, identifier, verify_signature, encode_der=None):
    info = plistlib.loads(ordinary_file(bundle / "Info.plist", bundle))
    executable = info.get("CFBundleExecutable")
    if (info.get("CFBundleIdentifier") != identifier.split(".", 1)[1]
            or not isinstance(executable, str) or Path(executable).name != executable or executable in ("", ".", "..")):
        raise IdentityError("Installed bundle identity or executable is invalid")
    signature = verify_signature(bundle)
    main_path = bundle / executable
    main = macho_evidence(ordinary_file(main_path, bundle))
    if main["fileType"] != 2:
        raise IdentityError("Main installed image is not executable")
    images = [(main_path, main, verify_signature(main_path))]
    debug_names = [name for name in main["dependencies"] if name.endswith(".debug.dylib")]
    if len(debug_names) > 1:
        raise IdentityError("Multiple linked debug images")
    for name in debug_names:
        prefix, separator, filename = name.rpartition("/")
        if not separator or prefix not in ("@rpath", "@executable_path") or Path(filename).name != filename:
            raise IdentityError("Linked debug image has an unexpected install path")
        path = bundle / filename
        value = macho_evidence(ordinary_file(path, bundle))
        if value["fileType"] != 6:
            raise IdentityError("Linked debug image is not a dylib")
        images.append((path, value, verify_signature(path)))
    sources = []
    identity_values = []
    if signature:
        validate_identity(signature, identifier)
        identity_values.append(signature)
    for path, image, signed_entitlements in images:
        if signed_entitlements:
            validate_identity(signed_entitlements, identifier)
            identity_values.append(signed_entitlements)
        if image["derEntitlements"] and (not image["entitlements"] or encode_der is None):
            raise IdentityError("Actual DER entitlement needs its same-image XML and official encoder")
        for value, digest, payload in image["entitlements"]:
            validate_identity(value, identifier)
            identity_values.append(value)
            sources.append({"image": path.name, "source": "__TEXT,__entitlements", "sha256": digest})
            if image["derEntitlements"]:
                actual_der = image["derEntitlements"][0]
                regenerated_der = encode_der(payload)
                if not regenerated_der or actual_der != regenerated_der:
                    raise IdentityError("Actual DER and XML entitlement sections contradict each other")
                sources.append({"image": path.name, "source": "__TEXT,__ents_der",
                                "sha256": hashlib.sha256(actual_der).hexdigest(),
                                "officialEncoderByteEqualityVerified": True})
    if not sources:
        raise IdentityError("No actual installed simulator entitlement section")
    groups = {tuple(value.get("keychain-access-groups", [])) for value in identity_values}
    if len(groups) != 1:
        raise IdentityError("Contradictory signed and embedded private Keychain identities")
    return {"signatureVerified": True, "applicationIdentifier": identifier,
            "applicationPrivateKeychainIdentityVerified": True, "keychainSharingExpanded": False,
            "distributionCertificateUsed": False, "installedMachOIdentityVerified": True,
            "signatureEntitlementBlobPresent": bool(signature), "identitySources": sources,
            "verifiedImages": [{"image": path.name, "sha256": value["sha256"],
                                "signatureEntitlementBlobPresent": bool(signed)} for path, value, signed in images],
            "actualKeychainLifecycle": "Requires the separate live native XCTest result."}


def codesign_identity(path):
    subprocess.run(["codesign", "--verify", "--strict", str(path)], check=True, capture_output=True, timeout=60)
    result = subprocess.run(["codesign", "-d", "--entitlements", "-", str(path)],
                            check=True, capture_output=True, timeout=60)
    if len(result.stdout) > 1024 * 1024:
        raise IdentityError("Oversized signature entitlement blob")
    if not result.stdout:
        # Xcode's simulator identity is validated from the installed image below.
        return None
    try:
        value = plistlib.loads(result.stdout)
    except (ValueError, plistlib.InvalidFileException) as error:
        raise IdentityError("Malformed actual signature entitlement blob") from error
    if not isinstance(value, dict) or not value:
        raise IdentityError("Empty nonzero signature entitlement blob")
    return value


def official_der(xml):
    # This is the exact encoder invocation observed in the Xcode build log.
    with tempfile.TemporaryDirectory(prefix="notelite-installed-identity-") as directory:
        source, output = Path(directory) / "actual-section.xml", Path(directory) / "regenerated.der"
        source.write_bytes(xml)
        subprocess.run(["/usr/bin/derq", "query", "-f", "xml", "-i", str(source),
                        "-o", str(output), "--raw"], check=True, capture_output=True, timeout=60)
        if not output.is_file() or not 0 < output.stat().st_size <= 1024 * 1024:
            raise IdentityError("Official DER encoding failed")
        return output.read_bytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--identifier", default="G74YSFJX76.com.lucas0623z.yinban")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.identifier != "G74YSFJX76.com.lucas0623z.yinban":
        raise IdentityError("Unexpected application scope")
    evidence = inspect_installed_app(args.app, args.identifier, codesign_identity, official_der)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf8")
    print("Actual simulator signature and installed private application identity verified.")


if __name__ == "__main__":
    main()
