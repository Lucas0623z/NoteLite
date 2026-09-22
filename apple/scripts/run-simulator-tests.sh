#!/bin/bash
set -euo pipefail

family="${1:?Specify iPhone or iPad}"
case "$family" in
  iPhone|iPad) ;;
  *) echo "Unsupported simulator family: $family" >&2; exit 2 ;;
esac

devices_file="$RUNNER_TEMP/notelite-simulators-$family.json"
xcrun simctl list devices available --json > "$devices_file"
device_id=$(python3 - "$devices_file" "$family" <<'PY'
import json, sys
devices = json.load(open(sys.argv[1]))["devices"]
found = [d["udid"] for runtime, rows in devices.items() if "iOS" in runtime
         for d in rows if d.get("isAvailable") and sys.argv[2] in d["name"]]
if not found:
    raise SystemExit("No available " + sys.argv[2] + " simulator")
print(found[0])
PY
)
# Clean up even when tests fail, so the next device family can still run independently.
trap 'xcrun simctl shutdown "$device_id" >/dev/null 2>&1 || true' EXIT
xcodebuild test -project NoteLite.xcodeproj -scheme NoteLite \
  -destination "platform=iOS Simulator,id=$device_id" \
  -parallel-testing-enabled NO -resultBundlePath "TestResults-$family.xcresult" \
  CODE_SIGNING_ALLOWED=NO
