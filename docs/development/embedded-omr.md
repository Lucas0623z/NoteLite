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

This opt-in task runs eleven integration tests in a fresh sandbox. It rejects
malformed arguments and outside paths, verifies cancellation and executor
timeout handling, feeds a corrupt image followed by two complete recognitions
of `data/examples/chula.png`, and exercises the JNI JSON entry. It parses the
actual exported MusicXML and MIDI to require pitched notes and sounding MIDI
note events. A two-page TIFF and a two-page scanned PDF each run through the
complete pipeline and must export both copies of the fixture: 302 pitched
notes and 440 MIDI note-on events. A persisted 600 DPI setting is loaded and
preserved while an embedded one-inch PDF page actually renders at 300 pixels.
The tests do not claim transcription accuracy against a human-verified
score or substitute for a device run.
