#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Build a real iOS app around already-compiled Zero/desktop/OCR static artifacts.
set -euo pipefail
sdk=${1:-iphonesimulator}
case "$sdk" in iphoneos|iphonesimulator) ;; *) echo "Expected iphoneos or iphonesimulator" >&2; exit 2 ;; esac
repo=$(cd "$(dirname "$0")/../.." && pwd)
runtime=${2:?Pass the headless runtime artifact directory}
ocr=${3:?Pass the OCR install artifact directory}
output=${4:-"$repo/build/embedded-probe/$sdk-arm64"}
test "$(uname -s)" = Darwin
: "${JAVA_HOME:?JAVA_HOME must point to host JDK21 for building the engine}"
command -v xcodegen >/dev/null
command -v python3 >/dev/null
runtime=$(cd "$runtime" && pwd)
ocr=$(cd "$ocr" && pwd)
mkdir -p "$output"
output=$(cd "$output" && pwd)
test -f "$runtime/include/jni.h"
test -f "$runtime/runtime/lib/modules"
test -f "$runtime/static-libs/lib/zero/libjvm.a"
test -f "$runtime/static-libs/lib/libawt_headless.a"
test -f "$ocr/lib/libjnitesseract.a"
test -f "$ocr/share/tessdata/eng.traineddata"
work=$(mktemp -d "$output/build.XXXXXX")
project="$work/project"
resources="$project/Generated/ProbeResources"
mkdir -p "$project/Generated" "$output/evidence"
cp -R "$repo/apple/EmbeddedOMRProbe/Sources" "$project/Sources"
cp -R "$repo/apple/EmbeddedOMRRuntime/Sources" "$project/RuntimeSources"
cp "$repo/apple/EmbeddedOMRProbe/project.yml" "$project/project.yml"

# Compile all real engine classes and stage runtime dependencies. No placeholder jars.
(
  cd "$repo"
  bash ./gradlew --no-daemon --console=plain \
    -I tools/audiveris-port/oracle.gradle -I tools/audiveris-port/embedded-probe.gradle \
    "-PembeddedProbeStage=$resources" :app:stageEmbeddedProbe
) 2>&1 | tee "$output/evidence/java-build.log"
python3 "$repo/tools/audiveris-port/prepare-embedded-jars.py" "$resources" \
  2>&1 | tee "$output/evidence/java-packaging.log"
cp "$resources/java-packaging-report.json" "$output/evidence/"
cp -R "$runtime/runtime" "$resources/runtime"
cp -R "$ocr/share/tessdata" "$resources/tessdata"
if [ -d "$ocr/share/licenses" ]; then cp -R "$ocr/share/licenses" "$resources/licenses/ocr"; fi

python3 - "$runtime" "$ocr" "$project" "$sdk" <<'PY'
import hashlib, json, re, struct, subprocess, sys, zipfile
from pathlib import Path
runtime, ocr, project = map(Path, sys.argv[1:4])
sdk = sys.argv[4]
generated = project / 'Generated'
resources = generated / 'ProbeResources'
jni_md = sorted((runtime / 'include').rglob('jni_md.h'))
if len(jni_md) != 1:
    raise SystemExit('Expected exactly one target jni_md.h')

runtime_archives = sorted((runtime / 'static-libs/lib').rglob('*.a'))
ocr_jni = [ocr / 'lib' / f'lib{name}.a' for name in ('jnijavacpp', 'jnileptonica', 'jnitesseract')]
ocr_codecs = [ocr / 'lib' / f'lib{name}.a' for name in ('tesseract', 'leptonica', 'tiff', 'png16', 'jpeg', 'z')]
for archive in runtime_archives + ocr_jni + ocr_codecs:
    if not archive.is_file(): raise SystemExit(f'Missing native archive: {archive}')
    subprocess.run(['xcrun', 'lipo', str(archive), '-verify_arch', 'arm64'], check=True)

# Prefer the OCR build's ordinary zlib archive if OpenJDK also supplied one.
runtime_archives = [p for p in runtime_archives if p.name != 'libz.a']
# The iOS static image includes two alternative launcher implementations in
# libjli.a. Force-loading both defines JVMInit/LoadJavaVM and others twice.
# libinstrument still needs its independent JLI_ManifestIterate object, so let
# the linker select required libjli members through ordinary archive linking.
runtime_lazy = [p for p in runtime_archives if p.name == 'libjli.a']
runtime_forced = [p for p in runtime_archives if p.name != 'libjli.a']
symbols = set()
for archive in runtime_archives + ocr_jni:
    listing = subprocess.check_output(['xcrun', 'nm', '-gU', str(archive)], text=True)
    for line in listing.splitlines():
        match = re.search(r'\b_((?:Java_|JNI_OnLoad_|JNI_OnUnload_|JVM_|JDK_|JNU_)[A-Za-z0-9_]+)$', line)
        if match: symbols.add(match.group(1))
required = {'JNI_OnLoad_jnijavacpp', 'JNI_OnLoad_jnileptonica', 'JNI_OnLoad_jnitesseract'}
if not required <= symbols:
    raise SystemExit('Static JNI registration entry points missing: ' + ', '.join(sorted(required-symbols)))
keeper = ['/* Generated from actual target archives and checked static registration requirements. */',
          '#include <stddef.h>', '#include <jni.h>']
