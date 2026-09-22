#!/bin/bash
set -euo pipefail

family="${1:?Specify iPhone or iPad}"
case "$family" in
  iPhone|iPad) ;;
  *) echo "Unsupported simulator family: $family" >&2; exit 2 ;;
esac

devices_file="$RUNNER_TEMP/notelite-simulators-$family.json"
runtimes_file="$RUNNER_TEMP/notelite-runtimes-$family.json"
xcrun simctl list devices available --json > "$devices_file"
xcrun simctl list runtimes --json > "$runtimes_file"
selection=$(python3 - "$devices_file" "$runtimes_file" "$family" <<'PY'
import json, pathlib, sys
devices = json.load(open(sys.argv[1]))["devices"]
runtimes = {r["identifier"]: r for r in json.load(open(sys.argv[2]))["runtimes"]}
found = [(d["udid"], runtime) for runtime, rows in devices.items() if "iOS" in runtime
         for d in rows if d.get("isAvailable") and sys.argv[3] in d["name"]]
if not found:
    raise SystemExit("No available " + sys.argv[3] + " simulator")
device, runtime_id = found[0]
runtime = runtimes[runtime_id]
root = pathlib.Path(runtime["bundlePath"]) / "Contents/Resources/RuntimeRoot"
# Apple/WebKit bug 293831: iOS 18.5's Swift overlay lives in its Cryptex directory.
# Keep the app's iOS 16 deployment target and all WebKit functionality unchanged.
candidates = [root / "System/Cryptexes/OS/usr/lib/swift", root / "usr/lib/swift"]
swift = next((str(p) for p in candidates if (p / "libswiftWebKit.dylib").is_file()), "")
if runtime.get("version") == "18.5" and not swift:
    raise SystemExit("iOS 18.5 runtime is missing libswiftWebKit.dylib in its documented locations")
print(device)
print(swift or "-")
PY
)
device_id=${selection%%$'\n'*}
swift_path=${selection#*$'\n'}
if [ "$swift_path" = "-" ]; then swift_path=""; fi
# Clean up even when tests fail, so the next device family can still run independently.
trap 'xcrun simctl shutdown "$device_id" >/dev/null 2>&1 || true' EXIT
echo "Testing $family on $device_id; Swift overlay fallback: $swift_path"
xcodebuild test -project NoteLite.xcodeproj -scheme NoteLite \
  -destination "platform=iOS Simulator,id=$device_id" \
  -parallel-testing-enabled NO -resultBundlePath "TestResults-$family.xcresult" \
  -test-timeouts-enabled YES -default-test-execution-time-allowance 120 \
  -maximum-test-execution-time-allowance 180 \
  "NOTELITE_SIM_SWIFT_PATH=$swift_path" \
  CODE_SIGNING_ALLOWED=NO
