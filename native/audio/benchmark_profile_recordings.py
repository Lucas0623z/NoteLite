"""Optional production-native full-trace benchmark for original VSCO2/vocadito recordings.

Broad instrument settings are imported from the actual frontend profile file.
Nothing is tuned against expected labels. Identity and unjudged trace findings
are reported, including failures; this is not a room or microphone evaluation.
"""
import argparse
import array
import bisect
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_audio import wav, run

def sha(data):
    return hashlib.sha256(data).hexdigest()

def profiles(repo):
    result = subprocess.run(["node", "--input-type=module", "-e", "import {INSTRUMENT_PROFILES} from './practice-web/src/instruments.js';console.log(JSON.stringify(INSTRUMENT_PROFILES));"], cwd=repo, capture_output=True, text=True, encoding="utf-8", check=True)
    return {x["id"]: x for x in json.loads(result.stdout)}

def trace(exe, audio, folder, label, profile):
    args = ["--window", profile["windowSize"], "--min-frequency", profile["minHz"], "--max-frequency", profile["maxHz"], "--a4", 440]
    frames, _ = run(exe, audio, *args)
    target = folder / (label + ".frames.json")
    target.write_text(json.dumps(frames, separators=(",", ":")), encoding="utf-8")
    notes = [e for e in frames if e.get("type") == "note-on"]
    releases = [e for e in frames if e.get("type") == "note-off"]
    uncertainty = [e for e in frames if e.get("type") == "uncertainty"]
    audible = [f for f in frames if not f.get("type") and f.get("rms", 0) >= .0005]
    return frames, {"arguments": args, "trace": str(target.resolve()), "traceSha256": sha(target.read_bytes()),
                    "notes": notes, "releases": releases, "uncertainty": uncertainty,
                    "audibleFrames": len(audible), "unjudgedAudibleFrames": sum(not f.get("voiced") for f in audible),
                    "unjudgedAudibleFraction": sum(not f.get("voiced") for f in audible) / len(audible) if audible else None}

def note_annotations(path):
    with path.open(newline="", encoding="utf-8") as f:
        return [{"onsetMs": float(row[0]) * 1000, "midi": round(69 + 12 * math.log2(float(row[1]) / 440)), "durationMs": float(row[2]) * 1000} for row in csv.reader(f) if row]

def annotation_comparison(events, reference):
    compared = []
    for event in events:
        time = event["onsetMs"]
        # Native startup timestamp can precede a manually annotated attack.
        neighbors = [n for n in reference if n["onsetMs"] - 100 <= time <= n["onsetMs"] + n["durationMs"] + 100]
        compared.append({"id": event["id"], "midi": event["midi"], "onsetMs": time,
                         "referenceCandidates": neighbors, "identityMatches": any(n["midi"] == event["midi"] for n in neighbors),
                         "outsideAnnotatedNotes": not neighbors})
    return {"onsets": len(events), "pitchMatchesAtAnnotatedTime": sum(e["identityMatches"] for e in compared),
            "falseIdentityWithReference": sum(bool(e["referenceCandidates"]) and not e["identityMatches"] for e in compared),
            "outsideAnnotatedNotes": sum(e["outsideAnnotatedNotes"] for e in compared), "comparisons": compared}

