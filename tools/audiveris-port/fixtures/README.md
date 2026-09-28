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

## Complete two-page documents

`chula-two-page.pdf` and `chula-two-page.tiff` preserve the actual inputs from
the source-built JDK 28 host run [36419489365](https://github.com/Lucas0623z/NoteLite/actions/runs/36419489365).
Both contain two copies of the original scan. The PDF uses lossless pixels and
page dimensions at 300 DPI; the TIFF contains two ImageIO sequence frames.
Their construction, input hashes and reference hashes are recorded in
`chula-two-page-provenance.json`.

Each document produces two movements, each with its own MusicXML and MIDI.
The format-specific references contain every semantic event from both movements:
302 pitched notes, 14 other notes, 38 measures and 440 MIDI note-on events in total.
Both references also matched all outputs from the independent Linux run
[36418912394](https://github.com/Lucas0623z/NoteLite/actions/runs/36418912394).

The mobile gate uses these exact input bytes. It requires two matching
MusicXML/MIDI pairs and compares each movement in full; losing the second page,
pairing the wrong MIDI, or changing music while retaining the same totals fails.

```sh
python3 tools/audiveris-port/verify_embedded_score.py /path/to/pdf/export/job \
  --expected-movements 2 \
  --reference tools/audiveris-port/fixtures/chula-two-page-pdf-semantic-reference.json \
  --source-image tools/audiveris-port/fixtures/chula-two-page.pdf \
  --report build/pdf-parity.json
```
