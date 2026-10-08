"""Partitura score normalization and genuine offline alignment baselines."""
from collections import defaultdict
import io
import json
import math
import re
from pathlib import Path
import subprocess
import tempfile
import warnings
import zipfile


VARIANTS = {
    "clarinet": {"bb": -2, "a": -3, "eb": 3, "concert": 0},
    "horn": {"f": -7, "bb": -2, "concert": 0},
    "trumpet": {"bb": -2, "concert": 0},
    "contrabass": {"octave": -12, "concert": 0},
    "euphonium": {"bass": 0, "bb-treble": -14},
}

# Qualified names precede broad family terms, as in the existing UI resolver.
NAMES = [(r"harpsichord|羽管键琴|大键琴","harpsichord"),(r"english horn|cor anglais|英国管","english-horn"),
         (r"electric bass|acoustic bass|bass guitar|^bass$|贝斯","bass"),(r"organ|管风琴","organ"),
         (r"accordion|手风琴","accordion"),(r"harmonica|口琴","harmonica"),(r"piccolo|短笛","piccolo"),
         (r"recorder|竖笛","recorder"),(r"guitar|吉他","guitar"),(r"sax|萨克斯","sax"),
         (r"二胡|erhu","erhu"),(r"古筝|guzheng","guzheng"),(r"琵琶|pipa","pipa"),(r"古琴|guqin","guqin"),(r"唢呐|suona","suona"),
         (r"piano|keyboard|钢琴|电子琴|键盘|^pno\.?$|^pf\.?$","piano"),
         (r"contrabass|double bass|低音提琴|^cb\.?$","contrabass"),(r"violin|小提琴|^vln?\.?$","violin"),
         (r"viola|中提琴|^vla\.?$","viola"),(r"cello|violoncello|大提琴|^vc\.?$","cello"),
         (r"\bharp\b|竖琴|^hp\.?$","harp"),(r"flute|长笛|笛子|^fl\.?$","flute"),
         (r"clarinet|单簧管|^cl\.?$","clarinet"),(r"bassoon|巴松|大管|^bsn\.?$|^fg\.?$","bassoon"),
         (r"oboe|双簧管|^ob\.?$","oboe"),(r"euphonium|次中音号|上低音号|^euph\.?$","euphonium"),
         (r"trumpet|小号|^tpt\.?$|^trp\.?$","trumpet"),(r"trombone|长号|^tbn\.?$","trombone"),
         (r"tuba|大号|^tba\.?$","tuba"),(r"\bhorn\b|圆号|法国号|^hn\.?$|^cor\.?$","horn"),
         (r"voice|vocal|soprano|mezzo|contralto|baritone|tenor|choir|声乐|人声|合唱","voice")]


def name_profile(name):
    return next((instrument for pattern,instrument in NAMES if re.search(pattern,str(name),re.I)), None)


