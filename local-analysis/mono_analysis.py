"""Real pYIN, CREPE and aubio recorded monophonic review adapters."""
import hashlib
import copy
import json
import math
from pathlib import Path
import subprocess
import numpy as np


def read_audio(path):
    import soundfile
    audio, rate = soundfile.read(str(path), dtype="float32", always_2d=True)
    return audio.mean(axis=1), rate


def frames_to_notes(times, frequencies, confidence, seconds, a4=440, threshold=.5, engine="pyin", onsets=()):
    """Stable contiguous voiced frames become attacks, with releases and cents.

    Gaps and semitone changes split events. Pitch trackers alone cannot reliably
    identify re-articulation with no silence; this limitation is retained.
    """
    notes, active, next_onset = [], None, 0
    onsets = sorted(float(t) for t in onsets if math.isfinite(float(t)))
    hop = float(np.median(np.diff(times))) if len(times) > 1 else .01
    for time, frequency, certainty in zip(times, frequencies, confidence):
        new_attack = False
        while next_onset < len(onsets) and onsets[next_onset] <= time:
            if active is not None and onsets[next_onset] > active["onset"]+.08:
                new_attack = True
            next_onset += 1
        if new_attack and active is not None:
            finish_note(notes, active, min(seconds, float(time)), a4, engine); active = None
        if not math.isfinite(float(frequency)) or frequency <= 0 or certainty < threshold:
            if active is not None:
                finish_note(notes, active, min(seconds, float(time)), a4, engine); active = None
            continue
        pitch = 69+12*math.log2(float(frequency)/a4)
        midi = round(pitch)
        if active is not None and midi != active["midi"]:
            finish_note(notes, active, min(seconds, float(time)), a4, engine); active = None
        if active is None:
            active = {"midi": midi, "onset": float(time), "pitch": [], "confidence": []}
        active["pitch"].append(pitch); active["confidence"].append(float(certainty))
    if active is not None:
        finish_note(notes, active, min(seconds, float(times[-1])+hop), a4, engine)
    return notes


def finish_note(notes, active, end, a4, engine):
    if end-active["onset"] < .06:
        return
    pitch = float(np.median(active["pitch"]))
    spread = float(np.median(np.abs(np.asarray(active["pitch"])*100-pitch*100)))
    notes.append({"midi": active["midi"], "onset": round(active["onset"], 6), "duration": round(end-active["onset"], 6),
                  "cents": round((pitch-active["midi"])*100, 3), "pitchCents": round(pitch*100, 3),
                  "frequency": round(a4*2**((pitch-69)/12), 6), "confidence": round(float(np.median(active["confidence"])), 6),
                  "engine": engine, "voiced": True, "centsSampleCount": len(active["pitch"]),
                  "centsSpread": round(spread,3), "centsSpreadStatistic": "mad", "centsReliability": "aggregate-median"})


def detector_range(low, high, a4):
    return {"minHz": low, "maxHz": high,
            "minMidi": math.ceil(69+12*math.log2(low/a4)-.5),
            "maxMidi": math.floor(69+12*math.log2(high/a4)+.5)}


def uncertain_frames(times, probability, audio, rate, seconds, threshold):
    """Only audible low-confidence intervals are uncertain; silence is not a note."""
    result, start = [], None
    hop = float(np.median(np.diff(times))) if len(times) > 1 else .01
    for time, confidence in zip(times, probability):
        center = int(time*rate); window = audio[max(0, center-int(rate*.02)):min(len(audio), center+int(rate*.02))]
        audible = len(window) and float(np.sqrt(np.mean(window**2))) >= .008
        uncertain = audible and (not math.isfinite(float(confidence)) or confidence < threshold)
        if uncertain and start is None: start = max(0, float(time)-hop/2)
        if not uncertain and start is not None:
            if time-start >= .06: result.append({"onset": round(start,6), "duration": round(float(time)-start,6), "reason": "low-confidence-voicing"})
            start = None
    if start is not None and seconds-start >= .06:
        result.append({"onset": round(start,6), "duration": round(seconds-start,6), "reason": "low-confidence-voicing"})
    return result


