"""Actual model/library checks required before an installed engine is advertised."""
import json
import math
from pathlib import Path
import struct
import tempfile
import wave


def verify(home: Path, native=True):
    from analyze import analyze
    from score_tools import normalize, align_parangonar, align_nakamura
    results = {}
    with tempfile.TemporaryDirectory(prefix="notelite-runtime-verify-") as directory:
        path = Path(directory)/"tone.wav"
        rate, seconds = 22050, 3
        audio = bytearray()
        for k in range(rate*seconds):
            t = k/rate
            sample = .23*math.sin(2*math.pi*440*2**(.25/12)*(t-.5)) if .5 <= t < 2.3 else 0
            audio.extend(struct.pack("<h", round(sample*32767)))
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(rate); wav.writeframes(audio)
        for engine in (["basic-pitch", "pyin", "crepe", "aubio"] if native else ["basic-pitch", "pyin", "crepe"]):
            output = analyze(path, home, {"engine":engine,"a4":440,"minHz":100,"maxHz":1000})
            correct = [n for n in output["notes"] if n["midi"] == 69 and n["duration"] > 1]
            if not correct or abs(correct[0]["cents"]-25) > 15:
                raise ValueError(f"Actual {engine} detuned-tone verification failed: {output['notes']}")
            if not output.get("postprocessing",{}).get("rawNotesPreserved") or "rawNotes" not in output:
                raise ValueError(f"Actual {engine} onset-evidence adapter did not preserve original notes")
            results[engine] = {"passed":True,"midi":69,"cents":correct[0]["cents"],"onset":correct[0]["onset"],"duration":correct[0]["duration"],
                               "rawNotesPreserved":True,"postprocessing":output["postprocessing"]["method"]}
        xml = b'<score-partwise version="3.1"><part-list><score-part id="P1"><part-name>Test</part-name></score-part></part-list><part id="P1"><measure number="1"><attributes><divisions>1</divisions><time><beats>3</beats><beat-type>4</beat-type></time></attributes><note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note><note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration></note><note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration></note></measure></part></score-partwise>'
        score = normalize(xml, {"expandRepeats":False})
        if [n["sourceNoteId"] for n in score["notes"]] != ["P1:0","P1:1","P1:2"]:
            raise ValueError("Actual Partitura identity verification failed")
        results["partitura"] = {"passed":True,"notes":len(score["notes"])}
        performance = [{"midi":n["midi"],"onset":time,"duration":.45,"confidence":.9} for n,time in zip(score["notes"],[1,1.7,2.7])]
        for engine in (["parangonar", "nakamura"] if native else ["parangonar"]):
            output = align_parangonar(score["notes"],performance) if engine == "parangonar" else align_nakamura(score["notes"],performance,home)
            if len(output["pairs"]) != 3 or output["missing"] or output["extra"]:
                raise ValueError(f"Actual {engine} alignment verification failed: {output}")
            results[engine] = {"passed":True,"pairs":3,"algorithm":output["metadata"]["algorithm"]}
    return results


if __name__ == "__main__":
    import argparse
    import sys
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime",type=Path,required=True)
    parser.add_argument("--require-native",action="store_true")
    args=parser.parse_args()
    sys.path.insert(0,str(args.runtime.resolve()))
    try:
        print(json.dumps(verify(args.runtime.resolve(),native=args.require_native),allow_nan=False))
    except Exception as error:
        print(f"Actual runtime verification failed: {error}",file=sys.stderr)
        raise SystemExit(1)
