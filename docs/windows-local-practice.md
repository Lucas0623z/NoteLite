# Windows local instrument practice

This change builds on the desktop branding branch used by PR #8. It retains the
desktop editor, practice layout, OSMD rendering, MIDI/keyboard matching,
PianoBooster integration and local Audiveris 5.13.1 OMR. Apple and Linux clients
keep their existing input paths.

## Use

Extract the entire Windows x64 distribution and launch
`bin/音伴-你的音乐搭子.bat` with Java 21. Recognize and check the score, then open
the existing Book-menu practice studio. `bin/PracticeStudio.bat` also opens a
MusicXML/MXL file directly, or the example score without a file argument.

In the existing practice settings, select the instrument after recognition.
Unnamed local OMR parts open this dialog and require a choice before listening.
For multiple parts, select and configure each part before choosing all parts.
The instrument list covers piano, violin, viola, cello, contrabass, harp, flute,
clarinet, bassoon, oboe, horn, trumpet, trombone, tuba, euphonium and voice, while
preserving earlier instrument options. Select the score's transposition variant
where offered; explicit MusicXML transposition is never applied twice.

Choose MIDI for MIDI instruments, microphone for a single melody, or recording
analysis for chords. Recording analysis starts with the normal practice button;
press the same button again to finish and analyze. Alternatively import a
completed 16-bit PCM WAV through the settings dialog. Check the reference score
and set its tempo first. Recorded analysis currently requires standard A4=440 Hz;
live microphone practice retains the existing adjustable tuning. The existing review view displays the comparison and
allows retrying a passage.

## Local processing

Windows microphone audio is captured by bundled miniaudio 0.11.25. Independently
implemented MPM/YIN detectors estimate a single pitch; acoustic attack and legato
timestamps come from captured sample positions. Instrument settings choose broad
frequency ranges and analysis windows, without snapping detected audio to the
expected score. Ordinary microphone practice does not save raw audio.

Recording mode saves a temporary PCM16 WAV. Bundled Python 3.11.9, ONNX Runtime
1.20.1 and Basic Pitch 0.4.0 process it locally after capture. The Python/model
files ship in `tools/local-analysis`; users do not install Python. Imported audio
passes only through the local loopback service. Captured temporary audio is
deleted after successful analysis, replacement or closing the page. Ending a
failed capture rejects its partial recording. No audio or OMR job is sent to a
remote recognition service.

Build-time dependencies are checksum pinned in
`local-analysis/windows-lock.json`. A first build needs their downloads; a verified
cache supports `install-windows.ps1 -Offline`. Package notices and license files
travel with the runtime. Do not distribute just the executable or application
JAR: retain `bin`, `lib`, `licenses` and `tools` together.

## Assessment limits

Instrument profiles provide configuration, not a claim that all sixteen real
instruments have passed continuous-playing validation. Live microphone assessment
is monophonic. Dense piano, harp chords, ensembles, breath/bow modulation, noise,
weak fundamentals and octave ambiguities can still produce errors. MIDI remains
the preferred piano input. Basic Pitch is completed-recording transcription,
not a real-time polyphonic listening service.

Recorded comparison preserves exact MIDI pitch and octave, matches repeated
attacks in order and supports simultaneous notes. Alignment removes one constant
starting offset; it does not warp rhythm or silently change the selected tempo.
Model confidence below 0.4 is retained as unjudged evidence. A weak nearby
same-pitch detection can mark a score note as needing confirmation. Confidence is
a model activation rather than a calibrated accuracy probability. Reports do not
grade timbre, fingering, pedal, technique or expressive interpretation.

## Verification and reproduction

- `node --test practice-web/test/*.test.mjs`: parsing, explicit/manual
  transposition, sixteen profiles, live gate/lifecycle and recorded comparison.
- `python native/audio/test_audio.py --exe native/audio/build/NoteLiteAudio.exe`:
  168 synthetic native cases, including silence/noise rejection, harmonic tones,
  repeated pitches, Unicode PCM16 recording and sample-derived onset timestamps.
- `python native/audio/test_audio.py --capture-smoke`: explicit short capture
  from the default Windows microphone, orderly stop and WAV finalization.
- `app/build/local-analysis/python/python.exe local-analysis/smoke_test.py
  --runtime app/build/local-analysis`: runs the actual packaged ONNX model on
  silence and a synthesized chord/repeated-note recording.
- `gradlew.bat :app:test --tests 'com.notelite.omr.practice.*'` and existing MIDI
  exporter tests: Java service boundaries, loopback routes and MIDI behavior.
- Installed desktop launcher recognition of `data/examples/chula.png` must
  produce nonempty MusicXML and MIDI. The desktop workflow runs this package check.

The native production stability gate matched the first note in 30/30 isolated
baseline samples and 20/20 separate held-out samples. Across full sample traces,
baseline contained four wrong-pitch events and eleven events beyond the first;
held-out contained zero wrong-pitch events and one beyond the first. These are
edited isolated samples, with no independent attack ground truth, and do not
establish real-room or continuous-playing accuracy. See the native guide for raw
detector results and sources.

The actual Basic Pitch model detected all five expected attacks in a six-second
synthesized C-major/D/C recording within 25 ms, plus one weak harmonic detection
(MIDI 86, confidence 0.319519). That extra detection is disclosed and left
unjudged. An upstream 9.097823-second vocal sample produced 28 notes; it has no
independent reference here, so this is execution evidence only. No aggregate
sixteen-instrument accuracy claim follows from these checks.
