# NoteLite Windows local audio helper

`NoteLiteAudio.exe` captures Windows microphones and plays WAV/reference audio
and continuous metronome clicks using vendored miniaudio 0.11.25. All capture,
monophonic MPM/YIN pitch estimation, stable acoustic note events, uncertainty
intervals, release detection and optional WAV recording run locally. There is no runtime download,
score-dependent pitch correction, network access, or target-note snapping.
The existing piano/MIDI path is separate.

## Build

From a Windows PowerShell prompt in the repository:

```powershell
./tools/build-local-audio.ps1
./tools/build-local-audio.ps1 -Compiler 'C:\toolchain\bin\gcc.exe'
./tools/build-local-audio.ps1 -AnalysisTools
```

The script uses GCC/Clang/Visual Studio on PATH or a local CLion bundled MinGW.
The script imports an installed Visual Studio environment if needed. Its default output is
`native/audio/build/NoteLiteAudio.exe`; `-OutputDirectory` can override this.
The source is already vendored, so compilation requires no network. A CMake
project is also provided for Windows toolchains. The MinGW-built binary imports
only Windows system `KERNEL32.dll` and `msvcrt.dll`.
`-AnalysisTools` additionally compiles actual aubio and the nine Nakamura
baseline tools from the pinned source under `local-analysis/vendor/` into
`native/audio/build/analysis-tools/`. No downloading or Python is needed to
compile these helpers. The GCC build has been exercised locally; the script
also supplies MSVC C/C++ build options for Windows CI.
The MinGW Nakamura build includes its matching `libwinpthread-1.dll` beside
the executables; copy the whole Nakamura directory when packaging. The build
performs a real three-note SPR/FMT/HMM/matching/error/realignment/correspondence
round trip before reporting success, catching runtime and file-I/O ABI failures.

## Runtime contract

```text
NoteLiteAudio.exe --min-frequency 27.5 --max-frequency 4200 --window 4096
NoteLiteAudio.exe --min-frequency 27.5 --max-frequency 4200 --window 4096 --record C:\absolute\practice.wav
NoteLiteAudio.exe --analyze C:\absolute\existing.wav
NoteLiteAudio.exe --list-devices
NoteLiteAudio.exe --capture-device 0 --a4 442
NoteLiteAudio.exe --play C:\absolute\practice.wav --start-ms 200 --end-ms 800 --playback-device 0
NoteLiteAudio.exe --metronome 120 --playback-device 0
```

- Capture/output PCM is mono Float32 at 48,000 Hz; miniaudio converts the device's
  native format/rate. Analysis hops are 480 samples (10 ms).
- `--window`: power of two from 1024 to 16384, default 4096. The minimum frequency
  must allow at least 1.33 periods in the selected window. Default bounds are
  27.5–4200 Hz; the maximum allowed bound is 10,000 Hz. These are broad instrument
  limits, not restrictions to the current score's expected notes.
- `--record` requires an absolute Windows path. It records exactly the mono PCM
  supplied to the analysis worker, quantized to standard 16-bit PCM WAV. A Unicode path is accepted.
  The standalone helper records only with this flag. The Windows practice UI
  enables it by default for local replay; its retention checkbox can disable it.
- `--analyze` decodes/resamples an existing WAV to the same mono 48 kHz pipeline;
  it never opens a microphone. It accepts `--record` for a PCM16 recording round trip.
- stdin line `STOP` or stdin EOF terminates capture, drains queued samples and
  finalizes the WAV. The process exits 0 for success, 2 for setup/configuration
  failure and 3 for capture/recording failure. Offline input shorter than one
  window produces ready/stopped without fabricated zero-padded pitch frames.
- `--a4` defines the concert tuning used for acoustic MIDI/cents conversion,
  415–466 Hz, default 440. It does not alter estimated frequency.
- Device enumeration returns UTF-8 names and zero-based `index`/`default` for
  capture and playback arrays. Omitting the device flags uses the Windows
  default. Re-enumerate after devices change; indices are not persistent IDs.
- WAV playback converts to stereo Float32 48 kHz, preserves stereo, and validates
  the selected start/end range against the file duration. Reference tones may
  be supplied as generated WAVs. Progress contains rendered `sampleCount`,
  relative `timeMs`, and absolute source `positionMs` every approximately 100 ms.
  Ready uses `mode:"playback"`, `startMs` and `endMs`. EOF or STOP ends playback.