def part_instrument(tree, part, options):
    meta = options.get("metadata", {})
    evidence = meta.get("parts", {})
    provenance = evidence.get(part.id, {}) if isinstance(evidence,dict) else next((p for p in evidence if isinstance(p,dict) and p.get("id") == part.id),{})
    if not isinstance(provenance,dict): provenance = {}
    choice = options.get("byPart", {}).get(part.id, {})
    selected = choice.get("instrument", options.get("instrument", "auto") if options.get("part","all") in ("all",part.id) else "auto")
    variant = choice.get("variant", options.get("variant", "concert"))
    origin = provenance.get("origin",meta.get("origin","score"))
    if selected not in ("auto", "", None):
        return {"id":part.id,"label":part.part_name or part.id,"instrument":selected,"variant":variant,
                "reliable":True,"provenance":"manual","metadata":provenance}
    result = {"id":part.id,"label":part.part_name or part.id,"instrument":"auto","variant":"concert",
              "reliable":False,"provenance":origin,"metadata":provenance}
    # OMR's playback-default piano is not evidence about the photographed part.
    if provenance.get("confirmed") is False or provenance.get("instrumentConfirmed") is False:
        return result
    score_part = next((p for p in tree.findall("part-list/score-part") if p.get("id") == part.id),None)
    heading = score_part.findtext("part-name",part.part_name or "") if score_part is not None else part.part_name or ""
    score_names = [p.findtext("instrument-name","") for p in score_part.findall("score-instrument")] if score_part is not None else []
    score_names += provenance.get("instrumentNames",[]) or []
    named_part = name_profile(heading)
    names = ([heading]+score_names) if named_part and named_part not in ("piano","voice") else (score_names+[heading])
    names += [provenance.get("name",""),provenance.get("abbreviation","")]
    if score_part is not None:
        names += [score_part.findtext("part-abbreviation","")]+[p.findtext("instrument-abbreviation","") for p in score_part.findall("score-instrument")]
    for name in names:
        inferred = name_profile(name)
        if inferred:
            return result|{"instrument":inferred,"reliable":True,"provenance":"score-name","metadataName":name}
    program_text = score_part.findtext("midi-instrument/midi-program") if score_part is not None else None
    program = int(program_text) if program_text else int(provenance.get("program",0) or 0)
    explicit = program_text is not None or provenance.get("programExplicit",program>0)
    programs = {23:"harmonica",41:"violin",42:"viola",43:"cello",44:"contrabass",47:"harp",57:"trumpet",58:"trombone",59:"tuba",61:"horn",69:"oboe",70:"english-horn",71:"bassoon",72:"clarinet",73:"piccolo",74:"flute",75:"recorder"}
    inferred = programs.get(program)
    for lo,hi,instrument in [(1,8,"piano"),(17,24,"organ"),(25,32,"guitar"),(33,40,"bass"),(53,55,"voice"),(57,64,"brass"),(65,68,"sax"),(73,80,"flute")]:
        if inferred is None and lo <= program <= hi: inferred = instrument
    unknown_name = any(str(n).strip() and not re.fullmatch(r"(?:part|staff|instrument|unknown|unnamed|声部|乐器|未命名|未标明)(?:\s*\d+)?",str(n).strip(),re.I) for n in names)
    if explicit and inferred and (program != 1 or not unknown_name):
        result.update(instrument=inferred,reliable=True,provenance="score-midi-program")
    return result


def manual_transpose(part, options):
    values = options.get("byPart", {}).get(part, {})
    if not values:
        values = next((p for p in options.get("instrumentOptions", []) if p.get("partId", p.get("part")) == part), {})
    if not values and options.get("part", "all") in ("all", part):
        values = options
    explicit = options.get("transpositions", {}).get(part, values.get("transposeSemitones"))
    if explicit is not None:
        amount = float(explicit)
        if amount != round(amount) or not -48 <= amount <= 48:
            raise ValueError("Invalid manual transposition")
        return int(amount)
    instrument = values.get("instrument", values.get("instrumentId", ""))
    variant = values.get("variant", "concert")
    if instrument in VARIANTS:
        return VARIANTS[instrument].get(variant, 0)
    return 0


