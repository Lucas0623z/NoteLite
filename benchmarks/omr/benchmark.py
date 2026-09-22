"""Reproducible image -> NoteLite OMR -> MIDI benchmark, with independent event truth.

generate: typeset authored MusicXML fixtures with Verovio and rasterize with resvg.
run: invoke an installed NoteLite distribution on each PNG and evaluate its MIDI.
All timings are quarter-note beats; no tempo fitting or score alignment is applied.
The fixture generator, reference writer and comparator never read NoteLite source.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET

import mido


def event(pitches, duration=1, **kwargs):
    return {"pitches": [] if pitches == "r" else pitches.split(),
            "duration": str(duration), **kwargs}


def line(*items):
    return [event(x) if isinstance(x, str) else event(*x) for x in items]


def fixtures():
    return [
        {"id": "01_diatonic", "description": "8 measures, monophonic treble, quarter and half notes",
         "parts": [{"clefs": ["G"], "measures": [
             [line("C4", "D4", "E4", "F4")], [line("G4", "A4", "B4", "C5")],
             [line("D5", "C5", "B4", "A4")], [line(("G4", 2), ("E4", 2))],
             [line("F4", "A4", "G4", "E4")], [line("D4", "F4", "E4", "C4")],
             [line(("D4", 2), ("G4", 2))], [line(("C4", 4))]]}]},
        {"id": "02_accidentals", "description": "6 measures, sharp and flat accidentals, chromatic notes",
         "parts": [{"clefs": ["G"], "measures": [
             [line("C4", "C#4", "D4", "D#4")], [line("E4", "F4", "F#4", "G4")],
             [line("G#4", "A4", "Bb4", "B4")], [line("C5", "Bb4", "Ab4", "G4")],
             [line("Gb4", "F4", "Eb4", "D4")], [line(("Db4", 2), ("C4", 2))]]}]},
        {"id": "03_rhythm_ties", "description": "4 measures, rests, dotted notes, eighths and tied notes",
         "parts": [{"clefs": ["G"], "measures": [
             [[event("C4", "3/2"), event("D4", "1/2"), event("r", 1), event("E4", 1, tie="start")]],
             [[event("E4", 1, tie="stop"), event("F4", "1/2"), event("G4", "1/2"), event("A4", 2)]],
             [line(("r", "1/2"), ("G4", "1/2"), ("F4", "3/2"), ("E4", "1/2"), ("D4", 1))],
             [line(("C4", 3), ("r", 1))]]}]},
        {"id": "04_piano", "description": "8 measures, piano grand staff, triads, broken chords and bass whole notes",
         "parts": [{"clefs": ["G", "F"], "measures": [
             [line("C4", "E4", "G4", "C5"), line(("C3", 4))],
             [line(("D4 F4 A4", 2), ("G4 B4 D5", 2)), line(("G2", 4))],
             [line("E4", "G4", "C5", "E5"), line(("C3", 4))],
             [line(("F4 A4 C5", 2), ("E4 G4 C5", 2)), line(("F2", 4))],
             [line("D4", "F4", "A4", "D5"), line(("D3", 4))],
             [line(("E4 G4 B4", 2), ("F4 A4 D5", 2)), line(("G2", 4))],
             [line("G4", "B4", "D5", "F5"), line(("G2", 4))],
             [line(("C4 E4 G4 C5", 4)), line(("C3", 4))]]}]},
        {"id": "05_polyphony", "description": "4 measures, two simultaneous voices on one treble staff",
         "parts": [{"clefs": ["G"], "voice_staves": [1, 1], "measures": [
             [line("C5", "D5", "E5", "F5"), line(("C4", 2), ("G4", 2))],
             [line("G5", "F5", "E5", "D5"), line(("B3", 2), ("G4", 2))],
             [line(("E5", "1/2"), ("F5", "1/2"), "G5", ("C5", 2)), line(("C4", 2), ("E4", 2))],
             [line(("B4", 2), ("C5", 2)), line(("G3", 2), ("C4", 2))]]}]},
        {"id": "06_tuplets", "description": "4 measures, triplet eighths mixed with quarter notes",
         "parts": [{"clefs": ["G"], "measures": [
             [line(("C4", "1/3"), ("D4", "1/3"), ("E4", "1/3"), "F4", "G4", "A4")],
             [line(("B4", "1/3"), ("C5", "1/3"), ("D5", "1/3"), ("C5", "1/3"), ("B4", "1/3"), ("A4", "1/3"), ("G4", 2))],
             [line("E4", "F4", ("G4", "1/3"), ("A4", "1/3"), ("B4", "1/3"), "C5")],
             [line(("G4", 2), ("C4", 2))]]}]},
        {"id": "07_repeats", "description": "4 written measures with repeat barlines; truth is expanded playback (8 measures)",
         "repeat": True, "parts": [{"clefs": ["G"], "measures": [
             [line("C4", "D4", "E4", "F4")], [line("G4", "E4", "C4", "E4")],
             [line("F4", "A4", "G4", "B4")], [line("C5", "G4", "E4", "C4")]]}]},
    ]


def sub(parent, tag, value=None, **attrib):
    element = ET.SubElement(parent, tag, attrib)
    if value is not None:
        element.text = str(value)
    return element


def pitch_data(pitch):
    match = re.fullmatch(r"([A-G])([#b]?)([0-8])", pitch)
    step, accidental, octave = match.groups()
    alter = {"": 0, "#": 1, "b": -1}[accidental]
    midi = (int(octave) + 1) * 12 + {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[step] + alter
    return step, alter, int(octave), midi


def to_musicxml(spec):
    root = ET.Element("score-partwise", version="4.0")
    work = sub(root, "work")
    sub(work, "work-title", spec["id"])
    part_list = sub(root, "part-list")
    for pindex, part in enumerate(spec["parts"], 1):
        score_part = sub(part_list, "score-part", id=f"P{pindex}")
        sub(score_part, "part-name", "Piano")
        score_instrument = sub(score_part, "score-instrument", id=f"I{pindex}")
        sub(score_instrument, "instrument-name", "Piano")
        midi_instrument = sub(score_part, "midi-instrument", id=f"I{pindex}")
        sub(midi_instrument, "midi-channel", pindex)
        sub(midi_instrument, "midi-program", 1)
    for pindex, part in enumerate(spec["parts"], 1):
        pnode = sub(root, "part", id=f"P{pindex}")
        for mi, measure in enumerate(part["measures"]):
            mnode = sub(pnode, "measure", number=str(mi + 1))
            accidental_state = {}
            if mi == 0:
                attributes = sub(mnode, "attributes")
                sub(attributes, "divisions", 12)
                sub(sub(attributes, "key"), "fifths", 0)
                meter = sub(attributes, "time")
                sub(meter, "beats", 4)
                sub(meter, "beat-type", 4)
                if len(part["clefs"]) > 1:
                    sub(attributes, "staves", len(part["clefs"]))
                for staff_index, clef in enumerate(part["clefs"], 1):
                    cnode = sub(attributes, "clef", number=str(staff_index))
                    sub(cnode, "sign", clef)
                    sub(cnode, "line", 2 if clef == "G" else 4)
                direction = sub(mnode, "direction", placement="above")
                metronome = sub(sub(direction, "direction-type"), "metronome")
                sub(metronome, "beat-unit", "quarter")
                sub(metronome, "per-minute", 120)
                sub(direction, "sound", tempo="120")
            if spec.get("repeat") and mi == 0:
                sub(sub(mnode, "barline", location="left"), "repeat", direction="forward")
            for voice_index, voice in enumerate(measure):
                if voice_index:
                    sub(sub(mnode, "backup"), "duration", 48)
                staff = part.get("voice_staves", list(range(1, len(part["clefs"]) + 1)))[voice_index]
                beam_position = 0
                for ei, ev in enumerate(voice):
                    duration = Fraction(ev["duration"])
                    for chord_index, pitch in enumerate(ev["pitches"] or [None]):
                        node = sub(mnode, "note")
                        if chord_index:
                            sub(node, "chord")
                        if pitch is None:
                            sub(node, "rest")
                        else:
                            step, alter, octave, _ = pitch_data(pitch)
                            pitch_node = sub(node, "pitch")
                            sub(pitch_node, "step", step)
                            if alter:
                                sub(pitch_node, "alter", alter)
                            sub(pitch_node, "octave", octave)
                        sub(node, "duration", int(duration * 12))
                        if ev.get("tie"):
                            sub(node, "tie", type=ev["tie"])
                        sub(node, "voice", voice_index + 1)
                        note_type = {Fraction(4): "whole", Fraction(3): "half", Fraction(2): "half",
                                     Fraction(3, 2): "quarter", Fraction(1): "quarter", Fraction(1, 2): "eighth",
                                     Fraction(1, 3): "eighth"}[duration]
                        sub(node, "type", note_type)
                        if duration in (Fraction(3), Fraction(3, 2)):
                            sub(node, "dot")
                        if pitch:
                            step, alter, octave, _ = pitch_data(pitch)
                            previous_alter = accidental_state.get((staff, step, octave), 0)
                            if alter or previous_alter != alter:
                                sub(node, "accidental", {1: "sharp", -1: "flat", 0: "natural"}[alter])
                            accidental_state[(staff, step, octave)] = alter
                        if duration == Fraction(1, 3):
                            tm = sub(node, "time-modification")
                            sub(tm, "actual-notes", 3)
                            sub(tm, "normal-notes", 2)
                            sub(tm, "normal-type", "eighth")
                        if "voice_staves" in part:
                            sub(node, "stem", "up" if voice_index == 0 else "down")
                        if len(part["clefs"]) > 1:
                            sub(node, "staff", staff)
                        if ev.get("tie"):
                            sub(sub(node, "notations"), "tied", type=ev["tie"])
                        if duration == Fraction(1, 3):
                            position = beam_position % 3
                            sub(node, "beam", ["begin", "continue", "end"][position], number="1")
                            if position in (0, 2):
                                sub(sub(node, "notations"), "tuplet", type="start" if position == 0 else "stop", number="1", bracket="no")
                    if duration == Fraction(1, 3):
                        beam_position += 1
                assert sum(Fraction(ev["duration"]) for ev in voice) == 4
            if mi == len(part["measures"]) - 1:
                barline = sub(mnode, "barline", location="right")
                sub(barline, "bar-style", "light-heavy")
                if spec.get("repeat"):
                    sub(barline, "repeat", direction="backward")
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def reference_events(spec):
    output = []
    for pi, part in enumerate(spec["parts"]):
        ties = {}
        for mi, measure in enumerate(part["measures"]):
            for vi, voice in enumerate(measure):
                onset = Fraction(mi * 4)
                for ev in voice:
                    duration = Fraction(ev["duration"])
                    for pitch in ev["pitches"]:
                        midi = pitch_data(pitch)[3]
                        key = (pi, vi, midi)
                        if ev.get("tie") == "stop" and key in ties:
                            output[ties.pop(key)]["duration"] += float(duration)
                        else:
                            output.append({"pitch": midi, "onset": float(onset), "duration": float(duration), "part": pi})
                            if ev.get("tie") == "start":
                                ties[key] = len(output) - 1
                    onset += duration
    if spec.get("repeat"):
        length = len(spec["parts"][0]["measures"]) * 4
        output += [{**ev, "onset": ev["onset"] + length} for ev in output]
    return sorted(output, key=lambda e: (e["onset"], e["pitch"]))


def write_midi(events, path):
    file = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    file.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=500000))
    timed = []
    for ev in events:
        timed.append((round(ev["onset"] * 480), 1, mido.Message("note_on", note=ev["pitch"], velocity=80)))
        timed.append((round((ev["onset"] + ev["duration"]) * 480), 0, mido.Message("note_off", note=ev["pitch"], velocity=0)))
    previous = 0
    for tick, _, message in sorted(timed, key=lambda item: (item[0], item[1])):
        track.append(message.copy(time=tick - previous))
        previous = tick
    file.save(path)


def read_midi(path):
    midi = mido.MidiFile(path)
    notes = []
    hanging = 0
    for ti, track in enumerate(midi.tracks):
        active = defaultdict(list)
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                active[(msg.channel, msg.note)].append(tick)
            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                key = (msg.channel, msg.note)
                if active[key]:
                    onset = active[key].pop(0)
                    notes.append({"pitch": msg.note, "onset": onset / midi.ticks_per_beat,
                                  "duration": (tick - onset) / midi.ticks_per_beat, "part": ti})
        hanging += sum(len(items) for items in active.values())
    return sorted(notes, key=lambda e: (e["onset"], e["pitch"])), hanging


def matched_count(reference, actual, predicate):
    # Maximum-cardinality bipartite matching avoids double credit for duplicate notes.
    neighbors = [[j for j, act in enumerate(actual) if predicate(ref, act)] for ref in reference]
    assigned = {}
    def augment(i, seen):
        for j in neighbors[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in assigned or augment(assigned[j], seen):
                assigned[j] = i
                return True
        return False
    for i in range(len(reference)):
        augment(i, set())
    return len(assigned)


def metrics(ref, actual):
    def onset_match(a, b):
        return a["pitch"] == b["pitch"] and abs(a["onset"] - b["onset"]) <= 0.0625 + 1e-8
    def note_match(a, b):
        return onset_match(a, b) and abs((a["onset"] + a["duration"]) - (b["onset"] + b["duration"])) <= max(0.0625, a["duration"] * 0.2) + 1e-8
    def summarize(tp):
        fp, fn = len(actual) - tp, len(ref) - tp
        return {"tp": tp, "fp": fp, "fn": fn, "precision": tp / len(actual) if actual else 0,
                "recall": tp / len(ref) if ref else 0, "f1": 2 * tp / (len(ref) + len(actual)) if ref or actual else 1}
    return {"reference_notes": len(ref), "predicted_notes": len(actual),
            "pitch_onset": summarize(matched_count(ref, actual, onset_match)),
            "pitch_onset_offset": summarize(matched_count(ref, actual, note_match)),
            "pitch_inventory_diagnostic": summarize(sum((Counter(e["pitch"] for e in ref) & Counter(e["pitch"] for e in actual)).values()))}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(args):
    import verovio
    import resvg_py
    from PIL import Image
    args.fixtures.mkdir(parents=True, exist_ok=True)
    manifest = {"kind": "authored synthetic engraving, not photographs or scans", "verovio": verovio.toolkit().getVersion(), "fixtures": []}
    for spec in fixtures():
        folder = args.fixtures / spec["id"]
        folder.mkdir(exist_ok=True)
        xml = folder / "reference.musicxml"
        xml.write_bytes(to_musicxml(spec))
        ref = reference_events(spec)
        (folder / "truth.json").write_text(json.dumps(ref, indent=2), encoding="utf-8")
        (folder / "spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
        write_midi(ref, folder / "reference.mid")
        toolkit = verovio.toolkit()
        toolkit.resetXmlIdSeed(20260922)
        toolkit.setOptions({"pageWidth": 2100, "pageHeight": 2970, "scale": 100, "adjustPageHeight": True,
                            "breaks": "auto", "header": "none", "footer": "none", "font": "Bravura"})
        if not toolkit.loadFile(str(xml)):
            raise RuntimeError(f"Unable to engrave {xml}")
        if toolkit.getPageCount() != 1:
            raise RuntimeError(f"Expected one page, got {toolkit.getPageCount()}")
        svg = toolkit.renderToSVG(1)
        (folder / "score.svg").write_text(svg, encoding="utf-8")
        png = folder / "score.png"
        music_font = Path(__file__).resolve().parents[2] / "app" / "res" / "Bravura.otf"
        png.write_bytes(resvg_py.svg_to_bytes(svg_string=svg, background="#ffffff", width=2480,
                                             font_files=[str(music_font)]))
        reread, hanging = read_midi(folder / "reference.mid")
        assert metrics(ref, reread)["pitch_onset_offset"]["f1"] == 1 and hanging == 0
        manifest["fixtures"].append({"id": spec["id"], "description": spec["description"], "reference_notes": len(ref),
                                     "png_size": Image.open(png).size, "png_sha256": sha(png), "musicxml_sha256": sha(xml)})
    (args.fixtures / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


def run(args):
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((args.fixtures / "manifest.json").read_text(encoding="utf-8"))
    result = {"fixture_manifest": manifest, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "jar_sha256": sha(args.application_jar or args.distribution / "lib" / "notelite.jar"), "truth_file": args.truth,
              "metric_definition": "one-to-one maximum-cardinality matching; exact MIDI pitch; onset tolerance 1/16 quarter beat; offset tolerance max(1/16 beat, 20% reference duration); no alignment or transposition; failures count all truth as false negatives",
              "cases": []}
    selected = manifest["fixtures"]
    if args.only:
        selected = [case for case in selected if case["id"] in args.only.split(",")]
    for case in selected:
        folder = args.fixtures / case["id"]
        out = args.output / case["id"]
        if out.exists() and any(out.iterdir()):
            raise RuntimeError(f"Refusing non-empty output directory (stale results could contaminate the benchmark): {out}")
        out.mkdir(exist_ok=True)
        classpath = str(args.distribution / "lib" / "*")
        if args.application_jar:
            classpath = str(args.application_jar.resolve()) + os.pathsep + classpath
        command = [args.java, "--enable-preview", "-Xmx4g", "-Dfile.encoding=UTF-8", "-Djava.util.PropertyResourceBundle.encoding=UTF-8",
                   "--add-exports=java.desktop/sun.awt.image=ALL-UNNAMED", "--enable-native-access=ALL-UNNAMED",
                   "-cp", classpath, "NoteLite", "-batch", "-transcribe", "-export", "-export-midi",
                   "-output", str(out.resolve()), "--", str((folder / case.get("input", "score.png")).resolve())]
        environment = dict(os.environ)
        if args.tessdata:
            environment["TESSDATA_PREFIX"] = str(args.tessdata.resolve())
        started = time.monotonic()
        timeout = False
        with (out / "console.txt").open("w", encoding="utf-8") as log:
            try:
                process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=environment,
                                         timeout=args.timeout, check=False)
                code = process.returncode
            except subprocess.TimeoutExpired:
                timeout = True
                code = None
        outputs = list(out.rglob("*.mid"))
        actual, hanging = read_midi(outputs[0]) if len(outputs) == 1 else ([], 0)
        truth = json.loads((folder / args.truth).read_text(encoding="utf-8"))
        status = "ok" if code == 0 and len(outputs) == 1 else "timeout" if timeout else "failed"
        item = {"id": case["id"], "status": status, "exit_code": code, "seconds": round(time.monotonic() - started, 3),
                "command": command, "midi_outputs": [str(p.resolve()) for p in outputs], "unclosed_notes": hanging,
                "metrics": metrics(truth, actual), "actual_notes": actual}
        result["cases"].append(item)
        (args.output / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"{case['id']}: {status}; notes={len(actual)}/{len(truth)}; onset_F1={item['metrics']['pitch_onset']['f1']:.3%}; full_F1={item['metrics']['pitch_onset_offset']['f1']:.3%}", flush=True)
    aggregates = {}
    for metric in ("pitch_onset", "pitch_onset_offset", "pitch_inventory_diagnostic"):
        totals = {name: sum(case["metrics"][metric][name] for case in result["cases"]) for name in ("tp", "fp", "fn")}
        totals["precision"] = totals["tp"] / (totals["tp"] + totals["fp"]) if totals["tp"] + totals["fp"] else 0
        totals["recall"] = totals["tp"] / (totals["tp"] + totals["fn"]) if totals["tp"] + totals["fn"] else 0
        totals["f1"] = 2 * totals["tp"] / (2 * totals["tp"] + totals["fp"] + totals["fn"]) if 2 * totals["tp"] + totals["fp"] + totals["fn"] else 1
        aggregates[metric] = totals
    result["aggregate"] = aggregates
    (args.output / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(aggregates, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    gen = subparsers.add_parser("generate")
    gen.add_argument("--fixtures", type=Path, required=True)
    execute = subparsers.add_parser("run")
    execute.add_argument("--fixtures", type=Path, required=True)
    execute.add_argument("--distribution", type=Path, required=True)
    execute.add_argument("--output", type=Path, required=True)
    execute.add_argument("--java", default="java")
    execute.add_argument("--tessdata", type=Path)
    execute.add_argument("--timeout", type=int, default=240)
    execute.add_argument("--only")
    execute.add_argument("--truth", default="truth.json")
    execute.add_argument("--application-jar", type=Path, help="Optional preserved application JAR, before distribution dependencies on the classpath")
    args = parser.parse_args()
    if args.action == "generate":
        generate(args)
    else:
        run(args)


if __name__ == "__main__":
    main()
