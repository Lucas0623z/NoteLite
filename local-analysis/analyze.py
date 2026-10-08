#!/usr/bin/env python3
"""NoteLite's offline WAV-to-note adapter for Spotify Basic Pitch 0.4.0.

No network, microphone, shell commands, or score data are used by this helper.
ONNX weights and all dependencies must already exist in the local runtime.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import wave

MAX_BYTES = 64 * 1024 * 1024
MAX_SECONDS = 600
MAX_NOTES = 20000


def inspect_wav(path: Path) -> float:
    if not path.is_absolute() or not path.is_file():
        raise ValueError("Input must be an existing absolute WAV path")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("WAV exceeds 64 MB")
    with wave.open(str(path), "rb") as wav:
        if wav.getcomptype() != "NONE" or wav.getsampwidth() != 2:
            raise ValueError("Use 16-bit PCM WAV")
        if wav.getnchannels() not in (1, 2) or not 8000 <= wav.getframerate() <= 96000:
            raise ValueError("Use mono/stereo WAV at 8000–96000 Hz")
        seconds = wav.getnframes() / wav.getframerate()
        if not 0 < seconds <= MAX_SECONDS:
            raise ValueError("Recording must last between 0 and 600 seconds")
        expected = wav.getnframes() * wav.getnchannels() * wav.getsampwidth()
        if len(wav.readframes(wav.getnframes())) != expected:
            raise ValueError("Truncated WAV data")
    return seconds


def note_result(events, seconds: float) -> dict:
    notes = []
    for start, end, pitch, confidence, *_ in events:
        onset, end, confidence = float(start), float(end), float(confidence)
        midi = int(pitch)
        if not all(math.isfinite(n) for n in (onset, end, confidence)):
            raise ValueError("Transcription contains non-finite values")
        # The final inference window is padded by upstream. Remove padding
        # events and trim releases to the actual recording duration.
        onset, end = max(0.0, onset), min(seconds, end)
        if 0 <= midi <= 127 and end > onset:
            notes.append({"midi": midi, "onset": round(onset, 6),
                          "duration": round(end-onset, 6),
                          "confidence": round(max(0.0, min(1.0, confidence)), 6)})
    if len(notes) > MAX_NOTES:
        raise ValueError("Transcription exceeds 20000 note events")
    notes.sort(key=lambda n: (n["onset"], n["midi"]))
    return {"schemaVersion": 1, "engine": "basic-pitch", "notes": notes,
            "seconds": round(seconds, 6)}


def model_path(home: Path) -> Path:
    model = home / "models" / "basic-pitch.onnx"
    manifest = home / "runtime-ready.json"
    if not model.is_file() or not manifest.is_file():
        raise ValueError("Local Basic Pitch runtime has not been installed")
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    if metadata.get("engine") != "basic-pitch" or metadata.get("version") != "0.4.0":
        raise ValueError("Unsupported local runtime version")
    if hashlib.sha256(model.read_bytes()).hexdigest() != metadata.get("modelSha256"):
        raise ValueError("Local model checksum mismatch; reinstall the runtime")
    return model


def analyze(path: Path, home: Path) -> dict:
    seconds = inspect_wav(path)
    model = model_path(home)
    # Prevent optional libraries from fetching assets. Basic Pitch weights are
    # supplied explicitly instead of using the runtime-dependent default model.
    os.environ.setdefault("NUMBA_NUM_THREADS", "2")
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    with contextlib.redirect_stdout(sys.stderr):
        from basic_pitch.inference import Model, predict
        runtime = Model(str(model))
        if runtime.model_type != Model.MODEL_TYPES.ONNX:
            raise ValueError("NoteLite requires the local ONNX runtime")
        _, _, events = predict(str(path), runtime, multiple_pitch_bends=False)
    return note_result(events, seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if not args.output.is_absolute() or args.input.resolve() == args.output.resolve():
            raise ValueError("Output must be a different absolute JSON path")
        result = analyze(args.input, Path(__file__).resolve().parent)
        args.output.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        return 0
    except Exception as error:
        print(f"Local audio analysis failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
