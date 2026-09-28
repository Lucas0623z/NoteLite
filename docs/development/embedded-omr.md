# Embedded OMR API

`EmbeddedOmrEngine` runs the existing full Java engine in the caller's JVM. It
uses the real `-batch -transcribe -export -export-midi` pipeline and returns the
generated MusicXML and MIDI files. It launches no process and downloads no
runtime, library, or model.

```java
// Call before loading Main, WellKnowns, or AWT. Import the input into this sandbox.
var engine = EmbeddedOmrEngine.open(Path.of("/absolute/app/sandbox/omr"));
var result = engine.recognize(engine.appHome().resolve("score.png"));
if (result.batch().status() == Main.BatchStatus.SUCCESS) {
    // result.musicXML(), result.midi(), and result.outputDirectory()
}
```

The JNI-friendly static method
`EmbeddedOmrEngine.recognizeToJSON(String appHome, String input)` returns a JSON
report and writes the same report as `embedded-result.json` in its fresh job
directory. It throws a Java exception for invalid initialization or paths;
native callers must inspect and clear pending JNI exceptions.

`open` establishes `java.awt.headless=true`, `notelite.appHome`, and
`java.io.tmpdir` before engine initialization. `WellKnowns` resolves config,
data, and log directories inside this explicit sandbox. Existing desktop
folder behavior is unchanged when `notelite.appHome` is absent. One sandbox
is supported per JVM; switching it after initialization is rejected.

In an explicit app sandbox, scanned PDFs render at 300 DPI, matching the iOS
input-size check. A persisted desktop PDF resolution cannot increase that
allocation. Desktop sessions without `notelite.appHome` retain their configured
resolution.

Both input and output paths are checked against canonical sandbox paths.
Every recognition call creates a new job directory, so old exports cannot be
mistaken for successful recognition. The public wrapper only accepts image/PDF
inputs and requests both formats. The lower-level
`Main.runEmbeddedBatch(String[])` accepts a restricted batch CLI and returns a
structured status without calling `System.exit`; desktop `Main.main` retains
its existing behavior.

Jobs serialize because the underlying engine has global state. Pools are
drained before reuse. If workers ignore interruption and do not terminate,
the result is `TIMED_OUT`, and another job is refused until those workers end.
No `Thread.stop` is used. Cancellation tokens are checked at image-job
boundaries; an active OCR/transcription call is allowed to finish. This is not
immediate mid-stage cancellation.

The host must bundle compatible Java modules, native OCR libraries and JavaCPP
bindings, classifier data, fonts, and OCR traineddata. Set `TESSDATA_PREFIX`
before JVM startup, or place models under `appHome/config/tessdata`. The Java
API alone does not establish that these dependencies run on iOS.

## Integration validation

```sh
TESSDATA_PREFIX=/path/to/bundled/tessdata ./gradlew :app:embeddedOmrTest
```

This opt-in task runs eighteen engine integration tests in a fresh sandbox and
three template scoring regressions. It rejects
malformed arguments and outside paths, verifies cancellation and executor
timeout handling, feeds a corrupt image followed by two complete recognitions
of `data/examples/chula.png`, and exercises the JNI JSON entry. It parses the
actual exported MusicXML and MIDI to require pitched notes and sounding MIDI
note events. A two-page TIFF and a two-page scanned PDF each run through the
complete pipeline and must export both copies of the fixture: 302 pitched
notes and 440 MIDI note-on events. A persisted 600 DPI setting is loaded and
preserved while an embedded one-inch PDF page actually renders at 300 pixels.
The native scheduling path is also exercised with a real recognition and full
desktop semantic comparison. Native jobs use a 300-second step budget and a
900-second total budget covering exports. Regression tests keep uncooperative
workers tracked after a deadline, reject overlapping jobs, and ensure late
workers cannot call a native cancellation token after its owner returns.
Step diagnostics record wall/CPU time, GC deltas and asynchronous timeout
thread dumps; an unavailable measurement stays explicit.
The tests do not claim transcription accuracy against a human-verified
score or substitute for a device run.

## Template scoring on Zero

Actual iPhone and iPad simulator run `36425731144` passed all thirteen component
gates, but HEADS reached its 300-second step limit. Its worker consumed 233.672
and 240.293 CPU seconds respectively, with only 54 and 47 milliseconds of GC.
Samples repeatedly reached `Template.evaluate`, including `Math.abs(double)`
and its native double-bit conversion. Neither run produced a score export.

The scorer now derives the same binary 0.0/1.0 mismatch directly from the two
foreground predicates. It retains point order, weight multiplication, both
running sums, clipping, unknown-distance handling and the empty-support
sentinel. This removes double-bit conversion calls from that inner loop.
Production bytecode matched the frozen original Java oracle on all 10,368
score pairs, 1,296 anchor cases and 57 distance-transform cases. CI also runs
21,888 direct score-bit pairs covering signed distances, ROI views,
clipping, six weight configurations and both point orders, plus explicit
sentinel and order-sensitive regressions. An iOS speedup and complete score
exports still require the next actual simulator run; host timings do not
establish Zero performance.

The follow-up iPhone run `36429216883` still reached the HEADS limit (300.043
wall seconds, 237.103 CPU seconds, 70 milliseconds of GC). Its later samples
remained in template iteration and distance-table reads. The embedded host now
registers a C++ implementation of the same ordered scoring arithmetic. Every
call snapshots the current point list, reads its fields before pinning the
distance array, performs bounded pure computation, then releases the array.
No point list is cached. Integer tables, ROI views and custom short-table
subclasses retain their Java behavior. Registration failure stops recognition.

The scorer builds with `-O2 -fno-fast-math -ffp-contract=off`. The probe requires
actual native call/pin/release evidence and exact small scoring cases before
the full score. It also writes and reads a real diagnostic MIDI file, comparing
track, tick and message bytes. These component checks add to full MusicXML/MIDI
parity, repeated-thread recognition and the two multipage document checks.

Host validation separates two JVMs: `embeddedOmrTest` accepts
`-PnativeTemplateLibrary=/absolute/library` to run the complete pipeline through
the registered scorer, while `nativeTemplateCheckedTest` requires that option
and enables `-Xcheck:jni` for scoring and boundary regressions. Each class gets a
fresh JVM. This separation avoids the JNI checker's guarded copies on every
small AWT rectangle during full-image rendering. Both tasks record their actual
enabled state and before/after native counters; the checked task also records
the real VM flag. Checked workers establish headless mode and an explicit test
sandbox before engine classes initialize, avoiding unrelated desktop shell
discovery. The ten checked tests passed with no JNI warnings in the complete
host console log: 21,888 public scoring comparisons and 945 boundary pairs,
including mutable point lists, ROI geometry, rejected arguments and concurrent
GC. The complete native host engine made 6,043,635 scoring calls with matching
pin/release counts and no copies; all five PNG exports and both movements of
each PDF/TIFF export matched the original complete MusicXML/MIDI semantics.
Default host tests still exercise Java scoring. Native iOS speed and complete
exports remain subject to the next full acceptance run.
