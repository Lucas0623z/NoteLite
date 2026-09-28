#!/usr/bin/env bash
# Cross-build the real OCR dependencies used by Audiveris, plus its JavaCPP JNI.
# Requires Xcode, CMake, Ninja, Git, and a host JDK 21. No signing credentials.
set -euo pipefail

sdk=${1:-iphonesimulator}
case "$sdk" in
  iphoneos) target=arm64-apple-ios16.0 ;;
  iphonesimulator) target=arm64-apple-ios16.0-simulator ;;
  *) echo "Usage: $0 iphoneos|iphonesimulator [output-directory]" >&2; exit 2 ;;
esac
repo=$(cd "$(dirname "$0")/../.." && pwd)
output=${2:-"$repo/build/ios-ocr/$sdk-arm64"}
mkdir -p "$output"
output=$(cd "$output" && pwd)
source_root="$repo/build/ios-ocr/sources"
build_root="$output/build"
prefix="$output/install"
mkdir -p "$source_root" "$build_root" "$prefix/lib" "$prefix/include" "$output/evidence"
test "$(uname -s)" = Darwin
: "${JAVA_HOME:?JAVA_HOME must point to a host JDK with JNI headers}"
test -f "$JAVA_HOME/include/jni.h"
sysroot=$(xcrun --sdk "$sdk" --show-sdk-path)
cc=$(xcrun --sdk "$sdk" --find clang)
cxx=$(xcrun --sdk "$sdk" --find clang++)
jobs=${BUILD_JOBS:-$(sysctl -n hw.logicalcpu)}
export PKG_CONFIG_LIBDIR="$prefix/lib/pkgconfig"
export PKG_CONFIG_PATH="$prefix/lib/pkgconfig"

fetch_source() {
  local name=$1 url=$2 commit=$3 destination="$source_root/$1"
  if [ ! -d "$destination/.git" ]; then
    git init -q "$destination"
    git -C "$destination" remote add origin "$url"
  fi
  # Do not silently reuse a cache containing a different remote or modified source.
  test "$(git -C "$destination" remote get-url origin)" = "$url"
  git -C "$destination" fetch --depth=1 origin "$commit"
  git -C "$destination" checkout --detach --quiet "$commit"
  test "$(git -C "$destination" rev-parse HEAD)" = "$commit"
  test -z "$(git -C "$destination" status --porcelain)"
  printf '%s\t%s\t%s\n' "$name" "$commit" "$url" >> "$output/evidence/sources.tsv"
  mkdir -p "$prefix/share/licenses/$name"
  find "$destination" -maxdepth 1 -type f \( -iname '*license*' -o -iname 'copying*' -o -iname '*copyright*' \) \
    -exec cp {} "$prefix/share/licenses/$name/" \;
}

: > "$output/evidence/sources.tsv"
fetch_source zlib https://github.com/madler/zlib.git 51b7f2abdade71cd9bb0e7a373ef2610ec6f9daf
fetch_source png https://github.com/pnggroup/libpng.git 872555f4ba910252783af1507f9e7fe1653be252
fetch_source jpeg https://github.com/libjpeg-turbo/libjpeg-turbo.git 20ade4dea9589515a69793e447a6c6220b464535
fetch_source tiff https://gitlab.com/libtiff/libtiff.git 9dff73bebc5661f2dace6f16e14cf9e857172f4e
fetch_source leptonica https://github.com/DanBloomberg/leptonica.git 63aef18d98432b8582a1565e241f7bd2ee9cc8d9
fetch_source tesseract https://github.com/tesseract-ocr/tesseract.git 3b7c70e34dea179549ed3e995872e2e019eb8477

common=(
  -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_POLICY_VERSION_MINIMUM=3.5
  -DCMAKE_SYSTEM_NAME=iOS -DCMAKE_SYSTEM_PROCESSOR=arm64
  "-DCMAKE_OSX_SYSROOT=$sysroot" -DCMAKE_OSX_ARCHITECTURES=arm64
  -DCMAKE_OSX_DEPLOYMENT_TARGET=16.0 -DCMAKE_MACOSX_BUNDLE=OFF
  "-DCMAKE_C_COMPILER=$cc" "-DCMAKE_CXX_COMPILER=$cxx"
  -DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY
  -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DBUILD_SHARED_LIBS=OFF
  "-DCMAKE_INSTALL_PREFIX=$prefix" -DCMAKE_INSTALL_LIBDIR=lib
  "-DCMAKE_PREFIX_PATH=$prefix" "-DCMAKE_FIND_ROOT_PATH=$prefix;$sysroot"
  -DCMAKE_FIND_ROOT_PATH_MODE_PROGRAM=NEVER
  -DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY -DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY
  -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ONLY
)

