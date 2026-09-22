# NoteLite local practice studio

The NoteLite Book menu opens the currently recognized score or imports an existing MusicXML/MXL from another notation/OMR product. Java serves a random loopback-only URL with bundled assets. Microphone samples are processed inside the browser; there are no telemetry, upload, CDN or cloud API calls.

Use Node 20+ to rebuild the checked-in runtime assets:

```
npm ci
npm test
npm run build
```

Then run `gradlew :app:test :app:installDist` with JDK 21. Node is only a build dependency, not an end-user requirement. Java's `PracticeStudio` main accepts an XML/MXL path or loads the original demonstration score. The normal desktop menu opens the browser automatically.

## Inputs and measured scope

- MIDI: note-on pitch matching, chords, wrong/missing notes and onset timing. Not pedal, dynamics, release duration, articulation or fingering assessment.
- Microphone: Pitchy 4.1.0 plus confidence/stability gating for one pitched voice only. Rejects polyphonic score selections. A4 is configurable; MusicXML transposition is applied to sounding pitches.
- Computer keyboard: an explicitly labelled functional demo, not a microphone or hardware accuracy measurement.
- Metadata: explicit instrument names first, General MIDI programs second. Unnamed instruments remain unknown. A classifier label is not evidence that that instrument has passed acoustic validation.
- Wait mode advances only after all pitches in the current group were played. Tempo mode uses a four-beat count-in and bounds matching windows by the next onset to prevent a missing fast note from shifting every following note.
- Practice reads repeats in written order and discloses that limit. MIDI export has separate repeat expansion. Notes under unsupported jump/ornament constructs are not promised as full performance interpretation.
- OMR bar lengths exceeding the time signature are flagged and cannot be used for assessment until corrected or excluded from the selected range. A user must review the reference score before starting.

OpenSheetMusicDisplay is a mature notation component and Pitchy is a pitch detector; the NoteLite assessment layer is new. The PianoBooster menu is a separate, real product bridge for MIDI keyboards. It launches an independently installed PianoBooster and does not pretend it is a microphone SDK. Cross-instrument PhonicScore/Practice Bird technology is a researched commercial option, not a bundled integration; obtaining its SDK/licence remains necessary.

External OMR integration currently uses MusicXML/MXL interchange. ScanScore exports can be imported directly; this does not imply ScanScore is installed, embedded or benchmarked. No commercial licence is purchased automatically.

See `app/res/practice/THIRD-PARTY.txt` for included runtime notices. Regression tests include actual Pitchy processing of synthesized waveforms; those numbers must not be described as real-room/instrument accuracy.

## Recorded instrument sample benchmark

The optional offline benchmark executes the production Pitchy detector and `PitchGate` against actual recorded instrument samples from [tonejs-instruments](https://github.com/nbrosowsky/tonejs-instruments), pinned to commit `622c2f1c32c8cfce4158ddc3eb26e518ddef37e5`. The samples are CC-BY-3.0; attribution and upstream sources are preserved in the manifests and the evidence archive. The repository states that its samples were trimmed, ramped, level-matched, normalized, denoised, and sometimes pitch-corrected. These recordings do **not** represent unprocessed room recordings, real-time microphone latency, continuous playing, or polyphonic assessment.

The initial set contains 30 files: three preselected notes each from violin, flute, acoustic guitar, piano, clarinet, saxophone, trumpet, cello, bassoon, and contrabass. After one gate correction, a separate set of 20 preselected, disjoint notes from the same instruments was evaluated without further tuning. Pitch truth is the exact note-to-file mapping in the upstream `Tonejs-Instruments.js`, not an estimate from the detector. The source-info file does not identify clarinet's upstream provider individually; the manifest preserves that uncertainty.

| Run | First note matches | No detection | Exactly one correct event per file | Wrong-pitch events | Events beyond first |
| --- | ---: | ---: | ---: | ---: | ---: |
| Initial 30 files, previous gate | 30/30 | 0 | 25/30 | 11 | 46 |
| Same 30 files, corrected gate | 30/30 | 0 | 26/30 | 11 | 20 |
| Separate 20 held-out files, corrected gate | 20/20 | 0 | 20/20 | 0 | 0 |

The correction prevents an audible, low-clarity segment from releasing a held note. Only low RMS releases the gate; invalid pitch estimates reset the consecutive-stability counter. It reduces duplicate events but does not resolve every octave/harmonic error in release tails. Legitimate octave changes remain accepted. Events beyond the first are reported rather than automatically called false positives: a source sample can contain multiple bow articulations and there is no independent onset ground truth. A repeated same-pitch attack without sufficient silence is still a known limitation. Do not describe the first-note match result as overall performance accuracy.

To reproduce, install the optional decoder (`soundfile==0.14.0` and `numpy==2.5.3` were used) in a Python environment, then run from `practice-web` after `npm ci`:

```sh
python -m pip install soundfile==0.14.0 numpy==2.5.3
python test/fetch-recorded-samples.py /absolute/path/to/work/practice-real-samples
node test/recorded-audio-benchmark.mjs /absolute/path/to/work/practice-real-samples/manifest.json
python test/fetch-recorded-samples.py /absolute/path/to/work/practice-heldout-samples --split heldout
node test/recorded-audio-benchmark.mjs /absolute/path/to/work/practice-heldout-samples/manifest.json
npm test
```

The decoder retains native sample rates and averages stereo channels without extra gain, pitch, or time processing. Analysis uses causal 4096-sample windows at approximately 60 frames/second, including attack and full release. The benchmark saves original OGG, decoded Float32 PCM, immutable source URLs, Git blob IDs, SHA256 hashes, every accepted event, and per-frame traces. `recorded-audio-metrics.json` is written beside each manifest. Sample binaries are kept outside the repository. Normal `npm test` runs deterministic synthetic regression tests without downloading recordings.