def xml_document(data):
    from lxml import etree
    if len(data) > 15*1024*1024:
        raise ValueError("MusicXML exceeds 15 MB")
    if data.startswith(b"PK"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if len(archive.infolist()) > 64:
                raise ValueError("MXL archive has too many files")
            container = etree.fromstring(archive.read("META-INF/container.xml"),
                                        etree.XMLParser(resolve_entities=False, no_network=True))
            roots = container.xpath("//*[local-name()='rootfile']/@full-path")
            if not roots or roots[0] not in archive.namelist():
                raise ValueError("MXL has no MusicXML root file")
            member = archive.getinfo(roots[0])
            if member.file_size > 30*1024*1024:
                raise ValueError("MXL expanded score is too large")
            data = archive.read(member)
    tree = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
    if tree.tag.rsplit("}", 1)[-1] != "score-partwise":
        raise ValueError("Partitura normalization requires score-partwise MusicXML")
    for element in tree.iter():
        if isinstance(element.tag, str):
            element.tag = element.tag.rsplit("}", 1)[-1]
    return tree


def normalize(data: bytes, options: dict):
    first_measure = integer_field(options.get("from", 1), "from", 1, 2147483647)
    last_measure = integer_field(options.get("to", 2147483647), "to", first_measure, 2147483647)
    import partitura
    from partitura import score as ps
    from lxml import etree
    tree = xml_document(data)
    source, original_parts = {}, {}
    notes_total = 0
    for pi, part in enumerate(tree.findall("part")):
        part_id = part.get("id", f"P{pi+1}")
        transpose, transpose_explicit, staff_transpose, beat_type = 0, False, {}, 4
        ordinal, measures = 0, []
        for mi, measure in enumerate(part.findall("measure")):
            label = measure.get("number", str(mi+1)); measures.append(label)
            for item in measure:
                if item.tag == "attributes":
                    beat_type = int(item.findtext("time/beat-type", str(beat_type)))
                    for trans in item.findall("transpose"):
                        semitones = int(trans.findtext("chromatic", "0"))+12*int(trans.findtext("octave-change", "0"))
                        if trans.get("number"):
                            staff_transpose[trans.get("number")] = semitones
                        else:
                            transpose, transpose_explicit, staff_transpose = semitones, True, {}
                elif item.tag == "note":
                    sid = f"nl_{pi}_{ordinal}"
                    item.set("id", sid)
                    staff = item.findtext("staff", "1")
                    source[sid] = {"id": f"{part_id}:{ordinal}", "part": part_id, "xmlIndex": ordinal,
                                   "mi": mi, "measure": label, "beatType": beat_type,
                                   "transposeSemitones": staff_transpose.get(staff, transpose),
                                   "transposeExplicit": staff in staff_transpose or transpose_explicit}
                    ordinal += 1; notes_total += 1
            if notes_total > 20000:
                raise ValueError("MusicXML exceeds 20000 source notes")
        original_parts[part_id] = measures
    with warnings.catch_warnings(record=True) as caught:
        loaded = partitura.load_musicxml(io.BytesIO(etree.tostring(tree)), force_note_ids="keep", quiet=True)
        if options.get("expandRepeats", True):
            loaded = ps.unfold_part_maximal(loaded, update_ids=False, ignore_leaps=False)
    messages = list(dict.fromkeys(str(w.message) for w in caught))
    notes, tempo, traversal, parts = [], [], [], []
    offset = min(float(p.quarter_map(p.first_point.t)) for p in loaded.parts)
    for part in loaded.parts:
        parts.append(part_instrument(tree,part,options))
        measures = list(part.measures)
        for occurrence, measure in enumerate(measures):
            start = float(part.quarter_map(measure.start.t))-offset
            end = float(part.quarter_map(measure.end.t))-offset
            if part is loaded.parts[0]:
                # Notes below supply the exact original measure index, including
                # textual measure labels. Empty measures use retained names.
                label = str(getattr(measure, "name", None) or measure.number)
                names = original_parts[part.id]
                mi = names.index(label) if label in names else max(0, int(measure.number or 1)-1)
                traversal.append({"occurrence": occurrence, "mi": mi, "measure": label, "onset": start, "duration": end-start})
        visits = defaultdict(int)
        for note in part.notes_tied:
            if isinstance(note, ps.GraceNote) or note.end_tied is None or note.duration_tied <= 0:
                continue
            meta = source.get(note.id)
            if not meta:
                raise ValueError("Partitura did not preserve a source note identity")
            onset = float(part.quarter_map(note.start.t))-offset
            duration = float(part.quarter_map(note.end_tied.t))-offset-onset
            if duration <= 0:
                continue
            matching_measures = [(i,m) for i,m in enumerate(measures) if m.start.t <= note.start.t < m.end.t]
            occurrence, measure = matching_measures[-1] if matching_measures else (0, measures[0])
            measure_start = float(part.quarter_map(measure.start.t))-offset
            sid = meta["id"]; visit = visits[sid]; visits[sid] += 1
            written = int(note.midi_pitch)
            transposition = meta["transposeSemitones"] if meta["transposeExplicit"] else manual_transpose(meta["part"], options)
            midi = written+transposition
            if not 0 <= midi <= 127:
                raise ValueError("Transposition moved a note outside MIDI range")
            if not (first_measure-1 <= meta["mi"] < last_measure):
                continue
            if options.get("part", "all") not in ("all", meta["part"]):
                continue
            notes.append({"id": sid, "sourceNoteId": sid, "occurrenceId": f"{sid}@{visit}", "occurrence": occurrence,
                          "sourceIdentity": {"partId": meta["part"], "xmlIndex": meta["xmlIndex"], "measureIndex": meta["mi"]},
                          "part": meta["part"], "voice": str(note.voice or 1), "staff": str(note.staff or 1),
                          "mi": meta["mi"], "measure": meta["measure"], "beat": (onset-measure_start)*meta["beatType"]/4+1,
                          "onset": onset, "duration": duration, "midi": midi, "writtenMidi": written,
                          "transposeSemitones": transposition, "transposeExplicit": meta["transposeExplicit"]})
            if part is loaded.parts[0] and occurrence < len(traversal):
                traversal[occurrence].update(mi=meta["mi"], measure=meta["measure"])
        for event in part.iter_all(ps.Tempo):
            quarter = 60_000_000/event.microseconds_per_quarter
            tempo.append({"onset": float(part.quarter_map(event.start.t))-offset, "bpm": float(quarter)})
    notes.sort(key=lambda n: (n["onset"], n["midi"], n["occurrenceId"]))
    if len(notes) > 50000:
        raise ValueError("Unfolded score exceeds 50000 notes")
    groups = []
    for note in notes:
        if not groups or abs(groups[-1]["onset"]-note["onset"]) > 1e-7:
            groups.append({k: note[k] for k in ("onset", "mi", "measure", "beat", "occurrence")}|{"notes": []})
        groups[-1]["notes"].append(note)
    return {"schemaVersion": 1, "engine": "partitura", "version": partitura.__version__, "timeUnit": "quarter",
            "notes": notes, "groups": groups, "tempo": sorted(tempo, key=lambda t: t["onset"]),
            "traversal": traversal, "parts": parts, "warnings": messages, "options": options}


def integer_field(value, label, minimum, maximum):
    # JSON saved through Java may encode an integer as 60.0. Accept that exact
    # value, but never truncate a fractional MIDI identity or list index.
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value != int(value)
            or not minimum <= value <= maximum):
        raise ValueError(f"{label} must be an integer between {minimum} and {maximum}")
    return int(value)


