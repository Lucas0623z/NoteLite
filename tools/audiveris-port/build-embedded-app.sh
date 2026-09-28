#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Compose the real NoteLite app with the exact static runtime used by the probe.
set -euo pipefail
sdk=${1:-iphonesimulator}
case "$sdk" in iphoneos|iphonesimulator) ;; *) echo "Expected iphoneos or iphonesimulator" >&2; exit 2 ;; esac
repo=$(cd "$(dirname "$0")/../.." && pwd)
embedding=${2:?Pass the probe output/embedding directory}
output=${3:-"$repo/build/embedded-app/$sdk-arm64"}
test "$(uname -s)" = Darwin
command -v xcodegen >/dev/null
command -v python3 >/dev/null
embedding=$(cd "$embedding" && pwd)
mkdir -p "$output"
output=$(cd "$output" && pwd)
for file in native-symbols.c native-libraries.xcconfig resources/build-inventory.json \
    resources/runtime/lib/modules resources/tessdata/eng.traineddata bridge/EmbeddedJVM.h bridge/EmbeddedJVM.mm; do
  test -f "$embedding/$file"
done
work=$(mktemp -d "$output/build.XXXXXX")
project="$work/project"
mkdir -p "$project/Generated" "$output/evidence"
ditto "$embedding/resources" "$project/Generated/OMRResources"
ditto "$embedding/bridge" "$project/EmbeddedRuntime"
cp "$embedding/native-symbols.c" "$project/Generated/"
cp "$embedding/native-libraries.xcconfig" "$project/Generated/"

python3 - "$repo" "$embedding" "$project" "$sdk" <<'PY'
import hashlib, json, re, sys
from pathlib import Path
repo, embedding, project = map(Path, sys.argv[1:4])
sdk = sys.argv[4]
inventory = json.loads((embedding / 'resources/build-inventory.json').read_text())
if inventory.get('sdk') != sdk or inventory.get('architecture') != 'arm64':
    raise SystemExit('The probe artifacts do not match the requested SDK and arm64 architecture')
for entry in inventory['nativeArchives']:
    archive = Path(entry['path'])
    if not archive.is_file():
        raise SystemExit('Native archive paths must remain available in this workspace: ' + entry['path'])
    digest = hashlib.sha256()
    with archive.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != entry['sha256']:
        raise SystemExit('A native archive changed after probe composition: ' + entry['path'])
config = (embedding / 'native-libraries.xcconfig').read_text()
for header in re.findall(r'"([^"]+)"', config.split('HEADER_SEARCH_PATHS = ', 1)[1].splitlines()[0]):
    if not Path(header).is_dir():
        raise SystemExit('Missing JNI include directory: ' + header)

# XcodeGen rebases source/package paths from the included project. Explicitly
# set the Info.plist build setting because arbitrary settings are plain strings.
spec = {
    'include': [{'path': str(repo / 'apple/project.yml'), 'relativePaths': True}],
    'packages': {'AudiverisCore': {'path': str(repo / 'apple/AudiverisCore')}},
    'targets': {'NoteLite': {
        'configFiles': {'Debug': 'Generated/native-libraries.xcconfig',
                        'Release': 'Generated/native-libraries.xcconfig'},
        'sources': [
            {'path': 'EmbeddedRuntime'},
            {'path': 'Generated/native-symbols.c'},
            {'path': 'Generated/OMRResources', 'type': 'folder', 'buildPhase': 'resources'},
        ],
        'settings': {'base': {
            'SWIFT_ACTIVE_COMPILATION_CONDITIONS': '$(inherited) EMBEDDED_OMR_RUNTIME',
            'SWIFT_OBJC_BRIDGING_HEADER': str(project / 'EmbeddedRuntime/EmbeddedJVM.h'),
            'INFOPLIST_FILE': str(repo / 'apple/NoteLite/Info.plist'),
            'CLANG_CXX_LANGUAGE_STANDARD': 'c++17',
            'GCC_SYMBOLS_PRIVATE_EXTERN': 'NO',
            'DEAD_CODE_STRIPPING': 'NO',
            'ENABLE_DEBUG_DYLIB': 'NO',
        }},
        'dependencies': [{'sdk': name} for name in (
            'Foundation.framework', 'UIKit.framework', 'CoreFoundation.framework',
            'CoreGraphics.framework', 'CoreText.framework', 'libc++.tbd', 'libiconv.tbd', 'libz.tbd')],
    }, 'NoteLiteOfflineUITests': {
        'type': 'bundle.ui-testing', 'platform': 'iOS',
        'sources': [{'path': str(repo / 'apple/NoteLiteOfflineUITests')}],
        'settings': {'base': {
            'PRODUCT_BUNDLE_IDENTIFIER': 'com.notelite.mobile.offline-uitests',
            'GENERATE_INFOPLIST_FILE': 'YES',
            'TEST_TARGET_NAME': 'NoteLite',
        }},
        'dependencies': [{'target': 'NoteLite'}],
    }},
    'schemes': {'NoteLiteOffline': {
        'build': {'targets': {'NoteLite': 'all', 'NoteLiteOfflineUITests': ['test']}},
        'test': {'config': 'Debug', 'macroExpansion': 'NoteLite',
                 'targets': ['NoteLiteOfflineUITests']},
    }},
}
(project / 'embedded-project.json').write_text(json.dumps(spec, indent=2) + '\n')
PY
cp "$project/embedded-project.json" "$output/evidence/embedded-project.json"
cp "$project/Generated/native-libraries.xcconfig" "$output/evidence/"
printf '%s\n' "$project" > "$output/evidence/project-location.txt"
(
  cd "$project"
  xcodegen generate --spec embedded-project.json
  xcodebuild -project NoteLite.xcodeproj -scheme NoteLite -configuration Release \
    -sdk "$sdk" -derivedDataPath "$work/DerivedData" ARCHS=arm64 \
    CODE_SIGNING_ALLOWED=NO build
) 2>&1 | tee "$output/evidence/build.log"
product="$work/DerivedData/Build/Products/Release-$sdk/NoteLite.app"
test -d "$product"
if [ "$sdk" = iphonesimulator ]; then codesign --force --sign - "$product"; fi

