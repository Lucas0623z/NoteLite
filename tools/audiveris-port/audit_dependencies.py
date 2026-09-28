#!/usr/bin/env python3
"""Inventory Java dependencies relevant to an in-process Apple OMR port.

This is a source import inventory, not bytecode reachability analysis. No build,
package installation or network access occurs unless explicitly requested.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


CATEGORIES = {
    "awt_geometry": r"java\.awt\.(?:geom\.|Point$|Rectangle$|Dimension$|Polygon$|Shape$)",
    "awt_other": r"java\.awt\.(?!(?:geom\.|Point$|Rectangle$|Dimension$|Polygon$|Shape$))",
    "swing": r"javax\.swing\.",
    "image_io": r"javax\.imageio\.",
    "imagej": r"ij\.",
    "jai": r"javax\.media\.jai\.",
    "pdfbox": r"org\.apache\.pdfbox\.",
    "native_bindings": r"(?:org\.bytedeco\.|com\.sun\.jna\.)",
    "jaxb": r"javax\.xml\.bind\.",
    "reflection": r"(?:java\.lang\.reflect\.|org\.reflections\.)",
    "desktop_frameworks": r"(?:org\.jdesktop\.|com\.jgoodies\.|com\.formdev\.)",
}
IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([\w.*]+)\s*;", re.MULTILINE)


def git_revision(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def assignment(source: str, key: str) -> str | None:
    match = re.search(rf"\b{re.escape(key)}\s*=\s*['\"]?([\w.\-]+)", source)
    return match.group(1) if match else None


def native_artifacts(versions: dict[str, str | None]) -> list[dict]:
    """Check the exact Maven releases used by this checkout, without downloading jars."""
    results = []
    for artifact, key in (("tesseract", "tesseract"), ("leptonica", "leptonica")):
        version = versions.get(key)
        javacpp = versions.get("javacpp")
        if not version or not javacpp:
            results.append({"artifact": artifact, "status": "version_not_found"})
            continue
        release = f"{version}-{javacpp}"
        url = f"https://repo.maven.apache.org/maven2/org/bytedeco/{artifact}/{release}/"
        item = {"artifact": artifact, "version": release, "url": url}
        try:
            with urlopen(url, timeout=20) as response:
                listing = response.read().decode("utf-8")
            prefix = re.escape(f"{artifact}-{release}-")
            suffixes = re.findall(rf'href="{prefix}([^"/]+)\.jar"', listing)
            classifiers = sorted(set(suffixes) - {"sources", "javadoc"})
            if not classifiers:
                item.update(status="unrecognized_listing", classifiers=[])
            else:
                item.update(
                    status="checked", classifiers=classifiers,
                    ios_classifier_present=any(c.startswith("ios-") for c in classifiers),
                )
        except (HTTPError, URLError, OSError, UnicodeError) as error:
            item.update(status="unavailable", error=str(error))
        results.append(item)
    return results


def audit(root: Path, check_native: bool) -> dict:
    source_root = root / "app/src/main/java"
    build_path = root / "app/build.gradle"
    properties_path = root / "gradle.properties"
    if not source_root.is_dir() or not build_path.is_file() or not properties_path.is_file():
        raise ValueError(f"Expected a NoteLite checkout at {root}")
    build = build_path.read_text(encoding="utf-8")
    properties = properties_path.read_text(encoding="utf-8")
    versions = {
        "application": assignment(build, "project.version"),
        "java": assignment(properties, "theMinJavaVersion"),
        "javacpp": assignment(build, "jcppVersion"),
        "tesseract": assignment(build, "tessVersion"),
        "leptonica": assignment(build, "leptVersion"),
        "tessdata": assignment(properties, "theTessdataTag"),
    }
    aliases = {"jcppVersion": "javacpp", "tessVersion": "tesseract", "leptVersion": "leptonica"}
    coordinates = set()
    for dependency in re.findall(r"['\"]([\w.\-]+:[\w.\-]+:[^'\"\s]+)['\"]", build):
        for alias, key in aliases.items():
            if versions[key]:
                dependency = dependency.replace("${" + alias + "}", versions[key])
                dependency = dependency.replace("$" + alias, versions[key])
        coordinates.add(dependency)

    findings = {name: [] for name in CATEGORIES}
    patterns = {name: re.compile(pattern) for name, pattern in CATEGORIES.items()}
    files = sorted(source_root.rglob("*.java"))
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix()
        contents = path.read_bytes()
        digest.update(relative.encode("utf-8") + b"\0" + contents + b"\0")
        source = contents.decode("utf-8-sig")
        in_ui_directory = "ui" in path.relative_to(source_root).parts[:-1]
        for match in IMPORT.finditer(source):
            imported = match.group(1)
            for name, pattern in patterns.items():
                if pattern.match(imported):
                    findings[name].append({
                        "file": relative,
                        "line": source.count("\n", 0, match.start(1)) + 1,
                        "import": imported,
                        "in_ui_directory": in_ui_directory,
                    })

    categories = {}
    for name, occurrences in findings.items():
        outside = {entry["file"] for entry in occurrences if not entry["in_ui_directory"]}
        categories[name] = {
            "file_count": len({entry["file"] for entry in occurrences}),
            "outside_ui_directory_file_count": len(outside),
            "import_count": len(occurrences),
            "occurrences": occurrences,
        }
    resources = []
    for path in sorted((root / "app/res").glob("*")):
        if path.is_file() and (path.suffix.lower() in {".ttf", ".otf"} or "classifier" in path.name):
            resources.append({
                "path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            })
    report = {
        "schema_version": 1,
        "scope": "Static explicit-import inventory; not a call graph or an iOS build result.",
        "ui_directory_rule": "Only a literal ui directory is classified as UI; other files may also contain UI code.",
        "git_revision": git_revision(root),
        "java_source_tree_sha256": digest.hexdigest(),
        "java_source_file_count": len(files),
        "versions": versions,
        "preview_features_enabled": "--enable-preview" in build,
        "direct_dependency_coordinates": sorted(coordinates),
        "categories": categories,
        "resources": resources,
    }
    if check_native:
        report["native_artifacts"] = native_artifacts(versions)
    return report


def markdown(report: dict) -> str:
    lines = ["# Audiveris / NoteLite Apple port dependency inventory", "",
             report["scope"], "", f"Revision: `{report['git_revision']}`",
             f"Java sources: {report['java_source_file_count']}",
             f"Source SHA-256: `{report['java_source_tree_sha256']}`", "",
             "## Versions", "", "| Component | Version |", "| --- | --- |"]
    lines += [f"| {key} | {value or 'not found'} |" for key, value in report["versions"].items()]
    lines += ["", f"Java preview features enabled: {report['preview_features_enabled']}", "",
              "## Explicit imports", "", report["ui_directory_rule"], "",
              "Files can appear in several rows. Counts do not establish runtime reachability.", "",
              "| Dependency | Files | Files outside ui directories | Imports |",
              "| --- | ---: | ---: | ---: |"]
    for name, category in report["categories"].items():
        lines.append(f"| {name} | {category['file_count']} | "
                     f"{category['outside_ui_directory_file_count']} | {category['import_count']} |")
    lines += ["", "## Example source locations", ""]
    for name, category in report["categories"].items():
        examples = [entry for entry in category["occurrences"] if not entry["in_ui_directory"]][:3]
        for entry in examples:
            lines.append(f"- {name}: `{entry['file']}:{entry['line']}` imports `{entry['import']}`")
    if "native_artifacts" in report:
        lines += ["", "## Maven native artifacts", ""]
        for item in report["native_artifacts"]:
            classifiers = ", ".join(item.get("classifiers", []))
            lines.append(f"- {item['artifact']}: {item['status']}; {classifiers}")
            if "ios_classifier_present" in item:
                lines.append(f"  iOS classifier present: {item['ios_classifier_present']}")
            if "error" in item:
                lines.append(f"  Lookup error: {item['error']}")
    lines += ["", "Use `--format json` for every import location, dependency coordinate and resource checksum.", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path, help="Write the report to this file instead of standard output.")
    parser.add_argument("--check-native-artifacts", action="store_true",
                        help="Query Maven Central listings for the pinned Tesseract and Leptonica releases.")
    args = parser.parse_args()
    try:
        report = audit(args.root.resolve(), args.check_native_artifacts)
        rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n" if args.format == "json" else markdown(report)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