def alignment_rows(rows, label):
    if not isinstance(rows, list):
        raise ValueError(f"{label} must be a note list")
    result = []
    for i, original in enumerate(rows):
        if not isinstance(original, dict):
            raise ValueError(f"{label}[{i}] must be a note object")
        row = dict(original)  # A recheck must not mutate the saved report.
        row["midi"] = integer_field(row.get("midi"), f"{label}[{i}].midi", 0, 127)
        for field in ("writtenMidi", "modelMidi"):
            if field in row:
                row[field] = integer_field(row[field], f"{label}[{i}].{field}", 0, 127)
        for field in ("mi", "occurrence"):
            if field in row:
                row[field] = integer_field(row[field], f"{label}[{i}].{field}", 0, 2147483647)
        if "transposeSemitones" in row:
            row["transposeSemitones"] = integer_field(row["transposeSemitones"], f"{label}[{i}].transposeSemitones", -127, 127)
        if isinstance(row.get("sourceIdentity"), dict):
            row["sourceIdentity"] = dict(row["sourceIdentity"])
            for field in ("xmlIndex", "measureIndex"):
                if field in row["sourceIdentity"]:
                    row["sourceIdentity"][field] = integer_field(row["sourceIdentity"][field], f"{label}[{i}].sourceIdentity.{field}", 0, 2147483647)
        for field in ("onset", "duration"):
            value = row.get(field)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value < 0 or field == "duration" and value == 0):
                raise ValueError(f"{label}[{i}].{field} must be a finite {'positive' if field == 'duration' else 'nonnegative'} number")
        if "confidence" in row:
            value = row["confidence"]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{label}[{i}].confidence must be between 0 and 1")
        result.append(row)
    return result