- `--metronome BPM`, 20–400 BPM, streams clicks continuously until STOP/EOF. It
  accents each fourth beat, starts the first click at sample zero and computes
  all spacing from rendered samples. Ready uses `mode:"metronome"`, `bpm` and
  `endMs:null`. Optional `--start-ms` selects the initial beat-clock phase: at
  120 BPM, phase 250 ms renders 250 ms of quiet before the next beat. Progress
  `positionMs` includes that initial phase; `timeMs` remains elapsed rendered
  time. PCM generation runs on the bounded playback worker queue; the
  audio callback copies prepared samples. Playback underruns abort explicitly.
- `--loopback` captures the Windows WASAPI renderer for integration tests; with
  `--playback-device` it selects that renderer. It does not select a microphone.

stdout is one UTF-8 JSON object per line. Diagnostic prose goes to stderr.

```json
{"type":"ready","sampleRate":48000,"timeMs":0}
{"frequency":440.003,"clarity":0.997,"rms":0.08,"timeMs":0,"onset":true,"sampleCount":0,"onsetTimeMs":0,"pitchTimeMs":42.666667}
{"frequency":440.001,"clarity":0.998,"rms":0.08,"timeMs":10,"onset":false,"sampleCount":480,"onsetTimeMs":0,"pitchTimeMs":52.666667}
{"type":"stopped","sampleCount":48000,"timeMs":1000}
```

Live `ready` is emitted only after successful device startup. Offline ready adds
`"mode":"analyze"`. `timeMs` on a pitch frame is the **window's first sample
index**, divided by 48 kHz. The first full window therefore has index/time 0.
A full 4096-sample window is available after 85.33 ms, in addition to device and
queue scheduling latency. The timestamp never comes from a wall clock, UI frame
rate, or the number of JSON lines. `stopped` reports all successfully consumed
PCM frames and is emitted after the WAV has been finalized. No frequency is
rounded to a MIDI note in raw frames. Unvoiced/rejected input has frequency/clarity 0.
Raw frames additionally include `voiced:true|false|null`, `confidence`,
`inputRms` for the latest 10 ms hop and sample-derived `endTimeMs`.

## Native acoustic events

Windows practice consumes the native stable events. Three agreeing periodic
frames with clarity ≥0.9 confirm a candidate; no score information enters this
detector. A held note emits one note-on and a note-update roughly every 100 ms;
three quiet hops release it at the first quiet hop. A new same-pitch attack closes
the previous event, while a continuous legato pitch change uses the independent
window midpoint when no associated attack exists. Quiet periodic notes are
accepted down to RMS 0.001; digital quiet below 0.0005 is rest.

```json
{"type":"note-on","schemaVersion":1,"id":"n1","midi":69,"cents":0.2,"frequency":440.05,"confidence":0.99,"timingConfidence":1,"voiced":true,"onsetMs":100,"offsetMs":null,"durationMs":0,"timeMs":100,"sampleCount":4800,"reason":"attack"}
{"type":"note-off","schemaVersion":1,"id":"n1","midi":69,"cents":0.1,"frequency":440.03,"confidence":0.99,"timingConfidence":1,"voiced":false,"onsetMs":100,"offsetMs":500,"durationMs":400,"timeMs":500,"sampleCount":24000,"reason":"silence"}
```

`note-update` has the same ID/identity, current measured frequency/cents,
`offsetMs:null`, elapsed duration and current sample time. Note-off summarizes
mean accepted cents/confidence and pairs with the same note-on ID. Its reason is
`silence`, `rearticulation`, `pitch-change`, or `stop`. All event times are capture
sample times. `timingConfidence` is a detector heuristic (1 for acoustic attack,
0.6 for legato midpoint, 0.5 following uncertainty), not a calibrated probability.

Sustained unreliable audible input emits paired `type:"uncertainty"` intervals
with ID `u1`, `midi:null`, `cents:null`, `voiced:null`, onset/offset/duration and
raw confidence. Reasons include `weak-signal`, `aperiodic`, `unstable`,
`pitch-ambiguity`, and `octave-ambiguity`. The open interval has `offsetMs:null`;
the closing interval has its final offset/duration. A stable estimate or actual
quiet closes it. The shared scorer can defer judgment over these intervals.

To avoid octave cascades from fading fundamentals, unarticulated jumps of ten
or more semitones need clarity ≥0.985. An unarticulated octave with RMS below
12% of that note's previously accepted peak remains uncertain. A 60-cent
identity hysteresis reduces note splitting around a semitone boundary; cents
retain the actual acoustic deviation. A clearly periodic, equal-level octave
legato is accepted. These rules can defer soft octave transitions; this is an
explicit acoustic ambiguity, not an invented note or expected-score correction.

