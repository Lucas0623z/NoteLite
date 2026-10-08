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


def install(destination: Path, cache: Path, lockfile: Path, offline: bool) -> None:
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
    from basic_pitch.inference import Model
    engine = Model(str(model))
    if engine.model_type != Model.MODEL_TYPES.ONNX or engine.model.get_inputs()[0].name != "serving_default_input_2:0":
        raise ValueError("Unexpected Basic Pitch ONNX model")
    (destination/"runtime-ready.json").write_text(json.dumps({
        "engine": "basic-pitch", "version": "0.4.0", "python": "3.11.9", "runtime": "onnx",
        "modelSha256": lock["modelSha256"], "lockSha256": checksum(lockfile)
    }), encoding="utf-8")
    print("Basic Pitch local ONNX runtime ready.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    install(args.destination.resolve(), args.cache.resolve(), args.lock.resolve(), args.offline)
