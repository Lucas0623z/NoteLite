#!/usr/bin/env python3
"""Audit every native preset declaration against generated and/or linked JNI symbols."""
# SPDX-License-Identifier: AGPL-3.0-or-later
import argparse
import hashlib
import json
import re
import struct
import zipfile
from collections import Counter
from pathlib import Path


class ClassReader:
    def __init__(self, data):
        self.data = data
        self.offset = 0

    def read(self, count):
        end = self.offset + count
        if end > len(self.data):
            raise ValueError("Truncated class file")
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def u2(self):
        return struct.unpack(">H", self.read(2))[0]

    def u4(self):
        return struct.unpack(">I", self.read(4))[0]

    def attributes(self):
        for _ in range(self.u2()):
            self.read(2)
            self.read(self.u4())


def native_methods(data):
    reader = ClassReader(data)
    if reader.u4() != 0xCAFEBABE:
        raise ValueError("Invalid class file")
    reader.read(4)
    constants = [None] * reader.u2()
    index = 1
    while index < len(constants):
        tag = reader.read(1)[0]
        if tag == 1:
            # Class files use modified UTF-8, including UTF-16 surrogate units.
            constants[index] = reader.read(reader.u2()).replace(b"\xc0\x80", b"\0").decode("utf-8", "surrogatepass")
        elif tag in (7, 8, 16, 19, 20):
            constants[index] = reader.u2()
        elif tag in (3, 4, 9, 10, 11, 12, 17, 18):
            reader.read(4)
        elif tag in (5, 6):
            reader.read(8)
            index += 1
        elif tag == 15:
            reader.read(3)
        else:
            raise ValueError(f"Unknown constant-pool tag {tag}")
        index += 1
    reader.read(2)
    name = constants[constants[reader.u2()]]
    reader.read(2)
    reader.read(2 * reader.u2())
    for _ in range(reader.u2()):
        reader.read(6)
        reader.attributes()
    methods = []
    for _ in range(reader.u2()):
        flags, method, descriptor = reader.u2(), reader.u2(), reader.u2()
        if flags & 0x0100:
            methods.append((name, constants[method], constants[descriptor]))
        reader.attributes()
    return methods


def mangle(text):
    substitutions = {"/": "_", "_": "_1", ";": "_2", "[": "_3"}
    return "".join(substitutions.get(character,
                   character if character.isascii() and character.isalnum() else f"_0{ord(character):04x}")
                   for character in text)


def audit_declarations(declarations, symbols):
    overloads = Counter((owner, method) for owner, method, _ in declarations)
    missing = []
    classes = set()
    for owner, method, descriptor in declarations:
        classes.add(owner)
        short = "Java_" + mangle(owner) + "_" + mangle(method)
        long = short + "__" + mangle(descriptor[1:descriptor.index(")")])
        overloaded = overloads[owner, method] > 1
        # JavaCPP emits a separate long symbol for each native overload. A short
        # alias cannot prove that every overload's ABI has an implementation.
        if long not in symbols and (overloaded or short not in symbols):
            missing.append({"class": owner, "method": method, "descriptor": descriptor,
                            "requiresLongName": overloaded,
                            "expectedShort": short, "expectedLong": long})
    if not declarations:
        raise ValueError("No native preset declarations found; refusing an empty audit")
    return {"nativeDeclarations": len(declarations), "nativeClasses": len(classes), "missing": missing,
            "passed": not missing}


def audit(jars, symbols):
    declarations = []
    for jar in jars:
        with zipfile.ZipFile(jar) as archive:
            for name in archive.namelist():
                if not name.endswith(".class") or not name.startswith(("org/bytedeco/leptonica/", "org/bytedeco/tesseract/")):
                    continue
                declarations.extend(native_methods(archive.read(name)))
    return audit_declarations(declarations, symbols)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jars-manifest", type=Path, required=True)
    parser.add_argument("--sources-dir", type=Path)
    parser.add_argument("--symbols", type=Path, help="Actual xcrun nm -gU output")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.sources_dir is None and args.symbols is None:
        parser.error("Provide --sources-dir and/or --symbols")
    jars = [Path(path) for path in json.loads(args.jars_manifest.read_text())]
    if len(jars) != 2 or {path.name.split("-")[0] for path in jars} != {"leptonica", "tesseract"}:
        raise ValueError("Expected one Leptonica and one Tesseract API JAR")
    report = {"jars": [{"name": jar.name, "sha256": hashlib.sha256(jar.read_bytes()).hexdigest()}
                       for jar in jars]}
    if args.sources_dir is not None:
        sources = [(args.sources_dir / f"jni{name}.cpp").read_text() for name in ("leptonica", "tesseract")]
        symbols = set(re.findall(r"JNIEXPORT\s+\w+\s+JNICALL\s+(Java_\w+)\s*\(", "\n".join(sources)))
        report["generated"] = audit(jars, symbols)
    if args.symbols is not None:
        symbols = set(re.findall(r"\b_?(Java_[A-Za-z0-9_]+)$", args.symbols.read_text(), re.M))
        report["linked"] = audit(jars, symbols)
    report["passed"] = all(report[phase]["passed"] for phase in ("generated", "linked") if phase in report)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({phase: {key: value for key, value in report[phase].items() if key != "missing"}
                      for phase in ("generated", "linked") if phase in report}, indent=2))
    if not report["passed"]:
        raise SystemExit("Native preset bindings are missing; see the detailed audit report")


if __name__ == "__main__":
    main()
