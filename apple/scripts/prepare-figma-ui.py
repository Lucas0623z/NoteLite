#!/usr/bin/env python3
"""Copy the separately built, unchanged-layout Figma interface into Xcode resources."""
from pathlib import Path
import json
import re
import shutil
import sys


def main():
    apple = Path(__file__).resolve().parents[1]
    source = apple.parent / "figma-ui" / "dist"
    target = apple / "FigmaUI"
    if target.resolve().parent != apple.resolve() or target.name != "FigmaUI":
        raise RuntimeError("Unexpected Apple resource destination")
    index = source / "index.html"
    if not index.is_file():
        raise RuntimeError("Build figma-ui before preparing the Apple resources")
    html = index.read_text(encoding="utf-8")
    if re.search(r'(?:src|href)=["\']/assets/', html):
        raise RuntimeError("Figma build must use relative asset paths (Vite base './')")
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    print(json.dumps({"resources": str(target), "files": sum(1 for item in target.rglob("*") if item.is_file())}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
