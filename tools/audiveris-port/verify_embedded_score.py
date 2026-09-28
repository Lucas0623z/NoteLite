#!/usr/bin/env python3
"""Compare real embedded MusicXML/MIDI output with the desktop engine's semantics.

This proves port parity for a fixture, not that the desktop recognition is a
human-verified transcription. Layout, timestamps and filesystem paths are ignored.
No external libraries, network access, or XML entity resolution are used.
"""
import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
import zipfile

MAX_XML_BYTES = 32 * 1024 * 1024


def read_xml(path):
    if path.suffix.lower() == ".mxl":
        with zipfile.ZipFile(path) as archive:
            container = ET.fromstring(archive.read("META-INF/container.xml"))
            roots = [node.get("full-path") for node in container.iter()
                     if node.tag.rsplit("}", 1)[-1] == "rootfile"
                     and node.get("media-type") == "application/vnd.recordare.musicxml+xml"]
            if len(roots) != 1:
                raise ValueError("Expected one declared MusicXML score in MXL container")
            info = archive.getinfo(roots[0])
            if info.file_size > MAX_XML_BYTES:
                raise ValueError("Score XML exceeds fixture limit")
            data = archive.read(info)
    else:
        if path.stat().st_size > MAX_XML_BYTES:
            raise ValueError("Score XML exceeds fixture limit")
        data = path.read_bytes()
    if b"<!ENTITY" in data.upper():
        raise ValueError("XML entity declarations are not accepted")
    root = ET.fromstring(data)
    if root.tag != "score-partwise":
        raise ValueError("Expected score-partwise MusicXML")
    return root


def semantic_node(node):
    # MusicXML display coordinates and font choices differ across platforms.
    ignored = {"default-x", "default-y", "relative-x", "relative-y", "font-family",
               "font-size", "font-style", "font-weight", "color", "placement",
               "print-object", "print-spacing", "justify", "halign", "valign",
               "bezier-x", "bezier-y", "bezier-x2", "bezier-y2"}
    return {"tag": node.tag,
            "attributes": {k: v for k, v in sorted(node.attrib.items()) if k not in ignored},
            "text": (node.text or "").strip(),
            "children": [semantic_node(child) for child in node]}


def musicxml_semantics(path):
    root = read_xml(path)
    result = []
    totals = Counter()
    note_tags = {"pitch", "rest", "unpitched", "chord", "grace", "cue", "tie",
                 "voice", "type", "dot", "accidental", "time-modification", "staff",
                 "notations", "lyric"}
    for part_index, part in enumerate(root.findall("part")):
        divisions = 1
        measures = []
        for measure in part.findall("measure"):
            cursor = Fraction(0)
            previous_onset = Fraction(0)
            events = []
            for node in measure:
                if node.tag == "attributes":
                    if node.find("divisions") is not None:
                        divisions = int(node.findtext("divisions"))
                        if divisions <= 0:
                            raise ValueError("Invalid MusicXML divisions")
                    kept = [semantic_node(child) for child in node if child.tag in
                            {"key", "time", "staves", "clef", "transpose", "measure-style"}]
                    if kept:
                        events.append({"kind": "attributes", "onset": str(cursor), "values": kept})
                elif node.tag in {"backup", "forward"}:
                    duration = Fraction(node.findtext("duration", "0")) / divisions
                    cursor += duration * (-1 if node.tag == "backup" else 1)
                elif node.tag == "note":
                    duration = Fraction(node.findtext("duration", "0")) / divisions
                    chord = node.find("chord") is not None
                    onset = previous_onset if chord else cursor
                    events.append({"kind": "note", "onset": str(onset), "duration": str(duration),
                                   "values": [semantic_node(child) for child in node if child.tag in note_tags]})
                    previous_onset = onset
                    if not chord:
                        cursor += duration
                    totals["pitched_notes" if node.find("pitch") is not None else "other_notes"] += 1
                elif node.tag == "barline":
                    events.append({"kind": "barline", "value": semantic_node(node)})
                elif node.tag == "direction":
                    sounds = node.findall("sound")
                    if sounds:
                        events.append({"kind": "sound", "onset": str(cursor),
                                       "values": [semantic_node(sound) for sound in sounds]})
            measures.append({"number": measure.get("number"), "events": events})
        totals["measures"] += len(measures)
        result.append({"part": part_index, "measures": measures})
    if not totals["pitched_notes"]:
        raise ValueError("Recognition output has no pitched notes")
    return {"counts": dict(totals), "parts": result}


