"""Extract the pinned Windows CPython wheels into an isolated offline runtime.

The PowerShell entry point bootstraps CPython first. No pip dependency resolution
or package build scripts run: every downloaded archive is SHA-256 verified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import urllib.request
import zipfile


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def cached(artifact: dict, cache: Path, offline: bool) -> Path:
    path = cache/artifact["filename"]
    if not path.is_file():
        if offline:
            raise ValueError(f"Missing offline artifact: {path.name}")
        temporary = path.with_suffix(path.suffix+".partial")
        try:
            urllib.request.urlretrieve(artifact["url"], temporary)
            if checksum(temporary) != artifact["sha256"]:
                raise ValueError(f"Checksum mismatch: {path.name}")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    if checksum(path) != artifact["sha256"]:
        raise ValueError(f"Checksum mismatch: {path.name}")
    return path


def safe_target(base: Path, name: str) -> Path:
    parts = PurePosixPath(name).parts
    if not parts or any(part in ("..", "/") or ":" in part or "\\" in part for part in parts):
        raise ValueError("Unsafe package archive path")
    target = base.joinpath(*parts)
    if not target.resolve().is_relative_to(base.resolve()):
        raise ValueError("Package archive escapes runtime")
    return target


def install(destination: Path, cache: Path, lockfile: Path, offline: bool, native_tools: Path | None = None, skip_native=False) -> None:
    lock = json.loads(lockfile.read_text(encoding="utf-8"))
    (destination/"runtime-ready.json").unlink(missing_ok=True)
    site = destination/"python"/"site-packages"
    site.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    for artifact in lock["packages"]:
        archive = cached(artifact, cache, offline)
        print(f"Installing {artifact['name']} {artifact['version']}", flush=True)
        if archive.name.endswith(".whl"):
            with zipfile.ZipFile(archive) as wheel:
                for member in wheel.infolist():
                    name = member.filename
                    # ONNX's upstream conformance corpus is not needed for
                    # inference/conversion and exceeds legacy Windows path limits.
                    if artifact["name"] == "onnx" and name.startswith(("onnx/backend/test/", "onnx/test/")):
                        continue
                    base = site
                    # Entry-point scripts are not used in this isolated adapter.
                    # Purelib/platlib relocation is a normal wheel operation;
                    # no executable post-install scripts ever run.
                    if ".data/" in member.filename:
                        _, category, rest = member.filename.split("/", 2)
                        if category == "scripts":
                            continue
                        if category == "data":
                            base = destination/"python"
                        elif category not in ("purelib", "platlib"):
                            raise ValueError("Unexpected wheel relocation directory")
                        name = rest
                    target = safe_target(base, name)
                    if member.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with wheel.open(member) as source, target.open("wb") as output:
                            shutil.copyfileobj(source, output)
        elif artifact["name"] == "pretty-midi":
            # Pretty MIDI is pure Python but publishes an sdist only. Extract
            # its package and license without executing setup.py. The unused
            # soundfont is omitted; NoteLite never calls the synthesis API.
            with tarfile.open(archive) as source:
                for member in source.getmembers():
                    relative = PurePosixPath(member.name)
                    if len(relative.parts) == 2 and relative.parts[1] == "LICENSE.txt" and member.isfile():
                        license = safe_target(site, "pretty_midi/LICENSE.txt")
                        license.parent.mkdir(parents=True, exist_ok=True)
                        with source.extractfile(member) as contents, license.open("wb") as output:
                            shutil.copyfileobj(contents, output)
                        continue
                    if len(relative.parts) < 2 or relative.parts[1] != "pretty_midi":
                        continue
                    if relative.suffix.lower() == ".sf2":
                        continue
                    target = safe_target(site, str(PurePosixPath(*relative.parts[1:])))
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    elif member.isfile():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with source.extractfile(member) as contents, target.open("wb") as output:
                            shutil.copyfileobj(contents, output)
                    else:
                        raise ValueError("Unsupported source archive entry")
            # Upgrade/reinstall of an earlier NoteLite runtime must also remove
            # this specific obsolete asset. No other installed files are touched.
            safe_target(site, "pretty_midi/TimGM6mb.sf2").unlink(missing_ok=True)
        else:
            raise ValueError("Unsupported package archive")
    source = site/"basic_pitch"/"saved_models"/"icassp_2022"/"nmp.onnx"
    model = destination/"models"/"basic-pitch.onnx"
    model.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, model)
    if checksum(model) != lock["modelSha256"]:
        raise ValueError("Basic Pitch model checksum mismatch")
    shutil.copy2(lockfile.with_name("analyze.py"), destination/"analyze.py")
    shutil.copy2(lockfile.with_name("THIRD-PARTY.txt"), destination/"THIRD-PARTY.txt")
    # Embeddable CPython reads only this local list and ignores external
    # PYTHONPATH/user packages. Wheel .pth files are not required.
    (destination/"python"/"python311._pth").write_text(
        "python311.zip\n.\nsite-packages\nimport site\n", encoding="utf-8")
    # Import and load the actual model before writing the readiness marker.
    import sys
    sys.path.insert(0, str(site))
    sys.path.insert(0, str(lockfile.parent))
    from basic_pitch.inference import Model
    engine = Model(str(model))
    if engine.model_type != Model.MODEL_TYPES.ONNX or engine.model.get_inputs()[0].name != "serving_default_input_2:0":
        raise ValueError("Unexpected Basic Pitch ONNX model")
    import bz2
    from crepe_onnx import convert
    crepe_archive = cached(lock["crepe"], cache, offline)
    crepe_weights = cache/"crepe-tiny.h5"
    crepe_weights.write_bytes(bz2.decompress(crepe_archive.read_bytes()))
    crepe_model = destination/"models"/"crepe-tiny.onnx"
    convert(crepe_weights, crepe_model)
    import partitura, parangonar, librosa
    import onnxruntime
    onnxruntime.InferenceSession(str(crepe_model), providers=["CPUExecutionProvider"])
    for name in ("mono_analysis.py", "crepe_onnx.py", "score_tools.py", "pitch_refinement.py", "runtime_smoke.py", "onset_evidence.py"):
        shutil.copy2(lockfile.with_name(name), destination/name)
    licenses = destination/"licenses"; licenses.mkdir(exist_ok=True)
    shutil.copy2(lockfile.with_name("vendor")/"crepe"/"LICENSE", licenses/"CREPE-MIT.txt")
    if not skip_native:
        native_tools = native_tools or lockfile.parent.parent/"native"/"audio"/"build"/"analysis-tools"
        aubio = native_tools/"AubioMono.exe"
        names = ["SprToFmt3x", "Fmt3xToHmm", "ScorePerfmMatcher", "ErrorDetection", "RealignmentMOHMM", "MatchToCorresp"]
        if not aubio.is_file() or not all((native_tools/"nakamura"/(name+".exe")).is_file() for name in names):
            raise ValueError("Build tools/build-local-audio.ps1 -AnalysisTools before installing the complete runtime")
        binaries = destination/"native"; binaries.mkdir(exist_ok=True)
        shutil.copy2(aubio, binaries/"AubioMono.exe")
        (binaries/"nakamura").mkdir(exist_ok=True)
        for executable in (native_tools/"nakamura").iterdir():
            if executable.is_file() and executable.suffix.lower() in (".exe", ".dll"):
                shutil.copy2(executable, binaries/"nakamura"/executable.name)
        shutil.copy2(lockfile.parent/"vendor"/"aubio"/"COPYING", licenses/"aubio-GPL3.txt")
        shutil.copy2(lockfile.parent/"vendor"/"nakamura"/"LICENCE.txt", licenses/"Nakamura-MIT.txt")
        # Ship corresponding source, adapter and build scripts alongside GPL
        # aubio binaries. This also preserves Nakamura's published baseline code.
        sources = destination/"sources"
        for component in ("aubio", "nakamura"):
            shutil.copytree(lockfile.parent/"vendor"/component, sources/"local-analysis"/"vendor"/component, dirs_exist_ok=True)
        native_source = lockfile.parent.parent/"native"/"audio"
        shutil.copytree(native_source/"vendor"/"gcc-runtime", licenses/"GCC-Runtime", dirs_exist_ok=True)
        native_copy = sources/"native"/"audio"
        # Earlier installers could copy generated recordings into corresponding
        # source. Remove only that exact obsolete installed subtree; never the
        # original validation directory or a symlink/junction target.
        stale_output = native_copy/"test-output"
        if stale_output.exists():
            if (not native_copy.resolve().is_relative_to(destination.resolve())
                    or stale_output.is_symlink()
                    or stale_output.resolve() != native_copy.resolve()/"test-output"):
                raise ValueError("Unsafe installed test-output cleanup path")
            shutil.rmtree(stale_output)
        shutil.copytree(native_source, native_copy, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("build", "test-output", "work", "cache", "__pycache__", "*.pyc"))
        (sources/"tools").mkdir(parents=True,exist_ok=True)
        shutil.copy2(lockfile.parent.parent/"tools"/"build-local-audio.ps1", sources/"tools"/"build-local-audio.ps1")
    metadata = {
        "engine": "basic-pitch", "version": "0.4.0", "python": "3.11.9", "runtime": "onnx",
        "modelSha256": lock["modelSha256"], "lockSha256": checksum(lockfile), "crepeModelSha256": checksum(crepe_model),
        "partitura": partitura.__version__, "parangonar": parangonar.__version__, "librosa": librosa.__version__,
        "engines": ["basic-pitch", "pyin", "crepe"]+([] if skip_native else ["aubio"]),
        "alignmentBaselines": ["parangonar"]+([] if skip_native else ["nakamura"])
    }
    (destination/"runtime-manifest.json").write_text(json.dumps(metadata), encoding="utf8")
    from runtime_smoke import verify
    metadata["smoke"] = verify(destination, native=not skip_native)
    (destination/"runtime-ready.json").write_text(json.dumps(metadata), encoding="utf8")
    print("Actual local audio engines and offline baselines verified and ready.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--native-tools", type=Path)
    parser.add_argument("--skip-native", action="store_true")
    args = parser.parse_args()
    install(args.destination.resolve(), args.cache.resolve(), args.lock.resolve(), args.offline, args.native_tools, args.skip_native)
