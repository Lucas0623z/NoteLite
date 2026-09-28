"""Release gates must reject a green run that tested different code or native builds."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "native_artifacts", Path(__file__).with_name("download-native-artifacts.py"))
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


class NativeArtifactGateTests(unittest.TestCase):
    def setUp(self):
        self.run = {"id": 123, "head_sha": "a" * 40,
                    "path": ".github/workflows/audiveris-ios-embedded-probe.yml",
                    "html_url": "https://github.com/example/app/actions/runs/123",
                    "status": "completed", "conclusion": "success"}

    def test_success_requires_matching_workflow_and_source(self):
        self.assertEqual(self.run, native.validate_run(
            self.run, "audiveris-ios-embedded-probe.yml", "a" * 40))
        for key, value in [("status", "in_progress"), ("conclusion", "failure"),
                           ("path", ".github/workflows/apple-client.yml"), ("head_sha", "b" * 40)]:
            with self.subTest(key=key):
                altered = dict(self.run, **{key: value})
                with self.assertRaises(ValueError):
                    native.validate_run(altered, "audiveris-ios-embedded-probe.yml", "a" * 40)

    def test_acceptance_must_use_the_same_native_builds(self):
        sources = {"RUNTIME_RUN": dict(self.run), "OCR_RUN": dict(self.run, id=456)}
        native.validate_acceptance_sources(copy.deepcopy(sources), sources)
        for key in sources:
            changed = copy.deepcopy(sources)
            changed[key]["id"] += 1
            with self.subTest(key=key), self.assertRaises(ValueError):
                native.validate_acceptance_sources(changed, sources)
        with self.assertRaises(ValueError):
            native.validate_acceptance_sources({}, sources)

    def test_runtime_must_include_the_complete_matching_module_image(self):
        inventory = {"source_commit": "a" * 40, "platform": "device", "vm": "zero",
                     "headless_build_exit_code": 0, "java_desktop_jmod": True,
                     "runtime_module_image": True, "missing_required_libraries": []}
        native.validate_runtime(inventory, "device", "a" * 40)
        for key, value in [("source_commit", "b" * 40), ("platform", "simulator"),
                           ("vm", "server"), ("headless_build_exit_code", 1),
                           ("java_desktop_jmod", False), ("runtime_module_image", False),
                           ("missing_required_libraries", ["libfontmanager.a"])]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                native.validate_runtime(dict(inventory, **{key: value}), "device", "a" * 40)

    def test_only_real_run_ids_are_accepted(self):
        self.assertEqual("123", native.run_id(123))
        for value in ("", "0", "-1", "--help", "123\n", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                native.run_id(value)


if __name__ == "__main__":
    unittest.main()
