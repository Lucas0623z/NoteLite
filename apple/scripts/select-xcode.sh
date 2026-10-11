#!/bin/bash
set -euo pipefail
# These stable paths are listed in the official runner inventory. Inspect the
# actual image first; absent versions are skipped rather than blindly selected.
# https://github.com/actions/runner-images/blob/main/images/macos/macos-26-Readme.md
selected=""
for candidate in \
  /Applications/Xcode_26.6.app \
  /Applications/Xcode_26.5.app \
  /Applications/Xcode_26.4.1.app \
  /Applications/Xcode_26.3.app \
  /Applications/Xcode_26.2.app \
  /Applications/Xcode_26.1.1.app \
  /Applications/Xcode_26.0.1.app \
  /Applications/Xcode.app; do
  if [ ! -x "$candidate/Contents/Developer/usr/bin/xcodebuild" ]; then continue; fi
  version=$(DEVELOPER_DIR="$candidate/Contents/Developer" xcodebuild -version | head -n 1)
  if [[ "$version" == *[Bb]eta* || "$version" == *[Pp]review* ]]; then continue; fi
  sdk=$(DEVELOPER_DIR="$candidate/Contents/Developer" xcrun --sdk iphoneos --show-sdk-version)
  if [ "${sdk%%.*}" -lt 26 ]; then continue; fi
  selected="$candidate/Contents/Developer"
  break
done
if [ -z "$selected" ]; then
  echo "No installed stable Xcode with the required iOS 26 SDK; inspect runner inventory." >&2
  exit 1
fi
export DEVELOPER_DIR="$selected"
if [ -n "${GITHUB_ENV:-}" ]; then printf 'DEVELOPER_DIR=%s\n' "$selected" >> "$GITHUB_ENV"; fi
xcodebuild -version
xcrun --sdk iphoneos --show-sdk-version
printf 'Selected installed developer directory: %s\n' "$selected"