# Verify every embedded byte against the resources used by the acceptance probe,
# and check that app assets, native methods, and the iPhone/iPad target survived.
python3 - "$repo" "$embedding" "$product" "$sdk" "$output/evidence" <<'PY'
import hashlib, json, plistlib, re, subprocess, sys
from pathlib import Path
repo, embedding, app = map(Path, sys.argv[1:4])
sdk, evidence = sys.argv[4], Path(sys.argv[5])
def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()
info = plistlib.loads((app / 'Info.plist').read_bytes())
source_info = plistlib.loads((repo / 'apple/NoteLite/Info.plist').read_bytes())
binary = app / info['CFBundleExecutable']
if not binary.is_file(): raise SystemExit('The built app executable is missing')
if set(info.get('UIDeviceFamily', [])) != {1, 2}:
    raise SystemExit('The app must support both iPhone and iPad')
for key in ('CFBundleDisplayName', 'CFBundleDocumentTypes', 'UTImportedTypeDeclarations',
            'UTExportedTypeDeclarations', 'NSMicrophoneUsageDescription'):
    if key in source_info and source_info[key] != info.get(key):
        raise SystemExit('The embedded build changed original app metadata: ' + key)
subprocess.run(['xcrun', 'lipo', str(binary), '-verify_arch', 'arm64'], check=True)
load_commands = subprocess.check_output(['xcrun', 'vtool', '-show-build', str(binary)], text=True)
(evidence / 'macho-build.txt').write_text(load_commands)
expected_platform = 'IOSSIMULATOR' if sdk == 'iphonesimulator' else 'IOS'
if not re.search(r'\bplatform\s+' + expected_platform + r'\b', load_commands):
    raise SystemExit('The executable has the wrong Mach-O platform for ' + sdk)
symbols = subprocess.check_output(['xcrun', 'nm', '-gU', str(binary)], text=True)
required = ['JNI_CreateJavaVM', 'JNI_OnLoad_jnijavacpp',
            'JNI_OnLoad_jnileptonica', 'JNI_OnLoad_jnitesseract', 'loadfunctions']
for symbol in required:
    if not re.search(r'\b_' + re.escape(symbol) + r'$', symbols, re.M):
        raise SystemExit('The app is missing a statically linked native entry point: ' + symbol)

bundled = app / 'OMRResources'
inventory = []
for original in sorted((embedding / 'resources').rglob('*')):
    if not original.is_file(): continue
    relative = original.relative_to(embedding / 'resources')
    installed = bundled / relative
    checksum = digest(original)
    if not installed.is_file() or digest(installed) != checksum:
        raise SystemExit('Embedded resource differs from the tested probe: ' + str(relative))
    inventory.append({'path':str(relative), 'bytes':installed.stat().st_size, 'sha256':checksum})
