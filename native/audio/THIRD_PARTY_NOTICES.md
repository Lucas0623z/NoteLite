# Vendored native audio dependency

**miniaudio 0.11.25**, David Reid / mackron.

- Upstream: https://github.com/mackron/miniaudio
- Fixed release: https://github.com/mackron/miniaudio/releases/tag/0.11.25
- Header source: https://raw.githubusercontent.com/mackron/miniaudio/0.11.25/miniaudio.h
- Header SHA-256: `ac7af4de748b7e26b777f37e01cee313a308a7296a3eb080e2906b320cc55c89`
- License source: https://raw.githubusercontent.com/mackron/miniaudio/0.11.25/LICENSE
- License SHA-256: `457f1b500e0adf6bc059edddfa78a2f62012e7c3bb43476c20e0bd23b25ba0eb`
- Chosen license: MIT No Attribution (alternative 2). The original complete
  dual-license notice is preserved in `vendor/miniaudio/LICENSE`.

The header is unmodified. Its embedded dr_wav decoder/encoder notices are
preserved verbatim. Unneeded MP3/FLAC/resource-manager/engine features
are disabled by preprocessor definitions in the NoteLite translation unit.
Neither build nor runtime fetches miniaudio from the network.

MPM and YIN pitch code in this directory was implemented for NoteLite from the
published mathematical equations. No aubio, Essentia, TarsosDSP, Pitchy, libsndfile
or other pitch-detector implementation is included in `NoteLiteAudio.exe`.

## Optional recorded-analysis executables

`AubioMono.exe` statically links actual **aubio 0.4.9**, Paul Brossier and
contributors, GPL-3.0-or-later. Pinned source and original `COPYING` are at
`local-analysis/vendor/aubio/`. Official archive SHA-256:
`d48282ae4dab83b3dc94c16cf011bcb63835c1c02b515490e1883049c3d1f3da`.
Upstream: https://aubio.org/ . The adapter `aubio_mono.c` is GPL-3.0-or-later
when linked into this executable. Its WAV decoder preserves the miniaudio
license notices above. This is a separate process from the MIT MPM/YIN helper.

The nine **Nakamura alignment tools, MIT240109 release**, are compiled from
unchanged source at `local-analysis/vendor/nakamura/Code/`, with the original
`LICENCE.txt` retained. Official archive SHA-256:
`cf75af54435c6ad83a7b578b691724866f6df5701e8529d86ae2a3db1e85bddd`.
Upstream: https://midialignment.github.io/ . A command-line definition of `M_PI`
supplies the mathematical constant on Windows; the upstream files are unchanged.
The local-analysis distribution must include these corresponding sources,
licenses, and attributions alongside the built executables.

GCC/MinGW builds statically link GCC runtime support; the Nakamura builds also
link libstdc++. The GCC Runtime Library Exception 3.1 and GPLv3 notices are
retained under `vendor/gcc-runtime/`. This exception permits eligible compiled
programs to be distributed under their own licenses. The verified MinGW C++
build retains its compiler's matching CRT and bundles `libwinpthread-1.dll`
beside the Nakamura executables. The original MinGW-w64/winpthreads license notices are
also retained under `vendor/gcc-runtime/`.