def analyze_mono(path: Path, home: Path, seconds: float, options: dict):
    engine = options.get("engine", "pyin")
    a4 = float(options.get("a4", 440))
    threshold = float(options.get("threshold", .5))
    if not 400 <= a4 <= 480 or not 0 <= threshold <= 1:
        raise ValueError("Invalid A4 or voiced threshold")
    audio, rate = read_audio(path)
    from onset_evidence import gate_candidates, AcousticOnsets
    low, high = float(options.get("minHz", 55)), float(options.get("maxHz", 2000))
    if not 15 <= low < high <= 10000:
        raise ValueError("Invalid monophonic pitch range")
    high = min(high, rate/2-1)
    warnings = ["Monophonic review: overlapping voices are not separable; re-attacks without silence may merge."]
    if engine == "pyin":
        import librosa
        # Keep at least four periods of the lowest requested pitch. Resampling
        # reduces pYIN's quadratic candidate search cost on low instruments.
        analysis_rate = min(rate, 22050) if high < 10000 else rate
        signal = librosa.resample(audio, orig_sr=rate, target_sr=analysis_rate) if analysis_rate != rate else audio
        frame_length = max(2048, 2**math.ceil(math.log2(4*analysis_rate/low)))
        hop = max(128, round(analysis_rate*.01))
        frequency, voiced, probability = librosa.pyin(signal, sr=analysis_rate, fmin=low, fmax=high,
                                                      frame_length=frame_length, hop_length=hop, center=True)
        probability = np.where(voiced, probability, 0)
        times = librosa.frames_to_time(np.arange(len(frequency)), sr=analysis_rate, hop_length=hop)
        onsets = librosa.onset.onset_detect(y=signal, sr=analysis_rate, hop_length=hop, units="time")
        raw_notes = frames_to_notes(times, frequency, probability, seconds, a4, threshold, engine, onsets)
        qualified,onset_proof = gate_candidates(audio,rate,onsets,times,frequency)
        notes = frames_to_notes(times, frequency, probability, seconds, a4, threshold, engine, qualified)
        configuration = {"sampleRate": analysis_rate, "window": frame_length, "hop": hop}
    elif engine == "crepe":
        from crepe_onnx import track
        model = home/"models"/"crepe-tiny.onnx"
        manifest=home/"runtime-manifest.json"
        if not manifest.is_file():manifest=home/"runtime-ready.json"
        metadata = json.loads(manifest.read_text(encoding="utf8"))
        if hashlib.sha256(model.read_bytes()).hexdigest() != metadata.get("crepeModelSha256"):
            raise ValueError("CREPE model checksum mismatch")
        times, frequency, probability = track(audio, rate, model)
        if low < 32.7 or high > 1975.6:
            warnings.append("CREPE model supports approximately 32.7–1975.6 Hz; expected notes outside this range require another detector and remain unjudged.")
        low, high = max(low,32.7), min(high,1975.6)
        if low >= high: raise ValueError("Selected pitch range does not intersect the CREPE model range")
        probability[(frequency < low) | (frequency > high)] = 0
        import librosa
        onsets = librosa.onset.onset_detect(y=audio, sr=rate, hop_length=256, units="time")
        raw_notes = frames_to_notes(times, frequency, probability, seconds, a4, threshold, engine, onsets)
        qualified,onset_proof = gate_candidates(audio,rate,onsets,times,frequency)
        notes = frames_to_notes(times, frequency, probability, seconds, a4, threshold, engine, qualified)
        configuration = {"sampleRate": 16000, "window": 1024, "hop": 160, "model": "official-crepe-tiny"}
    elif engine == "aubio":
        binary = home/"native"/"AubioMono.exe"
        if not binary.is_file():
            raise ValueError("The bundled actual aubio executable is unavailable")
        output = path.with_name("aubio-notes.json")
        try:
            subprocess.run([str(binary), "--input", str(path), "--output", str(output), "--a4", str(a4),
                            "--min-hz", str(low), "--max-hz", str(high)], check=True, timeout=180,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            raw = json.loads(output.read_text(encoding="utf8"))
            if "frames" in raw:
                frames = raw["frames"]
                times = np.array([f["time"] for f in frames]); frequency = np.array([f["frequency"] for f in frames])
                probability = np.array([f["confidence"] for f in frames])
                probability[(frequency < low) | (frequency > high)] = 0
                notes = frames_to_notes(times, frequency, probability, seconds, a4, threshold, engine, raw.get("onsets", []))
                raw_notes = copy.deepcopy(notes)
                onset_proof = [{"candidateOnset":t,"accepted":True,"reason":"actual-aubio-complex-onset"} for t in raw.get("onsets",[])]
            else:
                notes = raw["notes"]
                for note in notes:
                    frequency = note.get("frequency", 440*2**((note["midi"]-69)/12))
                    pitch = 69+12*math.log2(frequency/a4)
                    note.update(midi=round(pitch), cents=round((pitch-round(pitch))*100, 3), pitchCents=pitch*100,
                                engine="aubio", voiced=True)
                times, probability = np.array([]), np.array([])
                raw_notes = copy.deepcopy(notes);onset_proof=[]
            configuration = {"sampleRate": raw.get("sampleRate"), "window": raw.get("window"), "hop": raw.get("hop"), "algorithm": raw.get("algorithm")}
        finally:
            output.unlink(missing_ok=True)
    else:
        raise ValueError("Unknown monophonic review engine")
    acoustic=AcousticOnsets(audio,rate);previous={}
    for note in notes:
        prior=previous.get(note["midi"])
        evidence=acoustic.evaluate(note["onset"],prior["onset"] if prior else None,note["frequency"])
        note["onsetEvidence"]=evidence
        if prior and not evidence["accepted"]:
            note.update(reviewRequired=True,onsetReliable=False,reviewReason="unconfirmed-same-pitch-reattack")
        elif prior:note["onsetReliable"]=True
        previous[note["midi"]]=note
    postprocessing={"method":"waveform-onset-evidence-v1","rawNotesPreserved":True,"rawNoteCount":len(raw_notes),"noteCount":len(notes),
                    "candidateOnsets":onset_proof,"suppressedCandidateOnsets":[p for p in onset_proof if not p["accepted"]]}
    uncertainty=uncertain_frames(times,probability,audio,rate,seconds,threshold)
    uncertainty += [{"onset":n["onset"],"duration":n["duration"],"reason":"unconfirmed-same-pitch-reattack"} for n in notes if n.get("reviewRequired")]
    return {"schemaVersion": 1, "engine": engine, "seconds": seconds, "a4": a4, "notes": notes,"rawNotes":raw_notes,"postprocessing":postprocessing,
            "supportedPitchRange": detector_range(low,high,a4), "configuration": configuration,
            "uncertaintyIntervals": uncertainty, "warnings": warnings}
