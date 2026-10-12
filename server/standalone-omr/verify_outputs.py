#!/usr/bin/env python3
"""Validate one completed Audiveris batch job; never launch OMR or contact a server.

Python 3.10+, standard library. PDF page counting additionally needs `pdfinfo`
(Ubuntu poppler-utils), or installed pypdf. No XML external entities are fetched.
This checks useful, complete exports; it does not prove transcription accuracy.

Example:
  python3 verify_outputs.py --fixture dichterliebe --input /tmp/Dichterliebe01.pdf \
    --outputs /tmp/job/output --log /tmp/job/combined.log \
    --run-metadata /tmp/job/run.json --report /tmp/job/verification.json

run.json: {"exitCode":0,"elapsedSeconds":123.4,"startedAtUnix":1791720000.0}
startedAtUnix is the actual process-start Unix time, not the verifier start time.
Use a new empty output directory for every run. Run --self-test for validator
regressions only; their tiny XML examples are not OMR acceptance samples.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
import zipfile

MAX_XML = 32 * 1024 * 1024
MAX_ARCHIVE_FILES = 10000
MAX_ARCHIVE_EXPANDED = 512 * 1024 * 1024
MAX_LOG = 32 * 1024 * 1024
UPSTREAM_COMMIT = "9e1e55cd2746037d059345881c53e6a6754bffbd"
FIXTURES = {
    "allegretto": {
        "path": "data/examples/allegretto.png",
        "gitBlobSha": "11eb5b733c5fa3fe279463b7a195aa5010290dd1",
        "sha256": "a9207f26b57415d8c54602881316c003319c5593ed8baf4c3af13715c41b3065",
        "bytes": 67744, "pages": 1, "minParts": 1,
        "minMeasures": 12, "minPitchedNotes": 20,
        "description": "Rinck Allegretto: real 17-measure, two-staff printed score",
    },
    "dichterliebe": {
        "path": "data/examples/Dichterliebe01.pdf",
        "gitBlobSha": "7c53237e79cb9eac35ce0511d2127aa2f0e6f55b",
        "sha256": "4169e43dda320cb1dc23e79ffd861ee2b78bffd84dd24997ab964d574aa8723f",
        "bytes": 175329, "pages": 2, "minParts": 2,
        "minMeasures": 20, "minPitchedNotes": 80,
        "description": "Schumann Im wunderschonen Monat Mai: two pages, voice and piano, 26 measures",
    },
}
for _fixture in FIXTURES.values():
    _fixture["url"] = ("https://raw.githubusercontent.com/Audiveris/audiveris/"
                       + UPSTREAM_COMMIT + "/" + _fixture["path"])


class VerificationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def children(node, name):
    return [child for child in node if local_name(child.tag) == name]


def child(node, name):
    return next(iter(children(node, name)), None)


def text(node, name, default=""):
    element = child(node, name)
    return (element.text or "").strip() if element is not None else default


def xml_from_bytes(data, label):
    require(len(data) <= MAX_XML, f"{label}: XML exceeds {MAX_XML} bytes")
    # Reject declarations even in UTF-16/32; external MusicXML DOCTYPE without
    # an internal entity declaration is allowed. ElementTree does not fetch it.
    require(b"<!ENTITY" not in data.replace(b"\0", b"").upper(),
            f"{label}: XML entity declarations are not accepted")
    try:
        return ET.fromstring(data)
    except ET.ParseError as error:
        raise VerificationError(f"{label}: malformed XML: {error}") from error


def safe_member(name):
    require(name and "\\" not in name and not name.startswith("/"),
            f"unsafe ZIP member: {name!r}")
    pieces = name.rstrip("/").split("/")
    require(all(piece not in {"", ".", ".."} and ":" not in piece for piece in pieces),
            f"unsafe ZIP member: {name!r}")
    return str(PurePosixPath(name))


@contextmanager
def checked_archive(path):
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        require(0 < len(infos) <= MAX_ARCHIVE_FILES, "invalid ZIP entry count")
        require(sum(info.file_size for info in infos) <= MAX_ARCHIVE_EXPANDED,
                "ZIP expanded size exceeds validation bound")
        names = [safe_member(info.filename) for info in infos]
        require(len(names) == len(set(names)), "duplicate ZIP member names")
        require(not any(info.flag_bits & 1 for info in infos), "encrypted ZIP member")
        for info in infos:
            mode = info.external_attr >> 16
            require(mode & 0o170000 != 0o120000, "ZIP symbolic link not accepted")
        require(archive.testzip() is None, "ZIP CRC validation failed")
        yield archive


def archive_xml(archive, name):
    require(name in archive.namelist(), f"ZIP missing {name}")
    info = archive.getinfo(name)
    require(not info.is_dir() and info.file_size <= MAX_XML,
            f"{name}: invalid/oversized XML entry")
    return xml_from_bytes(archive.read(info), name)


def read_musicxml(path):
    with checked_archive(path) as archive:
        container = archive_xml(archive, "META-INF/container.xml")
        require(local_name(container.tag) == "container", "invalid MXL container root")
        roots = [node for node in container.iter() if local_name(node.tag) == "rootfile"]
        require(len(roots) == 1, "MXL must declare exactly one score rootfile; use useOpus=false")
        rootfile = roots[0]
        require(rootfile.get("media-type") == "application/vnd.recordare.musicxml+xml",
                "MXL rootfile has an unexpected media type")
        name = rootfile.get("full-path", "")
        safe_member(name)
        score = archive_xml(archive, name)
        require(local_name(score.tag) == "score-partwise",
                "expected partwise MusicXML (opus/timewise is outside this acceptance contract)")
        if "mimetype" in archive.namelist():
            require(archive.read("mimetype").strip() == b"application/vnd.recordare.musicxml",
                    "incorrect MXL mimetype")
        return score, {"scoreMember": name, "containerValid": True,
                       "archiveCrcValid": True, "archiveEntries": len(archive.infolist())}


def inspect_score(root):
    parts = children(root, "part")
    part_list = child(root, "part-list")
    declared = children(part_list, "score-part") if part_list is not None else []
    actual_ids = [part.get("id") for part in parts]
    declared_ids = [part.get("id") for part in declared]
    require(parts and all(actual_ids) and len(set(actual_ids)) == len(actual_ids),
            "MusicXML has no parts or duplicate/empty part IDs")
    require(set(actual_ids) == set(declared_ids) and len(declared_ids) == len(actual_ids),
            "MusicXML part-list and exported parts disagree")
    counts = Counter()
    part_reports = []
    warnings = []
    reference_measures = None
    for part in parts:
        measures = children(part, "measure")
        require(measures, f"part {part.get('id')}: no measures")
        measure_numbers = [measure.get("number") for measure in measures]
        if reference_measures is None:
            reference_measures = measure_numbers
        elif measure_numbers != reference_measures:
            warnings.append(f"part {part.get('id')}: measure numbering differs across parts")
        pages = [{"index": 1, "measures": 0, "pitchedNotes": 0, "rests": 0}]
        part_counts = Counter()
        for index, measure in enumerate(measures):
            if index and any(element.get("new-page") == "yes"
                             for element in children(measure, "print")):
                pages.append({"index": len(pages) + 1, "measures": 0,
                              "pitchedNotes": 0, "rests": 0})
            pages[-1]["measures"] += 1
            for note in children(measure, "note"):
                counts["notes"] += 1
                pitch, rest, unpitched = child(note, "pitch"), child(note, "rest"), child(note, "unpitched")
                require(sum(element is not None for element in (pitch, rest, unpitched)) == 1,
                        "MusicXML note must have exactly one of pitch/rest/unpitched")
                if pitch is not None:
                    require(text(pitch, "step") in "ABCDEFG" and len(text(pitch, "step")) == 1,
                            "invalid pitched note step")
                    try:
                        octave = int(text(pitch, "octave"))
                        alter = Fraction(text(pitch, "alter", "0"))
                    except (ValueError, ZeroDivisionError) as error:
                        raise VerificationError("invalid pitch octave/alter") from error
                    require(0 <= octave <= 9 and -4 <= alter <= 4, "pitch outside MusicXML bounds")
                    counts["pitchedNotes"] += 1
                    part_counts["pitchedNotes"] += 1
                    pages[-1]["pitchedNotes"] += 1
                elif rest is not None:
                    counts["rests"] += 1
                    part_counts["rests"] += 1
                    pages[-1]["rests"] += 1
                else:
                    counts["unpitchedNotes"] += 1
                if child(note, "grace") is not None:
                    counts["graceNotes"] += 1
                else:
                    try:
                        duration = Fraction(text(note, "duration"))
                    except (ValueError, ZeroDivisionError) as error:
                        raise VerificationError("non-grace note has no valid duration") from error
                    require(duration > 0, "non-grace note has nonpositive duration")
                counts["lyrics"] += len(children(note, "lyric"))
        counts["partMeasures"] += len(measures)
        part_reports.append({"id": part.get("id"), "measures": len(measures),
                             "layoutPages": len(pages), "pageContent": pages,
                             "pitchedNotes": part_counts["pitchedNotes"], "rests": part_counts["rests"]})
    require(counts["pitchedNotes"] > 0, "recognition contains no pitched notes")
    layout_pages = max(part["layoutPages"] for part in part_reports)
    require(all(part["layoutPages"] == layout_pages for part in part_reports),
            "physical-page layout boundaries differ across exported parts")
    combined_pages = []
    for page_index in range(layout_pages):
        content = {key: sum(part["pageContent"][page_index][key] for part in part_reports)
                   for key in ("pitchedNotes", "rests")}
        content["index"] = page_index + 1
        content["scoreMeasures"] = max(part["pageContent"][page_index]["measures"] for part in part_reports)
        require(content["pitchedNotes"] > 0, f"exported layout page {page_index + 1} has no pitched notes")
        combined_pages.append(content)
    return {**dict(counts), "parts": len(parts), "scoreMeasures": max(len(children(part, "measure")) for part in parts),
            "layoutPages": layout_pages, "pageContent": combined_pages,
            "partContent": part_reports, "warnings": warnings}


def inspect_book(path, physical_pages, version):
    with checked_archive(path) as archive:
        root = archive_xml(archive, "book.xml")
        require(local_name(root.tag) == "book", "OMR has an invalid book.xml root")
        require(root.get("software-version", "").removeprefix("v") == version,
                f"saved OMR version is not expected {version}: {root.get('software-version')}")
        stubs = children(root, "sheet")
        require(len(stubs) == physical_pages, f"OMR has {len(stubs)} sheets; input has {physical_pages} pages")
        sheet_reports, references = [], set()
        for expected_number, stub in enumerate(stubs, 1):
            number = int(stub.get("number", "0"))
            require(number == expected_number, "OMR physical sheet numbers are incomplete/out of order")
            require(stub.get("invalid", "false").lower() not in {"true", "1"},
                    f"OMR physical sheet {number} was invalidated")
            steps = text(stub, "steps").split()
            require("PAGE" in steps, f"OMR sheet {number} did not finish PAGE")
            pages = children(stub, "page")
            require(pages, f"OMR sheet {number} contains no recognized logical pages")
            ids = [int(page.get("id", "0")) for page in pages]
            require(ids == list(range(1, len(ids) + 1)), "OMR logical page IDs are incomplete/out of order")
            require(all(children(page, "system") for page in pages),
                    f"OMR sheet {number} has a logical page without music systems")
            # Audiveris 5.11 uses Sheet.INTERNALS_RADIX="sheet#". Accept the
            # older no-hash spelling as well when checking legacy fixture ZIPs.
            prefixes = (f"sheet#{number}/", f"sheet{number}/")
            require(any(name.startswith(prefixes) and name.endswith(".xml") for name in archive.namelist()),
                    f"OMR is missing persisted sheet material for physical sheet {number}")
            references.update((number, identifier) for identifier in ids)
            sheet_reports.append({"number": number, "finishedPage": True, "steps": steps,
                                  "logicalPages": len(pages), "logicalPageIds": ids})
        score_reports, mapped = [], []
        for index, score in enumerate(children(root, "score"), 1):
            pages = [(int(page.get("sheet-number", "0")), int(page.get("sheet-page-id", "0")))
                     for page in children(score, "page")]
            require(pages, f"OMR movement {index} has no page mappings")
            require(pages == sorted(pages) and len(pages) == len(set(pages)),
                    f"OMR movement {index}: duplicate/reordered pages")
            mapped.extend(pages)
            score_reports.append({"movement": index, "pages": [list(page) for page in pages]})
        require(score_reports, "OMR book has no recognized scores")
        require(set(mapped) == references and len(mapped) == len(references),
                "OMR movement maps omit or duplicate recognized logical pages")
        return {"version": root.get("software-version"), "sourcePath": root.get("path"),
                "archiveCrcValid": True, "physicalPages": physical_pages,
                "logicalPages": len(references), "sheets": sheet_reports,
                "movements": score_reports}


def inspect_input(path):
    if path.suffix.lower() == ".pdf":
        if shutil.which("pdfinfo"):
            result = subprocess.run(["pdfinfo", str(path.resolve())], capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=30)
            require(result.returncode == 0, f"pdfinfo rejected input: {result.stderr.strip()}")
            matches = re.findall(r"^Pages:\s+(\d+)\s*$", result.stdout, re.MULTILINE)
            require(len(matches) == 1 and int(matches[0]) > 0, "pdfinfo did not return an actual page count")
            return {"pages": int(matches[0]), "pageCountMethod": "pdfinfo",
                    "pdfinfoWarnings": result.stderr.strip()}
        try:
            from pypdf import PdfReader
        except ImportError as error:
            raise VerificationError("PDF validation needs Ubuntu poppler-utils (pdfinfo), or pypdf") from error
        reader = PdfReader(path, strict=True)
        require(not reader.is_encrypted, "encrypted PDF acceptance input is not supported")
        require(len(reader.pages) > 0, "PDF input has no pages")
        return {"pages": len(reader.pages), "pageCountMethod": "pypdf"}
    require(path.suffix.lower() == ".png", "acceptance inputs must be PNG or PDF")
    with path.open("rb") as stream:
        header = stream.read(33)
    require(len(header) == 33 and header[:8] == b"\x89PNG\r\n\x1a\n"
            and header[8:16] == b"\x00\x00\x00\rIHDR", "invalid PNG header")
    width, height = struct.unpack(">II", header[16:24])
    require(width > 0 and height > 0, "PNG input dimensions are empty")
    return {"pages": 1, "pageCountMethod": "single PNG", "width": width, "height": height}


def inspect_midi(path):
    """Parse real SMF events, including running status; file existence is not enough."""
    require(0 < path.stat().st_size <= MAX_XML, "MIDI is empty or exceeds validation bound")
    data = path.read_bytes()
    require(len(data) >= 14 and data[:4] == b"MThd", "invalid MIDI header")
    header_length = struct.unpack_from(">I", data, 4)[0]
    require(header_length >= 6 and 8 + header_length <= len(data), "truncated MIDI header")
    format_number, track_count, division = struct.unpack_from(">HHH", data, 8)
    require(format_number in (0, 1) and 0 < track_count <= 512
            and (format_number != 0 or track_count == 1), "invalid MIDI format/track count")
    require(division > 0 and not division & 0x8000, "MIDI converter must use positive PPQ timing")
    cursor = 8 + header_length
    events, parsed_event_count = [], 0

    def variable_length(position, limit):
        value = 0
        for _ in range(4):
            require(position < limit, "truncated MIDI variable-length value")
            byte = data[position]
            position += 1
            value = (value << 7) | (byte & 127)
            if not byte & 128:
                return value, position
        raise VerificationError("MIDI variable-length value exceeds four bytes")

    for track_index in range(track_count):
        require(cursor + 8 <= len(data) and data[cursor:cursor + 4] == b"MTrk", "missing MIDI track chunk")
        length = struct.unpack_from(">I", data, cursor + 4)[0]
        cursor += 8
        limit = cursor + length
        require(limit <= len(data), "truncated MIDI track")
        ticks, running, ended = 0, None, False
        while cursor < limit:
            delta, cursor = variable_length(cursor, limit)
            ticks += delta
            require(cursor < limit, "MIDI event has no status/data")
            status = data[cursor]
            if status & 128:
                cursor += 1
                running = status if status < 0xF0 else None
            else:
                require(running is not None, "invalid MIDI running status")
                status = running
            parsed_event_count += 1
            require(parsed_event_count <= 1000000, "MIDI event count exceeds validation bound")
            if 0x80 <= status <= 0xEF:
                command, channel = status & 0xF0, status & 15
                size = 1 if command in (0xC0, 0xD0) else 2
                require(cursor + size <= limit and all(byte < 128 for byte in data[cursor:cursor + size]),
                        "invalid/truncated MIDI channel event")
                if command in (0x80, 0x90):
                    pitch, velocity = data[cursor:cursor + 2]
                    events.append((ticks, track_index, parsed_event_count, channel, pitch,
                                   command == 0x90 and velocity > 0))
                cursor += size
            elif status == 0xFF:
                require(cursor < limit, "truncated MIDI meta event")
                meta_type = data[cursor]
                cursor += 1
                meta_length, cursor = variable_length(cursor, limit)
                require(cursor + meta_length <= limit, "truncated MIDI meta payload")
                if meta_type == 0x2F:
                    require(meta_length == 0 and cursor == limit, "invalid MIDI end-of-track event")
                    ended = True
                cursor += meta_length
            elif status in (0xF0, 0xF7):
                size, cursor = variable_length(cursor, limit)
                require(cursor + size <= limit, "truncated MIDI SysEx event")
                cursor += size
            else:
                raise VerificationError(f"unsupported MIDI track status {status:#x}")
        require(ended, f"MIDI track {track_index + 1} has no valid end-of-track")
    require(cursor == len(data), "unexpected trailing data after MIDI tracks")
    active = defaultdict(deque)
    note_ons, completed, unmatched_offs, zero_duration = 0, 0, 0, 0
    pitches = set()
    for ticks, _, _, channel, pitch, is_on in sorted(events):
        key = (channel, pitch)
        if is_on:
            active[key].append(ticks)
            note_ons += 1
            pitches.add(pitch)
        elif active[key]:
            onset = active[key].popleft()
            if ticks > onset:
                completed += 1
            else:
                zero_duration += 1
        else:
            unmatched_offs += 1
    dangling = sum(len(onsets) for onsets in active.values())
    require(note_ons > 0 and completed > 0, "MIDI has no sounding positive-duration note-on/off pair")
    require(dangling == 0, f"MIDI has {dangling} note-ons without note-offs")
    warnings = []
    if unmatched_offs:
        warnings.append(f"MIDI has {unmatched_offs} unmatched note-off events")
    if zero_duration:
        warnings.append(f"MIDI has {zero_duration} zero-duration notes")
    return {"path": str(path), "bytes": len(data), "sha256": sha256(path),
            "format": format_number, "tracks": track_count, "ticksPerQuarter": division,
            "noteOns": note_ons, "positiveDurationNotes": completed,
            "unmatchedNoteOffs": unmatched_offs, "danglingNoteOns": dangling,
            "zeroDurationNotes": zero_duration, "midiPitches": sorted(pitches), "warnings": warnings}


def inspect_log(path):
    require(path.stat().st_size <= MAX_LOG, "log exceeds validation bound")
    data = path.read_bytes()
    require(data.strip(), "batch log is empty")
    lines = data.decode("utf-8", errors="replace").splitlines()
    warnings = [{"line": index, "text": line} for index, line in enumerate(lines, 1)
                if re.search(r"\bWARN(?:ING)?\b", line)]
    failures = [{"line": index, "text": line} for index, line in enumerate(lines, 1)
                if re.search(r"\bERROR\b|OutOfMemoryError|UnsatisfiedLinkError|NoClassDefFoundError|"
                             r"Could not export|Could not load|Exception occurred|"
                             r"(?i:OCR is not available|OCR engine.*not available|"
                             r"No OCR available|Tesseract data could not be found|"
                             r"Could not initialize TessBaseAPI|Could not link Tesseract engine|"
                             r"Error in loading local OCR languages|Could not create OCR order|OCR link error|"
                             r"Language '.+' is not supported|collection of supported languages is empty|"
                             r"failed to (?:initialize|init).*tess|error opening data file.*traineddata|"
                             r"timeout .*step|cancelled .*book|transcription did not complete)", line)]
    return {"sha256": sha256(path), "warningCount": len(warnings), "warnings": warnings,
            "fatalCount": len(failures), "fatalMessages": failures}


def verify(args):
    report = {"schema": 1, "verifiedAt": datetime.now(timezone.utc).isoformat(),
              "status": "failed", "claim": "batch output structure, useful content and full input-page coverage",
              "accuracyGroundTruth": False, "errors": [], "warnings": []}
    started = time.monotonic()
    try:
        fixture = FIXTURES.get(args.fixture)
        source = args.input.resolve(strict=True)
        output_dir = args.outputs.resolve(strict=True)
        metadata_path = args.run_metadata.resolve(strict=True)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        require(isinstance(metadata, dict), "run metadata must be a JSON object")
        report["batch"] = {"exitCode": metadata.get("exitCode"),
                           "elapsedSeconds": metadata.get("elapsedSeconds"),
                           "startedAtUnix": metadata.get("startedAtUnix"),
                           "metadataSha256": sha256(metadata_path)}
        report["log"] = inspect_log(args.log.resolve(strict=True))
        report["warnings"].extend(item["text"] for item in report["log"]["warnings"])
        require(type(metadata.get("exitCode")) is int and metadata["exitCode"] == 0,
                f"batch process failed or exit code missing: {metadata.get('exitCode')}")
        elapsed = metadata.get("elapsedSeconds")
        require(isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool)
                and math.isfinite(elapsed) and elapsed > 0, "actual batch elapsedSeconds must be positive")
        started_at = metadata.get("startedAtUnix")
        require(isinstance(started_at, (int, float)) and not isinstance(started_at, bool)
                and math.isfinite(started_at) and 0 < started_at <= time.time() + 2,
                "run metadata must include actual positive startedAtUnix")
        digest = sha256(source)
        expected_sha = args.source_sha256 or (fixture["sha256"] if fixture else None)
        require(expected_sha and re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha),
                "use --fixture or --source-sha256 to pin the input")
        require(digest == expected_sha.lower(), "input SHA256 does not match pinned source")
        input_info = inspect_input(source)
        expected_pages = args.expect_pages or (fixture["pages"] if fixture else None)
        if expected_pages:
            require(input_info["pages"] == expected_pages, "actual input page count disagrees with fixture")
        report["input"] = {"path": str(source), "bytes": source.stat().st_size,
                           "sha256": digest, **input_info}
        if fixture:
            report["fixture"] = {"name": args.fixture, "upstreamCommit": UPSTREAM_COMMIT, **fixture}
        require(report["log"]["fatalCount"] == 0, "batch log contains runtime/export/OCR failures")
        if args.fail_on_warning:
            require(not report["warnings"], "--fail-on-warning: batch emitted warnings")
        require(output_dir.is_dir(), "outputs must name the dedicated batch output directory")
        books = [path for path in output_dir.rglob("*.omr") if path.stem == source.stem]
        require(len(books) == 1, f"expected one saved {source.stem}.omr; found {len(books)}")
        export_pattern = re.compile(re.escape(source.stem) + r"(?:\.mvt([1-9]\d*))?\.mxl$", re.IGNORECASE)
        exports = [path for path in output_dir.rglob("*") if path.is_file() and export_pattern.fullmatch(path.name)]
        require(exports, "no matching compressed MusicXML export found")
        selected = [books[0], *exports]
        require(all(not path.is_symlink() for path in selected), "output symbolic links are not accepted")
        require(all(path.stat().st_mtime + 2 >= started_at for path in selected),
                "output predates this batch run; use a new empty output folder")
        book = inspect_book(books[0], input_info["pages"], args.expected_version)
        saved_source_name = (book.get("sourcePath") or "").replace("\\", "/").rsplit("/", 1)[-1]
        require(saved_source_name == source.name, "saved OMR source filename does not match this input")
        movements = book["movements"]
        require(len(exports) == len(movements), "exported MXL count does not match saved movements")
        by_movement = {}
        for path in exports:
            match = export_pattern.fullmatch(path.name)
            number = int(match.group(1)) if match.group(1) else 1
            require(number not in by_movement, "duplicate movement exports")
            require((len(movements) == 1) == (match.group(1) is None),
                    "export filenames disagree with Audiveris single/multiple movement contract")
            root, container = read_musicxml(path)
            score = inspect_score(root)
            by_movement[number] = {"path": str(path), "bytes": path.stat().st_size,
                                   "sha256": sha256(path), **container, **score}
        require(set(by_movement) == set(range(1, len(movements) + 1)), "exported movement IDs are incomplete")
        physical_content = {page: {"logicalPages": 0, "pitchedNotes": 0, "scoreMeasures": 0}
                            for page in range(1, input_info["pages"] + 1)}
        for movement in movements:
            score = by_movement[movement["movement"]]
            require(score["layoutPages"] == len(movement["pages"]),
                    f"movement {movement['movement']}: MusicXML layout omits/adds recognized pages")
            for page_ref, content in zip(movement["pages"], score["pageContent"]):
                physical = physical_content[page_ref[0]]
                physical["logicalPages"] += 1
                physical["pitchedNotes"] += content["pitchedNotes"]
                physical["scoreMeasures"] += content["scoreMeasures"]
            report["warnings"].extend(score["warnings"])
        require(all(value["pitchedNotes"] > 0 for value in physical_content.values()),
                "one or more input physical pages has no pitched MusicXML content")
        scores = [by_movement[index] for index in sorted(by_movement)]
        totals = {"movements": len(scores), "partsAcrossMovements": sum(score["parts"] for score in scores),
                  "minimumPartsPerMovement": min(score["parts"] for score in scores),
                  "scoreMeasures": sum(score["scoreMeasures"] for score in scores),
                  "partMeasures": sum(score["partMeasures"] for score in scores),
                  "pitchedNotes": sum(score["pitchedNotes"] for score in scores),
                  "rests": sum(score.get("rests", 0) for score in scores),
                  "lyrics": sum(score.get("lyrics", 0) for score in scores),
                  "physicalPages": input_info["pages"], "logicalPages": book["logicalPages"]}
        minima = {"parts": args.min_parts or (fixture["minParts"] if fixture else 1),
                  "measures": args.min_measures or (fixture["minMeasures"] if fixture else 1),
                  "pitchedNotes": args.min_pitched_notes or (fixture["minPitchedNotes"] if fixture else 1)}
        report.update({"omr": {"path": str(books[0]), "sha256": sha256(books[0]), **book},
                       "exports": scores, "totals": totals, "acceptanceMinima": minima,
                       "physicalPageContent": [{"page": page, **content} for page, content in physical_content.items()]})
        require(totals["minimumPartsPerMovement"] >= minima["parts"], "too few parts in one or more movements")
        require(totals["scoreMeasures"] >= minima["measures"], "too few score measures")
        require(totals["pitchedNotes"] >= minima["pitchedNotes"], "too few pitched notes")
        midi_paths = args.midi or [path for path in output_dir.rglob("*")
                                  if path.is_file() and path.suffix.lower() in {".mid", ".midi"}
                                  and path.stem in {score_path.stem for score_path in exports}]
        report["midiRequired"] = args.require_midi
        report["midi"] = []
        if args.require_midi or midi_paths:
            require(len(midi_paths) == len(exports), "MIDI artifact count does not match exported movements")
            require({path.stem for path in midi_paths} == {path.stem for path in exports},
                    "each MIDI must have the same basename as its MusicXML movement")
            for path in sorted(midi_paths):
                require(not path.is_symlink() and path.stat().st_mtime + 2 >= started_at,
                        "MIDI is a symbolic link or predates this run")
                result = inspect_midi(path)
                report["midi"].append(result)
                report["warnings"].extend(result["warnings"])
            totals["midiNoteOns"] = sum(result["noteOns"] for result in report["midi"])
            totals["midiPositiveDurationNotes"] = sum(result["positiveDurationNotes"] for result in report["midi"])
        if args.fail_on_warning:
            require(not report["warnings"], "--fail-on-warning: output emitted warnings")
        report["status"] = "passed-with-warnings" if report["warnings"] else "passed"
    except (VerificationError, OSError, ValueError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        report["errors"].append(f"{type(error).__name__}: {error}")
    report["verificationElapsedSeconds"] = round(time.monotonic() - started, 6)
    return report


class ValidatorTests(unittest.TestCase):
    """Only validator defenses; deliberately not an OMR transcription test suite."""

    def score(self, second_page=True):
        note = "<note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>"
        page_print = '<print new-page="yes"/>' if second_page else ""
        return ("<score-partwise><part-list><score-part id='P1'><part-name>Test</part-name>"
                "</score-part></part-list><part id='P1'><measure number='1'>" + note
                + "</measure><measure number='2'>" + page_print + note + "</measure></part></score-partwise>").encode()

    def archive(self, folder, name, entries):
        path = Path(folder) / name
        with zipfile.ZipFile(path, "w") as archive:
            for member, data in entries:
                archive.writestr(member, data)
        return path

    def container(self, name="score.xml"):
        return ('<container><rootfiles><rootfile full-path="' + name
                + '" media-type="application/vnd.recordare.musicxml+xml"/></rootfiles></container>').encode()

    def book(self, pages=2, complete=True, invalid=False, omitted_mapping=False):
        sheets = "".join(f'<sheet number="{index}" invalid="{str(invalid).lower()}"><steps>'
                         + ("LOAD PAGE" if complete else "LOAD RHYTHMS")
                         + '</steps><page id="1"><system/></page></sheet>' for index in range(1, pages + 1))
        mappings = "".join(f'<page sheet-number="{index}" sheet-page-id="1"/>'
                           for index in range(1, pages + (0 if omitted_mapping else 1)))
        return (f'<book software-version="5.11.0" path="real.pdf">{sheets}<score>{mappings}</score></book>').encode()

    def test_useful_two_page_score(self):
        report = inspect_score(xml_from_bytes(self.score(), "test"))
        self.assertEqual((report["parts"], report["scoreMeasures"], report["pitchedNotes"], report["layoutPages"]), (1, 2, 2, 2))

    def test_empty_score_rejected(self):
        data = self.score().replace(b"<pitch><step>C</step><octave>4</octave></pitch>", b"<rest/>")
        with self.assertRaisesRegex(VerificationError, "no pitched"):
            inspect_score(xml_from_bytes(data, "test"))

    def test_invalid_pitch_rejected(self):
        with self.assertRaisesRegex(VerificationError, "step"):
            inspect_score(xml_from_bytes(self.score().replace(b"<step>C</step>", b"<step>H</step>"), "test"))

    def test_nonpositive_duration_rejected(self):
        with self.assertRaisesRegex(VerificationError, "nonpositive"):
            inspect_score(xml_from_bytes(self.score().replace(b"<duration>1</duration>", b"<duration>0</duration>"), "test"))

    def test_entity_utf16_rejected(self):
        with self.assertRaisesRegex(VerificationError, "entity"):
            xml_from_bytes('<!DOCTYPE a [<!ENTITY e "x">]><a>&e;</a>'.encode("utf-16"), "test")

    def test_valid_mxl_container(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.archive(folder, "a.mxl", [("META-INF/container.xml", self.container()), ("score.xml", self.score())])
            root, info = read_musicxml(path)
            self.assertTrue(info["containerValid"])
            self.assertEqual(local_name(root.tag), "score-partwise")

    def test_missing_container_root_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.archive(folder, "a.mxl", [("META-INF/container.xml", self.container()), ("wrong.xml", self.score())])
            with self.assertRaisesRegex(VerificationError, "missing score.xml"):
                read_musicxml(path)

    def test_zip_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.archive(folder, "a.mxl", [("../score.xml", self.score())])
            with self.assertRaisesRegex(VerificationError, "unsafe"):
                with checked_archive(path):
                    pass

    def omr_path(self, folder, **kwargs):
        pages = kwargs.get("pages", 2)
        return self.archive(folder, "real.omr", [("book.xml", self.book(**kwargs))]
                            + [(f"sheet#{index}/sheet#{index}.xml", b"<sheet/>") for index in range(1, pages + 1)])

    def test_omr_page_coverage_valid(self):
        with tempfile.TemporaryDirectory() as folder:
            result = inspect_book(self.omr_path(folder), 2, "5.11.0")
            self.assertEqual(result["movements"][0]["pages"], [[1, 1], [2, 1]])

    def test_omr_legacy_no_hash_material_compatible(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.archive(folder, "legacy.omr", [("book.xml", self.book())]
                                + [(f"sheet{index}/sheet{index}.xml", b"<sheet/>") for index in range(1, 3)])
            self.assertEqual(inspect_book(path, 2, "5.11.0")["physicalPages"], 2)

    def test_omr_missing_physical_page_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(VerificationError, "input has 2"):
                inspect_book(self.omr_path(folder, pages=1), 2, "5.11.0")

    def test_omr_unfinished_or_invalid_rejected(self):
        for kwargs in ({"complete": False}, {"invalid": True}):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(VerificationError):
                    inspect_book(self.omr_path(folder, **kwargs), 2, "5.11.0")

    def test_omr_missing_export_mapping_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(VerificationError, "omit"):
                inspect_book(self.omr_path(folder, omitted_mapping=True), 2, "5.11.0")

    def test_layout_single_page_not_same_as_two_page_omr(self):
        score = inspect_score(xml_from_bytes(self.score(second_page=False), "test"))
        self.assertEqual(score["layoutPages"], 1)
        self.assertNotEqual(score["layoutPages"], 2)

    def test_warning_reported_and_runtime_failure_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "batch.log"
            path.write_text("INFO starting\nWARN imperfect rhythm\nWARN Could not export score\n", encoding="utf-8")
            result = inspect_log(path)
            self.assertEqual(result["warningCount"], 2)
            self.assertEqual(result["fatalCount"], 1)

    def test_failed_process_retains_elapsed_and_warnings(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            source, log, metadata = base / "real.png", base / "batch.log", base / "run.json"
            source.write_bytes(b"not evaluated after actual process failure")
            log.write_text("WARN Timeout 120 seconds for step PAGE\n", encoding="utf-8")
            metadata.write_text(json.dumps({"exitCode": 2, "elapsedSeconds": 123.4,
                                            "startedAtUnix": time.time() - 124}), encoding="utf-8")
            args = argparse.Namespace(fixture=None, input=source, outputs=base,
                                      log=log, run_metadata=metadata)
            report = verify(args)
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["batch"]["elapsedSeconds"], 123.4)
            self.assertEqual(report["log"]["warningCount"], 1)

    def test_ocr_silent_degradation_is_fatal(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "batch.log"
            path.write_text("INFO No OCR available\nWARN TesseractOrder. Could not initialize TessBaseAPI languages: eng in legacy mode\n"
                            "WARN Language 'chi_sim' is not supported\n", encoding="utf-8")
            self.assertEqual(inspect_log(path)["fatalCount"], 3)

    def midi_path(self, folder, track):
        path = Path(folder) / "test.mid"
        path.write_bytes(b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480)
                         + b"MTrk" + struct.pack(">I", len(track)) + track)
        return path

    def test_midi_sounding_note_and_running_status(self):
        with tempfile.TemporaryDirectory() as folder:
            # Two consecutive note-ons; second uses running status, paired by
            # a note-off and a velocity-zero note-on; each sounds for 120 ticks.
            track = b"\x00\x90\x3c\x50\x00\x40\x50\x78\x80\x3c\x00\x00\x90\x40\x00\x00\xff\x2f\x00"
            result = inspect_midi(self.midi_path(folder, track))
            self.assertEqual((result["noteOns"], result["positiveDurationNotes"]), (2, 2))

    def test_midi_zero_velocity_only_is_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(VerificationError, "no sounding"):
                inspect_midi(self.midi_path(folder, b"\x00\x90\x3c\x00\x00\xff\x2f\x00"))

    def test_midi_dangling_note_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            track = b"\x00\x90\x3c\x50\x78\x80\x3c\x00\x00\x90\x40\x50\x00\xff\x2f\x00"
            with self.assertRaisesRegex(VerificationError, "without note-offs"):
                inspect_midi(self.midi_path(folder, track))

    def test_midi_truncated_track_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(VerificationError, "truncated"):
                inspect_midi(self.midi_path(folder, b"\x00\x90\x3c"))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--list-fixtures", action="store_true")
    parser.add_argument("--fixture", choices=sorted(FIXTURES))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--outputs", type=Path)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--run-metadata", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--source-sha256")
    parser.add_argument("--expect-pages", type=int)
    parser.add_argument("--expected-version", default="5.11.0")
    parser.add_argument("--min-parts", type=int)
    parser.add_argument("--min-measures", type=int)
    parser.add_argument("--min-pitched-notes", type=int)
    parser.add_argument("--require-midi", action="store_true", help="require independently converted MIDI for every movement")
    parser.add_argument("--midi", type=Path, action="append", help="explicit MIDI path (repeat per movement); otherwise discover matching .mid/.midi")
    parser.add_argument("--fail-on-warning", action="store_true")
    args = parser.parse_args()
    if args.list_fixtures:
        print(json.dumps({"upstreamCommit": UPSTREAM_COMMIT, "fixtures": FIXTURES}, ensure_ascii=False, indent=2))
        return 0
    if args.self_test:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ValidatorTests))
        return 0 if result.wasSuccessful() else 1
    for name in ("input", "outputs", "log", "run_metadata", "report"):
        if getattr(args, name) is None:
            parser.error("--" + name.replace("_", "-") + " is required")
    for name in ("expect_pages", "min_parts", "min_measures", "min_pitched_notes"):
        if getattr(args, name) is not None and getattr(args, name) <= 0:
            parser.error("--" + name.replace("_", "-") + " must be positive")
    report = verify(args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(args.report.resolve()),
                      "errors": report["errors"], "warningCount": len(report["warnings"]),
                      "elapsedSeconds": report.get("batch", {}).get("elapsedSeconds"),
                      "totals": report.get("totals")}, ensure_ascii=False))
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
