#!/usr/bin/env bash
# Build a pinned, interpreted OpenJDK runtime and attempt the missing headless
# desktop libraries. A successful archive build is not an OMR runtime test.
set -euo pipefail

platform="${1:-device}"
case "$platform" in
  device) sdk=iphoneos; triple=arm64-apple-ios16.0 ;;
  simulator) sdk=iphonesimulator; triple=arm64-apple-ios16.0-simulator ;;
  *) echo "Usage: $0 [device|simulator]" >&2; exit 2 ;;
esac

if [[ "$(uname -s)" != Darwin ]]; then
  echo "This build requires macOS and Xcode's Apple SDKs." >&2
  exit 2
fi
for tool in git curl shasum python3 xcodebuild xcrun autoconf gmake; do
  command -v "$tool" >/dev/null || { echo "Missing build tool: $tool" >&2; exit 2; }
done
: "${JAVA_HOME:?Set JAVA_HOME to a JDK 26, 27 or 28 bootstrap JDK}"
: "${MOBILE_JDK_HOST_HOME:?Build and unpack the matching macOS tools with build-mobile-jdk-tools.sh}"
[[ -x "$MOBILE_JDK_HOST_HOME/bin/jmod" && -x "$MOBILE_JDK_HOST_HOME/bin/jlink" ]] || exit 2

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
work_root="${MOBILE_JDK_WORK_DIR:-$repo_root/build/mobile-jdk/$platform}"
mkdir -p "$work_root"
work_root="$(cd "$work_root" && pwd)"
logs="$work_root/logs"
artifacts="$work_root/artifacts"
mkdir -p "$logs" "$artifacts"
exec > >(tee "$logs/build.log") 2>&1

mobile_ref=c1ed06aaef34c8dccf71e236d1ffa20918a77cfb
ffi_version=3.5.2
ffi_sha256=f3a3082a23b37c293a4fcd1053147b371f2ff91fa7ea1b2a52e335676bac82dc
source_dir="$work_root/openjdk-mobile"
conf_name="ios-$platform-aarch64-zero-release"
sdk_path="$(xcrun --sdk "$sdk" --show-sdk-path)"
mac_sdk="$(xcrun --sdk macosx --show-sdk-path)"

printf 'OpenJDK source: %s\nTarget: %s\nSDK: %s\n' "$mobile_ref" "$triple" "$sdk_path"
xcodebuild -version
"$JAVA_HOME/bin/java" -version

if [[ ! -d "$source_dir/.git" ]]; then
  git init "$source_dir"
  git -C "$source_dir" remote add origin https://github.com/openjdk/mobile.git
  git -C "$source_dir" fetch --depth 1 origin "$mobile_ref"
  git -C "$source_dir" checkout --detach FETCH_HEAD
fi
[[ "$(git -C "$source_dir" rev-parse HEAD)" == "$mobile_ref" ]] || {
  echo "Unexpected source revision; use a fresh MOBILE_JDK_WORK_DIR." >&2; exit 2;
}
if [[ -n "$(git -C "$source_dir" status --porcelain)" ]]; then
  echo "The runtime source checkout has changes; use a fresh MOBILE_JDK_WORK_DIR." >&2
  exit 2
fi
cp "$source_dir/make/conf/version-numbers.conf" "$artifacts/version-numbers.conf"

# Build libffi from the same release used by openjdk-mobile/ios-tools, retaining
# iPhoneOS vs iPhoneSimulator platform identity rather than reusing macOS arm64.
ffi_archive="$work_root/libffi-$ffi_version.tar.gz"
if [[ ! -f "$ffi_archive" ]]; then
  curl --fail --location --retry 3 \
    "https://github.com/libffi/libffi/releases/download/v$ffi_version/libffi-$ffi_version.tar.gz" \
    --output "$ffi_archive"