def align(payload, home):
    score = payload["score"]
    notes = alignment_rows(score.get("notes") or [n for g in score.get("groups", []) for n in g["notes"]], "score")
    performance = alignment_rows(payload.get("performance", []), "performance")
    options = payload.get("options", {})
    backend = options.get("backend", "parangonar")
    for i, n in enumerate(notes):
        n.setdefault("occurrenceId", f"{n.get('sourceNoteId',n.get('id',i))}@0")
        n.setdefault("sourceNoteId", n.get("id", str(i)))
    if len(notes) > 10000 or len(performance) > 10000:
        raise ValueError("Offline baseline is limited to 10000 notes per excerpt")
    if not notes or not performance:
        return {"schemaVersion":1,"engine":backend,"pairs":[],"missing":[n["occurrenceId"] for n in notes],
                "extra":list(range(len(performance))),"metadata":{"algorithm":"empty-input","evaluated":False}}
    if backend == "parangonar":
        return align_parangonar(notes, performance)
    if backend == "nakamura":
        return align_nakamura(notes, performance, home)
    raise ValueError("Unknown offline baseline")


def align_parangonar(notes, performance):
    notes = alignment_rows(notes, "score")
    performance = alignment_rows(performance, "performance")
    # Upstream DTW's 1x1 backtracking steps away from (0,0) before checking
    # its stopping condition. A distinct two-anchor tempo context is required.
    skipped = short_baseline_context(notes, performance, "parangonar", "3.3.3", "DualDTWNoteMatcher")
    if skipped is not None:
        return skipped
    import numpy as np
    import parangonar
    from parangonar.match import DualDTWNoteMatcher
    score_dtype=[("id","U256"),("onset_beat","f4"),("duration_beat","f4"),("onset_div","i4"),("duration_div","i4"),("pitch","i4"),("is_grace","?")]
    perf_dtype=[("id","U256"),("onset_sec","f4"),("duration_sec","f4"),("pitch","i4"),("velocity","i4")]
    score=np.array([(n["occurrenceId"],n["onset"],n["duration"],round(n["onset"]*480),max(1,round(n["duration"]*480)),n["midi"],False) for n in notes],dtype=score_dtype)
    perf=np.array([(str(i),n["onset"],n["duration"],n["midi"],round(n.get("confidence",.8)*100)) for i,n in enumerate(performance)],dtype=perf_dtype)
    actual=DualDTWNoteMatcher()(score,perf,process_ornaments=False)
    lookup={n["occurrenceId"]:n for n in notes};pairs=[];missing=[];extra=[]
    for item in actual:
        if item["label"]=="match":
            sid=item["score_id"];pairs.append({"sourceNoteId":lookup[sid]["sourceNoteId"],"occurrenceId":sid,"detectionIndex":int(item["performance_id"])})
        elif item["label"]=="deletion":missing.append(item["score_id"])
        elif item["label"]=="insertion":extra.append(int(item["performance_id"]))
    return {"schemaVersion":1,"engine":"parangonar","pairs":pairs,"missing":missing,"extra":extra,
            "metadata":{"version":"3.3.3","algorithm":"DualDTWNoteMatcher","evaluated":True}}