if not inventory or not (bundled / 'runtime/lib/modules').is_file():
    raise SystemExit('The runtime image is missing')
assets = list((bundled / 'assets').glob('*'))
if not any(p.suffix.lower() == '.otf' for p in assets) or not any(p.suffix.lower() == '.zip' for p in assets):
    raise SystemExit('Music fonts or the Audiveris classifier model are missing')
for original in (repo / 'app/res/practice').rglob('*'):
    if original.is_file():
        installed = app / 'practice' / original.relative_to(repo / 'app/res/practice')
        if not installed.is_file() or digest(original) != digest(installed):
            raise SystemExit('A bundled practice resource is missing or changed: ' + str(original))
if not (app / 'Assets.car').is_file(): raise SystemExit('Compiled app icons and assets are missing')
report = {
    'sdk': sdk, 'architecture': 'arm64', 'bundleIdentifier':info['CFBundleIdentifier'],
    'deviceFamilies':info['UIDeviceFamily'], 'embeddedRuntimeEnabled':True,
    'executableBytes':binary.stat().st_size, 'executableSHA256':digest(binary),
    'bundledResourceBytes':sum(item['bytes'] for item in inventory),
    'nativeEntryPoints':required, 'resources':inventory,
    'signedForDistribution':False, 'productionAppRecognitionExecuted':False,
}
(evidence / 'app-inventory.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({key: report[key] for key in ('bundleIdentifier', 'sdk', 'executableBytes', 'bundledResourceBytes')}))
PY
if [ -e "$output/NoteLite.app" ]; then mv "$output/NoteLite.app" "$work/previous-app"; fi
ditto "$product" "$output/NoteLite.app"
xcodebuild -version > "$output/evidence/xcode-version.txt"
printf 'Built offline NoteLite app: %s\n' "$output/NoteLite.app"
printf 'Build evidence: %s. Production-app recognition still requires an actual run.\n' "$output/evidence"

if [ "${NOTELITE_EMBEDDED_ARCHIVE:-0}" = 1 ]; then
  if [ "$sdk" != iphoneos ]; then
    echo "A device archive requires the iphoneos target." >&2; exit 2
  fi
  archive="$output/NoteLite.xcarchive"
  if [ -e "$archive" ]; then mv "$archive" "$work/previous-archive"; fi
  (
    cd "$project"
    xcodebuild archive -project NoteLite.xcodeproj -scheme NoteLite -configuration Release \
      -destination 'generic/platform=iOS' -derivedDataPath "$work/DerivedData" \
      -archivePath "$archive" ARCHS=arm64 CODE_SIGNING_ALLOWED=NO
  ) 2>&1 | tee "$output/evidence/archive.log"
  python3 - "$archive" "$output/evidence" <<'PY'
import hashlib, json, plistlib, subprocess, sys
from pathlib import Path
archive, evidence = map(Path, sys.argv[1:])
info = plistlib.loads((archive / 'Info.plist').read_bytes())
relative = Path(info['ApplicationProperties']['ApplicationPath'])
products = (archive / 'Products').resolve()
app = (products / relative).resolve()
if not app.is_relative_to(products) or not app.is_dir():
    raise SystemExit('The archive does not contain its declared application')
inventory = json.loads((evidence / 'app-inventory.json').read_text())
for entry in inventory['resources']:
    resource = app / 'OMRResources' / entry['path']
    if not resource.is_file() or hashlib.sha256(resource.read_bytes()).hexdigest() != entry['sha256']:
        raise SystemExit('The archive lost or changed an embedded resource: ' + entry['path'])
app_info = plistlib.loads((app / 'Info.plist').read_bytes())
if set(app_info.get('UIDeviceFamily', [])) != {1, 2}:
    raise SystemExit('The archived app must support iPhone and iPad')
binary = app / app_info['CFBundleExecutable']
subprocess.run(['xcrun', 'lipo', str(binary), '-verify_arch', 'arm64'], check=True)
(evidence / 'archive-inventory.json').write_text(json.dumps({
    'applicationPath': str(relative), 'embeddedResourceCount': len(inventory['resources']),
    'bundleIdentifier': app_info['CFBundleIdentifier'], 'signedForDistribution': False,
}, indent=2) + '\n')
PY
  ditto -c -k --sequesterRsrc --keepParent "$archive" "$output/NoteLite.xcarchive.zip"
  printf 'Created unsigned offline device archive: %s\n' "$output/NoteLite.xcarchive.zip"
fi
