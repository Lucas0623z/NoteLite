"""Score-bound NoteWise evidence normalization. No model, network or audio access.

Measurement remains client reported. Server validation establishes score identity,
event relationships and deterministic denominators, not that a person performed.
"""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
from statistics import median
from urllib.parse import quote
import xml.etree.ElementTree as ET

VERSION = "score-bound-opportunities-1"
RULES = {"version": "scoped-capability-1", "minOpportunities": 20,
         "minTakes": 3, "minDays": 2, "minCoverage": .8,
         "strengthMaxFailureRate": .05, "weaknessMinFailureRate": .2,
         "progressMinDifference": .1, "minTempoAnchors": 3}
DIMENSIONS = ("pitch", "onset", "duration", "intonation")
STEPS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
UNITS = {"maxima": 32, "long": 16, "breve": 8, "whole": 4, "half": 2,
         "quarter": 1, "eighth": .5, "16th": .25, "32nd": .125,
         "64th": .0625, "128th": .03125}
# Same manual variant contract as practice-web/src/instruments.js. Kept local
# in the service so reading an evidence snapshot cannot execute client code.
INSTRUMENT_VARIANTS = {key: {"concert": 0} for key in ("piano", "violin", "viola", "cello", "harp", "flute", "bassoon", "oboe", "trombone", "tuba", "voice", "harpsichord", "clavinet", "english-horn", "bass", "organ", "accordion", "harmonica", "piccolo", "recorder", "guitar", "sax", "erhu", "guzheng", "pipa", "guqin", "suona", "strings", "winds", "other")}
INSTRUMENT_VARIANTS.update(contrabass={"octave": -12, "concert": 0}, clarinet={"bb": -2, "a": -3, "eb": 3, "concert": 0}, horn={"f": -7, "bb": -2, "concert": 0}, trumpet={"bb": -2, "concert": 0}, euphonium={"bass": 0, "bb-treble": -14})
INSTRUMENT_VARIANTS.update({"english-horn": {"concert": 0, "f": -7},
                            "piccolo": {"concert": 0, "octave": 12},
                            "guitar": {"concert": 0, "octave": -12},
                            "bass": {"concert": 0, "octave": -12},
                            "sax": {"concert": 0, "bb-soprano": -2, "eb-alto": -9,
                                    "bb-tenor": -14, "eb-baritone": -21}})


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def number(value, low=0, high=86400000, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high or integer and value != int(value):
        raise ValueError("演奏数据包含无效数字。")
    return value


def string(value, maximum=160):
    if not isinstance(value, str) or not value or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError("演奏数据标识或版本无效。")
    return value


def fields(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ValueError("演奏数据字段与协议不一致。")


def boolean(value):
    if not isinstance(value, bool):
        raise ValueError("演奏数据状态无效。")
    return value


def items(value, maximum):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError("演奏数据超出范围。")
    return value


def near(a, b):
    return abs(float(a) - float(b)) < 1e-5


def source_id(part, measure, note):
    encoded = quote(part, safe="~!*'()-._")
    return f"{encoded}:{measure}:{note}"


def _text(node, tag, default=""):
    return node.findtext(tag, default).strip()


def _num(node, tag, default=0):
    return float(_text(node, tag, str(default)))


def _repeat_order(parts, count):
    forward, backward, endings = set(), {}, {}
    for part in parts:
        active = set()
        for i, measure in enumerate(part.findall("measure")):
            stop = False
            for bar in measure.findall("barline"):
                repeat, ending = bar.find("repeat"), bar.find("ending")
                if repeat is not None:
                    if repeat.get("direction") == "forward":
                        forward.add(i)
                    if repeat.get("direction") == "backward":
                        times = int(repeat.get("times", "2"))
                        number(times, 1, 100, True)
                        backward[i] = times
                if ending is not None:
                    if ending.get("type") == "start":
                        active = {int(v.strip()) for v in ending.get("number", "").split(",")}
                        if not active or min(active) < 1:
                            raise ValueError("房子编号无效。")
                    else:
                        stop = True
            if active:
                endings[i] = active.copy()
            if stop:
                active.clear()
    starts, regions, implicit = [], defaultdict(list), 0
    for i in range(count):
        if i in forward:
            starts.append(i)
        if i in backward:
            start = starts.pop() if starts else implicit
            regions[start].append((start, i, backward[i]))
            implicit = i + 1
    for value in regions.values():
        value.sort(key=lambda v: -v[1])
    active, order, index, last_pass, steps = [], [], 0, 1, 0
    while index < count:
        steps += 1
        if steps > max(100000, count * 100) or len(order) > 100000:
            raise ValueError("反复路线过长。")
        for region in regions[index]:
            if not any(v[0] == region for v in active):
                active.append([region, 1])
        turn = active[-1][1] if active else last_pass
        if not endings.get(index) or turn in endings[index]:
            order.append(index)
        jump = False
        while active and active[-1][0][1] == index:
            region, turn = active[-1]
            if turn < region[2]:
                active[-1][1] += 1
                index, jump = region[0], True
                break
            last_pass = active.pop()[1]
        if not jump:
            index += 1
    return order


def score_timeline(xml):
    """Mirror the client repeat/tie/tempo normalization, with independent XML input."""
    if not isinstance(xml, str) or len(xml.encode()) > 8 * 1024 * 1024 or "<!ENTITY" in xml.upper():
        raise ValueError("乐谱快照无效。")
    try:
        root = ET.fromstring(xml)
        for element in root.iter():
            element.tag = element.tag.rsplit("}", 1)[-1]
        if root.tag != "score-partwise":
            raise ValueError("需要 MusicXML partwise 快照。")
        if root.findall(".//segno") or root.findall(".//coda") or any(set(s.attrib) & {"dacapo", "dalsegno", "tocoda"} for s in root.findall(".//sound")):
            raise ValueError("跳转路线需先校对，不能生成可靠评估范围。")
        parts, data = root.findall("part"), []
        for part in parts:
            divisions, nominal, transpose, staff_transpose, measures = 1., 4., 0., {}, []
            transpose_explicit, staff_explicit = False, set()
            for mi, measure in enumerate(part.findall("measure")):
                cursor, previous, maximum, ni, notes, tempos = 0., 0., 0., 0, [], []
                for item in measure:
                    if item.tag == "attributes":
                        divisions = _num(item, "divisions", divisions)
                        number(divisions, .000001, 1000000)
                        time = item.find("time")
                        if time is not None:
                            if time.find("senza-misura") is not None:
                                nominal = None
                            else:
                                beats, denominators = time.findall("beats"), time.findall("beat-type")
                                nominal = sum(sum(float(v) for v in b.text.split("+")) * 4 / float(denominators[i].text) for i, b in enumerate(beats))
                                number(nominal, .000001, 100000)
                        for trans in item.findall("transpose"):
                            amount = _num(trans, "chromatic") + 12 * _num(trans, "octave-change")
                            if trans.get("number"):
                                staff_transpose[trans.get("number")] = amount
                                staff_explicit.add(trans.get("number"))
                            else:
                                transpose, staff_transpose = amount, {}
                                transpose_explicit, staff_explicit = True, set()
                    elif item.tag in {"backup", "forward"}:
                        duration = _num(item, "duration") / divisions
                        number(duration, .000001)
                        cursor += duration * (-1 if item.tag == "backup" else 1)
                        if cursor < -1e-7:
                            raise ValueError("声部游标越过小节起点。")
                        maximum = max(maximum, cursor)
                    elif item.tag in {"direction", "sound"}:
                        sound = item if item.tag == "sound" else item.find("sound")
                        at = cursor + _num(item, "offset") / divisions
                        sound_tempo = float(sound.get("tempo", "0")) if sound is not None else 0
                        offset = sound.find("offset") if sound is not None else None
                        direction_offset = item.find("offset")
                        sound_at = cursor + (_num(sound, "offset") / divisions if offset is not None else _num(item, "offset") / divisions if direction_offset is not None and direction_offset.get("sound") == "yes" else 0)
                        if sound_tempo > 0:
                            tempos.append((sound_at, sound_tempo))
                        if not (sound_tempo > 0 and near(sound_at, at)):
                            for metronome in item.findall("direction-type/metronome"):
                                if metronome.find("per-minute") is not None:
                                    bpm = _num(metronome, "per-minute") * UNITS.get(_text(metronome, "beat-unit"), 0) * (2 - 2 ** -len(metronome.findall("beat-unit-dot")))
                                    number(bpm, .000001, 10000)
                                    tempos.append((at, bpm))
                    elif item.tag == "note":
                        key = {"partId": part.get("id", ""), "measureIndex": mi, "noteIndex": ni}
                        ni += 1
                        if item.find("grace") is not None:
                            continue
                        duration = _num(item, "duration") / divisions
                        number(duration, .000001)
                        onset = previous if item.find("chord") is not None else cursor
                        if item.find("chord") is None:
                            previous, cursor = onset, cursor + duration
                        maximum = max(maximum, cursor, onset + duration)
                        pitch = item.find("pitch")
                        if pitch is None:
                            continue
                        step, octave, alter = _text(pitch, "step"), _num(pitch, "octave"), _num(pitch, "alter")
                        staff, voice = _text(item, "staff", "1"), _text(item, "voice", "1")
                        trans = staff_transpose.get(staff, transpose)
                        written = 12 * (octave + 1) + STEPS[step] + alter
                        midi = written + trans
                        number(midi, 0, 127, True)
                        notes.append({**key, "midi": midi, "writtenMidi": written, "step": step, "alter": alter, "octave": octave, "transpose": trans, "transposeExplicit": transpose_explicit or staff in staff_explicit, "staff": staff, "voice": voice, "start": onset, "end": onset + duration, "tieStart": any(t.get("type") == "start" for t in item.findall("tie")), "tieStop": any(t.get("type") == "stop" for t in item.findall("tie"))})
                pickup = nominal is not None and (mi == 0 or measure.get("implicit") == "yes") and 0 < maximum < nominal
                if nominal is not None and not pickup and maximum > nominal + 1e-7:
                    raise ValueError("乐谱小节超拍。")
                measures.append({"length": maximum if pickup or nominal is None else nominal, "notes": notes, "tempos": tempos})
            data.append(measures)
        count = max([len(v) for v in data] + [0])
        order = _repeat_order(parts, count)
        entry, written_tempos, inherited = [], [], 120.
        for mi in range(count):
            entry.append(inherited)
            merged = {}
            for part in data:
                for at, bpm in part[mi]["tempos"] if mi < len(part) else []:
                    if at in merged and not near(merged[at], bpm):
                        raise ValueError("声部速度冲突。")
                    merged[at] = bpm
            events = sorted(merged.items())
            written_tempos.append(events)
            if events:
                inherited = events[-1][1]
        quarter, tempo_map, offset, played, previous, visited, occurrences = [], {0: 120.}, 0., 120., -1, {}, defaultdict(int)
        for mi in order:
            occurrences[mi] += 1
            if mi <= previous:
                played = visited.get(mi, entry[mi])
            visited.setdefault(mi, played)
            tempo_map[offset] = played
            for at, bpm in written_tempos[mi]:
                tempo_map[offset + at] = bpm
            if written_tempos[mi]:
                played = written_tempos[mi][-1][1]
            for part in data:
                if mi < len(part):
                    quarter.extend({**n, "start": offset + n["start"], "end": offset + n["end"], "occurrenceOrdinal": occurrences[mi]} for n in part[mi]["notes"])
            offset += max([p[mi]["length"] for p in data if mi < len(p)] + [0])
            previous = mi
        ordered_tempos = sorted(tempo_map.items())
        def seconds(beat):
            result, start, bpm = 0., 0., 120.
            for at, next_bpm in ordered_tempos:
                if at > beat:
                    break
                result += max(0, at - start) * 60 / bpm
                start, bpm = at, next_bpm
            return result + max(0, beat - start) * 60 / bpm
        notes, ties = [], defaultdict(list)
        for note in sorted(quarter, key=lambda n: n["start"]):
            voice_key = note["partId"], note["voice"], note["midi"]
            opened = [n for n in ties[voice_key] if n["end"] >= note["start"] - 1e-7]
            candidates = [n for n in opened if near(n["end"], note["start"])]
            same_staff = [n for n in candidates if n["staff"] == note["staff"]]
            matching = same_staff or candidates
            if note["tieStop"] and len(matching) > 1:
                raise ValueError("同音延音线有歧义。")
            prior = matching[0] if note["tieStop"] and matching else None
            if prior is not None:
                prior["end"] = note["end"]
                if not note["tieStart"]:
                    opened.remove(prior)
            else:
                notes.append(note)
                if note["tieStart"]:
                    opened.append(note)
            ties[voice_key] = opened
        for note in notes:
            note["onsetBeat"], note["durationBeat"] = note["start"], note["end"] - note["start"]
            note["startMs"], note["durationMs"] = seconds(note["start"]) * 1000, (seconds(note["end"]) - seconds(note["start"])) * 1000
            note["sourceNoteId"] = source_id(note["partId"], note["measureIndex"], note["noteIndex"])
            note["occurrenceId"] = f"{note['sourceNoteId']}@{note['occurrenceOrdinal']}"
        return {"notes": notes, "initialTempo": tempo_map[0]}
    except (ET.ParseError, KeyError, IndexError, TypeError, OverflowError, ZeroDivisionError) as error:
        raise ValueError("乐谱快照无法可靠规范化。") from error


def unavailable(reason):
    return {"eligible": False, "outcome": "unavailable", "reason": reason}


def interval_label(left, right):
    if left["partId"] != right["partId"] or left["voice"] != right["voice"] or left["staff"] != right["staff"]:
        return None
    distance = abs(int(right["octave"] * 7 + list(STEPS).index(right["step"]) - left["octave"] * 7 - list(STEPS).index(left["step"])))
    semitones = abs(right["writtenMidi"] - left["writtenMidi"])
    simple, octaves = distance % 7, distance // 7
    expected = [0, 2, 4, 5, 7, 9, 11][simple] + 12 * octaves
    diff = semitones - expected
    perfect = simple in {0, 3, 4}
    quality = ("纯" if perfect else "大") if diff == 0 else "小" if diff == -1 and not perfect else "增" if diff == 1 else "减" if diff == (-1 if perfect else -2) else None
    names = "零一二三四五六七八九"
    ordinal = distance + 1
    written_ordinal = names[ordinal] if ordinal < 10 else "十" + (names[ordinal % 10] if ordinal % 10 else "") if ordinal < 20 else names[ordinal // 10] + "十" + (names[ordinal % 10] if ordinal % 10 else "") if ordinal < 100 else str(ordinal)
    return {"label": f"{quality}{written_ordinal}度" if quality else f"{semitones:g}半音跨度", "diatonicSteps": ordinal, "semitones": semitones}


def normalize_performance(value, score_xml, score_sha, score_revision, mode):
    try:
        return _normalize_performance(value, score_xml, score_sha, score_revision, mode)
    except (TypeError, KeyError, IndexError, OverflowError, UnicodeError, ZeroDivisionError) as error:
        raise ValueError("演奏数据格式无效。") from error


def _normalize_performance(value, score_xml, score_sha, score_revision, mode):
    allowed = {"schemaVersion", "contract", "status", "source", "verifiedByServer", "takeId", "eventId", "sourceScoreSha256", "scoreRevision", "inputKind", "detectorVersion", "matcherVersion", "judgeRulesVersion", "normalizerVersion", "mode", "bpm", "tuning", "captureClock", "capabilities", "attempts", "expected", "actualEvents", "opportunities", "errors", "coverageByDimension", "uncertainty", "completed", "terminal", "performanceDurationMs", "recording"}
    derived_fields = {"snapshotValidatedByServer", "serverNormalizerVersion", "serverMetrics"}
    fields(value, allowed | derived_fields | {"instrument"}, allowed - {"recording", "verifiedByServer"})
    # Read-back objects may be replayed; their server fields are discarded and
    # recomputed from the immutable score and raw measurements on every write.
    value = {k: v for k, v in value.items() if k not in derived_fields}
    if len(canonical(value)) > 1024 * 1024:
        raise ValueError("演奏记录超过 1 MB。")
    if value["schemaVersion"] != 2 or value["contract"] != "notewise-history-1" or value["source"] != "client-reported" or value["status"] not in {"analysed", "uncertain"}:
        raise ValueError("演奏协议或来源无效。")
    if value["sourceScoreSha256"] != score_sha or hashlib.sha256(score_xml.encode()).hexdigest() != score_sha or value["scoreRevision"] != score_revision:
        raise ValueError("演奏记录与原始乐谱快照不一致。")
    number(value["scoreRevision"], 1, 1000000, True)
    if mode not in {"strict", "follow"} or value["mode"] not in {mode, "wait"} or value["inputKind"] not in {"midi", "microphone"}:
        raise ValueError("演奏模式无效。")
    for key in ("takeId", "eventId", "detectorVersion", "matcherVersion", "judgeRulesVersion", "normalizerVersion"):
        string(value[key])
    if value["takeId"] != value["eventId"]:
        raise ValueError("演奏身份冲突。")
    bpm, duration = number(value["bpm"], 20, 400), number(value["performanceDurationMs"])
    number(value["tuning"], 400, 480)
    boolean(value["completed"]); boolean(value["terminal"])
    for uncertainty in items(value["uncertainty"], 20000):
        fields(uncertainty, {"timeMs", "offsetMs", "reason"}, {"timeMs", "reason"})
        number(uncertainty["timeMs"], 0, duration); string(uncertainty["reason"], 300)
        if "offsetMs" in uncertainty:
            number(uncertainty["offsetMs"], uncertainty["timeMs"], duration)
    for error in items(value["errors"], 5000):
        fields(error, {"type", "kind", "opportunityId", "eventId", "attemptId", "noteId", "measure", "expectedMidi", "playedMidi", "cents", "confidence", "resolved"}, {"type", "kind", "attemptId"})
        if error["type"] not in {"wrong", "missed", "extra", "rhythm", "uncertain"}:
            raise ValueError("演奏错误类型无效。")
        for field in ("kind", "opportunityId", "eventId", "attemptId", "noteId"):
            if field in error:
                string(error[field], 512 if field == "opportunityId" else 160)
        for field, low, high in (("measure", 0, 100000), ("expectedMidi", 0, 127), ("playedMidi", 0, 127), ("cents", -1200, 1200), ("confidence", 0, 1)):
            if field in error:
                number(error[field], low, high)
        if "resolved" in error:
            boolean(error["resolved"])
    if "recording" in value:
        recording = value["recording"]
        fields(recording, {"takeId", "available", "mime", "durationMs", "sampleRate", "sampleCount", "size", "interrupted"}, {"takeId", "available"})
        if recording["takeId"] != value["takeId"]:
            raise ValueError("录音与演奏身份不一致。")
        boolean(recording["available"])
        if "mime" in recording and recording["mime"] != "audio/wav":
            raise ValueError("本机录音格式无效。")
        for key, low, high in (("durationMs", 0, 86400000), ("sampleRate", 0 if not recording["available"] else 8000, 192000), ("sampleCount", 0, 10**10), ("size", 0, 100*1024*1024)):
            if key in recording:
                number(recording[key], low, high)
        if "sampleRate" in recording and recording["sampleRate"] != 0 and recording["sampleRate"] < 8000:
            raise ValueError("本机录音采样率无效。")
        if "interrupted" in recording:
            boolean(recording["interrupted"])
    clock = value["captureClock"]
    fields(clock, {"source", "unit", "timingCalibrated", "phaseAnchor", "sampleRate"}, {"source", "unit", "timingCalibrated"})
    if clock["unit"] != "ms" or clock["source"] not in {"host-monotonic", "audio-sample"}:
        raise ValueError("演奏时钟无效。")
    boolean(clock["timingCalibrated"])
    if "sampleRate" in clock:
        number(clock["sampleRate"], 8000, 192000)
    caps = value["capabilities"]
    fields(caps, {"pitch", "onset", "duration", "intonation", "polyphony", "recording"}, {"pitch", "onset", "duration", "intonation", "polyphony", "recording"})
    for flag in caps.values():
        boolean(flag)
    attempts = {}
    for attempt in items(value["attempts"], 100):
        fields(attempt, {"attemptId", "startMs", "endMs", "interrupted"}, {"attemptId", "startMs", "endMs", "interrupted"})
        key = string(attempt["attemptId"])
        if key in attempts:
            raise ValueError("演奏尝试重复。")
        start = number(attempt["startMs"])
        if attempt["endMs"] is not None:
            number(attempt["endMs"], start, duration)
        boolean(attempt["interrupted"])
        attempts[key] = attempt
    timeline = score_timeline(score_xml)
    instrument = value.get("instrument")
    if instrument is not None:
        fields(instrument, {"profileId", "variant", "transpose", "source"}, {"profileId", "variant", "transpose", "source"})
        if instrument["source"] != "manual" or instrument["profileId"] not in INSTRUMENT_VARIANTS or instrument["variant"] not in INSTRUMENT_VARIANTS[instrument["profileId"]] or instrument["transpose"] != INSTRUMENT_VARIANTS[instrument["profileId"]][instrument["variant"]]:
            raise ValueError("手动乐器及移调选择与已声明配置不一致。")
        number(instrument["transpose"], -48, 48, True)
        for note in timeline["notes"]:
            if not note["transposeExplicit"]:
                note["transpose"] = instrument["transpose"]
                note["midi"] = note["writtenMidi"] + instrument["transpose"]
                number(note["midi"], 0, 127, True)
    authority = {n["occurrenceId"]: n for n in timeline["notes"]}
    expected = {}
    expected_fields = {"partId", "measureIndex", "noteIndex", "sourceNoteId", "occurrenceId", "occurrenceOrdinal", "midi", "writtenMidi", "step", "alter", "octave", "transpose", "voice", "staff", "startMs", "durationMs", "onsetBeat", "durationBeat"}
    for note in items(value["expected"], 10000):
        fields(note, expected_fields | {"transposeExplicit"}, expected_fields)
        key = string(note["occurrenceId"])
        truth = authority.get(key)
        if key in expected or truth is None:
            raise ValueError("音符不属于该乐谱路线，或演奏机会重复。")
        if "transposeExplicit" in note and boolean(note["transposeExplicit"]) != truth["transposeExplicit"]:
            raise ValueError("谱面移调来源与原谱不一致。")
        for field in expected_fields - {"startMs", "durationMs"}:
            if isinstance(truth[field], (int, float)):
                if not near(number(note[field], -1000000, 1000000), truth[field]):
                    raise ValueError("预期音符与原谱不一致。")
            elif note[field] != truth[field]:
                raise ValueError("预期声部或音名与原谱不一致。")
        number(note["startMs"]); number(note["durationMs"], .000001)
        expected[key] = note
    if not expected or not attempts:
        raise ValueError("缺少演奏评估范围。")
    expected_groups = defaultdict(list)
    onset_sizes = defaultdict(int)
    for note in expected.values():
        expected_groups[note["startMs"], note["midi"]].append(note)
        onset_sizes[note["startMs"]] += 1
    offset = min(authority[k]["startMs"] for k in expected)
    ratio = timeline["initialTempo"] / bpm
    for key, note in expected.items():
        if not near(note["startMs"], (authority[key]["startMs"] - offset) * ratio) or not near(note["durationMs"], authority[key]["durationMs"] * ratio):
            raise ValueError("预期时间映射与乐谱速度不一致。")
    events, attacks, releases, stable_pitch = {}, {}, {}, defaultdict(list)
    actual_fields = {"eventId", "type", "timeMs", "onsetMs", "offsetMs", "frequency", "sourceId", "midi", "channel", "velocity", "confidence", "timingConfidence", "cents", "centsEvidence", "releaseReliable", "reason", "sampleCount", "sampleRate"}
    for event in items(value["actualEvents"], 20000):
        fields(event, actual_fields, {"eventId", "type", "timeMs", "confidence", "timingConfidence"})
        event_id = string(event["eventId"], 128)
        if event["type"] not in {"on", "off", "update", "uncertainty"}:
            raise ValueError("实际演奏事件类型无效。")
        number(event["timeMs"], 0, duration); number(event["confidence"], 0, 1); number(event["timingConfidence"], 0, 1)
        if event["type"] != "uncertainty":
            number(event.get("midi"), 0, 127, True)
        for key, low, high in (("channel", 0, 15), ("velocity", 0, 127), ("cents", -1200, 1200), ("sampleCount", 0, 10**10), ("sampleRate", 8000, 192000), ("onsetMs", 0, duration), ("offsetMs", 0, duration), ("frequency", 0, 96000)):
            if key in event:
                number(event[key], low, high)
        if "sourceId" in event:
            number(event["sourceId"], 0, 2**32-1, True)
        if event["type"] == "uncertainty" and "offsetMs" in event:
            number(event["offsetMs"], event["timeMs"], duration)
        if "releaseReliable" in event:
            boolean(event["releaseReliable"])
        if "reason" in event and event["reason"] != "":
            string(event["reason"], 300)
        if "centsEvidence" in event and event["centsEvidence"] not in {"none", "continuous-mpm-yin", "coarse-basic-pitch-contour"}:
            raise ValueError("连续音准证据类型无效。")
        identity = event_id, event["type"], event["timeMs"]
        if identity in events:
            if events[identity] != event:
                raise ValueError("重复演奏事件内容冲突。")
            continue
        events[identity] = event
        if event["type"] == "on":
            if event_id in attacks:
                raise ValueError("起音事件身份重复。")
            attacks[event_id] = event
        elif event["type"] == "off":
            if event_id in releases:
                raise ValueError("释放事件身份重复。")
            releases[event_id] = event
        if event["type"] in {"on", "update"} and event.get("centsEvidence") == "continuous-mpm-yin" and "cents" in event and event["confidence"] >= .95:
            stable_pitch[event_id].append(event)
    for event_id, release in releases.items():
        attack = attacks.get(event_id)
        if attack is None or attack["midi"] != release["midi"] or attack["timeMs"] > release["timeMs"] or attack.get("sourceId") != release.get("sourceId") or attack.get("channel") != release.get("channel"):
            raise ValueError("释放与起音关系无效。")
    for event_id, samples in list(stable_pitch.items()):
        attack, release = attacks.get(event_id), releases.get(event_id)
        stable_pitch[event_id] = [event for event in samples if attack and event["midi"] == attack["midi"] and event["timeMs"] >= attack["timeMs"] and (release is None or event["timeMs"] <= release["timeMs"])]
    normalized, used, opportunity_keys, entered_groups = [], {}, set(), defaultdict(set)
    # Basic Pitch emits neural activation strength, not calibrated probability.
    # Its official decoding threshold is distinct from real-time pitch confidence.
    pitch_threshold = .5 if value["detectorVersion"] == "basic-pitch-coreml-0.4.0" else .9
    opportunity_fields = {"opportunityId", "attemptId", "occurrenceId", "sourceNoteIds", "expectedMidi", "entered", "terminal", "completed", "evaluated", "outcome", "actualEventIds", "dimensions", "partId", "measureIndex", "noteIndex", "voice", "staff", "onsetBeat", "durationBeat", "firstTryCorrect"}
    # One phase anchor per take removes only constant capture offset; no latency claim.
    phase_event = attacks.get(clock.get("phaseAnchor"))
    phases = {}
    source_opportunities = items(value["opportunities"], 10000)
    if phase_event:
        anchors = [o for o in source_opportunities if phase_event["eventId"] in o.get("actualEventIds", []) and o.get("expectedMidi") == phase_event["midi"]]
        if len(anchors) == 1 and anchors[0].get("occurrenceId") in expected:
            phases[anchors[0].get("attemptId")] = phase_event["timeMs"] - expected[anchors[0]["occurrenceId"]]["startMs"]
    # Restarted attempts have their own origin on the same capture clock.
    for attempt_id in attempts:
        if attempt_id in phases:
            continue
        candidates = []
        for op in source_opportunities:
            note = expected.get(op.get("occurrenceId"))
            if note is None or op.get("attemptId") != attempt_id:
                continue
            for event_id in op.get("actualEventIds", []):
                event = attacks.get(event_id)
                if event and event["midi"] == note["midi"] and event["confidence"] >= pitch_threshold and event["timingConfidence"] >= .9:
                    candidates.append((event["timeMs"], event["timeMs"] - note["startMs"]))
        if candidates:
            phases[attempt_id] = min(candidates)[1]
    for opportunity in source_opportunities:
        fields(opportunity, opportunity_fields, opportunity_fields)
        op = deepcopy(opportunity)
        key, attempt_id = string(op["opportunityId"], 512), string(op["attemptId"])
        note = expected.get(op["occurrenceId"])
        if note is None or attempt_id not in attempts or key in opportunity_keys or op["expectedMidi"] != note["midi"]:
            raise ValueError("演奏机会身份与乐谱不一致。")
        opportunity_keys.add(key)
        phase = phases.get(attempt_id)
        for field in ("entered", "terminal", "completed", "evaluated", "firstTryCorrect"):
            boolean(op[field])
        source_notes = items(op["sourceNoteIds"], 256)
        if not source_notes or len(set(source_notes)) != len(source_notes):
            raise ValueError("演奏机会音符重复。")
        group = expected_groups[note["startMs"], note["midi"]]
        if set(source_notes) != {n["sourceNoteId"] for n in group}:
            raise ValueError("同起音同音高的谱面音符必须合并为一次机会。")
        group_key = attempt_id, note["startMs"], note["midi"]
        if group_key in entered_groups[attempt_id]:
            raise ValueError("同一次演奏机会重复。")
        entered_groups[attempt_id].add(group_key)
        event_ids = items(op["actualEventIds"], 10000)
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("演奏机会实际事件重复。")
        matched = []
        for event_id in event_ids:
            event = attacks.get(event_id)
            if event is None or event_id in used:
                raise ValueError("实际起音不存在或重复匹配。")
            used[event_id] = key
            attempt = attempts[attempt_id]
            if not attempt["startMs"] <= event["timeMs"] <= (attempt["endMs"] if attempt["endMs"] is not None else duration):
                raise ValueError("实际起音超出演奏尝试范围。")
            matched.append(event)
        matched.sort(key=lambda e: e["timeMs"])
        dimensions = {d: unavailable("该维度没有可靠评估证据") for d in DIMENSIONS}
        reliable = [e for e in matched if e["confidence"] >= pitch_threshold and e["timingConfidence"] >= .5]
        right = next((e for e in reliable if e["midi"] == note["midi"]), None)
        wrong = any(e["midi"] != note["midi"] for e in reliable)
        if not op["entered"]:
            if matched or op["completed"]:
                raise ValueError("未进入的机会不能包含演奏结果。")
            outcome = "pending"
        elif not op["terminal"] or matched and not reliable:
            outcome = "pending"
            dimensions["pitch"] = {"eligible": True, "outcome": "pending", "reason": "输入不可靠或机会尚未结束"}
        elif wrong:
            outcome = "wrong"
            dimensions["pitch"] = {"eligible": True, "outcome": "wrong"}
        elif right:
            outcome = "correct"
            dimensions["pitch"] = {"eligible": True, "outcome": "correct"}
        else:
            # Absence is never conclusive across interruption, noise or mic chords.
            target = note["startMs"] + (phase if phase is not None else attempts[attempt_id]["startMs"])
            uncertain_intervals = value["uncertainty"] + [e for e in value["actualEvents"] if e["type"] == "uncertainty"]
            overlap = any(e["timeMs"] <= target + note["durationMs"] + 500 and e.get("offsetMs", e["timeMs"]) >= target - 500 for e in uncertain_intervals)
            ambiguous = attempts[attempt_id]["interrupted"] or op["outcome"] == "pending" or overlap or value["inputKind"] == "microphone" and onset_sizes[note["startMs"]] > 1 and not caps["polyphony"]
            outcome = "pending" if ambiguous else "missed"
            dimensions["pitch"] = {"eligible": True, "outcome": "pending" if ambiguous else "wrong", **({"reason": "漏音证据不足"} if ambiguous else {})}
        if not caps["pitch"]:
            dimensions["pitch"] = unavailable("检测器未声明音高评估能力")
            outcome = "pending"
        if right is not None and mode == "strict" and right["timingConfidence"] >= .9 and phase is not None and caps["onset"] and not attempts[attempt_id]["interrupted"]:
            error = right["timeMs"] - note["startMs"] - phase
            dimensions["onset"] = {"eligible": True, "outcome": "wrong" if abs(error) > max(120, 60000 / bpm * .2) else "correct", "error": error}
        release = releases.get(right["eventId"]) if right else None
        if release and mode == "strict" and caps["duration"] and release.get("releaseReliable") is True and right["timingConfidence"] >= .9 and release["timingConfidence"] >= .9 and not attempts[attempt_id]["interrupted"]:
            error = release["timeMs"] - right["timeMs"] - note["durationMs"]
            dimensions["duration"] = {"eligible": True, "outcome": "wrong" if abs(error) > max(160, note["durationMs"] * .3) else "correct", "error": error}
        samples = stable_pitch.get(right["eventId"], []) if right else []
        if value["inputKind"] == "microphone" and caps["intonation"] and len(samples) >= 3 and max(e["timeMs"] for e in samples) - min(e["timeMs"] for e in samples) >= 100:
            error = median(e["cents"] for e in samples)
            dimensions["intonation"] = {"eligible": True, "outcome": "wrong" if abs(error) > 35 else "correct", "error": error}
        op.update(dimensions=dimensions, outcome=outcome, evaluated=dimensions["pitch"]["outcome"] in {"correct", "wrong"}, firstTryCorrect=outcome == "correct", completed=right is not None,
                  partId=note["partId"], measureIndex=note["measureIndex"], noteIndex=note["noteIndex"],
                  voice=note["voice"] if len(group) == 1 else "unknown", staff=note["staff"] if len(group) == 1 else "unknown", onsetBeat=note["onsetBeat"], durationBeat=note["durationBeat"])
        normalized.append(op)
    # Every selected expected pitch has exactly one opportunity in each attempt.
    required_groups = {(n["startMs"], n["midi"]) for n in expected.values()}
    for attempt_id in attempts:
        if {(k[1], k[2]) for k in entered_groups[attempt_id]} != required_groups:
            raise ValueError("演奏评估范围遗漏机会。")
    coverage = {}
    for dimension in DIMENSIONS:
        selected = [o["dimensions"][dimension] for o in normalized if o["dimensions"][dimension]["eligible"]]
        coverage[dimension] = {"eligible": len(selected), "evaluated": sum(d["outcome"] in {"correct", "wrong"} for d in selected), "failed": sum(d["outcome"] == "wrong" for d in selected), "pending": sum(d["outcome"] == "pending" for d in selected)}
    intervals, tempo_samples = [], []
    for attempt_id in attempts:
        by_voice = defaultdict(list)
        for op in normalized:
            if op["attemptId"] == attempt_id and op["entered"]:
                note = expected[op["occurrenceId"]]
                if len(op["sourceNoteIds"]) == 1:
                    by_voice[note["partId"], note["staff"], note["voice"]].append((note, op))
        for voice in by_voice.values():
            voice.sort(key=lambda v: (v[0]["onsetBeat"], v[0]["midi"]))
            for (left, _), (right_note, op) in zip(voice, voice[1:]):
                if near(left["onsetBeat"], right_note["onsetBeat"]):
                    continue
                label = interval_label(left, right_note)
                if label and op["dimensions"]["pitch"]["eligible"]:
                    intervals.append({**label, "opportunityId": op["opportunityId"], "outcome": op["dimensions"]["pitch"]["outcome"]})
        anchors = {}
        for op in normalized:
            if op["attemptId"] != attempt_id or not op["evaluated"]:
                continue
            note = expected[op["occurrenceId"]]
            found = [attacks[eid] for eid in op["actualEventIds"] if attacks[eid]["midi"] == note["midi"] and attacks[eid]["confidence"] >= pitch_threshold and attacks[eid]["timingConfidence"] >= .9]
            if found:
                anchors.setdefault(note["onsetBeat"], []).append(found[0]["timeMs"])
        ordered = sorted((beat, median(times)) for beat, times in anchors.items())
        if len(ordered) >= RULES["minTempoAnchors"]:
            for (beat, at), (next_beat, next_at) in zip(ordered, ordered[1:]):
                if next_at > at and next_beat > beat:
                    tempo = 60000 * (next_beat - beat) / (next_at - at)
                    if 20 <= tempo <= 400:
                        tempo_samples.append(tempo)
    tempo = median(tempo_samples) if len(tempo_samples) >= 2 else None
    spread = median(abs(v - tempo) for v in tempo_samples) / tempo if tempo else None
    if spread is not None and spread > .35:
        tempo = None
    result = deepcopy(value)
    result.update(opportunities=normalized, actualEvents=list(events.values()), coverageByDimension=coverage,
                  verifiedByServer=False, snapshotValidatedByServer=True, serverNormalizerVersion=VERSION,
                  status="uncertain" if any(c["pending"] for c in coverage.values()) else "analysed")
    result["serverMetrics"] = {"coverageByDimension": coverage,
        "selectedOpportunities": len(normalized), "enteredOpportunities": sum(o["entered"] for o in normalized),
        "unplayedOpportunities": sum(not o["entered"] for o in normalized),
        "actualTempoQuarterBpm": round(tempo, 2) if tempo else None,
        "actualTempoSampleCount": len(tempo_samples), "tempoRelativeDispersion": spread,
        "intervals": intervals, "unmatchedReliableAttacks": sum(eid not in used and event["confidence"] >= pitch_threshold for eid, event in attacks.items()),
        "measurementSource": "client-reported", "rulesVersion": RULES["version"]}
    # Teacher-facing error locators use the same deduplicated denominators.
    errors = []
    for op in normalized:
        for dimension in DIMENSIONS:
            judged = op["dimensions"][dimension]
            if judged["outcome"] not in {"wrong", "pending"}:
                continue
            pending = judged["outcome"] == "pending"
            kind = "pending-" + dimension if pending else "missing" if dimension == "pitch" and op["outcome"] == "missed" else dimension
            errors.append({"type": "uncertain" if pending else "missed" if kind == "missing" else "rhythm" if dimension in {"onset", "duration"} else "wrong", "kind": kind, "attemptId": op["attemptId"], "opportunityId": op["opportunityId"], "noteId": op["sourceNoteIds"][0], "measure": op["measureIndex"]+1, "expectedMidi": op["expectedMidi"], **({"cents": judged["error"]} if dimension == "intonation" and "error" in judged else {})})
    for event_id, event in attacks.items():
        if event_id not in used and event["confidence"] >= pitch_threshold:
            errors.append({"type": "extra", "kind": "unmatched-attack", "attemptId": next((a["attemptId"] for a in attempts.values() if a["startMs"] <= event["timeMs"] <= (a["endMs"] if a["endMs"] is not None else duration)), next(iter(attempts))), "eventId": event_id, "playedMidi": event["midi"], "confidence": event["confidence"]})
    result["errors"] = errors
    return result


def aggregate_music(rows, records, evidence, facts, scope, source_hash, aggregate_version):
    """Aggregate all selected validated snapshots before bounded fact selection."""
    analyzed = [(row, record, record.get("analysis") or {}) for row, record in zip(rows, records)
                if (record.get("analysis") or {}).get("snapshotValidatedByServer") is True
                and (record.get("analysis") or {}).get("serverNormalizerVersion") == VERSION]
    if not analyzed:
        return None
    counts = {d: {"eligible": 0, "evaluated": 0, "failed": 0, "pending": 0} for d in DIMENSIONS}
    references, interval_buckets, location_buckets, voices, comparison, tempos = [], defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list), []
    unplayed, selected, extras = 0, 0, 0
    for row, record, analysis in analyzed:
        ref = {"eventId": row["event_id"], "analysisVersion": row.get("analysis_version", 0), "analysisHash": row.get("analysis_hash"), "sourceContentHash": hashlib.sha256(canonical(analysis)).hexdigest(), "scoreSha256": row["score_sha256"], "scoreRevision": row["score_revision"], "field": "/analysis/serverMetrics", "normalizerVersion": VERSION}
        references.append(ref)
        metrics = analysis["serverMetrics"]
        selected += metrics["selectedOpportunities"]
        unplayed += metrics["unplayedOpportunities"]
        extras += metrics["unmatchedReliableAttacks"]
        for d in DIMENSIONS:
            for k in counts[d]:
                counts[d][k] += metrics["coverageByDimension"][d][k]
        opportunities = {o["opportunityId"]: o for o in analysis["opportunities"]}
        for interval in metrics["intervals"]:
            if interval["outcome"] in {"correct", "wrong", "pending"}:
                interval_buckets[interval["label"]].append((interval["outcome"], {**ref, "opportunityId": interval["opportunityId"]}))
        for op in opportunities.values():
            if op["dimensions"]["pitch"]["eligible"]:
                entry = op["dimensions"]["pitch"]["outcome"], {**ref, "opportunityId": op["opportunityId"]}
                location_buckets[row["score_sha256"], op["measureIndex"]].append(entry)
                voices[row["score_sha256"], op["partId"], op["staff"], op["voice"]].append(entry)
        actual_tempo = metrics["actualTempoQuarterBpm"]
        if actual_tempo is not None:
            tempos.append((actual_tempo, ref))
            # Comparable only in this identical score/scope/input/rules and
            # measured tempo band. No cross-piece difficulty assumptions.
            scope_signature = sorted((o["occurrenceId"], o["expectedMidi"]) for o in opportunities.values())
            key = (row["score_sha256"], hashlib.sha256(canonical(scope_signature)).hexdigest(), analysis["mode"], analysis["inputKind"], analysis["detectorVersion"], analysis["matcherVersion"], analysis["judgeRulesVersion"], clock_kind(analysis), hashlib.sha256(canonical(analysis.get("instrument"))).hexdigest(), analysis["tuning"], int(actual_tempo // 10))
            comparison[key].append((record["startedAt"], record["eventId"], metrics["coverageByDimension"], ref))

    def add(key, kind, dimension, label, statement, display, refs, state="verified_fact", limits=()):
        evidence_key = "evidence-music-" + key + "-" + source_hash[:16]
        # Evidence holds original locators; bounded fact never hides raw notes.
        evidence[evidence_key] = {"aggregationVersion": aggregate_version, "sourceSnapshotId": source_hash, "events": refs}
        facts.append({"factId": "music-" + key, "kind": kind, "dimension": dimension,
                      "label": label, "statement": statement, "displayValue": display,
                      "claimState": state, "scope": scope["description"],
                      "confidence": "medium" if state == "verified_fact" else "low" if state == "provisional_pattern" else "unknown",
                      "evidenceRefs": [evidence_key], "limitations": list(limits)})

    evaluated = sum(c["evaluated"] for c in counts.values())
    add("coverage", "data_quality", "other", "本次实际评估范围",
        f"当前范围有 {len(analyzed)} 条原谱快照匹配的演奏记录，共 {selected} 次选定机会；其中 {unplayed} 次未进入演奏范围，未计作漏音。各维度分别使用已评估机会作分母。",
        f"{len(analyzed)} 条记录；{selected} 次机会", references,
        limits=["实际声音和 MIDI 来自客户端；服务端核对原谱及事件关系，不证明测量或演奏者身份。", "未进入、待复核及不具备证据的维度不按正确或错误统计。"])
    labels = {"pitch": ("音高", "other"), "onset": ("相对起音节奏", "rhythm"), "duration": ("音符时值", "rhythm"), "intonation": ("连续音准", "other")}
    for d in DIMENSIONS:
        c, (label, dimension) = counts[d], labels[d]
        if c["evaluated"]:
            correct = c["evaluated"] - c["failed"]
            rate = round(100 * c["failed"] / c["evaluated"], 1)
            add(d + "-coverage", "performance_observation", dimension, label + "样本结果",
                f"当前样本中，{label}已评估 {c['evaluated']} 次，其中明确正确 {correct} 次、错误 {c['failed']} 次，错误占比 {rate:g}%；另有 {c['pending']} 次待复核。",
                f"{correct}/{c['evaluated']} 次正确；{rate:g}% 错误", references,
                "provisional_pattern", ["此结论仅针对已评估样本；不把待复核机会当作零错误。", "相对起音已移除常量采集延迟，未校准绝对声音延迟。"] if d == "onset" else ["此结论仅针对该维度的已评估样本；不代表整谱或其他技术维度。"])
        else:
            add(d + "-unavailable", "unavailable", dimension, label + "证据不足",
                f"当前样本没有可确认的{label}评估机会，该维度保持未知。", None, references, "unavailable",
                ["MIDI没有连续音准证据；自由跟谱不按目标速度评价起音和时值。"])
    pending = sum(c["pending"] for c in counts.values())
    if pending:
        add("pending", "pending_review", "other", "演奏证据待复核",
            f"各维度合计 {pending} 项评估待复核；同一机会可能涉及多个维度，此数不作为错音数。", f"{pending} 项维度评估", references, "pending_review")
    if extras:
        add("extra-attacks", "performance_observation", "other", "未匹配起音",
            f"当前样本存在 {extras} 个高置信度起音未绑定原谱机会，需核对是否多弹、重弹或检测误差。", f"{extras} 个起音", references, "provisional_pattern")
    if tempos:
        low, high = min(t[0] for t in tempos), max(t[0] for t in tempos)
        add("measured-tempo", "performance_observation", "tempo", "实际起音提取速度",
            f"当前 {len(tempos)} 条记录可从多个不同谱面起音位置提取实际速度，中位速度范围为 {low:g}–{high:g} BPM（四分音符单位）；不是设置的目标速度。",
            f"{low:g}–{high:g} BPM", [v[1] for v in tempos], "provisional_pattern",
            ["速度来自已匹配起音；停顿、重弹和低覆盖范围会限制可比性。"])
    else:
        add("tempo-unavailable", "unavailable", "tempo", "实际速度暂不可判定",
            "当前演奏缺少足够可靠且不同的起音位置，不能用目标速度或练习时长代替实际速度。", None, references, "unavailable")

    # All buckets were counted above. Only four largest sample buckets of each
    # class enter the bounded model input; ranking is by denominator, not errors.
    for label, entries in sorted(interval_buckets.items(), key=lambda item: (-len(item[1]), item[0]))[:4]:
        known = [entry for entry in entries if entry[0] != "pending"]
        if not known:
            continue
        failed = sum(entry[0] == "wrong" for entry in known)
        key = "interval-" + hashlib.sha256(label.encode()).hexdigest()[:12]
        add(key, "performance_observation", "interval", "原谱音程样本",
            f"当前原谱拼写产生的{label}转换有 {len(known)} 次已评估机会，其中错误 {failed} 次；不据次数判定它是最弱音程。",
            f"{label}：{failed}/{len(known)} 次错误", [entry[1] for entry in entries], "provisional_pattern")
    for ordinal, ((score_hash, measure), entries) in enumerate(sorted(location_buckets.items(), key=lambda item: (-len(item[1]), item[0]))[:3], 1):
        known = [entry for entry in entries if entry[0] != "pending"]
        if known:
            failed = sum(entry[0] == "wrong" for entry in known)
            add(f"location-{ordinal}", "performance_observation", "location", "原谱小节范围样本",
                f"所选乐谱范围 {ordinal} 的第 {measure + 1} 小节已评估 {len(known)} 次音高机会，其中正确 {len(known)-failed} 次、错误 {failed} 次。",
                f"第 {measure+1} 小节：{failed}/{len(known)} 次错误", [entry[1] for entry in entries], "provisional_pattern", ["只比较该乐谱版本的小节，不合并不同曲谱同号小节。"])
    for ordinal, (_, entries) in enumerate(sorted(voices.items(), key=lambda item: (-len(item[1]), item[0]))[:2], 1):
        known = [entry for entry in entries if entry[0] != "pending"]
        if known:
            failed = sum(entry[0] == "wrong" for entry in known)
            add(f"voice-{ordinal}", "performance_observation", "hand_voice", "原谱声部范围样本",
                f"原谱声部范围 {ordinal} 已评估 {len(known)} 次音高机会，其中错误 {failed} 次；谱面声部不自动推断为左手或右手。",
                f"声部范围 {ordinal}：{failed}/{len(known)} 次错误", [entry[1] for entry in entries], "provisional_pattern")

    capability_claims, progress_claims = [], []
    for key, takes in sorted(comparison.items(), key=lambda item: repr(item[0])):
        takes.sort(key=lambda v: (v[0], v[1]))
        days = {v[0][:10] for v in takes}
        if len(takes) < RULES["minTakes"] or len(days) < RULES["minDays"]:
            continue
        for d in DIMENSIONS:
            total = {name: sum(v[2][d][name] for v in takes) for name in counts[d]}
            coverage = total["evaluated"] / total["eligible"] if total["eligible"] else 0
            if total["evaluated"] < RULES["minOpportunities"] or coverage < RULES["minCoverage"]:
                continue
            rate = total["failed"] / total["evaluated"]
            kind = "strength" if rate <= RULES["strengthMaxFailureRate"] else "weakness" if rate >= RULES["weaknessMinFailureRate"] else None
            if kind:
                capability_claims.append((kind, d, total, takes, rate))
            # Separate earlier/later windows; both must satisfy sample coverage.
            split = len(takes) // 2
            earlier, later = takes[:split], takes[split:]
            windows = [{name: sum(v[2][d][name] for v in window) for name in counts[d]} for window in (earlier, later)]
            if all(w["evaluated"] >= RULES["minOpportunities"] and w["eligible"] and w["evaluated"] / w["eligible"] >= RULES["minCoverage"] for w in windows) and earlier[-1][0][:10] < later[0][0][:10]:
                before, after = (w["failed"] / w["evaluated"] for w in windows)
                if before - after >= RULES["progressMinDifference"]:
                    progress_claims.append((d, before, after, takes))
    for ordinal, (kind, d, total, takes, rate) in enumerate(capability_claims[:4], 1):
        label = labels[d][0]
        add(f"capability-{ordinal}", kind, "consistency", label + ("范围内稳定表现" if kind == "strength" else "范围内反复问题"),
            f"按固定规则，该相同原谱、范围、输入和实际速度档的{label}有 {len(takes)} 次练习、{total['evaluated']} 次已评估机会，错误占比 {rate*100:g}%，满足本范围的{'稳定表现' if kind == 'strength' else '反复问题'}门槛。",
            f"{rate*100:g}% 错误；{total['evaluated']} 次机会", [v[3] for v in takes], limits=["仅为固定规则对可比范围的分类；不推广到其他曲目、速度、演奏者身份或全局能力。"])
    for ordinal, (d, before, after, takes) in enumerate(progress_claims[:2], 1):
        add(f"progress-{ordinal}", "progress", "consistency", "可比范围的样本变化",
            f"该可比范围的{labels[d][0]}错误占比从早期窗口 {before*100:g}% 降为后期窗口 {after*100:g}%，两个窗口均满足固定覆盖及样本门槛。",
            f"{before*100:g}% → {after*100:g}%", [v[3] for v in takes], limits=["此为相同曲谱、范围、检测规则及实际速度档的窗口变化；不说明因果或跨曲能力。"])
    add("tags-unavailable", "unavailable", "technique", "曲目类型和技巧标签未声明",
        "当前原谱快照未声明经确认的曲目类型或技巧标签，未从曲名、时长、错音或模型推断技巧分类。", None, references, "unavailable")
    return {"version": VERSION, "claimRules": RULES, "recordCount": len(analyzed),
            "coverageByDimension": counts, "evaluatedDimensionOpportunities": evaluated,
            "selectedOpportunities": selected, "unplayedOpportunities": unplayed,
            "actualTempoRecords": len(tempos), "stableCapabilityRulesSatisfied": bool(capability_claims),
            "progressRulesSatisfied": bool(progress_claims), "intervalBuckets": {key: {"evaluated": sum(e[0] != "pending" for e in entries), "failed": sum(e[0] == "wrong" for e in entries), "pending": sum(e[0] == "pending" for e in entries)} for key, entries in interval_buckets.items()},
            "locationBucketCount": len(location_buckets), "voiceBucketCount": len(voices)}


def clock_kind(analysis):
    clock = analysis["captureClock"]
    return clock["source"], clock["timingCalibrated"], clock.get("sampleRate")
