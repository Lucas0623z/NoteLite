#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Exercise the actual library recognition and practice flow with the embedded VM.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
build=${1:?Pass the build-embedded-app.sh output directory}
device=${2:?Pass an available iPhone or iPad simulator UDID}
output=${3:?Pass a directory for UI test evidence}
test "$(uname -s)" = Darwin
build=$(cd "$build" && pwd)
project=$(cat "$build/evidence/project-location.txt")
test -d "$project/NoteLite.xcodeproj"
mkdir -p "$output"
output=$(cd "$output" && pwd)
run=$(mktemp -d "$output/run.XXXXXX")
xcrun simctl boot "$device" 2>/dev/null || true
xcrun simctl bootstatus "$device" -b
# A previous successful fixture must not replace this run's real recognition.
# Preserve its app data before clearing this test app from the selected simulator.
previous=$(xcrun simctl get_app_container "$device" com.lucas0623z.yinban data 2>/dev/null || true)
if [ -n "$previous" ] && [ -d "$previous" ]; then
  xcrun simctl terminate "$device" com.lucas0623z.yinban 2>/dev/null || true
  ditto "$previous" "$run/previous-app-data"
  xcrun simctl uninstall "$device" com.lucas0623z.yinban
fi
set +e
xcodebuild -project "$project/NoteLite.xcodeproj" -scheme NoteLiteOffline \
  -configuration Debug -sdk iphonesimulator -destination "id=$device" \
  -derivedDataPath "$build/OfflineTestDerivedData" -resultBundlePath "$run/OfflineRecognition.xcresult" \
  -parallel-testing-enabled NO -maximum-concurrent-test-simulator-destinations 1 \
  -test-timeouts-enabled YES -default-test-execution-time-allowance 2400 \
  -maximum-test-execution-time-allowance 2400 ARCHS=arm64 CODE_SIGNING_ALLOWED=NO \
  test 2>&1 | tee "$run/test.log"
status=${PIPESTATUS[0]}
set -e
if [ -d "$run/OfflineRecognition.xcresult" ]; then
  xcrun xcresulttool export attachments --path "$run/OfflineRecognition.xcresult" \
    --output-path "$run/attachments" || true
fi
# Preserve the app's actual persisted scores and settings even when the UI test fails.
container=$(xcrun simctl get_app_container "$device" com.lucas0623z.yinban data 2>/dev/null || true)
if [ -n "$container" ] && [ -d "$container" ]; then
  if [ -d "$container/Documents" ]; then ditto "$container/Documents" "$run/Documents"; fi
  if [ -d "$container/Library/Application Support" ]; then
    ditto "$container/Library/Application Support" "$run/ApplicationSupport"
  fi
fi
python3 - "$device" "$status" "$run" "$repo" <<'PY'
import json, subprocess, sys, uuid
from pathlib import Path
device, status, output = sys.argv[1], int(sys.argv[2]), Path(sys.argv[3])
repo = Path(sys.argv[4])
semantic_passed = False
failure = None
if status == 0:
    try:
        library = output / 'ApplicationSupport/NoteLite'
        records = json.loads((library / 'library.json').read_text())
        matches = [r for r in records if r['filename'] == 'chula.png']
        if len(matches) != 1 or matches[0]['phase'] != 'ready' or matches[0]['recognitionLocation'] != 'device':
            raise ValueError('The production library did not persist one completed local chula recognition')
        record_id = str(uuid.UUID(matches[0]['id'])).upper()
        score = library / record_id
        subprocess.run([sys.executable, str(repo / 'tools/audiveris-port/verify_embedded_score.py'),
                        str(score / 'results'), '--reference',
                        str(repo / 'tools/audiveris-port/fixtures/chula-semantic-reference.json'),
                        '--source-image', str(score / 'source.png'),
                        '--report', str(output / 'production-semantic-parity.json')], check=True)
        semantic_passed = True
    except Exception as error:
        failure = str(error)
        print('Production score validation failed: ' + failure, file=sys.stderr)
report = {
    'simulatorUDID': device, 'xcodebuildExitStatus':status,
    'productionAppOfflineUITestsPassed':status == 0,
    'productionScoreSemanticComparisonPassed':semantic_passed,
    'resultBundle':'OfflineRecognition.xcresult',
}
if failure: report['validationError'] = failure
(output / 'execution.json').write_text(json.dumps(report, indent=2) + '\n')
if status == 0 and not semantic_passed: raise SystemExit(1)
PY
exit "$status"
