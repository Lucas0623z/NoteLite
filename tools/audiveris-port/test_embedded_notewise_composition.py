"""Exercise embedded project assembly with synthetic archives, without Xcode.

These checks verify the generated bridge and retain the existing artifact
integrity guard. They do not claim native compilation, inference or signing.
"""
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools/audiveris-port/build-embedded-app.sh"


def composition_body():
    source = SCRIPT.read_text(encoding="utf8")
    return source.split('python3 - "$repo" "$embedding" "$project" "$sdk" <<\'PY\'\n', 1)[1].split("\nPY\n", 1)[0]


def included_local_headers(path, seen=None):
    seen = set() if seen is None else seen
    path = path.resolve()
    if path in seen:
        return ""
    seen.add(path)
    text = path.read_text(encoding="utf8")
    return text + "\n" + "\n".join(included_local_headers(path.parent / name, seen)
                                  for name in re.findall(r'^\s*#include\s+"([^"]+)"', text, re.M))


class EmbeddedNoteWiseCompositionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.embedding, self.project = self.root / "embedding", self.root / "project"
        (self.embedding / "resources").mkdir(parents=True)
        (self.project / "Generated").mkdir(parents=True)
        (self.project / "EmbeddedRuntime").mkdir()
        (self.project / "EmbeddedRuntime/EmbeddedJVM.h").write_text("#pragma once\nvoid *synthetic_jvm_entry(void);\n", encoding="utf8")
        self.archive = self.root / "synthetic-native.a"
        self.archive.write_bytes(b"synthetic archive integrity fixture, not a native runtime")
        include = self.root / "jni-include"
        include.mkdir()
        self.inventory = {"sdk": "iphoneos", "architecture": "arm64", "nativeArchives": [
            {"path": str(self.archive), "sha256": hashlib.sha256(self.archive.read_bytes()).hexdigest()}]}
        (self.embedding / "resources/build-inventory.json").write_text(json.dumps(self.inventory), encoding="utf8")
        (self.embedding / "native-libraries.xcconfig").write_text('HEADER_SEARCH_PATHS = $(inherited) "' + str(include) + '"\n', encoding="utf8")

    def tearDown(self):
        self.temporary.cleanup()

    def compose(self, repo=REPO):
        with patch.object(sys, "argv", ["compose", str(repo), str(self.embedding), str(self.project), "iphoneos"]):
            exec(compile(composition_body(), str(SCRIPT) + ":composition", "exec"), {"__name__": "__main__"})

    def test_embedded_bridge_exposes_both_jvm_and_local_notewise_api(self):
        self.compose()
        specification = json.loads((self.project / "embedded-project.json").read_text(encoding="utf8"))
        bridge = Path(specification["targets"]["NoteLite"]["settings"]["base"]["SWIFT_OBJC_BRIDGING_HEADER"])
        declarations = included_local_headers(bridge)
        for symbol in ("synthetic_jvm_entry", "nw_create_profile", "nw_push", "nw_poll", "nw_destroy", "nw_finish", "nl_note_event"):
            self.assertRegex(declarations, r"\b" + symbol + r"\b")
        self.assertEqual(specification["include"], [{"path": str(REPO / "apple/project.yml"), "relativePaths": True}])
        self.assertIn({"path": "Generated/OMRResources", "type": "folder", "buildPhase": "resources"}, specification["targets"]["NoteLite"]["sources"])
        self.assertEqual((self.project / "EmbeddedRuntime/EmbeddedJVM.h").read_text(), "#pragma once\nvoid *synthetic_jvm_entry(void);\n")

    def test_composition_rejects_missing_notewise_native_source(self):
        missing_repo = self.root / "incomplete-source"
        with self.assertRaisesRegex(SystemExit, "local NoteWise native source is missing"):
            self.compose(missing_repo)
        self.assertFalse((self.project / "embedded-project.json").exists())

    def test_existing_exact_native_archive_guard_still_rejects_changed_bytes(self):
        self.archive.write_bytes(b"changed synthetic archive")
        with self.assertRaisesRegex(SystemExit, "native archive changed after probe composition"):
            self.compose()
        self.assertFalse((self.project / "embedded-project.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
