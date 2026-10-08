# Windows local audio and score analysis

The installed Windows runtime contains real Spotify **Basic Pitch 0.4.0**
polyphonic transcription (official ICASSP 2022 ONNX model), **librosa 0.10.2.post1
pYIN**, official **CREPE tiny** weights converted to ONNX, and native **aubio
0.4.9 yinfast + complex onset** monophonic review. **Partitura 1.9.0** normalizes
MusicXML/MXL, and **Parangonar 3.3.3** and **Nakamura 240109** are executable
offline score/performance alignment baselines. CPython 3.11.9 x64 and ONNX Runtime
1.20.1 are bundled. All processing and Audiveris OMR remain local.

## Build and install

From the repository root, on Windows x64:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/build-local-audio.ps1 -AnalysisTools
powershell -NoProfile -ExecutionPolicy Bypass -File local-analysis/install-windows.ps1 -Destination app/build/local-analysis
```

The installer verifies every SHA-256-pinned Python archive, wheel and official
CREPE weight in `windows-lock.json`, extracts them without running pip resolution
or package setup scripts, copies the actual compiled native engines and licenses,
and executes real model and alignment smoke tests. Only a fully passing
installation receives `runtime-ready.json`. Java advertises a capability only
when that engine's smoke proof is present. `-SkipNative` produces a reduced
development runtime and does not advertise aubio/Nakamura.

The cache is `local-analysis/cache`. `-Offline` reinstalls using verified cached
archives. `-Cache <directory>` chooses a pre-seeded cache; `-NativeTools <directory>`
chooses compiled native tools. Copy the complete runtime to `tools/local-analysis`
in the Windows distribution. Users need no system Python, TensorFlow, PyTorch or
network model fetch. `-Dnotelite.analysis.home=<directory>` / `NOTELITE_ANALYSIS_HOME`
select a development runtime; an invalid override is reported as unavailable.
Basic Pitch's upstream Python 3.11 TensorFlow dependency is omitted because this
adapter explicitly loads ONNX. Pretty MIDI's pure Python sdist retains its license
and omits unused soundfonts. Native source provenance is under `vendor/`; installed
corresponding source and adapter/build scripts ship under `sources/`.

## Helper contract

```powershell
tools/local-analysis/python/python.exe tools/local-analysis/analyze.py --input C:/takes/take.wav --output C:/takes/result.json --operation analyze --options C:/takes/options.json
```

Paths must be absolute and different. All operations return UTF-8 schemaVersion 1
JSON and perform no network access. Java APIs are `analyze(byte[] wav, Map options)`,
`normalize(byte[] xml, Map options)`, and `align(Map score, List notes, Map options)`.
Java bounds input, output and concurrency, imposes a five-minute process timeout,
validates results, terminates cancellation and removes its temporary files.

`analyze` accepts complete 16-bit mono/stereo PCM WAV, 8–96 kHz, up to 64 MB / 600
seconds. Options: `engine:basic-pitch|pyin|crepe|aubio`, `a4:400..480`, `minHz`,
`maxHz`, `threshold`. Acoustic requests with `input:recording|microphone` require
`verified:true` after instrument selection. Notes retain MIDI/octave, actual onset
and release duration in seconds, confidence, frequency, cents relative to chosen
A4 and absolute `pitchCents`. Basic Pitch preserves its original contour/model
MIDI and refines coarse cents from clear recorded spectral peaks without reading
the score. Ambiguous spectra retain explicit 1/3-semitone contour resolution.

Results include `supportedPitchRange:{minHz,maxHz,minMidi,maxMidi}`,
`uncertaintyIntervals:[{onset,duration,reason}]`, configuration and warnings. CREPE
supports about 32.7–1975.6 Hz; Basic Pitch supports 27.5–4186 Hz. Expected notes
outside detector range remain unjudged. pYIN resamples and adapts its window to at
least four periods of the lowest profile pitch; aubio adapts its native window.
Low-confidence audible frames become uncertainty intervals, while silence does
not become a fabricated note. Mono algorithms cannot separate simultaneous voices.
Confidence is engine evidence, not a calibrated probability. Harmonics, noise,
weak fundamentals and overlap can cause errors. The score-independent onset
evidence layer qualifies same-pitch re-attacks from local energy valleys plus a
rapid rise, quiet-to-voiced rises or clear transients. It resets attack history,
preserves 125ms articulated candidates and suppresses steady/crescendo/vibrato
peaks. Basic Pitch adjacent same-pitch fragments without a new acoustic attack
merge before pitch refinement. `rawNotes`, original contour steps/confidence,
`postprocessing`, segment indices and onset evidence retain model results.
Unconfirmed separate re-attacks retain real confidence with `reviewRequired:true`
and `onsetReliable:false`; they are unjudged. Flat-energy re-articulation without
a clear transient can remain uncertain. No score pitches/timing enter this layer.

`normalize` accepts MusicXML or bounded MXL. Partitura unfolds repeat traversal,
combines tied durations and returns quarter-note `notes`, `groups`, tempo events,
traversal and part metadata. Each note keeps frontend ID `partId:xml-note-ordinal`
(including rest/grace ordinals), separate repeat `occurrenceId`, source measure
identity, staff/voice, written MIDI and sounding MIDI. Explicit XML transpose is
applied once. Manual per-part variants apply only when XML transpose is absent;
automatic instrument naming never silently transposes. Options preserve
`part/from/to/instrument/variant/byPart` and metadata parts as list or map.
Unconfirmed local OMR playback-default Piano is not reliable instrument evidence.

`align` input: `{score:normalizedScore,performance:notes,options:{backend}}`, with
`backend:parangonar|nakamura`. Both run published algorithms and return source/
occurrence-to-detection `pairs`, `missing`, `extra` and algorithm provenance.
Parangonar runs `DualDTWNoteMatcher`; Nakamura runs SPR conversion, HMM matching,
error detection, merged-output HMM realignment and correspondence. They are
evaluated offline baselines; the application owns shared live/recorded grading,
pitch/cents/onset/duration decisions and final reports.
Both comparisons require at least two distinct score and performance onsets.
Shorter excerpts return `metadata.evaluated:false`, `reason:insufficient-context`,
an explicit warning and empty baseline pairs/missing/extra; the shared judge
still assesses actual detections. This avoids the original single-event DTW
backtracking loop and single-event MOHMM realignment failure without inventing
published-algorithm results. Saved JSON integer values such as `60.0` are accepted
as exact identities, while fractional MIDI/index values are rejected.

## Verification

```powershell
local-analysis/runtime/python/python.exe local-analysis/test_analyze.py
local-analysis/runtime/python/python.exe local-analysis/test_score_tools.py
local-analysis/runtime/python/python.exe local-analysis/test_mono_engines.py
local-analysis/runtime/python/python.exe local-analysis/test_onset_evidence.py
local-analysis/runtime/python/python.exe local-analysis/runtime_smoke.py --runtime local-analysis/runtime --require-native
local-analysis/runtime/python/python.exe local-analysis/smoke_test.py --runtime local-analysis/runtime
```

Installation smoke executes an actual A4+25-cent recording through every
advertised audio detector and variable-tempo three-note alignment through both
baselines. Tests cover source/repeat identity, rest ordinals, explicit/manual
transpose, tied durations, unconfirmed OMR metadata, variable tempo, insertions/
deletions, actual saved-number roundtrips and bounded short-context subprocesses.
Polyphonic smoke uses silence and a six-second C-major/D/C recording
with five expected attacks, retaining extras. The initial ONNX output found all
five within 25 ms and one weak MIDI86 harmonic (confidence .319519).
Spotify's upstream `tests/resources/vocadito_10.wav` (9.097823 seconds) produced 28
actual timestamped notes; no ground truth is provided here for an accuracy claim.
The installed marker records actual smoke measurements.

`LocalAudioAnalysisTest` covers PCM/schema limits, proof-based discovery, real
interpreter process boundaries, malformed output, bounded cancellation and a
real Windows locked-log handle that must not mask the original timeout.
Licenses are retained in `licenses`, package `.dist-info`, and embedded Python;
see `THIRD-PARTY.txt` and `vendor/README.md`.

### Actual instrument excerpt comparison

```powershell
local-analysis/runtime/python/python.exe tools/recorded-engine-quality.py --manifest work/windows-performances/manifest.json --output work/recorded-engine-quality
```

The reproducible script invokes the real helper separately for all four detectors,
Partitura and both alignment baselines. It preserves full outputs/logs and reports
exact performed-pitch attacks, extras, timing/duration differences and measured
cents evidence. It checks baseline correspondence MIDI before counting a match as
correct. Fixtures are controlled sequences assembled from actual instrument
samples with upstream source hashes, not live musician performances.

With acoustic onset evidence, all four engines recover the labeled performed
attacks (6/6, 6/6 and 5/5) with no confident extras. Original model fragments remain
in `rawNotes`; the correct six-attack recording retains six acoustically supported
events. Both baselines retain only five exact-pitch matches for the wrong-octave
case: Nakamura's remaining correspondence is an octave substitution, while
Parangonar reports deletion/insertion. Both identify the missing note. These
controlled excerpts do not establish broad accuracy. Sample cents ground truth is
unavailable; actual cents/MAD/counts and known +25c synthetic calibration are
retained. Duration differences compare the cropped .52s performed notes, not a
legato .75s quarter-note target. The script does not test HTTP/common grading/UI.
