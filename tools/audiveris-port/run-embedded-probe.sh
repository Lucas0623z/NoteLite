#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Run the same app on a selected iPhone or iPad simulator and preserve real exports.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
app=${1:?Pass the built EmbeddedOMRProbe.app}
device=${2:?Pass a simulator UDID}
output=${3:?Pass an evidence output directory}
test "$(uname -s)" = Darwin
app=$(cd "$app" && pwd)
mkdir -p "$output"
output=$(cd "$output" && pwd)
bundle_id=com.notelite.embeddedprobe
timeout=${NOTELITE_PROBE_TIMEOUT_SECONDS:-1800}
xcrun simctl boot "$device" 2>/dev/null || true
xcrun simctl bootstatus "$device" -b
xcrun simctl install "$device" "$app"
container=$(xcrun simctl get_app_container "$device" "$bundle_id" data)
started=$(date +%s)
preserve_failure_evidence() {
  if [ -f "$output/stderr.log" ]; then
    echo "Final probe stderr (complete log is preserved with the artifacts):" >&2
    tail -n 120 "$output/stderr.log" >&2 || true
  fi
  if [ -d "$container/Documents" ]; then
    ditto "$container/Documents" "$output/Documents" || true
  fi
  python3 - "$output" "$device" "$started" <<'PY' || true
import json, shutil, sys
from pathlib import Path
output, device, started = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
roots = {
    'host': Path.home() / 'Library/Logs/DiagnosticReports',
    'simulator': Path.home() / 'Library/Developer/CoreSimulator/Devices' / device / 'data/Library/Logs/CrashReporter',
}
copied = []
for label, root in roots.items():
    if not root.is_dir():
        continue
    for source in root.rglob('EmbeddedOMRProbe*'):
        try:
            if not source.is_file() or source.stat().st_mtime < started - 2:
                continue
            target = output / 'DiagnosticReports' / label / source.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(str(target.relative_to(output)))
        except OSError as error:
            print('Could not preserve diagnostic:', source.name, str(error), file=sys.stderr)
(output / 'diagnostics-index.json').write_text(json.dumps({'reports': copied}, indent=2) + '\n')
PY
}
trap 'result=$?; if [ "$result" -ne 0 ]; then preserve_failure_evidence; fi; exit "$result"' EXIT
# Clear only the previous completion marker, so stale results cannot satisfy this run.
if [ -f "$container/Documents/embedded-probe-result.json" ]; then
  mv "$container/Documents/embedded-probe-result.json" "$output/previous-result.json"
fi
xcrun simctl launch --terminate-running-process \
  --stdout="$output/stdout.log" --stderr="$output/stderr.log" "$device" "$bundle_id" \
  > "$output/launch.txt"
pid=$(python3 - "$output/launch.txt" "$bundle_id" <<'PY'
import re, sys
from pathlib import Path
text = Path(sys.argv[1]).read_text()
match = re.search(r'^' + re.escape(sys.argv[2]) + r':\s*([1-9][0-9]*)\s*$', text, re.M)
if not match:
    raise SystemExit('simctl did not report the launched app PID; see launch.txt')
print(match.group(1))
PY
)
printf '%s\n' "$pid" > "$output/process-id.txt"
while [ ! -f "$container/Documents/embedded-probe-result.json" ]; do
  elapsed=$(($(date +%s) - started))
  if [ "$elapsed" -ge 10 ] && ! kill -0 "$pid" 2>/dev/null; then
    # Allow atomic result writes and delayed crash reports to arrive. Check the
    # completion marker and process again before declaring a premature exit.
    sleep 3
    if [ -f "$container/Documents/embedded-probe-result.json" ]; then break; fi
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "Probe process $pid exited before producing a completion report" >&2
      exit 1
    fi
  fi
  if [ "$elapsed" -ge "$timeout" ]; then
    echo "Probe did not produce a completion report within $timeout seconds" >&2
    exit 1
  fi
  sleep 2
done
ditto "$container/Documents" "$output/Documents"
cp "$container/Documents/embedded-probe-result.json" "$output/result.json"
python3 - "$output/result.json" <<'PY'
import json, sys
report = json.load(open(sys.argv[1]))
print(json.dumps(report, indent=2))
if report.get('status') != 'SUCCESS' or not report.get('fullScoreRecognitionTested'):
    raise SystemExit('Actual embedded recognition failed; preserved reports and logs contain the evidence')
if not report.get('sameProcessJNI') or 'Zero' not in report.get('javaVM', ''):
    raise SystemExit('The report was not produced by the embedded Zero JNI runtime')
if not report.get('cancelledBeforeVMStart'):
    raise SystemExit('The native pre-entry cancellation gate did not pass')
if report.get('pitchedNotes', 0) <= 0 or report.get('midiNoteOnEvents', 0) <= 0:
    raise SystemExit('No real musical output was validated')
memory = report.get('nativeMemory', {})
if (memory.get('platform') != 'ios-simulator' or memory.get('sampleCount', 0) <= 0
        or memory.get('peakSampledResidentBytes', 0) <= 0
        or memory.get('peakSampledPhysicalFootprintBytes', 0) <= 0):
    raise SystemExit('The probe did not record actual simulator process memory samples')
PY
job=$(python3 - "$output/result.json" <<'PY'
import json, re, sys
from pathlib import PurePosixPath
name = PurePosixPath(json.load(open(sys.argv[1]))['outputDirectory']).name
if not re.fullmatch(r'job-[A-Za-z0-9_-]+', name):
    raise SystemExit('Unexpected job directory in completion report')
print(name)
PY
)
python3 "$repo/tools/audiveris-port/verify_embedded_score.py" \
  "$output/Documents/omr/jobs/$job" \
  --reference "$repo/tools/audiveris-port/fixtures/chula-semantic-reference.json" \
  --source-image "$repo/data/examples/chula.png" \
  --report "$output/semantic-parity.json"
