# Written-MIDI audit

The `results/before` and `results/after` folders retain 15 actual MusicXML inputs, written MIDI files and the expected/actual MIDI event lists. `summary.json` records the baseline and corrected Java source hashes and exact note statistics. These are deliberately chosen serialization scenarios, **not image-recognition or performance-recognition accuracy**.

The baseline is 5/15 fully correct cases and exact pitch/channel/onset/offset note F1 71.43% (30 of 44 reference notes matched, 40 predicted note-ons). The corrected implementation passes 15/15 and 44/44 notes. One tempo event is separately tested. Note-level and individual MIDI-message-level metrics are not interchangeable.

To regenerate the current output with Java 21:

```
./gradlew :app:test --tests com.notelite.omr.score.MidiExporterAccuracyTest --tests com.notelite.omr.score.MidiExporterAdvancedTest
```

New files go to `app/build/midi-accuracy/current`. Set `NOTELITE_MIDI_AUDIT_PHASE` to another simple folder name to keep another run. The expected references live in `MidiExporterAccuracyTest`; no data is read from Markdown to establish expected results.

Image/PDF recognition is measured separately in `benchmarks/omr`, using the actual batch engine and independent score references.
