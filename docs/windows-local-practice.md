# Windows local practice

This Windows change retains the PR #8 desktop layout, editor, local Audiveris
5.13.1 OMR and existing PianoBooster integration. Cloud services, billing and a
shared Flutter interface are excluded. Other platforms keep their input paths.

## Use

Extract the complete Windows x64 ZIP and launch `bin/音伴-你的音乐搭子.bat`
with Java 21. Open the Book-menu practice studio after recognizing and checking
the score. `bin/PracticeStudio.bat` also accepts MusicXML/MXL directly.

The existing settings dialog offers piano, violin, viola, cello, contrabass,
harp, flute, clarinet, bassoon, oboe, horn, trumpet, trombone, tuba, euphonium and
voice, alongside previous choices. Unnamed local OMR parts require a manual
instrument choice for acoustic assessment. An exporter-generated piano patch
does not identify an instrument. Configure each part before choosing all parts.
Explicit MusicXML transposition takes precedence over manual score variants.

Use microphone for one monophonic part, MIDI for chords, or recorded analysis
for overlapping notes. Keyboard demonstration supports attack and release.
Select capture/playback devices when needed. Confirm the score, range, BPM and
A4 before starting; an imported score always requires confirmation.

- **Wait for the correct note:** immediately prompts wrong notes without
  advancing. One held note cannot satisfy several repeated attacks.
- **Strict tempo:** native count-in/metronome; a fixed clock checks pitch,
  onset and duration. Missing a chord tone does not change the following pitch
  identities. Pause preserves the remaining beat phase.
- **Free following:** permits tempo changes, pauses and repeated passages.
  Repositioning requires context, rather than one matching pitch.

Feedback favors early suspect prompts, as requested. Low confidence, weak
voicing, ambiguous attacks and unsupported pitches remain pending review.
Wrong octaves remain wrong pitch identities. Median pitch evidence reduces
vibrato sensitivity; coarse contours are not precise intonation measurements.
Technique, fingering, timbre, pedal and expression are not graded.

Completed microphone sessions save PCM16 audio by default; settings can disable
retention. Reports and optional recordings live in
`%LOCALAPPDATA%/NoteLite/practice`. Replay a performance or problem location on
the original score, recheck with another installed detector, export a portable
ZIP, or reopen local history. Removal moves a take to the local recovery area;
history offers restoration. Audio and OMR remain local.

Analysis WAVs are bounded to 64 MB and 10 minutes, whichever limit is reached
first. Higher sample rates or stereo audio can reach the size limit sooner.
If captured segments cannot be reliably combined, the report and original
recovery segments are retained with an explicit warning and their offsets in
the exported report. They are not presented as a successful combined recording.
Reference listening synthesizes sounding pitches, rather than instrument timbre.

## Responsibilities

|Responsibility|Implementation|
|---|---|
|OMR|Existing local Audiveris 5.13.1|
|Normalization|Actual Partitura 1.9.0 plus the local schema: original/occurrence IDs, parts, written/sounding pitch, ties and navigation|
|Presentation|OSMD original-score cursor and individual note colors; no PCM processing in the page|
|Capture/playback|Native miniaudio 0.11.25; PCM, sample-based timing, device selection, recording and metronome|
|Live single voice|Own native MPM/YIN and acoustic event layer: confidence, voicing, uncertainty, attacks and releases|
|Recorded mono|Actual librosa pYIN 0.10.2.post1, official CREPE tiny weights through an equivalent ONNX network, actual aubio 0.4.9 reference|
|Recorded polyphony|Actual Spotify Basic Pitch 0.4.0 ONNX; notes, durations, contours and waveform-only refinement|
|Following|Own online state machine; actual Parangonar 3.3.3 DualDTW and the published six-stage Nakamura pipeline for recorded comparison|
|Grading|Shared Java judge for microphone, MIDI, keyboard and recordings: exact pitch identity, cents, onset, duration, wrong/missing/extra and unjudged evidence|
|Archive|Source score, normalized practice package, actual events, report and optional WAV; replay/recheck|

Published alignment baselines provide correspondence evidence. A substitution
is never automatically correct: the common judge retains actual detected pitch.
The published matchers need at least two distinct score and performance onsets.
For shorter context, comparison is explicitly marked unevaluated; the common
judge still assesses the actual detected notes without invented baseline pairs.
Strict recorded analysis removes one global starting offset using multi-note
context, unless an explicit start time is supplied. It does not warp individual
timing mistakes away. Free mode reports its different timing scope.
Live microphone chord separation is not provided.

The complete pinned Python 3.11.9/model runtime is bundled; users need no separate
Python. Live and recorded A4 use the same 415–466 Hz range. CREPE supports roughly
32.7–1975.6 Hz; other engines have different limits. Unsupported expected notes
remain unjudged. Raw model notes and acoustic postprocessing evidence are kept
for review; the detector never consults the expected score.

## Build and verification

Windows packaging needs Java 21 and a C/C++ compiler. Actual native/runtime
verification is a dependency of `:app:installDist` and `:app:distZip`. Downloads
are checksum pinned in `local-analysis/windows-lock.json`;
`install-windows.ps1 -Offline` uses a verified cache. Keep `bin`, `lib`,
`licenses` and `tools` together. Runtime notices and corresponding sources,
including actual aubio and original Nakamura source, accompany their builds.

- From `practice-web`: `node --test test/*.test.mjs` covers existing parsing,
  transposition, profiles, input lifecycle and legacy behavior.
- `python native/audio/test_audio.py --exe native/audio/build/NoteLiteAudio.exe`
  runs 168 audio/detector cases.
- `python native/audio/test_events.py --exe native/audio/build/NoteLiteAudio.exe`
  covers sustain, attacks, fast repeats and timing. Add `--hardware` for actual
  Windows loopback playback, metronome and STOP/EOF tests.
- `gradlew.bat -PtargetOS=windows-x86_64 :app:installLocalAnalysis :app:test
  --tests 'com.notelite.omr.practice.*'` checks the actual runtime, shared judge,
  recording preservation, restore and local service.
- `app/build/local-analysis/python/python.exe
  app/build/local-analysis/runtime_smoke.py --runtime app/build/local-analysis
  --require-native` exercises four actual engines on detuned audio, Partitura
  and both matchers. Readiness is written only after these checks pass.
- `tools/windows-practice-smoke.py --url <diagnostic-url> --output
  work/windows-e2e.json` exercises HTTP practice, saved packages, actual
  microphone WAV and native replay. Use an isolated practice directory.
- `tools/windows-recorded-smoke.py --url <diagnostic-url>` and
  `tools/recorded-engine-quality.py` compare edited real-instrument passages
  through actual models, baseline matching and the common judge.
- See the native recorded-validation guide for pinned sample fetch/benchmark
  scripts, source hashes and independently annotated human voice recordings.

The installed desktop smoke test exports nonempty MusicXML and MIDI from
`data/examples/chula.png`. USB MIDI hardware was unavailable locally; protocol
and exporter regressions were tested, but hardware performance is not claimed.

Execution establishes integration; acoustic accuracy needs separate recording
and musician evidence. Library samples, synthesized audio and full human voice
performances are reported separately. No sixteen-instrument live-room acceptance
claim follows. Euphonium has no suitable independent recording in this run;
low harp fundamentals, horn ambiguity and human voice still require further
musician validation. See the delivered Windows validation report for results.
