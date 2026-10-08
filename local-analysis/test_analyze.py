import importlib.util
import math
from pathlib import Path
import tempfile
import unittest
import wave

spec = importlib.util.spec_from_file_location("analyze", Path(__file__).with_name("analyze.py"))
analyze = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analyze)


class AdapterTest(unittest.TestCase):
    def test_midi_octaves_attacks_confidence_and_actual_duration(self):
        result = analyze.note_result([(1.0, 1.4, 60, .8, None), (1.0, 1.6, 72, .7, None),
                                      (2.0, 5.0, 60, 1.1, None), (3.1, 4, 65, .9, None)], 3)
        self.assertEqual([60, 72, 60], [n["midi"] for n in result["notes"]])
        self.assertEqual(1, result["notes"][2]["duration"])
        self.assertEqual(1, result["notes"][2]["confidence"])
        self.assertEqual("basic-pitch", result["engine"])

    def test_invalid_model_values_are_rejected(self):
        with self.assertRaises(ValueError):
            analyze.note_result([(0, 1, 60, math.nan, None)], 2)

    def test_pcm_header_is_checked_and_truncated_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"take.wav"
            with wave.open(str(path), "wb") as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(8000)
                wav.writeframes(bytes(16000))
            self.assertEqual(1, analyze.inspect_wav(path))
            path.write_bytes(path.read_bytes()[:-100])
            with self.assertRaises(ValueError):
                analyze.inspect_wav(path)


if __name__ == "__main__":
    unittest.main()