build_install() {
  local name=$1
  shift
  cmake -S "$source_root/$name" -B "$build_root/$name" "${common[@]}" "$@"
  cmake --build "$build_root/$name" --parallel "$jobs"
  cmake --install "$build_root/$name"
}

build_install zlib -DZLIB_BUILD_EXAMPLES=OFF
codec_paths=("-DZLIB_INCLUDE_DIR=$prefix/include" "-DZLIB_LIBRARY=$prefix/lib/libz.a")
build_install png "${codec_paths[@]}" -DPNG_SHARED=OFF -DPNG_STATIC=ON -DPNG_FRAMEWORK=OFF \
  -DPNG_TESTS=OFF -DPNG_TOOLS=OFF -DPNG_EXECUTABLES=OFF
build_install jpeg -DENABLE_SHARED=OFF -DENABLE_STATIC=ON -DWITH_SIMD=OFF -DWITH_TURBOJPEG=OFF -DWITH_JAVA=OFF
codec_paths+=("-DPNG_PNG_INCLUDE_DIR=$prefix/include" "-DPNG_LIBRARY=$prefix/lib/libpng16.a"
              "-DJPEG_INCLUDE_DIR=$prefix/include" "-DJPEG_LIBRARY=$prefix/lib/libjpeg.a")
build_install tiff "${codec_paths[@]}" -Dtiff-tools=OFF -Dtiff-tests=OFF -Dtiff-contrib=OFF \
  -Dtiff-docs=OFF -Dtiff-install=ON -Dtiff-opengl=OFF -Dcxx=OFF \
  -Dzlib=ON -Djpeg=ON -Dlibdeflate=OFF -Djbig=OFF -Dlerc=OFF -Dlzma=OFF -Dzstd=OFF -Dwebp=OFF
codec_paths+=("-DTIFF_INCLUDE_DIR=$prefix/include" "-DTIFF_LIBRARY=$prefix/lib/libtiff.a")
# TIFF's static export contains CMath::CMath, ZLIB::ZLIB and JPEG::JPEG.
# Leptonica 1.85 copies that interface without finding CMath itself. Resolve
# the real SDK math library through TIFF's own finder before importing it,
# and preload the codec targets before Tesseract imports static Leptonica.
cat > "$build_root/codec-dependencies.cmake" <<EOF
list(APPEND CMAKE_MODULE_PATH "$source_root/tiff/cmake")
find_package(CMath REQUIRED)
find_package(ZLIB REQUIRED)
find_package(JPEG REQUIRED)
find_package(PNG REQUIRED)
find_package(TIFF REQUIRED)
EOF
codec_imports=("-DCMAKE_PROJECT_INCLUDE=$build_root/codec-dependencies.cmake")
build_install leptonica "${codec_paths[@]}" "${codec_imports[@]}" -DBUILD_PROG=OFF -DSW_BUILD=OFF -DSTRICT_CONF=ON \
  -DENABLE_ZLIB=ON -DENABLE_PNG=ON -DENABLE_JPEG=ON -DENABLE_TIFF=ON \
  -DENABLE_GIF=OFF -DENABLE_WEBP=OFF -DENABLE_OPENJPEG=OFF
# A device binary cannot be run by CMake's host-side try_run. The supplied answer
# is a cross-build assumption, checked by the simulator TIFF round-trip below.
build_install tesseract "${codec_paths[@]}" "${codec_imports[@]}" "-DLeptonica_DIR=$prefix/lib/cmake/leptonica" \
  -DLEPT_TIFF_RESULT=0 -DBUILD_TRAINING_TOOLS=OFF -DBUILD_TESTS=OFF -DSW_BUILD=OFF \
  -DOPENMP_BUILD=OFF -DENABLE_NATIVE=OFF -DENABLE_LTO=OFF -DGRAPHICS_DISABLED=ON \
  -DDISABLE_TIFF=OFF -DDISABLE_ARCHIVE=ON -DDISABLE_CURL=ON

