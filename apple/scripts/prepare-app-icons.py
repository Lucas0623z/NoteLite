#!/usr/bin/env python3
"""Package the user-supplied, complete square logo at the existing Apple sizes.

Only full-image resampling is performed: no crop, redraw, mask or recoloring.
Use --verify-only to inspect the committed assets without changing them.
"""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image

SOURCE_SHA256 = "624e7b112e0bac0af8233de93b7ee6febf820644584c9343fbcbd92352aa5ed5"


def prepare(verify_only=False):
    repository = Path(__file__).resolve().parents[2]
    source = repository / "figma-ui/src/imports/app-logo.png"
    icons = repository / "apple/NoteLite/Assets.xcassets/AppIcon.appiconset"
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("The supplied original logo does not match its locked source hash")
    with Image.open(source) as original:
        original.load()
        if original.format != "PNG" or original.mode != "RGB" or original.size != (1254, 1254):
            raise ValueError("Expected the original opaque 1254x1254 RGB PNG logo")
        manifest = json.loads((icons / "Contents.json").read_text(encoding="utf8"))
        dimensions = {}
        for entry in manifest["images"]:
            name = entry["filename"]
            if Path(name).name != name:
                raise ValueError("Unexpected app icon filename")
            width, height = (float(x) for x in entry["size"].split("x"))
            scale = float(entry.get("scale", "1x")[:-1])
            size = (int(width * scale), int(height * scale))
            if width != height or name != f"AppIcon-{size[0]}.png":
                raise ValueError("App icon size does not match its asset catalog reference")
            if name in dimensions and dimensions[name] != size:
                raise ValueError("Conflicting app icon dimensions")
            dimensions[name] = size
        if sorted(size[0] for size in dimensions.values()) != [16, 32, 64, 128, 256, 512, 1024]:
            raise ValueError("Required native icon resolutions are incomplete")
        if sum(e.get("platform") == "ios" and e["size"] == "1024x1024" for e in manifest["images"]) != 1:
            raise ValueError("The universal iPhone/iPad App Store icon reference is missing")
        if sum(e["idiom"] == "mac" for e in manifest["images"]) != 10:
            raise ValueError("The native Mac icon slots are incomplete")
        evidence = []
        for name, size in sorted(dimensions.items(), key=lambda pair: pair[1][0]):
            resized = original.resize(size, Image.Resampling.LANCZOS)
            target = icons / name
            if not verify_only:
                resized.save(target, format="PNG", optimize=True)
            with Image.open(target) as actual:
                actual.load()
                if actual.format != "PNG" or actual.mode != "RGB" or actual.size != size:
                    raise ValueError("App icon must have exact dimensions and no alpha channel")
                if actual.tobytes() != resized.tobytes():
                    raise ValueError("App icon does not preserve the entire supplied logo")
            evidence.append({"path": target.relative_to(repository).as_posix(),
                             "size": list(size), "mode": "RGB", "alpha": False,
                             "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    project = (repository / "apple/project.yml").read_text(encoding="utf8")
    if project.count("ASSETCATALOG_COMPILER_APPICON_NAME: AppIcon") != 2:
        raise ValueError("Both Apple application targets must reference AppIcon")
    return {"status": "passed", "source": {"path": source.relative_to(repository).as_posix(),
             "size": [1254, 1254], "mode": "RGB", "alpha": False, "sha256": SOURCE_SHA256},
            "operation": "Full square image resized with LANCZOS; no cropping, redrawing or masking",
            "appIconCatalogReferences": 11, "nativePlatforms": ["iPhone", "iPad", "Mac"],
            "storeIconSize": [1024, 1024], "assets": evidence,
            "nativeAssetCompilerExecuted": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()
    proof = prepare(arguments.verify_only)
    if arguments.report:
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({"status": proof["status"], "sourceSize": proof["source"]["size"],
                      "iconsVerified": len(proof["assets"]), "storeIconSize": proof["storeIconSize"],
                      "sourceSHA256": SOURCE_SHA256, "alpha": False}))
