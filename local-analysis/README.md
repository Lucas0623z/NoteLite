# Windows local recorded-audio analysis

NoteLite uses Spotify Basic Pitch **0.4.0** with its **ICASSP 2022 ONNX model** for
completed audio recordings. The helper runs on a bundled **CPython 3.11.9 x64**,
with **ONNX Runtime 1.20.1**, entirely on the user's computer. It complements the
existing live microphone/MIDI practice path. Audiveris OMR remains local.

## Install and package

From the repository root, on Windows x64:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File local-analysis/install-windows.ps1 -Destination app/build/local-analysis
```

The installer downloads only the exact Python archive and package artifacts in
`windows-lock.json`, checks every SHA-256 digest before extraction, extracts the
local model from the pinned Basic Pitch wheel, and imports the real inference
library and loads the model before creating `runtime-ready.json`. No pip resolver
or source-package build scripts run. Pretty MIDI publishes a pure Python source
archive; only its package files are extracted. Python 3.11's upstream Basic Pitch
TensorFlow dependency is intentionally omitted because this adapter explicitly
loads the supported ONNX model. All actually used dependencies are pinned.

The default cache is `local-analysis/cache`. After one successful download, the
same command with `-Offline` reinstalls using that verified cache with no network.
Use `-Cache <absolute-directory>` to supply a pre-seeded cache to a disconnected
Windows build machine. Preserve the complete installed directory when copying it
to the application's `tools/local-analysis`; users need no Python installation.

The Java service discovers the directory beside the installed application. For a
development run, `-Dnotelite.analysis.home=<absolute-directory>` or the environment
variable `NOTELITE_ANALYSIS_HOME` selects an explicit runtime. An invalid explicit
override is reported as unavailable rather than silently selecting another one.

## Runtime contract

```powershell
tools/local-analysis/python/python.exe tools/local-analysis/analyze.py --input C:/takes/take.wav --output C:/takes/notes.json
```

Input/output paths must be absolute and different. Input must be a complete
16-bit PCM WAV, mono or stereo, 8000–96000 Hz, up to 64 MB and 600 seconds. No
uploads, downloads, model fetching, score data, or microphone access occur in the
helper. A successful result is UTF-8 JSON:

```json
{"schemaVersion":1,"engine":"basic-pitch","seconds":6.0,"notes":[{"midi":60,"onset":0.998458,"duration":1.278381,"confidence":0.655851}]}
```

Onsets/durations are seconds from the actual WAV start. Notes retain exact MIDI
pitch, including octave and simultaneous chord tones. Python validates the input;
Java validates input and output again, limits concurrency to one analysis, enforces
a five-minute process timeout, terminates interrupted processes, and removes its
temporary recording/result/cache files. Java `LocalAudioAnalysis.analyze(byte[])`
returns the validated JSON bytes for the loopback HTTP service.

`practice-web/src/recorded-analysis.js` exports
`analyzeRecording(groups, notes, {bpm, toleranceMs, offsetSeconds,
confidenceThreshold})`. Score onset/duration units are quarter-note beats. The
report shares `PracticeSession.report()` keys and preserves score note identities,
actual onset timestamps, detected releases and confidence. Alignment removes only
a constant offset: explicit `offsetSeconds`, or the first confident detected onset.
It does not alter the selected tempo or warp performance rhythm. Ordered attacks
at each exact pitch recover after insertions/deletions, and a held note can satisfy
only one repeated score attack. Wrong octaves never count as correct.

The default confidence threshold is **0.4**. Weak detections remain in `notes`,
`played`, and `unjudged` diagnostics, but are not graded as wrong/extra. A weak
same-pitch attack close to a missing score note marks that note `uncertain`, to be
confirmed by the player. Missing notes without such evidence remain `missing`.
Transcription is probabilistic, particularly for harmonics, noise, dense chords,
and multiple instruments playing together. Confidence is model activation, not
a calibrated probability of correctness. Inspect questionable detections before
treating a report as an authoritative musical judgment.

## Verify

```powershell
python local-analysis/test_analyze.py
node --test practice-web/test/recorded-analysis.test.mjs
local-analysis/runtime/python/python.exe local-analysis/smoke_test.py --runtime local-analysis/runtime
```

The smoke test executes the actual ONNX model against silence and a synthesized
polyphonic recording with repeated attacks. It reports any additional model
detections rather than hiding them. `--reference <absolute-PCM-WAV-path>` also
executes the real helper on an existing recording without assuming its accuracy
or inventing a ground-truth score. A development check used Spotify's upstream
[`vocadito_10.wav`](https://github.com/spotify/basic-pitch/blob/v0.4.0/tests/resources/vocadito_10.wav)
(9.097823 seconds); the adapter returned 28 timestamped notes. The 6-second
synthesized C-major/D/C recording returned all five expected attacks within 25 ms
of their starts, plus one weak harmonic detection (MIDI 86, confidence 0.319519).

`LocalAudioAnalysisTest` covers bounded PCM validation, output-schema validation,
runtime discovery, execution of a real interpreter, malformed subprocess output,
and termination of a hung helper. The subprocess tests require an installed
runtime; the other tests run without one. Third-party licenses remain with the
installed packages; see `THIRD-PARTY.txt`.
