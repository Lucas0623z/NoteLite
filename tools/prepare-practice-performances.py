"""Prepare edited, real-sample flute sequences; never record or infer a performance.

Run with local-analysis/runtime/python/python.exe (numpy, scipy and soundfile).
Only three pinned OGG samples are downloaded, checked and decoded in memory.
The original benchmark folder is protected; the default output is a new folder.
"""
import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import platform
import urllib.request
import xml.etree.ElementTree as ET

import numpy as np
import scipy
from scipy.signal import resample_poly
import soundfile as sf


ROOT = Path(__file__).resolve().parent.parent
COMMIT = "622c2f1c32c8cfce4158ddc3eb26e518ddef37e5"
SOURCE_ROOT = f"https://raw.githubusercontent.com/nbrosowsky/tonejs-instruments/{COMMIT}"
LICENSE_URL = "https://creativecommons.org/licenses/by/3.0/"
SAMPLES = {
    60: ("C4", "22cb2eefdd60d7174e05176424cee8b062e3a5170fe3563fd7655ef3cf565163"),
    72: ("C5", "678b870c299836c55b2143b0c2fbd5237ddf2b2c84fd40c6b205107d4fd4baa1"),
    84: ("C6", "da07b3ffffd5ca69c30d062b6716d29d6c6dca069510a2e54e701db245fb1937"),
}
EXPECTED = [60, 72, 84, 72, 60, 60]
CASES = {
    "correct_repeated_flute": EXPECTED,
    "wrong_octave_flute": [60, 72, 72, 72, 60, 60],
    "missed_flute": [60, 72, None, 72, 60, 60],
}
RATE, BPM = 48000, 80
LEAD, INTERVAL, CLIP, TAIL, FADE = .25, .75, .52, .20, .005
METHOD = (
    "Controlled sequence assembled from actual instrument recordings; mono decode, "
    "polyphase resampling to 48000 Hz, trim to 5 ms before the first sample at "
    "4% of peak amplitude, crop to .52 s and fade the final 5 ms. Notes start "
    "after .25 s at .75 s spacing, with .23 s between crops. No pitch shifting "
    "or amplitude normalization. PCM16 conversion multiplies by 32767 and "
    "truncates toward zero, without dithering. Expected/performed MIDI labels come from "
    "upstream sample mappings; performed onsets/durations describe assembly, "
    "not independently annotated acoustic boundaries. Not a live musician performance."
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def download_sample(midi):
    label, expected_sha = SAMPLES[midi]
    url = f"{SOURCE_ROOT}/samples/flute/{label}.ogg"
    request = urllib.request.Request(url, headers={"User-Agent": "NoteLite-practice-fixture-setup"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024 or sha(data) != expected_sha:
        raise ValueError(f"Pinned sample checksum/size mismatch: {label}")
    signal, source_rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    mono = signal.mean(axis=1, dtype=np.float32)
    divisor = math.gcd(RATE, source_rate)
    mono = resample_poly(mono, RATE // divisor, source_rate // divisor)
    peak = float(np.max(np.abs(mono)))
    if not math.isfinite(peak) or peak <= 0:
        raise ValueError(f"Invalid or silent source: {label}")
    above = np.flatnonzero(np.abs(mono) >= peak * .04)
    start = max(0, int(above[0]) - round(FADE * RATE))
    length = round(CLIP * RATE)
    if len(mono) - start < length:
        raise ValueError(f"Source too short for the declared crop: {label}")
    crop = mono[start:start + length].copy()
    fade = round(FADE * RATE)
    crop[-fade:] *= np.linspace(1, 0, fade, dtype=crop.dtype)
    source = {"url": url, "sha256": expected_sha, "label": label,
              "license": "CC-BY-3.0", "licenseUrl": LICENSE_URL,
              "attribution": "nbrosowsky / tonejs-instruments sample collection",
              "licenseSource": f"{SOURCE_ROOT}/README.md"}
    processing = {"label": label, "sourceRate": int(source_rate), "sourceChannels": int(signal.shape[1]),
                  "resampledFrames": len(mono), "trimStartSample": start,
                  "thresholdSample": int(above[0]), "cropFrames": length, "fadeFrames": fade}
    return crop, source, processing


def music_xml(title):
    score = ET.Element("score-partwise", version="4.0")
    work = ET.SubElement(score, "work"); ET.SubElement(work, "work-title").text = title
    parts = ET.SubElement(score, "part-list"); entry = ET.SubElement(parts, "score-part", id="P1")
    ET.SubElement(entry, "part-name").text = "Flute"
    instrument = ET.SubElement(entry, "score-instrument", id="P1-I1")
    ET.SubElement(instrument, "instrument-name").text = "Flute"
    part = ET.SubElement(score, "part", id="P1"); measure = ET.SubElement(part, "measure", number="1")
    attributes = ET.SubElement(measure, "attributes"); ET.SubElement(attributes, "divisions").text = "4"
    key = ET.SubElement(attributes, "key"); ET.SubElement(key, "fifths").text = "0"
    time = ET.SubElement(attributes, "time"); ET.SubElement(time, "beats").text = "6"; ET.SubElement(time, "beat-type").text = "4"
    clef = ET.SubElement(attributes, "clef"); ET.SubElement(clef, "sign").text = "G"; ET.SubElement(clef, "line").text = "2"
    direction = ET.SubElement(measure, "direction", placement="above")
    direction_type = ET.SubElement(direction, "direction-type")
    metronome = ET.SubElement(direction_type, "metronome")
    ET.SubElement(metronome, "beat-unit").text = "quarter"; ET.SubElement(metronome, "per-minute").text = str(BPM)
    ET.SubElement(direction, "sound", tempo=str(BPM))
    for index, midi in enumerate(EXPECTED):
        note = ET.SubElement(measure, "note", id=f"flute-{index + 1}")
        pitch = ET.SubElement(note, "pitch"); ET.SubElement(pitch, "step").text = "C"; ET.SubElement(pitch, "octave").text = str(midi // 12 - 1)
        ET.SubElement(note, "duration").text = "3"; ET.SubElement(note, "voice").text = "1"
        ET.SubElement(note, "type").text = "eighth"; ET.SubElement(note, "dot")
        rest = ET.SubElement(measure, "note"); ET.SubElement(rest, "rest")
        ET.SubElement(rest, "duration").text = "1"; ET.SubElement(rest, "voice").text = "1"; ET.SubElement(rest, "type").text = "16th"
    ET.indent(score, space="  ")
    return ET.tostring(score, encoding="utf-8", xml_declaration=True)


def compare_case(new_file, previous_file):
    result = {"previousFile": str(previous_file.resolve()), "newFile": str(new_file.resolve()),
              "previousSha256": sha(previous_file.read_bytes()), "newSha256": sha(new_file.read_bytes())}
    original, rate = sf.read(previous_file, dtype="int16", always_2d=True)
    generated, new_rate = sf.read(new_file, dtype="int16", always_2d=True)
    result.update(previousRate=rate, newRate=new_rate, previousFrames=len(original), newFrames=len(generated),
                  previousChannels=original.shape[1], newChannels=generated.shape[1],
                  bytesEqual=result["previousSha256"] == result["newSha256"])
    same_layout = rate == new_rate and original.shape == generated.shape
    result["pcmEqual"] = bool(same_layout and np.array_equal(original, generated))
    if same_layout:
        difference = generated.astype(np.int32) - original.astype(np.int32)
        locations = np.argwhere(difference != 0)
        result.update(changedSamples=len(locations), firstDifferenceSample=int(locations[0, 0]) if len(locations) else None,
                      maxAbsoluteDifferencePcm16=int(np.max(np.abs(difference))),
                      rmsDifferencePcm16=float(np.sqrt(np.mean(difference.astype(np.float64) ** 2))))
    return result


def prepare(output, compare_manifest):
    output = output.resolve()
    # Keep the exact already-measured files unchanged, including through symlinks.
    protected = { (ROOT / "work/windows-performances").resolve() }
    previous = json.loads(compare_manifest.read_text(encoding="utf-8")) if compare_manifest.is_file() else None
    if previous:
        protected.update(Path(case["file"]).resolve().parent for case in previous["cases"])
    if output in protected:
        raise ValueError("Choose a separate output directory; original measured fixtures are protected")
    clips, sources, processing = {}, {}, []
    for midi in SAMPLES:
        clips[midi], sources[midi], detail = download_sample(midi); processing.append(detail)
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"method": METHOD, "cases": []}
    for name, pitches in CASES.items():
        audio = np.zeros(round((LEAD + len(pitches) * INTERVAL + TAIL) * RATE), dtype=np.float32)
        performed, used_sources = [], []
        for index, midi in enumerate(pitches):
            if midi is None: continue
            onset = LEAD + index * INTERVAL; start = round(onset * RATE)
            audio[start:start + len(clips[midi])] = clips[midi]
            performed.append({"midi": midi, "onset": onset, "duration": CLIP}); used_sources.append(sources[midi].copy())
        # Explicit quantization matches the already-measured fixture writer;
        # floating-point libsndfile writes use a different scaling/rounding rule.
        pcm = np.clip(audio * 32767, -32768, 32767).astype("<i2")
        wav_file = output / f"{name}.wav"; sf.write(wav_file, pcm, RATE, subtype="PCM_16")
        score_file = output / f"{name}.musicxml"; score_file.write_bytes(music_xml(name))
        manifest["cases"].append({"name": name, "file": str(wav_file), "expected": EXPECTED.copy(),
                                  "performed": performed, "bpm": BPM, "sources": used_sources,
                                  "scoreFile": str(score_file), "waveSha256": sha(wav_file.read_bytes())})
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    proof = {"method": METHOD, "software": {"python": platform.python_version(), "numpy": np.__version__,
             "scipy": scipy.__version__, "soundfile": sf.__version__, "libsndfile": sf.__libsndfile_version__},
             "processing": processing, "rate": RATE, "frames": round((LEAD + len(EXPECTED) * INTERVAL + TAIL) * RATE),
             "encoding": "PCM_16", "comparisonManifest": str(compare_manifest.resolve()), "comparisons": []}
    if previous:
        by_name = {case["name"]: case for case in previous["cases"]}
        for case in manifest["cases"]:
            baseline = by_name[case["name"]]
            if baseline["expected"] != case["expected"] or baseline["performed"] != case["performed"]:
                raise ValueError(f"Existing assembly labels differ: {case['name']}")
            proof["comparisons"].append(compare_case(Path(case["file"]), Path(baseline["file"])))
    (output / "comparison.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    (output / "METHOD.md").write_text(
        "# Controlled flute performance fixtures\n\n" + METHOD + "\n\n"
        "Original OGG files are downloaded into memory only. The app/package contains neither "
        "the originals nor these fixture WAVs. Sample attribution: nbrosowsky / tonejs-instruments, "
        f"[CC BY 3.0]({LICENSE_URL}); [pinned source/license README]({SOURCE_ROOT}/README.md). "
        "The trims, crop and fade are modifications. The upstream collection itself contains edited samples.\n\n"
        "MusicXML contains six expected C4/C5/C6/C5/C4/C4 notes, including the two deliberately repeated C4s. "
        "Each is a dotted eighth (0.75 quarter beats; 0.5625 s at 80 BPM) followed by a sixteenth rest "
        "(0.25 beats), in one 6/4 measure. This nominal score duration differs from the actual 0.52 s crop; "
        "the performed manifest preserves 0.52 s. The direction includes a valid direction-type/metronome.\n\n"
        "comparison.json records source processing, dependency versions and full PCM16 differences against "
        "the existing measured files. Resampler/decoder/PCM quantization versions can change samples. "
        "Do not replace prior measured evidence or apply its results to changed WAVs without rerunning tests.\n",
        encoding="utf-8")
    return proof


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "work/windows-performances-reproduced")
    parser.add_argument("--compare", type=Path, default=ROOT / "work/windows-performances/manifest.json",
                        help="Read-only baseline manifest; comparison is skipped when it does not exist")
    arguments = parser.parse_args()
    result = prepare(arguments.output, arguments.compare)
    print(json.dumps({"output": str(arguments.output.resolve()), "comparisons": result["comparisons"]}, indent=2))
