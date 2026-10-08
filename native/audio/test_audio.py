"""Execute the production Windows helper on deterministic PCM and optional attributed recordings.

Only standard-library Python is required. No microphone is opened and no files are downloaded.
Real recordings use the existing practice-web benchmark's checksum-verified manifest.
"""
import argparse
import array
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import struct
import subprocess
import sys
import time
import wave

RATE = 48000
PROFILES = {
    "sine": [1], "flute_like": [1, .2, .04, .02],
    "clarinet_like": [1, 0, .65, 0, .4, 0, .2],
    "bowed_string_like": [1, .75, .5, .4, .3, .2],
    "plucked_string_like": [1, .8, .45, .3, .2, .12],
    "voice_like": [1, .45, .3, .4, .25, .12],
}


def wav(path, samples, rate=RATE):
    """Lossless float WAV permits verifying the recorder without quantization differences."""
    values = array.array("f", samples)
    if sys.byteorder != "little":
        values.byteswap()
    data = values.tobytes()
    header = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(data), b"WAVE",
                         b"fmt ", 16, 3, 1, rate, rate * 4, 4, 32, b"data", len(data))
    path.write_bytes(header + data)


def run(exe, path, *arguments, successful=True):
    result = subprocess.run([str(exe), "--analyze", str(path), *map(str, arguments)],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    frames = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    if successful:
        assert result.returncode == 0, (result.returncode, frames, result.stderr)
        assert frames[0]["type"] == "ready", frames[:1]
        assert frames[-1]["type"] == "stopped", frames[-1:]
    return frames, result.returncode


def tones(hz, harmonics, seconds=.35, cents=0, snr_db=None, rate=RATE):
    rand = random.Random(4817)
    hz *= 2 ** (cents / 1200)
    total = sum(harmonics)
    output = []
    for i in range(round(rate * seconds)):
        envelope = min(1, i / (rate * .01))
        output.append(.25 / total * envelope * sum(
            a * math.sin(2 * math.pi * (h + 1) * hz * i / rate + .31 * h)
            for h, a in enumerate(harmonics) if (h + 1) * hz < rate / 2))
    if snr_db is not None:
        rms = math.sqrt(sum(s * s for s in output) / len(output))
        scale = rms * 10 ** (-snr_db / 20) * math.sqrt(3)
        output = [s + rand.uniform(-scale, scale) for s in output]
    return output


def pitches(frames, expected, minimum_clarity=.8):
    audible = [f for f in frames if not f.get('type') and f["rms"] >= .005]
    accepted = [f for f in audible if f["frequency"] > 0 and f["clarity"] >= minimum_clarity]
    cents = [1200 * math.log2(f["frequency"] / expected) for f in accepted]
    return {"audibleFrames": len(audible), "acceptedFrames": len(accepted),
            "medianCents": statistics.median(cents) if cents else None,
            "correctFrames": sum(abs(c) < 50 for c in cents),
            "onsets": sum(f["onset"] for f in frames if not f.get('type'))}


def synthetic(exe, folder):
    results = []
    path = folder / "synthetic.wav"
    for profile, harmonics in PROFILES.items():
        for midi in [36, 40, 43, 48, 52, 55, 60, 64, 67, 72, 76, 79, 84]:
            hz = 440 * 2 ** ((midi - 69) / 12)
            for noise in [None, 20]:
                wav(path, tones(hz, harmonics, snr_db=noise))
                frames, _ = run(exe, path)
                metrics = pitches(frames, hz)
                assert metrics["acceptedFrames"] >= 10, (profile, midi, noise, metrics)
                assert abs(metrics["medianCents"]) < 8, (profile, midi, noise, metrics)
                assert metrics["onsets"] == 1, (profile, midi, noise, metrics)
                results.append({"profile": profile, "midi": midi, "snrDb": noise, **metrics})
    for rate in [44100, 48000]:
        for cents in [-42, 42]:
            wav(path, tones(440, [1], cents=cents, rate=rate), rate)
            frames, _ = run(exe, path)
            metrics = pitches(frames, 440)
            assert abs(metrics["medianCents"] - cents) < 1, (rate, cents, metrics)
            results.append({"profile": "detuned", "inputRate": rate, "cents": cents, **metrics})
    for kind in ["silence", "white_noise", "dc"]:
        rand = random.Random(2378)
        samples = [0 if kind == "silence" else .2 if kind == "dc" else rand.uniform(-.2, .2)
                   for _ in range(RATE // 2)]
        wav(path, samples)
        frames, _ = run(exe, path)
        assert all(f["frequency"] == 0 and not f["onset"] for f in frames if not f.get('type')), kind
        results.append({"profile": kind, "falsePitchedFrames": 0})
    # No intervening silence: a quiet same-pitch decay is followed by a second pluck.
    samples = []
    for i in range(RATE):
        level = .2 if i < RATE * .35 or i >= RATE * .55 else .03
        samples.append(level * math.sin(2 * math.pi * 440 * i / RATE))
    wav(path, samples)
    frames, _ = run(exe, path)
    attacks = [f for f in frames if not f.get('type') and f["onset"]]
    assert len(attacks) == 2, attacks
    assert abs(attacks[0]['onsetTimeMs']) < 10
    assert abs(attacks[1]['onsetTimeMs'] - 550) <= 10, attacks
    results.append({"profile": "same_pitch_without_silence", "onsets": len(attacks)})
    # An isolated attack must retain the same sample-derived time with longer
    # pitch windows. The JSON frame may arrive later; the acoustic time does not.
    delayed = [0.0] * round(RATE * .25) + tones(440, [1], seconds=.45)
    wav(path, delayed)
    for window in [4096, 8192]:
        delayed_frames, _ = run(exe, path, '--window', window)
        onset_frames = [f for f in delayed_frames if f.get('onset')]
        assert len(onset_frames) == 1, (window, onset_frames)
        assert abs(onset_frames[0]['onsetTimeMs'] - 250) <= 10, (window, onset_frames)
    results.append({'profile': 'acoustic_attack_timestamp_independent_of_window', 'attackMs': 250, 'windowSamples': [4096, 8192]})
    # A legato A4->B4 begins only 40 ms after the attack, inside the 8192-sample
    # window. Keep oscillator phase continuous and amplitude constant so this
    # is a pitch change, not a new envelope attack.
    legato = [0.0] * round(RATE * .25)
    phase = 0.0
    for i in range(round(RATE * .55)):
        hz = 440 if i < round(RATE * .04) else 440 * 2 ** (2 / 12)
        legato.append(.15 * math.sin(phase))
        phase += 2 * math.pi * hz / RATE
    wav(path, legato)
    legato_frames, _ = run(exe, path, '--window', 8192)
    before_change = [f for f in legato_frames if not f.get('type') and f.get('frequency', 0) > 0 and
                     f.get('onsetTimeMs') == 250 and abs(1200 * math.log2(f['frequency'] / 440)) < 30]
    changed_pitch = [f for f in legato_frames if not f.get('type') and f.get('frequency', 0) > 0 and
                     1200 * math.log2(f['frequency'] / 440) > 80 and f['clarity'] >= .9]
    assert before_change, 'The held A4 must establish its own acoustic attack first'
    assert changed_pitch, 'The production detector must resolve the legato pitch change'
    assert any(f['timeMs'] <= 250 for f in changed_pitch), 'Exercise the change while the old attack is still inside the full analysis window'
    assert all(f['onsetTimeMs'] is None for f in changed_pitch), changed_pitch[:3]
    assert all(not f['onset'] for f in changed_pitch), changed_pitch[:3]
    results.append({'profile': 'legato_within_initial_attack_window', 'attackMs': 250,
                    'pitchChangeMs': 290, 'windowSamples': 8192})
    wav(path, samples)
    trace = [f for f in frames if not f.get('type')]
    assert trace[0]["sampleCount"] == 0 and trace[0]["timeMs"] == 0
    for previous, current in zip(trace, trace[1:]):
        assert current["sampleCount"] - previous["sampleCount"] == 480
        assert abs(current["timeMs"] - previous["timeMs"] - 10) < .00001
    assert frames[-1]["sampleCount"] == len(samples)
    results.append({"profile": "sample_timestamps", "firstSample": 0, "hopSamples": 480})
    recording = folder / "录音回放.wav"
    frames, _ = run(exe, path, "--record", recording)
    reread, _ = run(exe, recording)
    with wave.open(str(recording), 'rb') as captured:
        assert captured.getsampwidth() == 2 and captured.getnchannels() == 1
        assert captured.getframerate() == RATE and captured.getnframes() == len(samples)
    before = [f for f in frames if not f.get('type')]
    after = [f for f in reread if not f.get('type')]
    assert len(before) == len(after)
    for original, decoded in zip(before, after):
        assert original['sampleCount'] == decoded['sampleCount']
        assert original['onset'] == decoded['onset']
        assert abs(original['frequency'] - decoded['frequency']) < .01
        assert abs(original['rms'] - decoded['rms']) < .00004
    assert reread[-1]["sampleCount"] == len(samples)
    results.append({"profile": "unicode_pcm16_recording_roundtrip", "samples": len(samples)})
    for arguments in [("--window", "4097"), ("--min-frequency", "NaN"),
                      ("--max-frequency", "-2"), ("--window", "1024", "--min-frequency", "27.5"),
                      ("--record", "relative.wav")]:
        frames, code = run(exe, path, *arguments, successful=False)
        assert code != 0 and any(f.get("type") == "error" for f in frames), (arguments, code, frames)
    return {"method": "Production NoteLiteAudio.exe --analyze, artificial PCM without pitch snapping",
            "limitation": "Synthetic regression only; does not establish live microphone, room noise, polyphonic or real-instrument accuracy.",
            "cases": results}


def recorded(exe, manifest_path, folder):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results = []
    for sample in manifest["samples"]:
        original = Path(sample["original"]).read_bytes()
        pcm = Path(sample["pcm"]).read_bytes()
        assert hashlib.sha256(original).hexdigest() == sample["sourceSha256"]
        assert hashlib.sha256(pcm).hexdigest() == sample["pcmSha256"]
        values = array.array("f")
        values.frombytes(pcm)
        if sys.byteorder != "little":
            values.byteswap()
        path = folder / "recorded-input.wav"
        wav(path, values, sample["sampleRate"])
        frames, _ = run(exe, path)
        trace_path = folder / f"{sample['instrument']}-{sample['label'].replace('#', 'sharp')}.frames.json"
        trace_path.write_text(json.dumps(frames, separators=(',', ':')), encoding="utf-8")
        expected = 440 * 2 ** ((sample["expectedMidi"] - 69) / 12)
        metrics = pitches(frames, expected)
        accepted = [f for f in frames if not f.get('type') and f.get("frequency", 0) > 0 and f.get("clarity", 0) >= .8 and f["rms"] >= .005]
        first = accepted[0] if accepted else None
        native_notes = [e for e in frames if e.get('type') == 'note-on']
        results.append({"instrument": sample["instrument"], "label": sample["label"],
                        "sourceUrl": sample["sourceUrl"], "sourceSha256": sample["sourceSha256"],
                        "firstPitchMatches": bool(first and abs(1200 * math.log2(first["frequency"] / expected)) < 50),
                        "firstTimeMs": first["timeMs"] if first else None,
                        "expectedMidi": sample["expectedMidi"], "trace": str(trace_path.resolve()),
                        "nativeFirstNoteMatches": bool(native_notes and native_notes[0]['midi'] == sample['expectedMidi']),
                        "nativeNoteCount": len(native_notes),
                        "nativeWrongPitchEvents": sum(e['midi'] != sample['expectedMidi'] for e in native_notes),
                        "nativeExtraEvents": max(0,len(native_notes)-1),
                        "nativeEvents": [e for e in frames if e.get('type') in ['note-on','note-off','uncertainty']], **metrics})
    return {"method": "Production native MPM/YIN on all checksum-verified upstream recorded-instrument PCM",
            "manifest": str(manifest_path), "attribution": manifest.get("attribution"),
            "limitation": manifest.get("limitation"), "samples": len(results),
            "firstPitchMatches": sum(r["firstPitchMatches"] for r in results),
            "results": results}


def capture_smoke(exe, folder):
    """Explicit opt-in device smoke test; discard the temporary audio immediately."""
    recording = folder / "capture-smoke.wav"
    try:
        process = subprocess.Popen([str(exe), '--record', str(recording)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        first = process.stdout.readline()
        first_frame = json.loads(first)
        if first_frame.get('type') != 'ready':
            stdout, stderr = process.communicate(timeout=8)
            raise AssertionError(('Default capture device not ready', first_frame, stdout, stderr))
        time.sleep(.75)
        stdout, stderr = process.communicate(input='STOP\n', timeout=8)
        frames = [first_frame, *[json.loads(line) for line in stdout.splitlines() if line.strip()]]
        assert process.returncode == 0 and frames[-1]['type'] == 'stopped', frames[-2:]
        with wave.open(str(recording), 'rb') as captured:
            samples = captured.getnframes()
            assert captured.getsampwidth() == 2 and captured.getnchannels() == 1
            assert captured.getframerate() == RATE and samples > 0
        assert samples == frames[-1]['sampleCount']
        offline_frames, _ = run(exe, recording)
        assert offline_frames[-1]['sampleCount'] == samples
        trace = [f for f in frames if not f.get('type')]
        assert not trace or (trace[0]['sampleCount'] == 0 and trace[0]['timeMs'] == 0)
        eof = subprocess.run([str(exe)], input='', text=True, capture_output=True, timeout=8)
        eof_frames = [json.loads(line) for line in eof.stdout.splitlines() if line.strip()]
        assert eof.returncode == 0 and eof_frames[0]['type'] == 'ready' and eof_frames[-1]['type'] == 'stopped'
        return {'method': 'Brief explicit Windows default capture test; no acoustic content interpreted',
                'cases': [{'profile': 'default_device_ready_STOP_PCM16_WAV', 'samples': samples,
                           'durationMs': samples / RATE * 1000, 'pitchFrames': len(trace)},
                          {'profile': 'stdin_EOF_cleanup', 'samples': eof_frames[-1]['sampleCount']}],
                'temporaryRecordingDeleted': True}
    finally:
        if recording.exists():
            recording.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, default=Path(__file__).parent / "build" / "NoteLiteAudio.exe")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--capture-smoke", action='store_true', help='Explicitly open the default Windows capture device briefly; discard temporary recording')
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "test-output")
    args = parser.parse_args()
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    if args.capture_smoke:
        result = capture_smoke(args.exe.resolve(), folder)
    else:
        result = recorded(args.exe.resolve(), args.manifest.resolve(), folder) if args.manifest else synthetic(args.exe.resolve(), folder)
    target = folder / ('capture-smoke-results.json' if args.capture_smoke else "recorded-results.json" if args.manifest else "synthetic-results.json")
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"cases": len(result.get("cases", result.get("results", []))),
                      "firstPitchMatches": result.get("firstPitchMatches"), "report": str(target)}))


if __name__ == "__main__":
    main()
