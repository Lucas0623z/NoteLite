#!/usr/bin/env python3
"""Hash only the reviewed public account-service file list; never walk a tree."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def public_manifest(root):
    root = Path(root)
    names = json.loads((root / "deploy/public-source-files.json").read_text(encoding="utf-8"))
    if not isinstance(names, list) or not names or any(not isinstance(n, str) for n in names):
        raise ValueError("Invalid public source list")
    if len(set(n.casefold() for n in names)) != len(names):
        raise ValueError("Duplicate public source path")
    required = {"account_service.py", "practice_analysis.py", "performance_analysis.py", "fixtures/notewise-v2.json", "test_performance_analysis.py", "test_history_analysis_versions.py"}
    if not required <= set(names):
        raise ValueError("Incomplete performance analysis source offer")
    result = {}
    for name in names:
        relative = PurePosixPath(name)
        if (not name or "\\" in name or ":" in name or relative.is_absolute()
                or any(p in {"..", "private", "private-assets", "skills", "__pycache__"} for p in relative.parts)
                or relative.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".pem", ".p12", ".wav", ".mp3"}):
            raise ValueError("Unsafe public source path")
        path = root / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Missing or escaped public source file")
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(sorted(result.items()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    output = json.dumps(public_manifest(arguments.root), indent=2) + "\n"
    if arguments.output:
        arguments.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
