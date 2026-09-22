"""Re-score retained MIDI events against the same repeat-expanded playback truth.

This is analysis of already-run exports, not another invocation of the application.
Source metadata is refreshed from the license/provenance manifest, while raw event
data, original invocation, elapsed time, and application JAR checksum are retained.
"""
import argparse
import json
from pathlib import Path
import shutil

from benchmark import metrics


def aggregate(cases):
    output = {}
    for name in ("pitch_onset", "pitch_onset_offset", "pitch_inventory_diagnostic"):
        totals = {key: sum(case["metrics"][name][key] for case in cases) for key in ("tp", "fp", "fn")}
        tp, fp, fn = totals["tp"], totals["fp"], totals["fn"]
        totals.update(precision=tp / (tp + fp) if tp + fp else 0,
                      recall=tp / (tp + fn) if tp + fn else 0,
                      f1=2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 1)
        output[name] = totals
    return output


def retain(run, fixture_path, destination, truth_file):
    result = json.loads((run / "results.json").read_text(encoding="utf-8"))
    result["fixture_manifest"] = json.loads((fixture_path / "manifest.json").read_text(encoding="utf-8"))
    result["rescored_against"] = truth_file
    destination.mkdir(parents=True, exist_ok=True)
    for case in result["cases"]:
        truth = json.loads((fixture_path / case["id"] / truth_file).read_text(encoding="utf-8"))
        case["original_run_metrics"] = case["metrics"]
        case["metrics"] = metrics(truth, case["actual_notes"])
        case_dest = destination / case["id"]
        case_dest.mkdir(exist_ok=True)
        for name in ("console.txt", "score.mid", "score.mxl"):
            source = run / case["id"] / name
            if source.exists():
                shutil.copy2(source, case_dest / name)
    result["aggregate"] = aggregate(result["cases"])
    (destination / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    script_dir = Path(__file__).resolve().parent
    scenarios = [("baseline-synthetic", "omr-baseline-final-synthetic", "fixtures", "truth.json"),
                 ("baseline-external", "omr-baseline-external", "external-fixtures", "truth-expanded.json"),
                 ("fixed-synthetic", "omr-final-synthetic", "fixtures", "truth.json"),
                 ("fixed-external", "omr-final-external", "external-fixtures", "truth-expanded.json")]
    summary = {}
    for label, run, fixtures, truth in scenarios:
        result = retain(args.runs / run, script_dir / fixtures, args.output / label, truth)
        summary[label] = {"jar_sha256": result["jar_sha256"], "aggregate": result["aggregate"],
                          "cases": [{key: case[key] for key in ("id", "status", "seconds", "metrics", "original_run_metrics")}
                                    for case in result["cases"]]}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    for label, result in summary.items():
        print(label, json.dumps(result["aggregate"]["pitch_onset_offset"]))
        for case in result["cases"]:
            print(case["id"], case["metrics"]["reference_notes"], case["metrics"]["predicted_notes"],
                  round(100 * case["metrics"]["pitch_onset"]["f1"], 3),
                  round(100 * case["metrics"]["pitch_onset_offset"]["f1"], 3))


if __name__ == "__main__":
    main()