def midi_semantics(path):
    data = path.read_bytes()
    if data[:4] != b"MThd" or len(data) < 14:
        raise ValueError("Invalid MIDI header")
    header_size = struct.unpack_from(">I", data, 4)[0]
    format_number, track_count, resolution = struct.unpack_from(">HHH", data, 8)
    if format_number > 1 or resolution == 0 or resolution & 0x8000:
        raise ValueError("Fixture requires MIDI type 0/1 with metrical timing")
    position = 8 + header_size
    events = []

    def vlq(track, offset):
        value = 0
        for _ in range(4):
            byte = track[offset]
            offset += 1
            value = (value << 7) | (byte & 127)
            if not byte & 128:
                return value, offset
        raise ValueError("Invalid MIDI variable-length value")

    for _ in range(track_count):
        if data[position:position + 4] != b"MTrk":
            raise ValueError("Missing MIDI track")
        length = struct.unpack_from(">I", data, position + 4)[0]
        track = data[position + 8:position + 8 + length]
        if len(track) != length:
            raise ValueError("Truncated MIDI track")
        position += 8 + length
        offset = tick = 0
        running = None
        while offset < len(track):
            delta, offset = vlq(track, offset)
            tick += delta
            status = track[offset]
            if status & 128:
                offset += 1
            elif running is not None:
                status = running
            else:
                raise ValueError("MIDI running status missing")
            beat = str(Fraction(tick, resolution))
            if status == 255:
                running = None
                kind = track[offset]
                size, offset = vlq(track, offset + 1)
                payload = track[offset:offset + size]
                offset += size
                if kind in {0x51, 0x58, 0x59}:
                    events.append([beat, "meta", kind, payload.hex()])
            elif status in {240, 247}:
                running = None
                size, offset = vlq(track, offset)
                offset += size
            elif 128 <= status <= 239:
                running = status
                command, channel = status & 240, status & 15
                size = 1 if command in {192, 208} else 2
                payload = list(track[offset:offset + size])
                if len(payload) != size or any(v > 127 for v in payload):
                    raise ValueError("Invalid MIDI channel message")
                offset += size
                if command == 144 and payload[1] == 0:
                    command = 128
                if command in {128, 144, 176, 192, 224}:
                    if command == 128:
                        payload[1] = 0  # release velocity does not change note duration
                    events.append([beat, "channel", channel, command, *payload])
            else:
                raise ValueError(f"Unexpected MIDI status {status}")
    events.sort(key=lambda event: (Fraction(event[0]), json.dumps(event[1:])))
    count = sum(event[1] == "channel" and event[3] == 144 for event in events)
    if not count:
        raise ValueError("Recognition MIDI has no sounding notes")
    return {"note_on_count": count, "events": events}


def score_semantics(directory):
    xml = sorted(p for p in directory.rglob("*") if p.suffix.lower() in {".mxl", ".musicxml"})
    midi = sorted(directory.rglob("*.mid"))
    if len(xml) != 1 or len(midi) != 1:
        raise ValueError(f"Expected one score and MIDI in {directory}, found {len(xml)} and {len(midi)}")
    return {"musicxml": musicxml_semantics(xml[0]), "midi": midi_semantics(midi[0])}


def differences(expected, actual, path="", limit=20):
    if type(expected) is not type(actual):
        return [{"path": path, "expected": expected, "actual": actual}]
    result = []
    if isinstance(expected, dict):
        for key in sorted(set(expected) | set(actual)):
            result.extend(differences(expected.get(key), actual.get(key), f"{path}/{key}", limit))
            if len(result) >= limit:
                break
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            result.append({"path": path + "/length", "expected": len(expected), "actual": len(actual)})
        for index, (left, right) in enumerate(zip(expected, actual)):
            result.extend(differences(left, right, f"{path}/{index}", limit))
            if len(result) >= limit:
                break
    elif expected != actual:
        result.append({"path": path, "expected": expected, "actual": actual})
    return result[:limit]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_directory", type=Path)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--write-reference", action="store_true")
    parser.add_argument("--source-image", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    actual = score_semantics(args.job_directory)
    if args.write_reference:
        if not args.source_image:
            parser.error("--source-image is required when recording a desktop reference")
        reference = {"schema": 1, "kind": "desktop-engine-parity-reference",
                     "source_sha256": hashlib.sha256(args.source_image.read_bytes()).hexdigest(),
                     "semantics": actual}
        args.reference.parent.mkdir(parents=True, exist_ok=True)
        args.reference.write_text(json.dumps(reference, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Recorded desktop semantic reference; this is not a human transcription accuracy result.")
        return
    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    if args.source_image and hashlib.sha256(args.source_image.read_bytes()).hexdigest() != reference["source_sha256"]:
        raise ValueError("Input score differs from reference source")
    mismatch = differences(reference["semantics"], actual)
    report = {"passed": not mismatch, "comparison": "desktop-engine-semantic-parity",
              "musicxml_counts": actual["musicxml"]["counts"],
              "midi_note_on_count": actual["midi"]["note_on_count"], "differences": mismatch}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", encoding="utf-8")
    print(text)
    if mismatch:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
