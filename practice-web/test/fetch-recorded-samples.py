"""Download a fixed, predeclared real-instrument sample set and decode without normalization.

Requires soundfile and numpy. This is an optional benchmark setup script, not part of npm test.
Usage: python test/fetch-recorded-samples.py /absolute/path/to/work/practice-real-samples
"""
import concurrent.futures
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.request

import numpy as np
import soundfile as sf

COMMIT = "622c2f1c32c8cfce4158ddc3eb26e518ddef37e5"
REPOSITORY = "https://github.com/nbrosowsky/tonejs-instruments"
RAW = f"https://raw.githubusercontent.com/nbrosowsky/tonejs-instruments/{COMMIT}/"
SAMPLES = {
    "violin": ["A3", "A4", "A5"], "flute": ["C4", "C5", "C6"],
    "guitar-acoustic": ["E2", "C4", "E4"], "piano": ["C3", "C4", "C5"],
    "clarinet": ["F3", "F4", "F5"], "saxophone": ["D3", "D4", "D5"],
    "trumpet": ["A3", "F4", "A5"], "cello": ["C2", "C3", "C4"],
    "bassoon": ["G2", "C4", "A4"], "contrabass": ["E2", "A2", "E3"],
}
HELDOUT_SAMPLES = {
    "violin": ["C4", "E5"], "flute": ["E4", "A5"],
    "guitar-acoustic": ["A2", "G3"], "piano": ["A2", "E5"],
    "clarinet": ["D4", "A#4"], "saxophone": ["A#3", "G4"],
    "trumpet": ["D#4", "D5"], "cello": ["G2", "E3"],
    "bassoon": ["A2", "E4"], "contrabass": ["G1", "C#3"],
}
SOURCE = {
    "violin": "VSO2 (as stated in repository source info)", "flute": "VSO2",
    "guitar-acoustic": "University of Iowa", "piano": "VSO2",
    "clarinet": "Not individually listed in repository sample-source-info.txt",
    "saxophone": "Karoryfer", "trumpet": "VSO2",
    "cello": "Freesound 12408__flcellogrl__real-cello-notes", "bassoon": "VSO2", "contrabass": "VSO2",
}

def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "NoteLite-reproducible-audio-benchmark"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()

def sha256(data):
    return hashlib.sha256(data).hexdigest()

def main(folder, split="baseline"):
    folder.mkdir(parents=True, exist_ok=True)
    assets = {}
    for name in ["README.md", "LICENSE.md", "sample-source-info.txt", "Tonejs-Instruments.js"]:
        data = fetch(RAW + name)
        (folder / name).write_bytes(data)
        assets[name] = {"url": RAW + name, "sha256": sha256(data)}
    tree = json.loads(fetch(f"https://api.github.com/repos/nbrosowsky/tonejs-instruments/git/trees/{COMMIT}?recursive=1"))
    (folder / "tree.json").write_text(json.dumps(tree, indent=2), encoding="utf-8")
    blobs = {item["path"]: item["sha"] for item in tree["tree"] if item["type"] == "blob"}
    mapping = (folder / "Tonejs-Instruments.js").read_text(encoding="utf-8")
    jobs = []
    sample_set = HELDOUT_SAMPLES if split == "heldout" else SAMPLES
    for instrument, names in sample_set.items():
        block = re.search(r"'" + re.escape(instrument) + r"'\s*:\s*\{(.*?)\n\s*\}", mapping, re.S)
        if not block:
            raise ValueError(f"Missing authoritative mapping for {instrument}")
        note_map = dict(re.findall(r"'([^']+)'\s*:\s*'([^']+)\.\[mp3\|ogg\]'", block.group(1)))
        for note in names:
            stem = note_map[note]
            relative = f"samples/{instrument}/{stem}.ogg"
            if relative not in blobs:
                raise ValueError(f"Sample missing from official tree: {relative}")
            letter, accidental, octave = re.fullmatch(r"([A-G])([#b]?)(-?\d+)", note).groups()
            midi = (int(octave) + 1) * 12 + {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[letter] + {"": 0, "#": 1, "b": -1}[accidental]
            jobs.append((instrument, note, midi, relative))

    def download(job):
        instrument, note, midi, relative = job
        url = RAW + relative
        data = fetch(url)
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        audio, sample_rate = sf.read(target, dtype="float32", always_2d=True)
        # Browser input is mono; average the decoded channels without changing rate, gain, or pitch.
        mono = np.mean(audio, axis=1, dtype=np.float32)
        pcm = target.with_suffix(".f32")
        pcm_data = mono.astype("<f4", copy=False).tobytes()
        pcm.write_bytes(pcm_data)
        return {"instrument": instrument, "label": note, "expectedMidi": midi,
                "truth": "Exact note key in upstream Tonejs-Instruments.js sample mapping; not inferred from this detector",
                "source": SOURCE[instrument], "sourceUrl": url, "sourceGitBlobSha": blobs[relative],
                "sourceSha256": sha256(data), "original": str(target.resolve()),
                "pcm": str(pcm.resolve()), "pcmSha256": sha256(pcm_data),
                "sampleRate": sample_rate, "channels": audio.shape[1], "samples": len(mono),
                "durationSeconds": len(mono) / sample_rate, "peak": float(np.max(np.abs(mono))),
                "decoder": f"python-soundfile {sf.__version__}; libsndfile {sf.__libsndfile_version__}"}

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(download, jobs))
    manifest = {"repository": REPOSITORY, "commit": COMMIT, "sampleLicense": "CC-BY-3.0",
                "attribution": "Nicholas B. Brosowsky / tonejs-instruments; upstream sample providers in source-info",
                "licenseUrl": "https://creativecommons.org/licenses/by/3.0/",
                "limitation": "Edited real-instrument single-note samples. Upstream trimmed silence, added ramps, volume-matched, normalized, removed noise and sometimes pitch-corrected. Not live playing, room recordings, a microphone test, or polyphony.",
                "split": split,
                "sampling": "Fixed pitches per instrument selected before executing the detector; all selected files are reported, including failures. Heldout pitches are disjoint from the initial 30-sample set.",
                "localProcessing": "OGG decoded at its native sample rate; stereo averaged to mono Float32; no other local processing.",
                "sourceDocuments": assets, "samples": results}
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"samples": len(results), "instruments": len(sample_set), "split": split, "manifest": str((folder / "manifest.json").resolve())}))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--split", choices=["baseline", "heldout"], default="baseline")
    arguments = parser.parse_args()
    main(arguments.folder.resolve(), arguments.split)