def main(manifest_path, exe, folder):
    repo = Path(__file__).resolve().parents[2]
    current_profiles = profiles(repo)
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "source-manifest.json").write_bytes(manifest_bytes)
    source_exe = exe; exe_bytes = exe.read_bytes()
    # Freeze the binary so another agent's independent rebuild cannot mix runs.
    exe = folder / "benchmark-NoteLiteAudio.exe"; exe.write_bytes(exe_bytes)
    results = []
    for sample in manifest["samples"]:
        assert sha(Path(sample["original"]).read_bytes()) == sample["sourceSha256"]
        data = Path(sample["pcm"]).read_bytes()
        assert sha(data) == sample["pcmSha256"]
        values = array.array("f"); values.frombytes(data)
        if sys.byteorder != "little": values.byteswap()
        path = folder / "current.wav"; wav(path, values, sample["sampleRate"])
        frames, metrics = trace(exe, path, folder, sample["instrument"] + "-" + sample["label"].replace("#", "sharp"), current_profiles[sample["instrument"]])
        pitched = [f for f in frames if not f.get("type") and f.get("voiced") and f.get("frequency", 0) > 0]
        cents = [1200 * math.log2(f["frequency"] / (440 * 2 ** ((sample["expectedMidi"] - 69) / 12))) for f in pitched]
        metrics.update({"instrument": sample["instrument"], "label": sample["label"], "expectedMidi": sample["expectedMidi"],"source":sample.get("source"),"license":sample.get("license"),"instrumentCaveat":sample.get("instrumentCaveat"),
                        "sourceUrl": sample["sourceUrl"], "sourceSha256": sample["sourceSha256"], "truthSource": sample["truthSource"],
                        "firstNoteMatches": bool(metrics["notes"] and metrics["notes"][0]["midi"] == sample["expectedMidi"]),
                        "noDetection": not metrics["notes"], "falseIdentityEvents": sum(e["midi"] != sample["expectedMidi"] for e in metrics["notes"]),
                        "additionalAttackEvents": max(0, len(metrics["notes"]) - 1), "medianCentsFromLabel": statistics.median(cents) if cents else None,
                        "wrongPitchedFrames": sum(abs(c) >= 50 for c in cents), "pitchedFrames": len(cents)})
        results.append(metrics)
    voice = []
    if "voice" in manifest:
        voice_source = manifest_path.parent / "vocadito"
        for source in manifest["voice"]["files"]:
            assert sha(Path(source["path"]).read_bytes()) == source["sha256"]
        for track in manifest["voice"]["tracks"]:
            label = f"vocadito_{track}"
            audio = voice_source / "Audio" / (label + ".wav")
            frames, metrics = trace(exe, audio, folder, label, current_profiles["voice"])
            annotations = {}
            for annotator in [1, 2]:
                path = voice_source / "Annotations" / "Notes" / f"{label}_notesA{annotator}.csv"
                annotations[f"humanAnnotator{annotator}"] = annotation_comparison(metrics["notes"], note_annotations(path))
            f0path = voice_source / "Annotations" / "F0" / (label + "_f0.csv")
            with f0path.open(newline="") as f: reference = [(float(row[0])*1000, float(row[1])) for row in csv.reader(f) if row]
            times = [r[0] for r in reference]; frame_comparisons = []
            for frame in frames:
                if frame.get("type") or not frame.get("voiced") or frame.get("frequency", 0) <= 0: continue
                position = min(len(reference)-1, bisect.bisect_left(times, frame["timeMs"]))
                ref = reference[position]
                if position and abs(times[position-1]-frame["timeMs"]) < abs(ref[0]-frame["timeMs"]): ref = reference[position-1]
                if ref[1] > 0 and abs(ref[0]-frame["timeMs"]) < 15: frame_comparisons.append(1200*math.log2(frame["frequency"]/ref[1]))
            metrics.update({"track": label, "source": manifest["voice"]["sourceUrl"], "annotations": annotations,
                            "f0ComparedVoicedFrames": len(frame_comparisons), "f0PitchWithin50cFrames": sum(abs(c) < 50 for c in frame_comparisons),
                            "f0OctaveErrors": sum(abs(abs(c)-1200) < 50 for c in frame_comparisons)})
            voice.append(metrics)
    summary = {}
    for instrument in current_profiles:
        selected = [s for s in results if s["instrument"] == instrument]
        if selected:
            summary[instrument] = {"samples": len(selected), "firstNoteMatches": sum(s["firstNoteMatches"] for s in selected),
                                   "noDetection": sum(s["noDetection"] for s in selected), "falseIdentityEvents": sum(s["falseIdentityEvents"] for s in selected),
                                   "additionalAttackEvents": sum(s["additionalAttackEvents"] for s in selected), "unjudgedAudibleFrames": sum(s["unjudgedAudibleFrames"] for s in selected),
                                   "audibleFrames": sum(s["audibleFrames"] for s in selected)}
    output = {"manifest": str((folder/"source-manifest.json").resolve()), "manifestSha256": sha(manifest_bytes), "sourceExecutable": str(source_exe.resolve()),"executable": str(exe.resolve()), "executableSha256": sha(exe_bytes),
              "profilesSourceSha256": sha((repo / "practice-web/src/instruments.js").read_bytes()), "summary": summary,
              "method": "Production native full audio trace with actual broad instrument profile settings. Library pitch truth from original SFZ numeric mapping. Vocadito full recordings compared separately with BOTH independent human note annotations and human-corrected f0.",
              "limitation": "Edited instrument library samples; VSCO viola section, Iowa solo viola. Additional attacks are reported, not assumed false articulation without independent onset truth. Vocadito annotators disagree on boundaries/notes; both comparisons retained. No rooms or musicians used live. Euphonium remains uncovered.",
              "results": results, "voice": voice, "uncovered": manifest["uncovered"]}
    target = folder / "results.json"; target.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"summary": summary, "voice": [{"track": v["track"], "onsets": len(v["notes"]), "f0ComparedVoicedFrames": v["f0ComparedVoicedFrames"], "f0PitchWithin50cFrames": v["f0PitchWithin50cFrames"], "f0OctaveErrors": v["f0OctaveErrors"], "unjudgedAudibleFrames": v["unjudgedAudibleFrames"]} for v in voice], "output": str(target.resolve())}, indent=2))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.manifest.resolve(), args.exe.resolve(), args.output.resolve())
