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
preserved verbatim. Unneeded MP3/FLAC/playback/resource-manager/engine features
are disabled by preprocessor definitions in the NoteLite translation unit.
Neither build nor runtime fetches miniaudio from the network.

MPM and YIN pitch code in this directory was implemented for NoteLite from the
published mathematical equations. No aubio, Essentia, TarsosDSP, Pitchy, libsndfile
or other pitch-detector implementation is included in this executable.
