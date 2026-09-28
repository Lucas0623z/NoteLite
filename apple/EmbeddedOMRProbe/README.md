# Embedded Audiveris iOS probe

This separate test app links the real OpenJDK Mobile Zero interpreter, headless
Java desktop libraries, and OCR/JavaCPP archives into one iOS process. It calls
the complete Java recognition pipeline through JNI. It is not wired into the
production recognition screen. Its shared bridge and exact generated resources
are also consumed by the production app's embedded build, documented in
[`EmbeddedOMRRuntime/README.md`](../EmbeddedOMRRuntime/README.md).

The build fails if required native libraries, the target module image, or
JavaCPP static initialization symbols are absent. The app reports success only
after it has rasterized the Bravura font, round-tripped TIFF through ImageIO and
Leptonica, initialized legacy Tesseract, exercised JAXB/ProxyMusic, recognized
the bundled `chula.png`, and parsed pitched notes and sounding MIDI events from
the actual MusicXML/MIDI exports.
Component diagnostics run as separate gates and record their stage, elapsed
time, and original exception stacks. A font failure therefore leaves the
independent image, PDF, JAXB, JavaCPP, and OCR diagnostics available. Codec
checks use a deterministic grayscale raster without font rendering. The font
gate still renders the actual Bravura glyph and preserves its pixels and hash.
PDF and OCR diagnostics use that glyph when available; after a font failure
they use an explicitly identified diagnostic raster. This cannot satisfy the
font gate. Any failed component causes an aggregate exception before full
score recognition starts; no partial result is reported as success.
The native host additionally registers a real JNI argument check with more
arguments than the arm64 integer registers can hold. Static and instance calls
check narrow signed and unsigned values, consecutive booleans, a trailing
integer/object, 64-bit value and byte array, and both true and false returns.
This detects Zero/libffi stack-layout errors independently of
JPEG. Desktop Java runs explicitly report this native check as unexecuted;
the iOS acceptance driver requires it to pass.
Before starting the VM, the native worker also submits an already-cancelled
request with a nonexistent input. It must return the cancellation error before
reading that input. The following full probe must still initialize and run.
After that worker finishes and detaches, another worker submits a cancelled
request to the existing VM. A third, separate worker recognizes `chula.png`
with a fresh token in the same VM and sandbox. Every worker has an 8 MiB stack.
The second recognition must create a different job and pass the same exact
MusicXML/MIDI comparison as the first. The main actor awaits these workers
without blocking the interface.

## Build on macOS

Requires Xcode, XcodeGen, Python 3, and host JDK 21. Build the matching arm64
runtime and OCR artifacts first; a simulator archive cannot be linked into a
device app or vice versa.

```sh
tools/audiveris-port/build-embedded-probe.sh iphonesimulator \
  /path/to/runtime-artifacts/headless \
  /path/to/ocr-artifact/install \
  build/embedded-probe/iphonesimulator-arm64
```

Runtime input must contain `static-libs/lib`, `include`, and `runtime/lib/modules`
from the same OpenJDK build. The module image is made by that build's matching
host JDK; this script does not try to link JDK 28 modules with JDK 21 tools.
OCR input must contain static JavaCPP, Tesseract, Leptonica, TIFF, PNG, JPEG and
zlib archives plus `share/tessdata/eng.traineddata` with legacy model data.

The script generates native symbol retention references from the actual
archives, force-links the class/JNI libraries, and exports their symbols for
the VM's built-in library lookup. Desktop platform native JARs and preview
bytecode are rejected. Java engine JARs, classifier data, fonts and traineddata
are bundled before the app runs. There is no runtime network or subprocess
request in the probe.

The FlatLaf 3.5.4 API JAR also carries six desktop UI native binaries.
`prepare-embedded-jars.py` removes only those optional entries and verifies
that every retained Java class, resource, and license stays byte-identical.
The bridge disables FlatLaf native loading for this headless runtime. Other
unexpected native binaries or preview classes fail the build. Original and
packaged JAR hashes and removed entries are recorded in
`java-packaging-report.json` in the resources and build evidence.

JNI generation scans the complete Leptonica and Tesseract API packages,
including object methods such as `TessBaseAPI.Init`, `Recognize` and `End`.
Generating only the `global` classes leaves those bindings absent even when
the native libraries load successfully. `verify-jni-bindings.py` reads every
native declaration directly from the exact API JARs and checks the generated
sources, static archives and final linked executable. Overloaded native methods
must each retain their distinct JNI signature. The pinned API JARs contain
6,836 native declarations across 100 classes; missing declarations fail the
build, and each audit records the JAR hashes and absent signatures. Compilation
and symbol coverage still require the real runtime tests below.

