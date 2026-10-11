#!/usr/bin/env python3
"""Verify the bundled official model; --fetch restores only the locked assets."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile


def prepare(fetch: bool = False) -> dict:
    root = Path(__file__).resolve().parents[1] / "NoteWiseModels"
    lock = json.loads((root / "MODEL-LOCK.json").read_text(encoding="utf-8"))
    assert lock["version"] == "0.4.0" and lock["model"]["shape"] == [1, 43844, 1]
    if fetch:
        source = lock["sourceWheel"]
        with urllib.request.urlopen(source["url"], timeout=45) as response:
            data = response.read(source["size"] + 1)
        if len(data) != source["size"] or hashlib.sha256(data).hexdigest() != source["sha256"]:
            raise ValueError("Official model source wheel failed its locked checksum")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for item in lock["files"]:
                relative = Path(item["path"])
                target = (root / relative).resolve()
                if not target.is_relative_to(root.resolve()):
                    raise ValueError("Asset path escapes model directory")
                member = ("basic_pitch-0.4.0.dist-info/LICENSE" if relative.name == "BASIC-PITCH-LICENSE"
                          else "basic_pitch/saved_models/icassp_2022/nmp.mlpackage/" + relative.as_posix().split("/", 1)[1])
                content = archive.read(member)
                if len(content) != item["size"] or hashlib.sha256(content).hexdigest() != item["sha256"]:
                    raise ValueError("Source model asset failed its locked checksum")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
    for item in lock["files"]:
        target = (root / item["path"]).resolve()
        if not target.is_relative_to(root.resolve()) or not target.is_file():
            raise ValueError("Bundled model asset is missing or outside its directory")
        data = target.read_bytes()
        if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError("Bundled model asset failed its locked checksum")
    actual = {p.relative_to(root).as_posix() for p in (root / "NoteWiseBasicPitch.mlpackage").rglob("*") if p.is_file()}
    expected = {x["path"] for x in lock["files"] if x["path"].startswith("NoteWiseBasicPitch.mlpackage/")}
    if actual != expected:
        raise ValueError("Unexpected or missing file in the bundled model package")
    return {"status": "passed", "version": lock["version"], "filesVerified": len(lock["files"]),
            "bytesVerified": sum(x["size"] for x in lock["files"]), "networkUsed": fetch,
            "nativeInferenceTested": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare(args.fetch), sort_keys=True))
