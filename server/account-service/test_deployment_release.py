"""Exercise real release preflight and public source boundaries without deployment."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
REQUIRED = {"account_service.py", "practice_analysis.py", "performance_analysis.py", "integrated_service.py", "omr_bridge.py"}
spec = importlib.util.spec_from_file_location("public_manifest", ROOT / "deploy/build-public-manifest.py")
public_source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(public_source)


def release_preflight(name):
    # Installers perform privileged side effects at module load. Compile their
    # actual pure preflight function alone rather than executing any installer.
    tree = ast.parse((ROOT / "deploy" / name).read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "checked_account_release")
    namespace = {"Path": Path, "hashlib": hashlib}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROOT / "deploy" / name), "exec"), namespace)
    return namespace["checked_account_release"]


class DeploymentSourceTests(unittest.TestCase):
    def test_both_installers_require_the_new_normalizer_and_check_every_byte(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in REQUIRED:
                (root / name).write_bytes((name + " public fixture").encode())
            manifest = {n: hashlib.sha256((root / n).read_bytes()).hexdigest() for n in REQUIRED}
            for installer in ("install-ai.py", "install-integrated.py"):
                with self.subTest(installer=installer):
                    preflight = release_preflight(installer)
                    self.assertEqual(set(preflight(root, manifest)), REQUIRED)
                    with self.assertRaises(AssertionError):
                        preflight(root, {n: h for n, h in manifest.items() if n != "performance_analysis.py"})
                    (root / "performance_analysis.py").write_bytes(b"tampered")
                    with self.assertRaises(AssertionError):
                        preflight(root, manifest)
                    (root / "performance_analysis.py").write_bytes(b"performance_analysis.py public fixture")
                    for path in ("../escape.py", "C:/escape.py", "\\escape.py"):
                        with self.assertRaises(AssertionError):
                            preflight(root, {**manifest, path: "a" * 64})

    def test_current_public_manifest_contains_normalizer_evidence_and_no_private_assets(self):
        manifest = public_source.public_manifest(ROOT)
        self.assertIn("performance_analysis.py", manifest)
        self.assertIn("fixtures/notewise-v2.json", manifest)
        self.assertEqual(manifest["performance_analysis.py"], hashlib.sha256((ROOT / "performance_analysis.py").read_bytes()).hexdigest())
        self.assertFalse(any("skills/" in n or "private" in n or "system-prompt" in n for n in manifest))

    def test_unlisted_private_and_runtime_files_never_enter_source_offer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in public_source.public_manifest(ROOT):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / name).read_bytes())
            (root / "practice-history.sqlite").write_bytes(b"private database fixture")
            (root / "deepseek-key").write_bytes(b"synthetic private fixture")
            (root / "skills").mkdir()
            (root / "skills/system-prompt.txt").write_text("synthetic private prompt")
            self.assertEqual(public_source.public_manifest(root), public_source.public_manifest(ROOT))
            names = json.loads((root / "deploy/public-source-files.json").read_text())
            for unsafe in ("skills/system-prompt.txt", "practice-history.sqlite", "../escape.py"):
                (root / "deploy/public-source-files.json").write_text(json.dumps(names + [unsafe]))
                with self.assertRaises(ValueError):
                    public_source.public_manifest(root)


if __name__ == "__main__":
    unittest.main()
