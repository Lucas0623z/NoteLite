#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Resolve proven native builds for acceptance and the standard release archive."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess


def run_id(value):
    text = str(value)
    if not re.fullmatch(r"[1-9][0-9]*", text):
        raise ValueError("A real positive workflow run ID is required")
    return text


def validate_run(run, workflow, source_sha=None):
    if (run.get("status") != "completed" or run.get("conclusion") != "success"
            or run.get("path") != ".github/workflows/" + workflow):
        raise ValueError("Expected a successful completed " + workflow + ": " + str(run.get("html_url")))
    if source_sha is not None and run.get("head_sha") != source_sha:
        raise ValueError("The full embedded acceptance run must test this exact source commit")
    return {key: run[key] for key in ("id", "head_sha", "path", "html_url", "status", "conclusion")}


def validate_runtime(inventory, platform, source_commit):
    if (inventory.get("source_commit") != source_commit or inventory.get("platform") != platform
            or inventory.get("vm") != "zero" or inventory.get("headless_build_exit_code") != 0
            or not inventory.get("java_desktop_jmod") or not inventory.get("runtime_module_image")
            or inventory.get("missing_required_libraries") != []):
        raise ValueError("The downloaded runtime does not match the required source, platform, or complete build")


def validate_acceptance_sources(accepted, current):
    for key in ("RUNTIME_RUN", "OCR_RUN"):
        if accepted.get(key) != current.get(key):
            raise ValueError("The accepted app used different native build provenance: " + key)


def exactly_one(root, pattern):
    paths = list(root.rglob(pattern))
    if len(paths) != 1:
        raise ValueError("Expected exactly one " + pattern + " in " + str(root))
    return paths[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--platform", required=True, choices=("device", "simulator"))
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--runtime-run", default="")
    parser.add_argument("--ocr-run", default="")
    parser.add_argument("--acceptance-run", default="")
    parser.add_argument("--source-sha", default=os.environ.get("GITHUB_SHA", ""))
    args = parser.parse_args()
    if not args.repository or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
        raise ValueError("Pass the GitHub repository that owns the build artifacts")
    pinned = json.loads(Path(__file__).with_name("native-artifact-runs.json").read_text())
    native_runs = {
        "RUNTIME_RUN": run_id(args.runtime_run or pinned["runtime_run_id"]),
        "OCR_RUN": run_id(args.ocr_run or pinned["ocr_run_id"]),
    }

    def read_run(identifier, workflow, source_sha=None):
        run = json.loads(subprocess.check_output([
            "gh", "api", "repos/" + args.repository + "/actions/runs/" + run_id(identifier)], text=True))
        return validate_run(run, workflow, source_sha)

    def download(identifier, artifact, directory):
        subprocess.run(["gh", "run", "download", run_id(identifier), "--repo", args.repository,
                        "--name", artifact, "--dir", str(directory)], check=True)

    sources = {
        "RUNTIME_RUN": read_run(native_runs["RUNTIME_RUN"], "audiveris-mobile-runtime.yml"),
        "OCR_RUN": read_run(native_runs["OCR_RUN"], "audiveris-ios-ocr.yml"),
    }
    accepted = None
    if args.acceptance_run:
        if not re.fullmatch(r"[0-9a-fA-F]{40}", args.source_sha):
            raise ValueError("The release source must be a full Git commit SHA")
        accepted = read_run(args.acceptance_run, "audiveris-ios-embedded-probe.yml", args.source_sha)

    output = args.destination.resolve()
    if output.exists():
        raise ValueError("Use a new artifact directory; refusing to mix old and new build outputs: " + str(output))
    output.mkdir(parents=True)
    if accepted is not None:
        proof = output / "acceptance"
        download(args.acceptance_run, "embedded-omr-provenance-iphoneos", proof)
        evidence = json.loads(exactly_one(proof, "source-runs.json").read_text())
        validate_acceptance_sources(evidence, sources)
        (output / "accepted-run.json").write_text(json.dumps(accepted, indent=2) + "\n", encoding="utf-8")
    (output / "source-runs.json").write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8")

    sdk = "iphoneos" if args.platform == "device" else "iphonesimulator"
    download(native_runs["RUNTIME_RUN"], "audiveris-ios-runtime-" + args.platform, output / "runtime")
    download(native_runs["OCR_RUN"], "audiveris-ocr-" + sdk + "-arm64", output / "ocr")
    modules = exactly_one(output / "runtime", "headless/runtime/lib/modules")
    ocr = exactly_one(output / "ocr", "install/lib/libjnitesseract.a")
    inventory = json.loads(exactly_one(output / "runtime", "runtime-inventory.json").read_text())
    validate_runtime(inventory, args.platform, pinned["openjdk_source_commit"])
    resolved = {"EMBEDDED_RUNTIME": str(modules.parents[2]), "EMBEDDED_OCR": str(ocr.parents[1])}
    (output / "resolved-paths.json").write_text(json.dumps(resolved, indent=2) + "\n", encoding="utf-8")
    if os.environ.get("GITHUB_ENV"):
        with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as environment:
            for key, value in resolved.items():
                if "\n" in value or "\r" in value:
                    raise ValueError("Invalid build path")
                environment.write(key + "=" + value + "\n")
    print(json.dumps(resolved, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit("Native artifact preparation stopped: " + str(error)) from error
