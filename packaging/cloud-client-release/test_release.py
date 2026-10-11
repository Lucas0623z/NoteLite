"""Isolated payload/signing gate tests; all credential-looking values are synthetic."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SPEC = importlib.util.spec_from_file_location("cloud_release", Path(__file__).with_name("release.py"))
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.repo = self.root / "repo"
        self.figma, self.practice = self.repo / "figma-ui/dist", self.repo / "app/res/practice"
        for p in (self.figma, self.practice):
            p.mkdir(parents=True)
            (p / "index.html").write_text("<html><script src='app.js'></script></html>")
            (p / "app.js").write_text("(()=>{console.info('NoteLite');})();")
        (self.repo / "LICENSE").write_text("Original application license retained.")
        (self.practice / "THIRD-PARTY.txt").write_text("Basic Pitch original component name and license retained.")
        (self.practice / "demo.musicxml").write_text("<score-partwise/>")
        for name in ("react", "react-dom", "opensheetmusicdisplay"):
            node = self.repo / "figma-ui/node_modules" / name
            node.mkdir(parents=True)
            (node / "package.json").write_text(json.dumps({"name": name, "version": "1.0.0", "license": "MIT"}))
            (node / "LICENSE").write_text("Test license fixture retained in full. " * 3)
        self.output = self.root / "candidate"

    def prepare(self):
        return release.prepare(self.figma, self.practice, self.output, repo=self.repo)

    def test_real_copy_inventory_and_unsigned_candidate_scope(self):
        manifest = self.prepare()
        self.assertFalse(manifest["readyForDistribution"])
        self.assertFalse(manifest["serverOMRIncluded"])
        self.assertEqual((self.figma / "app.js").read_bytes(), (self.output / "FigmaUI/app.js").read_bytes())
        self.assertIn("Basic Pitch", (self.output / "practice/THIRD-PARTY.txt").read_text())
        archive = self.root / "candidate.zip"
        report = release.package(self.output, archive, "web-candidate")
        self.assertFalse(report["readyForDistribution"])
        with zipfile.ZipFile(archive) as z:
            self.assertEqual((self.output / "FigmaUI/app.js").read_bytes(), z.read("candidate/FigmaUI/app.js"))

    def test_source_maps_omitted_from_resources(self):
        (self.figma / "app.js.map").write_text('{"sourcesContent":["test source"]}')
        self.prepare()
        self.assertFalse((self.output / "FigmaUI/app.js.map").exists())

    def test_nested_runtime_dependency_license_is_retained(self):
        parent = self.repo / "figma-ui/node_modules/opensheetmusicdisplay"
        metadata = json.loads((parent / "package.json").read_text())
        metadata["dependencies"] = {"vexflow": "1.0.0"}
        (parent / "package.json").write_text(json.dumps(metadata))
        dependency = parent / "node_modules/vexflow"
        dependency.mkdir(parents=True)
        (dependency / "package.json").write_text(json.dumps({"name": "vexflow", "version": "1.0.0", "license": "MIT"}))
        (dependency / "LICENSE").write_text("Nested VexFlow license fixture retained in full. " * 3)
        self.prepare()
        self.assertIn("Nested VexFlow", (self.output / "FigmaUI/THIRD-PARTY.txt").read_text())

    def test_inline_or_external_sourcemap_reference_rejected(self):
        (self.figma / "app.js").write_text("console.info('app');\n//# sourceMappingURL=data:application/json;base64,e30=")
        with self.assertRaises(release.GateError): self.prepare()

    def test_added_or_changed_file_invalidates_inventory(self):
        self.prepare()
        (self.output / "FigmaUI/app.js").write_text("modified")
        with self.assertRaises(release.GateError): release.verify_inventory(self.output)

    def test_embedded_credential_rejected_without_echoing_value(self):
        (self.figma / "app.js").write_text("const bad='Bearer " + "A" * 43 + "';")
        with self.assertRaises(release.GateError) as error: self.prepare()
        self.assertNotIn("A" * 43, str(error.exception))

    def test_private_filename_rejected_before_reading(self):
        (self.figma / ".env").write_text("SYNTHETIC=fixture")
        with patch.object(Path, "read_bytes", side_effect=AssertionError("must not read forbidden private file")):
            with self.assertRaises(release.GateError): release.audit_tree(self.figma)

    def test_development_native_markers_rejected(self):
        (self.figma / "app.js").write_text("const diagnostic='noteLiteDiagnostics';")
        with self.assertRaises(release.GateError): self.prepare()

    def test_server_engine_and_user_payload_rejected(self):
        for name in ("server/account_service.py", "OMRResources/runtime/lib/modules", "lib/omr-midi.jar", "recording.wav", "uploaded.musicxml"):
            with self.subTest(name=name), self.assertRaises(release.GateError): release.policy(name)

    def test_unsafe_paths_and_duplicate_case_rejected(self):
        for name in ("../app.js", "C:/app.js", "dir\\app.js", "CON.txt", "app.js. "):
            with self.subTest(name=name), self.assertRaises(release.GateError): release.safe_name(name)
        self.assertRaises(release.GateError, release.audit_tree, self.root / "missing")

    def test_release_does_not_overwrite_existing_files(self):
        self.output.mkdir()
        (self.output / "keep.txt").write_text("user data outside package input")
        with self.assertRaises(release.GateError): self.prepare()
        self.assertTrue((self.output / "keep.txt").is_file())

    def test_signature_failure_produces_no_native_release_archive(self):
        self.prepare()
        archive = self.root / "native.zip"
        with patch.object(release, "verify_signature", side_effect=release.GateError("unsigned")):
            with self.assertRaises(release.GateError): release.package(self.output, archive, "windows", "Synthetic publisher")
        self.assertFalse(archive.exists())

    @unittest.skipUnless(os.name == "nt", "Actual Windows Authenticode rejection requires Windows")
    def test_actual_unsigned_windows_executable_is_rejected(self):
        app = self.root / "app"
        app.mkdir()
        (app / "NoteLite.exe").write_bytes(b"MZ" + b"\x00" * 128)
        with self.assertRaises(release.GateError): release.verify_signature(app, "windows", "CN=Synthetic publisher")

    def test_wrong_publisher_or_missing_timestamp_rejected(self):
        app = self.root / "signed-fixture"
        app.mkdir()
        (app / "NoteLite.exe").write_bytes(b"synthetic executable")
        for result in ({"status": "Valid", "publisher": "wrong", "timestamp": True},
                       {"status": "Valid", "publisher": "expected", "timestamp": False}):
            with patch.object(release.os, "name", "nt"), patch.object(release, "command", return_value=json.dumps(result)):
                with self.assertRaises(release.GateError): release.verify_signature(app, "windows", "expected")


if __name__ == "__main__":
    unittest.main()
