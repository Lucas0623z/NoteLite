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
# Clear only the previous completion marker, so stale results cannot satisfy this run.
if [ -f "$container/Documents/embedded-probe-result.json" ]; then
  mv "$container/Documents/embedded-probe-result.json" "$output/previous-result.json"
fi
xcrun simctl launch --terminate-running-process \
  --stdout="$output/stdout.log" --stderr="$output/stderr.log" "$device" "$bundle_id" \
  > "$output/launch.txt"
started=$(date +%s)
while [ ! -f "$container/Documents/embedded-probe-result.json" ]; do
  if [ $(($(date +%s) - started)) -ge "$timeout" ]; then
    ditto "$container/Documents" "$output/Documents" || true
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