def align_nakamura(notes, performance, home):
    notes = alignment_rows(notes, "score")
    performance = alignment_rows(performance, "performance")
    # The original RealignmentMOHMM also dereferences unavailable neighboring
    # context for a single event. Keep original tools intact; disclose a skip.
    skipped = short_baseline_context(notes, performance, "nakamura", "240109", "HMM error detection + merged-output HMM realignment")
    if skipped is not None:
        return skipped
    binary=Path(home)/"native"/"nakamura"
    commands=["SprToFmt3x","Fmt3xToHmm","ScorePerfmMatcher","ErrorDetection","RealignmentMOHMM","MatchToCorresp"]
    if not all((binary/(name+".exe")).is_file() for name in commands):
        raise ValueError("Nakamura published alignment tools are not installed")
    def pitch(midi):return ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"][midi%12]+str(midi//12-1)
    with tempfile.TemporaryDirectory(prefix="notelite-nakamura-") as folder:
        temp=Path(folder);ref=temp/"ref_spr.txt";perf=temp/"perf_spr.txt"
        # A constant reference conversion establishes an HMM tempo prior. It
        # does not impose that tempo on the performed sequence.
        ref.write_text("\n".join(f"{i}\t{n['onset']*.5:.6f}\t{(n['onset']+n['duration'])*.5:.6f}\t{pitch(n['midi'])}\t80\t64\t0" for i,n in enumerate(notes)),encoding="ascii")
        perf.write_text("\n".join(f"{i}\t{n['onset']:.6f}\t{n['onset']+n['duration']:.6f}\t{pitch(n['midi'])}\t80\t64\t0" for i,n in enumerate(performance)),encoding="ascii")
        fmt=temp/"ref_fmt3x.txt";hmm=temp/"ref_hmm.txt";pre=temp/"pre.txt";err=temp/"err.txt";real=temp/"real.txt";cor=temp/"corresp.txt"
        arguments=[[ref,fmt],[fmt,hmm],[hmm,perf,pre,"0.001"],[fmt,hmm,pre,err,"0"],[fmt,hmm,err,real,"0.3"],[real,ref,cor]]
        for name,args in zip(commands,arguments):
            try:
                subprocess.run([str(binary/(name+".exe"))]+list(map(str,args)),cwd=temp,check=True,timeout=120,capture_output=True)
            except subprocess.CalledProcessError as error:
                detail=(error.stderr or error.stdout or b"").decode("utf8",errors="replace")[-400:]
                raise ValueError(f"Actual Nakamura baseline failed at {name}, exit {error.returncode}: {detail}") from error
        pairs=[];missing=[];extra=[]
        for line in cor.read_text(encoding="utf8").splitlines():
            if line.startswith("//") or not line.strip():continue
            columns=line.split();played,expected=columns[0],columns[5]
            if expected=="*":extra.append(int(played))
            elif played=="*":missing.append(notes[int(expected)]["occurrenceId"])
            else:
                note=notes[int(expected)];pairs.append({"sourceNoteId":note["sourceNoteId"],"occurrenceId":note["occurrenceId"],"detectionIndex":int(played)})
    return {"schemaVersion":1,"engine":"nakamura","pairs":pairs,"missing":missing,"extra":extra,
            "metadata":{"version":"240109","algorithm":"HMM error detection + merged-output HMM realignment","evaluated":True}}


def short_baseline_context(notes, performance, engine, version, algorithm):
    score_onsets = len({n["onset"] for n in notes})
    performance_onsets = len({n["onset"] for n in performance})
    if score_onsets >= 2 and performance_onsets >= 2:
        return None
    # No fabricated pairs/deletions/insertions: the shared grader can still
    # judge the actual detected single note independently of either baseline.
    return {"schemaVersion":1,"engine":engine,"pairs":[],"missing":[],"extra":[],
            "warnings":[f"{engine} comparison skipped: at least two distinct score and performance onsets are required."],
            "metadata":{"version":version,"algorithm":algorithm,"evaluated":False,
                        "reason":"insufficient-context","scoreOnsets":score_onsets,
                        "performanceOnsets":performance_onsets,"minimumDistinctOnsets":2}}
