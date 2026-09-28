#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Remove optional FlatLaf desktop binaries and audit the actual iOS Java bundle.

FlatLaf 3.5.4's ordinary API JAR also embeds desktop UI native libraries. The
headless engine retains its Java classes, resources and notices, while those
optional libraries are disabled by the host and omitted from the iOS bundle.
Unexpected native libraries, signatures on a modified JAR, or preview classes
are errors, so a new dependency cannot silently lose required native code.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import struct
import zipfile

NATIVE = re.compile(r"\.(?:dll|dylib|so)(?:\.|$)", re.IGNORECASE)
SIGNATURE = re.compile(r"META-INF/[^/]+\.(?:SF|RSA|DSA|EC)", re.IGNORECASE)
FLATLAF_NATIVE_PREFIX = "com/formdev/flatlaf/natives/"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(jar):
    original_sha256 = digest(jar)
    removed = []
    classes = 0
    with zipfile.ZipFile(jar) as source:
        entries = source.infolist()
        native_entries = [entry.filename for entry in entries if NATIVE.search(entry.filename)]
        if native_entries:
            if jar.name != "flatlaf-3.5.4.jar" or any(
                not name.startswith(FLATLAF_NATIVE_PREFIX) for name in native_entries
            ):
                raise ValueError(f"Unexpected native binaries in {jar.name}: {native_entries}")
            if any(SIGNATURE.fullmatch(entry.filename) for entry in entries):
                raise ValueError(f"Refusing to modify a signed dependency: {jar.name}")
        for entry in entries:
            if entry.filename.endswith(".class"):
                data = source.read(entry)[:8]
                if len(data) == 8 and data[:4] == b"\xca\xfe\xba\xbe":
                    minor, _ = struct.unpack(">HH", data[4:8])
                    if minor == 65535:
                        raise ValueError(f"Preview bytecode cannot cross JDK versions: {jar.name}!{entry.filename}")
                    classes += 1
        if native_entries:
            pending = jar.with_suffix(".jar.pending")
            try:
                with zipfile.ZipFile(pending, "w") as target:
                    target.comment = source.comment
                    for entry in entries:
                        data = source.read(entry)
                        if entry.filename in native_entries:
                            removed.append({"entry":entry.filename, "bytes":len(data),
                                            "sha256":hashlib.sha256(data).hexdigest()})
                        else:
                            # writestr updates ZipInfo offsets; keep the source
                            # index intact for the byte-for-byte verification.
                            target.writestr(copy.copy(entry), data)
                # Verify that every retained entry, including licenses and classes,
                # has exactly the same uncompressed bytes before replacing the JAR.
                with zipfile.ZipFile(pending) as target:
                    expected = [entry.filename for entry in entries if entry.filename not in native_entries]
                    if target.namelist() != expected:
                        raise ValueError("Repacked JAR entry list changed unexpectedly")
                    for name in expected:
                        if source.read(name) != target.read(name):
                            raise ValueError(f"Retained Java resource changed: {jar.name}!{name}")
            except BaseException:
                pending.unlink(missing_ok=True)
                raise
    if removed:
        pending.replace(jar)
    return {"name":jar.name, "bytes":jar.stat().st_size, "classCount":classes,
            "originalSHA256":original_sha256, "sha256":digest(jar), "removedDesktopEntries":removed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resources", type=Path, help="Staged engine resource directory containing java/*.jar")
    args = parser.parse_args()
    jars = sorted((args.resources / "java").glob("*.jar"))
    if not jars:
        raise SystemExit("No actual engine JARs were staged")
    inventory = [prepare(jar) for jar in jars]
    report = {"jarCount":len(inventory), "flatLafNativeLoadingEnabled":False, "jars":inventory}
    (args.resources / "java-packaging-report.json").write_text(json.dumps(report, indent=2) + "\n")
    removed = sum(len(item["removedDesktopEntries"]) for item in inventory)
    print(f"Audited {len(inventory)} Java JARs; removed {removed} optional FlatLaf desktop binaries")


if __name__ == "__main__":
    main()
