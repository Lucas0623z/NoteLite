#!/usr/bin/env bash
# Build matching host jmod/jlink tools using a normal macOS configuration.
# The upstream cross build-JDK spec does not change the target OS from iOS.
set -euo pipefail
[[ "$(uname -s)" == Darwin ]] || { echo "macOS with Xcode is required" >&2; exit 2; }
: "${JAVA_HOME:?Set JAVA_HOME to bootstrap JDK 26, 27 or 28}"
repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
work_root="${MOBILE_JDK_TOOLS_WORK_DIR:-$repo_root/build/mobile-tools}"
mkdir -p "$work_root/logs" "$work_root/artifacts"
work_root="$(cd "$work_root" && pwd)"
exec > >(tee "$work_root/logs/host-tools.log") 2>&1
mobile_ref=c1ed06aaef34c8dccf71e236d1ffa20918a77cfb
source_dir="$work_root/openjdk-mobile"
if [[ ! -d "$source_dir/.git" ]]; then
  git init "$source_dir"
  git -C "$source_dir" remote add origin https://github.com/openjdk/mobile.git
  git -C "$source_dir" fetch --depth 1 origin "$mobile_ref"
  git -C "$source_dir" checkout --detach FETCH_HEAD
fi
[[ "$(git -C "$source_dir" rev-parse HEAD)" == "$mobile_ref" ]] || exit 2
[[ -z "$(git -C "$source_dir" status --porcelain)" ]] || exit 2
(
  cd "$source_dir"
  bash configure --with-conf-name=notelite-macos-tools \
    "--with-boot-jdk=$JAVA_HOME" --disable-warnings-as-errors \
    --with-zlib=system --with-native-debug-symbols=none \
    "--with-jobs=${MOBILE_JDK_JOBS:-3}"
  gmake CONF=notelite-macos-tools LOG=info jdk-image
)
image="$source_dir/build/notelite-macos-tools/images/jdk"
"$image/bin/java" -version
"$image/bin/jlink" --version
printf '%s\n' "$mobile_ref" > "$image/notelite-source-commit"
tar -czf "$work_root/artifacts/mobile-jdk-host-tools.tar.gz" \
  -C "$source_dir/build/notelite-macos-tools/images" jdk