# This pinned OpenJDK library has real JNI entry points but omits the static
# registration marker. Without it, System.loadLibrary("fallbackLinker") fails,
# hiding the existing libffi implementation from CABI and HarfBuzz's HBShaper.
# Match JDK DEF_STATIC_JNI_OnLoad; LibFallback.init still performs real setup.
fallback_marker = 'JNI_OnLoad_fallbackLinker'
registration_markers = []
if fallback_marker not in symbols:
    fallback_methods = {'Java_jdk_internal_foreign_abi_fallback_LibFallback_' + name
                        for name in ('init', 'doDowncall', 'createClosure', 'freeClosure',
                                     'ffi_1prep_1cif', 'ffi_1default_1abi')}
    if not fallback_methods <= symbols:
        raise SystemExit('The real fallback linker JNI implementation is incomplete')
    keeper += [f'JNIEXPORT jint JNICALL {fallback_marker}(JavaVM *vm, void *reserved) {{',
               '    (void)vm; (void)reserved; return JNI_VERSION_1_8;', '}']
    registration_markers.append(fallback_marker)
keeper += [f'extern void {symbol}(void);' for symbol in sorted(symbols)]
keeper += ['static void (* volatile retained[])(void) = {']
keeper += [f'    &{symbol},' for symbol in sorted(symbols)]
keeper += [f'    (void (*)(void))&{symbol},' for symbol in registration_markers]
keeper += ['};', 'void loadfunctions(void) {',
           '    for (size_t i = 0; i < sizeof(retained)/sizeof(retained[0]); ++i) {',
           '        void (* volatile symbol)(void) = retained[i]; (void)symbol;', '    }', '}']
(generated / 'native-symbols.c').write_text('\n'.join(keeper) + '\n')

def quoted(value):
    value = str(value)
    if '\n' in value or '"' in value: raise SystemExit('Unsupported build path character')
    return '"' + value + '"'
link = ['$(inherited)', '-Wl,-export_dynamic']
link += [quoted('-Wl,-force_load,' + str(p)) for p in runtime_forced + ocr_jni]
link += [quoted(p) for p in runtime_lazy + ocr_codecs]
settings = [
    'HEADER_SEARCH_PATHS = $(inherited) ' + quoted(runtime/'include') + ' ' + quoted(jni_md[0].parent),
    'OTHER_LDFLAGS = ' + ' '.join(link),
    'ARCHS = arm64', 'ONLY_ACTIVE_ARCH = YES',
]
(generated / 'native-libraries.xcconfig').write_text('\n'.join(settings) + '\n')

jar_inventory = []
for jar in sorted((resources / 'java').glob('*.jar')):
    with zipfile.ZipFile(jar) as archive:
        for name in archive.namelist():
            if re.search(r'\.(?:dll|dylib|so)(?:\.|$)', name, re.I):
                raise SystemExit(f'Desktop/dynamic native binary leaked into Java assets: {jar.name}!{name}')
            if name.endswith('.class'):
                data = archive.read(name)[:8]
                if len(data) == 8 and data[:4] == b'\xca\xfe\xba\xbe':
                    minor, major = struct.unpack('>HH', data[4:8])
                    if minor == 65535:
                        raise SystemExit(f'Preview bytecode cannot cross JDK versions: {jar.name}!{name}')
    jar_inventory.append({'name':jar.name,'bytes':jar.stat().st_size,
                          'sha256':hashlib.sha256(jar.read_bytes()).hexdigest()})
manifest = {'sdk':sdk, 'architecture':'arm64', 'nativeSymbolCount':len(symbols),
            'addedStaticRegistrationMarkers':registration_markers,
            'jars':jar_inventory, 'runtimeTested':False, 'fullScoreRecognitionTested':False,
            'nativeArchives':[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
                              for p in runtime_archives + ocr_jni + ocr_codecs]}
(resources/'build-inventory.json').write_text(json.dumps(manifest, indent=2)+'\n')
print(json.dumps({'jars':len(jar_inventory),'retainedNativeSymbols':len(symbols),'sdk':sdk}))
PY
# Production composition consumes the exact generated configuration/resources/bridge.
# Absolute header/archive paths remain valid in this build workspace.
if [ -e "$output/embedding" ]; then mv "$output/embedding" "$work/previous-embedding"; fi
mkdir -p "$output/embedding"
cp "$project/Generated/native-symbols.c" "$output/embedding/"
cp "$project/Generated/native-libraries.xcconfig" "$output/embedding/"
ditto "$resources" "$output/embedding/resources"
ditto "$repo/apple/EmbeddedOMRRuntime/Sources" "$output/embedding/bridge"
(
  cd "$project"
  xcodegen generate
  xcodebuild -project EmbeddedOMRProbe.xcodeproj -scheme EmbeddedOMRProbe \
    -configuration Release -sdk "$sdk" -derivedDataPath "$work/DerivedData" \
    ARCHS=arm64 CODE_SIGNING_ALLOWED=NO build
) 2>&1 | tee "$output/evidence/build.log"
product="$work/DerivedData/Build/Products/Release-$sdk/EmbeddedOMRProbe.app"
test -d "$product"
if [ -e "$output/EmbeddedOMRProbe.app" ]; then
  mv "$output/EmbeddedOMRProbe.app" "$work/previous-app"
fi
ditto "$product" "$output/EmbeddedOMRProbe.app"
cp "$resources/build-inventory.json" "$output/evidence/build-inventory.json"
xcodebuild -version > "$output/evidence/xcode-version.txt"
printf 'Built %s. Simulator/device execution has not been claimed.\n' "$output/EmbeddedOMRProbe.app"
if [ "$sdk" = iphonesimulator ]; then
  codesign --force --sign - "$output/EmbeddedOMRProbe.app"
  if [ -n "${NOTELITE_SIMULATOR_UDID:-}" ]; then
    bash "$repo/tools/audiveris-port/run-embedded-probe.sh" "$output/EmbeddedOMRProbe.app" \
      "$NOTELITE_SIMULATOR_UDID" "$output/simulator-results/$NOTELITE_SIMULATOR_UDID"
  fi
fi
