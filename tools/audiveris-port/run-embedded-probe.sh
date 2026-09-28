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
timeout=${NOTELITE_PROBE_TIMEOUT_SECONDS:-3900}
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
# Clear only previous completion reports, so stale results cannot satisfy this run.
for marker in embedded-probe-result.json embedded-probe-primary-result.json \
              embedded-probe-reuse-result.json embedded-probe-pdf-result.json embedded-probe-tiff-result.json; do
  if [ -f "$container/Documents/$marker" ]; then
    mv "$container/Documents/$marker" "$output/previous-$marker"
  fi
done
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
print_new_log_tail() {
  local file=$1 previous=$2 lines=0 added
  if [ -f "$file" ]; then lines=$(wc -l < "$file"); fi
  if [ "$lines" -gt "$previous" ]; then
    added=$((lines - previous))
    if [ "$added" -gt 40 ]; then added=40; fi
    printf 'Probe progress: %s (%s new lines shown)\n' "${file##*/}" "$added" >&2
    tail -n "$added" "$file" >&2 || true
  fi
  printf '%s\n' "$lines"
}
last_progress=$started
stdout_lines=0
stderr_lines=0
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
  if [ $(($(date +%s) - last_progress)) -ge 60 ]; then
    stdout_lines=$(print_new_log_tail "$output/stdout.log" "$stdout_lines")
    stderr_lines=$(print_new_log_tail "$output/stderr.log" "$stderr_lines")
    last_progress=$(date +%s)
  fi
  sleep 2
done
ditto "$container/Documents" "$output/Documents"
cp "$container/Documents/embedded-probe-result.json" "$output/result.json"
python3 - "$output/result.json" "$output/Documents/embedded-probe-primary-result.json" <<'PY'
import json, sys
report = json.load(open(sys.argv[1]))
print(json.dumps(report, indent=2))
if report.get('status') != 'SUCCESS' or not report.get('fullScoreRecognitionTested'):
    raise SystemExit('Actual embedded recognition failed; preserved reports and logs contain the evidence')
if not report.get('sameProcessJNI') or 'Zero' not in report.get('javaVM', ''):
    raise SystemExit('The report was not produced by the embedded Zero JNI runtime')
components = report.get('components', {})
if not components.get('jniMixedPrimitiveArgumentsRequired') or not components.get('jniMixedPrimitiveArguments'):
    raise SystemExit('The real mixed-primitive JNI stack ABI check did not pass')
if not components.get('nativeTemplateScoringRequired') or not components.get('nativeTemplateScoring'):
    raise SystemExit('The registered native template scorer was not exercised')
if (components.get('nativeTemplateScoringCalls', 0) < 50
        or components.get('nativeTemplatePins', 0) <= 0
        or components.get('nativeTemplatePins') != components.get('nativeTemplateReleases')
        or components.get('nativeTemplateCopiedPins') != 0):
    raise SystemExit('Native scorer calls, balanced releases, or direct array access not proven')
if not components.get('midiFileRoundtrip'):
    raise SystemExit('The real MIDI file reader/writer check did not pass')
if not report.get('cancelledBeforeVMStart'):
    raise SystemExit('The native pre-entry cancellation gate did not pass')
primary = json.load(open(sys.argv[2]))
if (primary.get('status') != 'SUCCESS' or not primary.get('fullScoreRecognitionTested')
        or primary.get('outputDirectory') != report.get('outputDirectory')):
    raise SystemExit('The original completed score report was not preserved')
reuse = report.get('vmReuse', {})
repeated = reuse.get('recognition', {})
if (reuse.get('status') != 'SUCCESS' or not reuse.get('cancelledOnExistingVM')
        or not reuse.get('workerCompletionObserved') or repeated.get('status') != 'SUCCESS'
        or not repeated.get('musicXML') or not repeated.get('midi')
        or repeated.get('outputDirectory') == report.get('outputDirectory')):
    raise SystemExit('Cross-thread cancellation and repeated real recognition did not pass')
documents = report.get('multipageDocuments', [])
if len(documents) != 2 or {record.get('format') for record in documents} != {'pdf', 'tiff'}:
    raise SystemExit('Both full multipage PDF and TIFF recognition results are required')
for record in documents:
    recognition = record.get('recognition', {})
    if (record.get('inputFile') != 'chula-two-page.' + record['format']
            or recognition.get('status') != 'SUCCESS'
            or not recognition.get('musicXML') or not recognition.get('midi')
            or record.get('nativeElapsedMilliseconds', 0) <= 0):
        raise SystemExit('A multipage document did not complete actual recognition and export')
if report.get('pitchedNotes', 0) <= 0 or report.get('midiNoteOnEvents', 0) <= 0:
    raise SystemExit('No real musical output was validated')
memory = report.get('nativeMemory', {})
if (memory.get('platform') != 'ios-simulator' or memory.get('sampleCount', 0) <= 0
        or memory.get('peakSampledResidentBytes', 0) <= 0
        or memory.get('peakSampledPhysicalFootprintBytes', 0) <= 0):
    raise SystemExit('The probe did not record actual simulator process memory samples')
PY
jobs=$(python3 - "$output/result.json" <<'PY'
import json, re, sys
from pathlib import PurePosixPath
report = json.load(open(sys.argv[1]))
records = [('primary', report), ('reuse', report['vmReuse']['recognition'])]
records += [(record['format'], record['recognition']) for record in report['multipageDocuments']]
names = [PurePosixPath(record['outputDirectory']).name for _, record in records]
if len(set(names)) != 4 or any(not re.fullmatch(r'job-[A-Za-z0-9_-]+', name) for name in names):
    raise SystemExit('Unexpected or reused job directory in completion report')
for (label, _), name in zip(records, names):
    print(label, name, sep='\t')
PY
)
while IFS=$'\t' read -r label job; do
  case "$label" in
    primary|reuse)
      reference=chula-semantic-reference.json
      input=chula.png
      movements=1
      if [ "$label" = primary ]; then report=semantic-parity.json; else report=reuse-semantic-parity.json; fi
      ;;
    pdf|tiff)
      reference="chula-two-page-$label-semantic-reference.json"
      input="chula-two-page.$label"
      movements=2
      report="$label-semantic-parity.json"
      ;;
    *) echo "Unexpected recognition label: $label" >&2; exit 1 ;;
  esac
  python3 "$repo/tools/audiveris-port/verify_embedded_score.py" \
    "$output/Documents/omr/jobs/$job" \
    --reference "$repo/tools/audiveris-port/fixtures/$reference" \
    --source-image "$output/Documents/omr/$input" \
    --expected-movements "$movements" \
    --report "$output/$report"
done <<< "$jobs"
