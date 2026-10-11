import importlib.util
import math
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("model_patch", Path(__file__).with_name("patch-notewise-coreml.py"))
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)


class NoteWiseModelPatchTests(unittest.TestCase):
    def test_exact_official_model_is_recoverable_and_repatch_identical(self):
        metadata = patcher.load_patch()
        current = (patcher.ROOT / patcher.MODEL).read_bytes()
        upstream = patcher.transform(current, metadata, restore=True)
        self.assertEqual(patcher.digest(upstream), "af7bf7d49bc167e0bf0c30aa2ca6b432c3e10df048d2dd4173ff3a738c020858")
        self.assertEqual(len(upstream), 123027)
        self.assertEqual(patcher.transform(upstream, metadata), current)

    def test_tampered_input_or_payload_cannot_be_patched(self):
        metadata = patcher.load_patch()
        current = (patcher.ROOT / patcher.MODEL).read_bytes()
        upstream = patcher.transform(current, metadata, restore=True)
        with self.assertRaises(ValueError):
            patcher.transform(upstream[:-1] + bytes([upstream[-1] ^ 1]), metadata)
        changed = dict(metadata, replacementOperations=list(metadata["replacementOperations"]))
        changed["replacementOperations"][0] = changed["originalOperation"]
        with self.assertRaises(ValueError):
            patcher.transform(upstream, changed)

    def test_wire_parser_rejects_truncation(self):
        for data in [b"\x12\x05ab", b"\x80", b"\x01a", b"\x00"]:
            with self.assertRaises(ValueError):
                list(patcher.fields(data))

    def test_exact_zero_semantics_has_no_epsilon(self):
        def repaired(x, y):
            zero = y == 0
            safe_y = 1 if zero else y
            quotient = x / safe_y
            return 0 if zero else quotient
        for x in [0, 2, -2, float("nan")]:
            self.assertEqual(repaired(x, 0), 0)
        for x, y in [(1, 1e-30), (-2, 7), (0, -1e-30), (3, 2)]:
            self.assertEqual(repaired(x, y), x / y)
        self.assertFalse(math.isnan(repaired(0, 0)))


if __name__ == "__main__":
    unittest.main()
