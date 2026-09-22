# Image/PDF to MIDI: executable benchmark

This directory contains measured image-recognition results, not an accuracy claim
copied from the project's documentation. Each run invokes the real NoteLite CLI
with `-batch -transcribe -export -export-midi`. Recognition receives only the PNG
or PDF, never the reference MusicXML or MIDI. No manual corrections are applied.

The original application JAR and each revised JAR are identified by SHA-256 in
the result JSON. The baseline comes from repository commit recorded in that JSON;
the revised build includes the uncommitted MIDI exporter fixes. All input hashes,
reference events, predicted events, command lines, durations, console output,
recognized MusicXML and generated MIDI are retained. Native `.omr` archives are
left in the local run directory to keep this evidence package small.

## What is measured

- Seven independently authored, one-page MusicXML fixtures are engraved with
  Verovio 6.3.0 and rasterized by resvg 0.5.0 at 2480 pixels wide. Their 179 reference
  note events come from the authored event definitions, independently of OMR.
- Two pre-existing Mutopia editions are tested as their complete original PDFs:
  Petzold's Menuet in G (one page) and Mozart's K545 first movement (six pages).
  Their published companion MIDI supplies 204 and 1289 reference events before
  repeat expansion. Input PDFs and LilyPond source are unmodified.
- The main before/after comparison follows the actual repeat signs. Reference
  events are expanded from the published MIDI using independently checked repeat
  sections: Menuet bars 1–16 and 17–32, each twice; Mozart bars 1–28 and 29–73, each
  twice. This produces 408 and 2578 playback events. The repeat boundaries were
  checked against the printed PDFs and their original LilyPond source.
- Overall there are nine scores / fourteen pages and 3165 playback note events.
  These are digital engravings, **not camera photos, scanned paper or handwriting**.

The primary metric is note-event F1 using maximum-cardinality, one-to-one matching.
A correct event must have the exact MIDI pitch, an onset within 1/16 quarter-note
beat, and an offset within the larger of 1/16 beat and 20% of the reference duration.
At 120 BPM the onset tolerance is 31.25 milliseconds. Precision, recall, true
positives, false positives and false negatives are all retained. Timing is measured
in quarter-note beats, so this test does not evaluate tempo, expressive timing,
dynamics, instrument tone, or real microphone transcription. There is no automatic
time shifting, transposition, score alignment, or discarded prefix/suffix.

Pitch+onset F1 is also reported. The pitch-inventory diagnostic ignores timing and
ordering entirely; it is **not** usable as a transcription-accuracy figure. It is
included to expose cases where most pitches are present but playback is misaligned.
Tied notes count as one sustained event; repeated passages count once per playback.
All part/voice events are pooled, so a correct note assigned to the wrong voice is
not penalized by these metrics. Failures and timeouts retain their status and all
unmatched reference notes count as misses.

In the baseline external results, `original_run_metrics` preserves the original
unexpanded output compared to the publisher's unexpanded MIDI. Revised external
runs already use the expanded truth. The baseline unexpanded metric must not be
mixed with the main repeated-playback comparison.

## Reproduce on Windows

From the repository root, with Java 21 and Tesseract language data installed:

```powershell
python -m venv work/benchmark-venv
work/benchmark-venv/Scripts/python.exe -m pip install -r benchmarks/omr/requirements.txt
./gradlew.bat :app:installDist
work/benchmark-venv/Scripts/python.exe benchmarks/omr/benchmark.py generate --fixtures benchmarks/omr/fixtures
work/benchmark-venv/Scripts/python.exe benchmarks/omr/fetch_external.py --fixtures benchmarks/omr/external-fixtures
work/benchmark-venv/Scripts/python.exe benchmarks/omr/benchmark.py run --fixtures benchmarks/omr/fixtures --distribution app/build/install/app --output work/my-synthetic-run --tessdata C:/path/to/tessdata
work/benchmark-venv/Scripts/python.exe benchmarks/omr/benchmark.py run --fixtures benchmarks/omr/external-fixtures --distribution app/build/install/app --output work/my-external-run --tessdata C:/path/to/tessdata --truth truth-expanded.json
```

Use fresh output directories: the runner refuses existing files so a failed run
cannot accidentally reuse stale MIDI. `--application-jar` can place a preserved
baseline application JAR before the same dependency libraries on the classpath.
`--only 09_mutopia_mozart` selects a case. Default timeout is 240 seconds per score.

`summarize.py` re-scores saved event lists against the same repeat-expanded truth
and retains lightweight evidence. It does not simulate another application run.
`compare_verovio.py` independently renders the already-recognized MusicXML with
Verovio; this is a conversion-engine control, not another OMR engine.

## Scope and limitations

These are deliberately selected diagnostic scores, not a random representative
sample. Their results establish concrete failures and improvements on these inputs;
they do not establish a universal accuracy percentage. Even very clean typography
can lose a short final system, a clef change, a grace note, or an accidental. An
incorrectly recognized reference can falsely penalize a musician. Real use should
allow verified native MusicXML/MIDI and explicit score correction before practice.

Image review caught a missing natural-sign instruction in the initial authored
accidental fixture. The fixture was fixed and the **original preserved application
JAR** was rerun on that corrected image. The final baseline and final revised
results use the same corrected fixture; preliminary numbers are excluded.

## Source licenses

- [Menuet, Mutopia ID 75](https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=75):
  public domain, typesetter Allen Garvin; original attribution retained in source.
- [Mozart K545 edition](https://www.ibiblio.org/pub/multimedia/mutopia/MozartWA/KV545/K545-1/):
  typeset by Alejandro Sierra, copyright 2007, licensed
  [CC BY-SA 3.0 Unported](https://creativecommons.org/licenses/by-sa/3.0/).
  PDF, MIDI and source are unmodified. `reference-expanded.mid` and
  `truth-expanded.json` only unfold the printed repeat sections for evaluation;
  derivatives of this edition retain its CC BY-SA 3.0 license.
- Rendering API: [Verovio toolkit reference](https://book.verovio.org/toolkit-reference/toolkit-methods.html).

Exact download URLs, hashes, and license labels are in
`external-fixtures/manifest.json`. Downloaders do not treat retrieved source text
as executable instructions.