fi
printf '%s  %s\n' "$ffi_sha256" "$ffi_archive" | shasum -a 256 --check
if [[ ! -d "$work_root/libffi-$ffi_version" ]]; then
  tar -xzf "$ffi_archive" -C "$work_root"
fi
ffi_source="$work_root/libffi-$ffi_version"
ffi_build="$work_root/libffi-build"
(
  cd "$ffi_source"
  # libffi 3.5.2 still generates armv7 configuration even with --only-ios.
  # Xcode 26 no longer links armv7; both of our supported targets are arm64.
  python3 - <<'PY'
from pathlib import Path
path = Path("generate-darwin-source-and-headers.py")
source = path.read_text()
for call in ("copy_src_platform_files(ios_device_armv7_platform)",
             "build_target(ios_device_armv7_platform, platform_headers)"):
    line = "        " + call + "\n"
    if source.count(line) != 1:
        raise SystemExit("Unexpected libffi generator context: " + call)
    source = source.replace(line, "")
path.write_text(source)
# Remove the corresponding project records as well: Xcode validates Sources
# and CopyFiles inputs before it applies architecture preprocessor guards.
project = Path("libffi.xcodeproj/project.pbxproj")
source = project.read_text()
armv7_files = ("ffi_armv7.c", "sysv_armv7.S", "ffi_armv7.h",
               "fficonfig_armv7.h", "ffitarget_armv7.h")
for name in armv7_files:
    if name not in source:
        raise SystemExit("Unexpected libffi project context: " + name)
lines = [line for line in source.splitlines(keepends=True)
         if not any(name in line for name in armv7_files)]
source = "".join(lines).replace('VALID_ARCHS = "arm64 armv7 armv7s x86_64";',
                              'VALID_ARCHS = "arm64 x86_64";')
if "armv7" in source:
    raise SystemExit("Unreviewed ARMv7 project entry remains")
project.write_text(source)
PY
  python3 generate-darwin-source-and-headers.py --only-ios
  xcodebuild -project libffi.xcodeproj -scheme libffi-iOS -sdk "$sdk" \
    -configuration Release -arch arm64 "SYMROOT=$ffi_build" \
    IPHONEOS_DEPLOYMENT_TARGET=16.0 CODE_SIGNING_ALLOWED=NO build
) 2>&1 | tee "$logs/libffi.log"
ffi_library="$ffi_build/Release-$sdk/libffi.a"
ffi_headers="$ffi_build/Release-$sdk/include/ffi"
[[ -f "$ffi_library" && -f "$ffi_headers/ffi.h" ]] || {
  echo "libffi archive or headers missing after build." >&2; exit 1;
}

# First record the stock runtime. The upstream iOS target deliberately excludes
# AWT/2D libraries, so this baseline alone cannot run Audiveris.
# Do not invoke target jmods/jdk-image: upstream then tries to link iOS shared
# libraries with unsupported ELF flags. Build target classes/data and static
# archives only; package the classes with the separate matching macOS tools.
(
  cd "$source_dir"
  bash configure \
    "--with-conf-name=$conf_name" \
    --disable-warnings-as-errors \
    --openjdk-target=aarch64-macos-ios \
    --with-jvm-variants=zero \
    --enable-headless-only \
    --disable-cds-archive \
    --with-freetype=bundled \
    --with-zlib=system \
    "--with-boot-jdk=$JAVA_HOME" \
    "--with-build-jdk=$MOBILE_JDK_HOST_HOME" \
    "--with-sysroot=$sdk_path" \
    "--with-libffi-include=$ffi_headers" \
    "--with-libffi-lib=$(dirname "$ffi_library")" \
    "--with-cups-include=$mac_sdk/usr/include" \
    "--with-extra-cflags=-target $triple" \
    "--with-extra-cxxflags=-target $triple" \
    "--with-extra-ldflags=-target $triple" \
    "--with-jobs=${MOBILE_JDK_JOBS:-3}"
  gmake "CONF=$conf_name" LOG=info static-libs-image java copy java.base-gendata release-file
) 2>&1 | tee "$logs/openjdk-baseline.log"

