# NoteLite Windows local audio helper

`NoteLiteAudio.exe` captures the default Windows microphone using vendored
miniaudio 0.11.25. All capture, monophonic MPM/YIN pitch estimation, attack
detection and optional WAV recording run locally. There is no runtime download,
score-dependent pitch correction, network access, or target-note snapping.
The existing piano/MIDI path is separate.

## Build

From a Windows PowerShell prompt in the repository:

```powershell
./tools/build-local-audio.ps1
./tools/build-local-audio.ps1 -Compiler 'C:\toolchain\bin\gcc.exe'
```

The script uses GCC/Clang/Visual Studio on PATH or a local CLion bundled MinGW.
For MSVC use a Visual Studio developer shell. Its default output is
`native/audio/build/NoteLiteAudio.exe`; `-OutputDirectory` can override this.
The source is already vendored, so compilation requires no network. A CMake
project is also provided for Windows toolchains. The MinGW-built binary imports
only Windows system `KERNEL32.dll` and `msvcrt.dll`.

## Runtime contract

```text
NoteLiteAudio.exe --min-frequency 27.5 --max-frequency 4200 --window 4096
NoteLiteAudio.exe --min-frequency 27.5 --max-frequency 4200 --window 4096 --record C:\absolute\practice.wav
NoteLiteAudio.exe --analyze C:\absolute\existing.wav
```

- Capture/output PCM is mono Float32 at 48,000 Hz; miniaudio converts the device's
  native format/rate. Analysis hops are 480 samples (10 ms).
- `--window`: power of two from 1024 to 16384, default 4096. The minimum frequency
  must allow at least 1.33 periods in the selected window. Default bounds are
  27.5–4200 Hz; the maximum allowed bound is 10,000 Hz. These are broad instrument
  limits, not restrictions to the current score's expected notes.
- `--record` requires an absolute Windows path. It records exactly the mono PCM
  supplied to the analysis worker, quantized to standard 16-bit PCM WAV. A Unicode path is accepted.
  Recording is opt-in; normal single-note listening does not save raw audio.
- `--analyze` decodes/resamples an existing WAV to the same mono 48 kHz pipeline;
  it never opens a microphone. It accepts `--record` for a PCM16 recording round trip.
- stdin line `STOP` or stdin EOF terminates capture, drains queued samples and
  finalizes the WAV. The process exits 0 for success, 2 for setup/configuration
  failure and 3 for capture/recording failure. Offline input shorter than one
  window produces ready/stopped without fabricated zero-padded pitch frames.

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
rounded to a MIDI note. Unvoiced/rejected input has frequency/clarity 0.

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
in regression tests. Soft legato attacks, natural bow/breath modulation, strong
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

The production UI stability gate is separately executed on the complete native
frame traces by `gate_benchmark.mjs`. First accepted notes matched 30/30 baseline
and 20/20 held-out samples. Baseline had four wrong-pitch events and 11 extra
events over full recordings, with 24/30 clean single attacks; held-out had zero
wrong-pitch events and one extra, with 19/20 clean single attacks. Updated gate
reports should accompany changes to either the native detector or UI gate;
first-pitch agreement alone does not establish clean, single-attack playing.

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
source uses the repository MIT license. The test suite does not bundle external
instrument recordings; users of a recorded-sample manifest retain its upstream
attribution and license requirements.
