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
import statistics

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


def note_result(events, seconds: float, a4: float = 440) -> dict:
    notes = []
    for start, end, pitch, confidence, *remaining in events:
        onset, end, confidence = float(start), float(end), float(confidence)
        midi = int(pitch)
        if not all(math.isfinite(n) for n in (onset, end, confidence)):
            raise ValueError("Transcription contains non-finite values")
        # The final inference window is padded by upstream. Remove padding
        # events and trim releases to the actual recording duration.
        onset, end = max(0.0, onset), min(seconds, end)
        if 0 <= midi <= 127 and end > onset:
            bends = remaining[0] if remaining and remaining[0] is not None else []
            cents_curve = [float(b)*100/3 for b in bends]
            absolute_pitch = midi+(statistics.median(cents_curve) if cents_curve else 0)/100
            sounding_frequency = 440*2**((absolute_pitch-69)/12)
            tuned_pitch = absolute_pitch-12*math.log2(a4/440)
            tuned_midi = round(tuned_pitch)
            notes.append({"midi": tuned_midi, "modelMidi": midi, "modelConfidence": confidence,
                          "modelPitchBendSteps": [int(b) for b in bends], "onset": round(onset, 6),
                          "duration": round(end-onset, 6),
                          "confidence": round(max(0.0, min(1.0, confidence)), 6),
                          "cents": round((tuned_pitch-tuned_midi)*100, 3), "pitchCents": round(tuned_pitch*100, 3),
                          "frequency": round(sounding_frequency, 6), "pitchBendCents": [round(c,3) for c in cents_curve],
                          "engine": "basic-pitch", "voiced": True})
    if len(notes) > MAX_NOTES:
        raise ValueError("Transcription exceeds 20000 note events")
    notes.sort(key=lambda n: (n["onset"], n["midi"]))
    return {"schemaVersion": 1, "engine": "basic-pitch", "notes": notes,
            "seconds": round(seconds, 6), "a4": a4}


def model_path(home: Path) -> Path:
    model = home / "models" / "basic-pitch.onnx"
    manifest = home / "runtime-manifest.json"
    if not manifest.is_file():
        manifest = home/"runtime-ready.json"
    if not model.is_file() or not manifest.is_file():
        raise ValueError("Local Basic Pitch runtime has not been installed")
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    if metadata.get("engine") != "basic-pitch" or metadata.get("version") != "0.4.0":
        raise ValueError("Unsupported local runtime version")
    if hashlib.sha256(model.read_bytes()).hexdigest() != metadata.get("modelSha256"):
        raise ValueError("Local model checksum mismatch; reinstall the runtime")
    return model


def analyze(path: Path, home: Path, options: dict | None = None) -> dict:
    options = options or {}
    if options.get("input") in ("microphone", "recording") and options.get("verified") is not True:
        raise ValueError("The selected instruments must be confirmed before acoustic analysis")
    seconds = inspect_wav(path)
    a4 = float(options.get("a4", 440))
    if not 400 <= a4 <= 480:
        raise ValueError("A4 must be 400–480 Hz")
    if options.get("engine", "basic-pitch") != "basic-pitch":
        from mono_analysis import analyze_mono
        return analyze_mono(path, home, seconds, options)
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
        _, _, events = predict(str(path), runtime, multiple_pitch_bends=True)
    result = note_result(events, seconds, a4)
    from mono_analysis import read_audio
    from onset_evidence import merge_basic_pitch
    signal,rate=read_audio(path)
    result["notes"],result["rawNotes"],result["postprocessing"]=merge_basic_pitch(result["notes"],signal,rate)
    from pitch_refinement import refine
    result["notes"] = refine(result["notes"], path, a4)
    from mono_analysis import detector_range
    result["supportedPitchRange"] = detector_range(27.5,4186.009,a4)
    result["uncertaintyIntervals"] = [{"onset": n["onset"], "duration": n["duration"], "reason": "low-confidence-transcription"}
                                       for n in result["notes"] if n["confidence"] < float(options.get("threshold", .4))]
    result["uncertaintyIntervals"] += [{"onset":n["onset"],"duration":n["duration"],"reason":"unconfirmed-same-pitch-reattack"}
                                       for n in result["notes"] if n.get("reviewRequired")]
    result["warnings"] = ["Basic Pitch models MIDI 21–108 at A4=440 Hz; expected notes outside this model range remain unjudged.",
                          "Confidence is an engine activation, not a calibrated probability. Unresolved contour cents use 1/3-semitone bins."]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--operation", choices=("analyze", "normalize", "align"), default="analyze")
    parser.add_argument("--options", type=Path)
    args = parser.parse_args()
    try:
        if not args.output.is_absolute() or args.input.resolve() == args.output.resolve():
            raise ValueError("Output must be a different absolute JSON path")
        home = Path(__file__).resolve().parent
        sys.path.insert(0, str(home))
        options = json.loads(args.options.read_text(encoding="utf8")) if args.options else {}
        if args.operation == "analyze":
            result = analyze(args.input, home, options)
        elif args.operation == "normalize":
            from score_tools import normalize
            result = normalize(args.input.read_bytes(), options)
        else:
            from score_tools import align
            payload = json.loads(args.input.read_text(encoding="utf8")); payload["options"] = options or payload.get("options", {})
            result = align(payload, home)
        args.output.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        return 0
    except Exception as error:
        print(f"Local audio analysis failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