For note-on practice timing use **`onsetTimeMs`**, which records the first sample
of the 480-sample hop in which the acoustic attack began. It remains associated
with the detected attack while the corresponding pitch is held; it is `null`
when no acoustic attack is available. Pitch delivery can follow that timestamp
by a full analysis window. `pitchTimeMs` is the sample-derived window midpoint,
used for a continuous legato pitch change without a distinct energy attack.
Window-start `timeMs` serves trace/PCM alignment and is not an acoustic attack
timestamp. In synthetic attacks at 250 ms, `onsetTimeMs` stayed within 10 ms for
both 4096- and 8192-sample windows; device buffering and uncertain real attacks
remain separate sources of latency/error.

Errors are structured and must be handled separately from pitch frames:

```json
{"type":"error","code":"CAPTURE_OVERFLOW","message":"Capture queue overflow: recording stopped without dropping or retiming samples."}
```

The callback only copies into a 262,144-sample bounded single-producer queue.
The worker performs FFTs, file writes and stdout writes. If the consumer cannot
keep up, capture stops with `CAPTURE_OVERFLOW` and exit code 3; it does not discard
samples and pretend the subsequent timestamps are contiguous. Device failure
and recording failure likewise abort explicitly.

## Detector and limits

`pitch.c` implements zero-padded radix-2 FFT autocorrelation, MPM's normalized
square difference function and first sufficiently strong positive-lobe peak,
plus a YIN cumulative-mean difference cross-check. The difference is divided by
the shrinking overlap length before accumulation. MPM/YIN candidates must agree
within 60 cents. Returned clarity is the lower of their two periodicity scores.
The implementation follows the published equations; it copies no external
pitch-detector source.

Attack detection runs on every short hop, independently of pitch window size.
It compares a smoothed approximately 40 ms energy envelope to a falling valley,
requires a new amplitude rise of at least 6 dB, and applies an 80 ms refractory
period. The attack timestamp precedes the wait for a stable periodic estimate.
It can identify a second pluck at the same pitch
without requiring digital silence. An unarticulated held note emits one onset
in regression tests. Each consumed attack resets the slow envelope reference,
so a preceding louder note does not re-arm a new soft attack while it is still
rising. Six 125 ms rearticulations without digital silence remain distinct in
regression tests. Soft legato attacks, natural bow/breath modulation, strong
background noise, weak fundamentals and octave ambiguities remain limits.
This is a monophonic pitch service; keyboard chords require the separate piano
input or recorded multi-pitch route.

References:

- Philip McLeod and Geoff Wyvill, *A Smarter Way to Find Pitch* (2005):
  https://www.cs.otago.ac.nz/tartini/papers/A_Smarter_Way_to_Find_Pitch.pdf
- Alain de Cheveigné and Hideki Kawahara, *YIN, a fundamental frequency estimator
  for speech and music* (2002): https://audition.ens.fr/adc/pdf/2002_JASA_YIN.pdf

## Verification

Run the actual executable on reproducible synthetic PCM:

```powershell
python native/audio/test_audio.py
python native/audio/test_audio.py --exe C:\absolute\NoteLiteAudio.exe
python native/audio/test_events.py
python native/audio/test_events.py --hardware
```

The 168-case regression checks six harmonic families, 13 pitches, clean and
20 dB noise, detuning at 44.1/48 kHz input rates, silence/white-noise/DC rejection,
same-pitch attacks, sample-derived attack timestamps independent of window size,
legato pitch changes within the preceding acoustic attack's analysis window,
Unicode PCM16 recording with quantization-tolerant verification and
invalid configuration handling. It opens no microphone and downloads nothing.
Reports and temporary audio go to ignored `native/audio/test-output/`.

For actual recorded-instrument samples, use the checksum-verified manifest from
`practice-web/test/fetch-recorded-samples.py`:

```powershell
python native/audio/test_audio.py --manifest C:\absolute\samples\manifest.json --output C:\absolute\results
node native/audio/gate_benchmark.mjs C:\absolute\results\recorded-results.json
```

Every declared sample is analyzed, including failures. The benchmark does not
trim to favorable sustain segments, normalize amplitudes or correct pitches.
It reports raw first-pitch accuracy separately from median cents and onset
counts. Initial 30 upstream recordings: 27/30 first accepted pitches matched;
20 disjoint held-out recordings: 18/20 matched. These samples are edited
isolated notes from tonejs-instruments, not live microphone or room recordings.
Multiple onsets in a bow/blown sample may be either physical articulations or
false attacks; the dataset has no independent onset ground truth. Live and
polyphonic performance are not established by these results.

