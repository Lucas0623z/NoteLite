# Full recognition reference

`chula-semantic-reference.json` records actual output of the complete desktop
Audiveris-derived engine on `data/examples/chula.png`. It was generated on
2026-09-28 with NoteLite commit `c266517`, Java 21, the original bundled fonts and
classifier, and tessdata 4.1.0 English legacy OCR. The file embeds the source
image SHA-256. This is a port parity reference, not a human-corrected score or an
accuracy benchmark.

The reference contains 151 pitched notes, 7 other notes, 19 measures and 220 MIDI
note-on events. MIDI includes playback repeats, so its note count differs from
the printed score. The gate compares actual pitch, rhythm, voice, staff, ties,
key/time/clef changes, barlines, sounding note boundaries and MIDI control/meta
events. It ignores layout coordinates, filesystem paths and encoding timestamps.

Eight independent desktop job exports passed the comparison, including repeated
jobs with the mobile headless Java platform classes. The iOS probe must pass the
same comparison on its own exports; a desktop result does not satisfy that gate.

```sh
python3 tools/audiveris-port/verify_embedded_score.py /path/to/one/export/job \
  --reference tools/audiveris-port/fixtures/chula-semantic-reference.json \
  --source-image data/examples/chula.png --report build/score-parity.json
python3 tools/audiveris-port/test_verify_embedded_score.py
```

Do not update this reference to hide a port mismatch. Investigate each semantic
difference against the desktop engine and source score before accepting a new
baseline. The verifier's tests deliberately change notes and note lengths while
keeping counts identical, so a count-only check cannot pass.
