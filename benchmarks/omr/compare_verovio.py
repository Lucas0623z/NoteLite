"""A separate mature MIDI renderer cannot recover notes lost or misread by OMR.

Evaluate Verovio on the exact MusicXML exported by NoteLite's original OMR run.
This control is not another image recognition engine and must not be reported as one.
"""
import argparse
import base64
import json
from pathlib import Path
import zipfile

import verovio
from benchmark import metrics, read_midi, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cases = []
    fixtures = Path(__file__).resolve().parent / "external-fixtures"
    for name in ("08_mutopia_minuet", "09_mutopia_mozart"):
        mxl = args.runs / name / "score.mxl"
        with zipfile.ZipFile(mxl) as archive:
            xml = archive.read("score.xml").decode("utf-8")
        toolkit = verovio.toolkit()
        assert toolkit.loadData(xml)
        output = args.output / f"{name}.mid"
        output.write_bytes(base64.b64decode(toolkit.renderToMIDI()))
        notes, hanging = read_midi(output)
        truth = json.loads((fixtures / name / "truth-expanded.json").read_text(encoding="utf-8"))
        case = {"id": name, "version": toolkit.getVersion(), "source_mxl_sha256": sha(mxl),
                "metrics": metrics(truth, notes), "unclosed_notes": hanging, "actual_notes": notes}
        cases.append(case)
        print(name, json.dumps(case["metrics"]))
    (args.output / "results.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