build_dir="$source_dir/build/$conf_name"
mkdir -p "$artifacts/baseline"
cp -R "$build_dir/images/static-libs" "$artifacts/baseline/"
cp -R "$build_dir/jdk/include" "$artifacts/baseline/"
cp "$ffi_library" "$artifacts/baseline/static-libs/lib/"
cp "$build_dir/spec.gmk" "$artifacts/baseline/spec.gmk"

# Add actual software raster/font rendering and replace the Cocoa-only platform
# entry points. The patch is pinned and rejects unexpected upstream contexts.
python3 "$repo_root/tools/audiveris-port/patch-mobile-desktop.py" "$source_dir"
git -C "$source_dir" diff --binary > "$artifacts/ios-headless.patch"
set +e
(
  cd "$source_dir"
  gmake "CONF=$conf_name" LOG=info static-libs-image java copy java.base-gendata release-file || exit $?
  python3 "$repo_root/tools/audiveris-port/package-mobile-modules.py" \
    "$build_dir" "$source_dir" "$MOBILE_JDK_HOST_HOME" "$artifacts/headless"
) 2>&1 | tee "$logs/openjdk-headless.log"
headless_status=${PIPESTATUS[0]}
set -e

# Record all produced libraries even on failure; do not manufacture placeholders.
python3 - "$build_dir" "$artifacts" "$platform" "$mobile_ref" "$headless_status" <<'PY'
import hashlib
import json
from pathlib import Path
import sys
build, output = map(Path, sys.argv[1:3])
required = ["zero/libjvm.a", "libjava.a", "libzip.a", "libnet.a", "libnio.a",
            "libawt.a", "libawt_headless.a", "libfontmanager.a", "libfreetype.a",
            "liblcms.a", "libjavajpeg.a", "libmlib_image.a"]
libraries = build / "images/static-libs/lib"
present = sorted(p.relative_to(libraries).as_posix() for p in libraries.rglob("*.a"))
report = {
    "source_commit": sys.argv[4], "platform": sys.argv[3], "vm": "zero",
    "adapter_patch_sha256": hashlib.sha256((output / "ios-headless.patch").read_bytes()).hexdigest(),
    "headless_build_exit_code": int(sys.argv[5]),
    "present_libraries": present,
    "missing_required_libraries": [name for name in required if name not in present],
    "java_desktop_jmod": (output / "headless/jmods/java.desktop.jmod").is_file(),
    "runtime_module_image": (output / "headless/runtime/lib/modules").is_file(),
    "runtime_tested": False,
    "audiveris_end_to_end_tested": False,
}
(output / "runtime-inventory.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
PY
if [[ "$headless_status" != 0 ]]; then
  echo "The stock Zero runtime built; the headless desktop adaptation failed. See saved compiler diagnostics." >&2
  exit "$headless_status"
fi
mkdir -p "$artifacts/headless"
cp -R "$build_dir/images/static-libs" "$artifacts/headless/"
cp -R "$build_dir/jdk/include" "$artifacts/headless/"
cp "$ffi_library" "$artifacts/headless/static-libs/lib/"
# These are the application's original, licensed font files; use the same
# contours for Audiveris templates. The default text fallback is FinaleJazzText.
mkdir -p "$artifacts/headless/runtime/lib/fonts"
find "$repo_root/app/res" -maxdepth 1 \( -name '*.otf' -o -name '*.ttf' \)   -exec cp {} "$artifacts/headless/runtime/lib/fonts/" \;
python3 - "$artifacts/runtime-inventory.json" <<'PY'
import json, sys
report = json.load(open(sys.argv[1]))
if (report["missing_required_libraries"] or not report["java_desktop_jmod"]
        or not report["runtime_module_image"]):
    raise SystemExit("Incomplete headless runtime; see runtime-inventory.json")
print("Required runtime libraries compiled; device linking and OMR execution remain to be tested.")
PY