Production native event traces matched the first note in 30/30 baseline and
20/20 held-out samples. Complete baseline clips had one wrong-pitch event and
seven extra events, with 26/30 single attacks; held-out had zero wrong-pitch events
and one extra, with 19/20 single attacks. These are measurements on edited
isolated recordings, not a guarantee of live playing accuracy. The browser
`NativePitchGate` remains a regression/fallback comparator, not the Windows
production scoring gate. First-pitch agreement alone does not establish clean,
single-attack playing.

The twelve native event regressions test real releases/durations, same-pitch
rearticulation, quiet tone release, legato and octave changes, fading harmonic
ambiguity, tuning, intonation hysteresis, noise uncertainty, digital rest,
soft rising attacks after louder notes and rapid repeated attacks.
The explicit Windows experience test enumerated one capture/four playback
devices, rendered exactly 28,800 samples for the 200–800 ms WAV range, detected
its A4 from actual WASAPI loopback audio, measured four 120 BPM click intervals
of 500 ms, and verified STOP/EOF during partial playback. Loopback recordings
contain the generated technical signal and are deleted after verification.
Resuming at phase 250 ms generated the next beat 250 ms into the native sample
timeline; repeated actual loopback checks measured its first click at 300–320 ms from capture
origin, including process startup and Windows output buffering, followed by
500 ms spacing. Native sample clocks do not remove hardware buffering latency.

An explicit device smoke test is available:

```powershell
python native/audio/test_audio.py --capture-smoke
```

This opens the default Windows capture device for approximately 750 ms, checks
ready/STOP/EOF and PCM16 finalization, and immediately deletes the temporary
recording. It does not interpret acoustic content. The verified Windows test
captured 36,000 samples and emitted 67 pitch windows; decoding the finalized WAV
recovered exactly those 36,000 samples.

## Third-party licensing

The vendored miniaudio header and license are under `vendor/miniaudio/`; see
`THIRD_PARTY_NOTICES.md` for the fixed version and checksums. NoteLite's own
MPM/YIN/events source uses the repository MIT license. The separate
`AubioMono.exe` is GPL-3.0-or-later through its aubio link; the Nakamura tools use
their upstream MIT terms. Corresponding pinned source and licenses are retained.
The test suite does not bundle external
instrument recordings; users of a recorded-sample manifest retain its upstream
attribution and license requirements.

## Recorded-analysis helpers

```text
AubioMono.exe --input C:\absolute\performance.wav --output C:\absolute\aubio.json --min-hz 27.5 --max-hz 4200 --a4 440
```

This adapter decodes mono 48 kHz PCM and calls the actual aubio 0.4.9 `yinfast`
pitch and `complex` onset implementations. It chooses a power-of-two analysis
window of at least four periods at the minimum bound, from 4096 to 16384
(8192 at 27.5 Hz), and uses 480-sample hops. Its JSON contains engine/version,
window/hop/range/tuning metadata, frames `{time,frequency,confidence}` in seconds,
aubio delay-corrected `onsets` in seconds, sampleCount and duration in seconds.
Frame time is the input window midpoint, clamped to zero during startup;
frequencies outside the broad profile range are rejected, never snapped.
The local Python recorded-review adapter turns these actual estimates into
notes. The separately compiled Nakamura command-line programs preserve the
upstream score/performance alignment pipeline for baseline comparison.

## Additional original-source instrument and voice validation

`fetch_profile_recordings.py` downloads fixed original VSCO2 CE and Iowa samples,
with optional vocadito full singing recordings and both human annotations.
`benchmark_profile_recordings.py` verifies original/PCM checksums and executes
the production Windows native helper over every full file using the actual
broad instrument profiles; all failures and uncertainty remain in its report.
These optional tools require the bundled numpy/soundfile Python runtime and
Node. They do not open a microphone or ship audio in the application.
See [the reproducible commands, licenses and measured limitations](PROFILE_RECORDINGS_VALIDATION.md).

## Controlled flute sequence fixture setup

Run `local-analysis/runtime/python/python.exe tools/prepare-practice-performances.py`
to recreate the correct, wrong-octave and missed-note cases in
`work/windows-performances-reproduced/`. The optional setup script downloads only
three SHA-256-pinned CC BY 3.0 ToneJS flute samples, edits them into PCM16 WAVs,
and writes source/license metadata, valid 6/4 MusicXML and a PCM comparison with
the existing measured fixtures. The original files are protected from overwrite.
These are controlled sequences assembled from edited instrument recordings,
not live musician performances; manifest durations remain the actual .52 s crops.
Neither original samples nor generated audio is included in the app distribution.