if [ ! -f "$repo/app/build/ios-jni/jnileptonica.cpp" ]; then
  (cd "$repo" && bash ./gradlew --no-daemon -I tools/audiveris-port/oracle.gradle :app:portJNI)
fi
native_flags=(-target "$target" -isysroot "$sysroot" -O2 -std=c++17 -fPIC
              "-I$prefix/include" "-I$JAVA_HOME/include" "-I$JAVA_HOME/include/darwin" -DJAVACPP_STATIC)
for library in jnijavacpp jnileptonica jnitesseract; do
  flags=()
  if [ "$library" != jnijavacpp ]; then
    # The original generated files use the dynamic-library entry name. Give
    # each one the statically linked JNI name recognized by an embedded JVM.
    flags=("-DJNI_OnLoad=JNI_OnLoad_$library" "-DJNI_OnUnload=JNI_OnUnload_$library")
  fi
  "$cxx" "${native_flags[@]}" "${flags[@]}" -c "$repo/app/build/ios-jni/$library.cpp" -o "$build_root/$library.o"
  xcrun --sdk "$sdk" ar rcs "$prefix/lib/lib$library.a" "$build_root/$library.o"
done

mkdir -p "$prefix/share/tessdata" "$prefix/bin"
model_commit=4767ea922bcc460e70b87b1d303ebdfed0897da8
model_hash=daa0c97d651c19fba3b25e81317cd697e9908c8208090c94c3905381c23fc047
curl --fail --location --retry 3 \
  "https://raw.githubusercontent.com/tesseract-ocr/tessdata/$model_commit/eng.traineddata" \
  -o "$prefix/share/tessdata/eng.traineddata"
printf '%s  %s\n' "$model_hash" "$prefix/share/tessdata/eng.traineddata" | shasum -a 256 -c -
curl --fail --location --retry 3 \
  "https://raw.githubusercontent.com/tesseract-ocr/tessdata/$model_commit/LICENSE" \
  -o "$prefix/share/tessdata/LICENSE"
printf 'tessdata/eng\t%s\tsha256:%s\n' "$model_commit" "$model_hash" >> "$output/evidence/sources.tsv"

# Force every JNI object into the link so omitted Leptonica/Tesseract symbols
# cause an error now, even though this smoke test does not start a Java VM.
"$cxx" "${native_flags[@]}" "$repo/tools/audiveris-port/ocr-smoke.cpp" \
  "-Wl,-force_load,$prefix/lib/libjnijavacpp.a" \
  "-Wl,-force_load,$prefix/lib/libjnileptonica.a" \
  "-Wl,-force_load,$prefix/lib/libjnitesseract.a" \
  "$prefix/lib/libtesseract.a" "$prefix/lib/libleptonica.a" "$prefix/lib/libtiff.a" \
  "$prefix/lib/libpng16.a" "$prefix/lib/libjpeg.a" "$prefix/lib/libz.a" \
  -framework Foundation -o "$prefix/bin/ocr-smoke"
codesign --force --sign - "$prefix/bin/ocr-smoke"
xcrun --sdk "$sdk" lipo -verify_arch arm64 "$prefix/bin/ocr-smoke"
xcrun vtool -show-build "$prefix/bin/ocr-smoke" > "$output/evidence/platform.txt"
xcrun nm -gU "$prefix/bin/ocr-smoke" > "$output/evidence/linked-symbols.txt"
for symbol in JNI_OnLoad_jnijavacpp JNI_OnLoad_jnileptonica JNI_OnLoad_jnitesseract pixReadMemTiff TessBaseAPICreate; do
  grep -q "_$symbol$" "$output/evidence/linked-symbols.txt"
done
for library in z png16 jpeg tiff leptonica tesseract jnijavacpp jnileptonica jnitesseract; do
  xcrun --sdk "$sdk" lipo -verify_arch arm64 "$prefix/lib/lib$library.a"
  shasum -a 256 "$prefix/lib/lib$library.a"
done > "$output/evidence/archive-sha256.txt"
xcodebuild -version > "$output/evidence/toolchain.txt"
cmake --version >> "$output/evidence/toolchain.txt"
"$JAVA_HOME/bin/java" -version 2>> "$output/evidence/toolchain.txt"
printf '%s\n' "Built $target native OCR + static JNI. Java VM integration has not run." \
  "Simulator execution, when applicable, is recorded separately in smoke.log." \
  > "$output/evidence/STATUS.txt"
printf 'OCR installation: %s\n' "$prefix"