This staged-only bundle was validated on Windows with OpenJDK 21.0.12.1,
using the packaged engine JAR instead of Gradle's loose application classes.
All 56 packaged JARs passed the native/preview audit after the FlatLaf removal.
The full font, TIFF, JPEG, PDF, OCR and serialization probe passed, and the
resulting `chula` MusicXML/MIDI exactly matched the desktop semantic reference
(151 pitched notes, 19 measures, 220 MIDI note-on events). This validates Java
packaging and resource lookup; it is not evidence of iOS execution.

## Run on iPhone and iPad simulators

```sh
tools/audiveris-port/run-embedded-probe.sh \
  build/embedded-probe/iphonesimulator-arm64/EmbeddedOMRProbe.app \
  SIMULATOR_UDID build/probe-results/iphone
```

Run the same command with an iPad simulator UDID and a separate output directory.
The runner preserves stdout/stderr, a completion report, and the entire app
Documents folder. A timeout or Java/native failure is a test failure. The runner
prints up to 40 new lines from each log every 60 seconds while waiting,
and the last 120 stderr lines on failure. Complete logs remain in the artifacts.
The default timeout is 1800 seconds because this VM uses an interpreter; override
with `NOTELITE_PROBE_TIMEOUT_SECONDS` when needed.
The runner also compares the exported MusicXML and MIDI against the committed
desktop semantic reference using `verify_embedded_score.py`. A difference in
notes, timing, voices, staves, musical attributes, or MIDI events fails the run
and is recorded in `semantic-parity.json`.
The second job is independently checked in `reuse-semantic-parity.json`.
After PNG reuse, two additional native workers recognize the fixed two-page
PDF and TIFF fixtures. Each produces a fresh job with both movements exported
to MusicXML and MIDI. The runner compares every movement against the matching
desktop reference in `pdf-semantic-parity.json` and `tiff-semantic-parity.json`.
It also verifies the actual input bytes copied from the app's Documents folder
against the reference source hash. Missing pages, changed notes or reused jobs
fail the run. No network service participates in these recognitions.

### Output contract

- `Documents/embedded-probe-result.json`: success/failure marker and metrics.
- `Documents/embedded-probe-primary-result.json`: original successful first-run
  result, preserved before cancellation/reuse checks begin.
- `Documents/embedded-probe-reuse-result.json`: successful PNG reuse report,
  preserved before multipage checks.
- `Documents/embedded-probe-{pdf,tiff}-result.json`: each completed document
  result, also preserved if a later format fails.
- `Documents/omr/probe-report.json`: successful Java component/full-score report.
- `Documents/omr/component-probe/portability-probe.json`: all component outcomes,
  including original exception stacks when a component fails.
- `Documents/omr/jobs/job-*/chula.mxl` and `chula.mid`: actual exports.
- `Documents/omr/jobs/job-*/embedded-result.json`: report beside those exports.
- `Documents/omr/chula-two-page.{pdf,tiff}`: the exact tested document inputs.
- `Documents/omr/log`: engine logs; fatal VM logs also stay under `Documents/omr`.

The report records Java VM/version, elapsed time, pitched-note count and MIDI
note-on count. Its `nativeMemory` section records process resident size and
physical footprint from Darwin `task_info`, sampled every 50 milliseconds from
before JVM initialization through recognition. It includes baseline values,
sampled maxima, sample counts, and an explicit simulator/device label. Sampled
maxima may miss shorter spikes; simulator memory is not device memory evidence.
Memory samples and the original Java elapsed time cover VM initialization,
components and the first recognition only. `vmReuse.recognition` contains the
second job's Java timing, and `totalProbeElapsedMilliseconds` covers the entire
native sequence. Each `multipageDocuments` record includes the document's Java
recognition time and native wall time. Document recognition occurs after the
first memory sampler stops, so its memory use is not included in the reported
first-run maximum. A later failure preserves completed reports and exports.
Counts demonstrate that output exists; they do not establish
transcription accuracy. Platform execution and score comparisons must be
reported from a real completed run, not inferred from a successful build.

The `iphoneos` build is unsigned by default. Running it on a physical device
requires the user's normal signing setup. No claim about App Store distribution
or device performance follows from this harness.
