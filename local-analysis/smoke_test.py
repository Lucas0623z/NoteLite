"""Execute the actual installed ONNX engine on known audio, with no network."""
import argparse
import json
import math
from pathlib import Path
import struct
import subprocess
import tempfile
import wave


def write_audio(path, silence=False):
    rate, seconds = 22050, 6
    samples = bytearray()
    for k in range(rate*seconds):
        time = k/rate
        value = 0
        if not silence:
            for start, duration, pitches in [(1, 1.3, [60, 64, 67]), (3, 1, [62]), (4.5, .8, [60])]:
                elapsed = time-start
                if 0 <= elapsed < duration:
                    envelope = min(1, elapsed/.015)*math.exp(-elapsed*1.7)*min(1, (duration-elapsed)/.08)
                    for pitch in pitches:
                        frequency = 440*2**((pitch-69)/12)
                        angle = 2*math.pi*frequency*elapsed
                        value += envelope*(math.sin(angle)+.25*math.sin(2*angle)+.1*math.sin(3*angle))*.16
        samples.extend(struct.pack("<h", round(max(-1, min(1, value))*32767)))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(rate)
        wav.writeframes(samples)


def run(runtime, input, output):
    process = subprocess.run([str(runtime/"python"/"python.exe"), str(runtime/"analyze.py"),
                              "--input", str(input), "--output", str(output)],
                             capture_output=True, text=True, timeout=300)
    if process.returncode:
        raise AssertionError(process.stderr)
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["schemaVersion"] == 1 and result["engine"] == "basic-pitch"
    print(json.dumps(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="notelite-model-smoke-") as directory:
        temp = Path(directory)
        chord = temp/"chord.wav"; write_audio(chord)
        result = run(args.runtime.resolve(), chord, temp/"chord.json")
        for pitch, time in [(60, 1), (64, 1), (67, 1), (62, 3), (60, 4.5)]:
            assert any(n["midi"] == pitch and abs(n["onset"]-time) < .15 for n in result["notes"]), (pitch, time)
        silence = temp/"silence.wav"; write_audio(silence, silence=True)
        assert run(args.runtime.resolve(), silence, temp/"silence.json")["notes"] == []
        if args.reference:
            run(args.runtime.resolve(), args.reference.resolve(), temp/"reference.json")
    print("Actual local Basic Pitch ONNX smoke tests passed.")


if __name__ == "__main__":
    main()
