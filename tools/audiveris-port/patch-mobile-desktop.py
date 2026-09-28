#!/usr/bin/env python3
"""Apply the reviewed headless adaptation to the pinned OpenJDK Mobile source.

This enables real OpenJDK software image/font rendering. It does not implement
AWT windows, printing, audio, or a Cocoa toolkit; none is required by batch OMR.
Each patch checks its source context and fails if upstream has changed.
"""
from pathlib import Path
import argparse
import re
import subprocess

SOURCE_COMMIT = "c1ed06aaef34c8dccf71e236d1ffa20918a77cfb"


def replace(root: Path, relative: str, old: str, new: str) -> None:
    path = root / relative
    source = path.read_text(encoding="utf-8")
    if source.count(old) != 1:
        raise SystemExit(f"Unexpected source patch context: {relative}: {old!r}")
    path.write_text(source.replace(old, new), encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    root = args.source.resolve()
    commit = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if commit != SOURCE_COMMIT:
        raise SystemExit(f"Expected {SOURCE_COMMIT}, found {commit}")

    # Zero's code buffers contain ZeroEntry records pointing at precompiled
    # C++ functions (assembler_zero.hpp, zeroInterpreterGenerator.hpp and
    # entry_zero.hpp), not emitted machine code. The upstream generic code
    # cache still requests executable memory, which a signed iOS process
    # cannot grant without a JIT entitlement. Keep these data buffers RW.
    # replace() asserts that this pinned allocation call appears exactly once.
    replace(root, "src/hotspot/share/memory/memoryReserver.cpp",
            "  return MemoryReserver::reserve(nullptr /* requested_address */,\n"
            "                                 size,\n"
            "                                 alignment,\n"
            "                                 page_size,\n"
            "                                 ExecMem,\n"
            "                                 mtCode);",
            "  // Zero stores interpreter entry records here, not machine code.\n"
            "  // iOS must not require a JIT entitlement for those data buffers.\n"
            "#if defined(__IOS__) && defined(ZERO)\n"
            "  const bool executable = false;\n"
            "#else\n"
            "  const bool executable = ExecMem;\n"
            "#endif\n"
            "  return MemoryReserver::reserve(nullptr /* requested_address */,\n"
            "                                 size,\n"
            "                                 alignment,\n"
            "                                 page_size,\n"
            "                                 executable,\n"
            "                                 mtCode);")

    replace(root, "make/modules/java.desktop/Lib.gmk",
            "ifeq ($(call isTargetOs, android ios), false)",
            "ifeq ($(call isTargetOs, android), false)")
    replace(root, "make/modules/java.desktop/Lib.gmk",
            "include LibCommon.gmk\n",
            "include LibCommon.gmk\n\n"
            "# Headless iOS does not compile CUPS code; do not inject macOS SDK headers.\n"
            "ifeq ($(call isTargetOs, ios), true)\n"
            "  CUPS_CFLAGS :=\n"
            "endif\n")
    awt = "make/modules/java.desktop/lib/AwtLibraries.gmk"
    replace(root, awt,
            "ifeq ($(call isTargetOs, linux macosx aix), true)",
            "ifeq ($(call isTargetOs, linux macosx aix ios), true)")
    # awt_Font.c stays in libawt_headless: it defines java.awt.Font.initIDs.
    # Font discovery is supplied by MobileFontManager, so neither FontConfig
    # nor X11 nor CUPS is used by this target.
    replace(root, awt, "  LIBAWT_HEADLESS_EXTRA_HEADER_DIRS :=",
            "  ifeq ($(call isTargetOs, ios), true)\n"
            "    LIBAWT_HEADLESS_EXCLUDE_FILES += fontpath.c CUPSfuncs.c "
            "X11Color.c X11FontScaler_md.c\n"
            "  endif\n\n  LIBAWT_HEADLESS_EXTRA_HEADER_DIRS :=")
    # JAWT is an interface for embedding desktop native windows. Its Unix
    # headers require X11 even in a headless build; it is not an OMR dependency.
    replace(root, awt, "LIBJAWT_EXTRA_HEADER_DIRS :=",
            "ifeq ($(call isTargetOs, ios), false)\nLIBJAWT_EXTRA_HEADER_DIRS :=")
    replace(root, awt, "TARGETS += $(BUILD_LIBJAWT)",
            "TARGETS += $(BUILD_LIBJAWT)\nendif # no native desktop windows on iOS")
    replace(root, "make/modules/java.desktop/lib/ClientLibraries.gmk",
            "else ifeq ($(call isTargetOs, macosx), true)",
            "else ifeq ($(call isTargetOs, macosx ios), true)")

    # mediaLib otherwise selects Linux malloc.h/memalign because iOS does not
    # define MACOSX. arm64 malloc already provides the required 8-byte
    # alignment, and stdlib.h declares it on iOS. Do not enable Cocoa paths
    # elsewhere by adding a global MACOSX define.
    medialib = "src/java.desktop/share/native/common/awt/medialib/mlib_sys.c"
    replace(root, medialib,
            "#else\n#include <malloc.h>\n#endif",
            "#elif !defined(__IOS__)\n#include <malloc.h>\n#endif")
    replace(root, medialib,
            "#if defined(_MSC_VER) || defined(AIX)\n",
            "// iOS arm64 malloc also supplies at least 8-byte alignment.\n"
            "#if defined(_MSC_VER) || defined(AIX) || defined(__IOS__)\n")

    # The OCR bundle contains libjpeg-turbo, while javajpeg contains IJG6b.
    # A static process must not interpose one implementation's functions onto
    # the other's private state. Prefix the bundled JDK C symbols, preserving
    # its JNI entry points and original pixel behavior.
    jpeg = root / "src/java.desktop/share/native/libjavajpeg"
    symbols = set()
    for source in jpeg.glob("*.c"):
        symbols.update(re.findall(r"\bGLOBAL\s*\([^)]*\)\s*([A-Za-z_]\w*)\s*\(",
                                  source.read_text(encoding="utf-8")))
    symbols = {name for name in symbols if not name.startswith(("imageio_", "sun_"))}
    symbols.update(("jpeg_std_message_table", "jpeg_zigzag_order", "jpeg_natural_order"))
    if len(symbols) != 102 or "jpeg_CreateDecompress" not in symbols:
        raise SystemExit(f"Unexpected pinned JPEG symbol inventory: {len(symbols)}")
    prefix = jpeg / "notelite_jpeg_symbols.h"
    prefix.write_text(
        "/* SPDX-License-Identifier: GPL-2.0-only WITH Classpath-exception-2.0 */\n"
        "/* Isolate bundled IJG6b from the independently linked OCR codec. */\n"
        "#ifndef NOTELITE_JDK_JPEG_SYMBOLS_H\n#define NOTELITE_JDK_JPEG_SYMBOLS_H\n"
        + "".join(f"#define {name} notelite_jdk_{name}\n" for name in sorted(symbols))
        + "#endif\n", encoding="utf-8", newline="\n")
    replace(root, "make/modules/java.desktop/lib/ClientLibraries.gmk",
            "    NAME := javajpeg, \\\n",
            "    NAME := javajpeg, \\\n"
            "    CFLAGS_ios := -include $(TOPDIR)/src/java.desktop/share/native/"
            "libjavajpeg/notelite_jpeg_symbols.h, \\\n")

    # iOS imports macosx/classes in upstream Modules.gmk. Keep all six classes
    # together there so the matching host build-JDK can also compile this tree.
    source_classes = Path(__file__).resolve().parent / "mobile-desktop"
    destination = root / "src/java.desktop/macosx/classes"
    installed = []
    for source in sorted(source_classes.rglob("*.java")):
        relative = source.relative_to(source_classes)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        text = source.read_text(encoding="utf-8")
        if target.exists():
            # Preserve the original copyright/license when replacing an
            # upstream platform entry point.
            text = target.read_text(encoding="utf-8").split("package ", 1)[0] + text
        target.write_text(text, encoding="utf-8", newline="\n")
        installed.append(target.relative_to(root).as_posix())
    if len(installed) != 6:
        raise SystemExit(f"Expected six platform classes, found {len(installed)}")
    # Intent-to-add makes the saved git diff include the new platform classes.
    subprocess.run(["git", "-C", str(root), "add", "--intent-to-add", "--", *installed],
                   check=True)
    subprocess.run(["git", "-C", str(root), "add", "--intent-to-add", "--",
                    prefix.relative_to(root).as_posix()], check=True)
    print(f"Applied headless software raster/font adaptation to {commit}")
    print("\n".join(installed))


if __name__ == "__main__":
    main()
