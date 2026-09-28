# Shared embedded JVM bridge

`Sources/EmbeddedJVM.h` and `.mm` are shared by the acceptance probe and the
production build that bundles the native runtime. Ordinary Apple builds do not
compile this bridge until the matching JNI headers, static archives, and
resource image are supplied.

Swift entry points:

```swift
let report = try EmbeddedJVM.recognize(
    resourceRoot: resources.path, sandbox: sandbox.path, input: importedInput.path
)
EmbeddedJVM.cancelCurrentRecognition()
```

The JSON report contains `status`, `outputDirectory`, `musicXML`, `midi`,
`elapsedMilliseconds`, and `errors`. Input must be inside the engine sandbox.
The caller copies successful outputs into library storage. Canceled jobs return
a cancellation error or `CANCELLED`, and should not be imported into the library.
Cancellation is safe at image-job boundaries; it does not forcibly stop OCR.
The output directory remains in a returned `CANCELLED` report for cleanup. A
`TIMED_OUT` job may still have active workers; keep its files until they stop.

Call recognition on a dedicated worker with at least an 8 MiB native stack.
The Zero interpreter uses that stack for Java execution. The bridge serializes
engine calls, starts one VM, attaches later workers to that VM, and retains it
for the app's lifetime. `cancelCurrentRecognition` can run on another thread.
The resource root and sandbox cannot change after VM creation.

Resources must contain `java/*.jar`, `runtime/lib/modules`, `assets` with music
and text fonts, and `tessdata/eng.traineddata`. Native methods are resolved from
statically linked and exported archives. `loadfunctions()` is generated from
the actual archive symbols by the build script.

The probe-only `EmbeddedJVM.run(resourceRoot:sandbox:)` uses the same bootstrap
to run component checks and complete score recognition. Production builds can
omit the probe Java JAR and app UI while keeping the shared bridge.

Missing libraries, unsupported VM flags, JNI exceptions, and failed exports are
reported as errors. A successful build alone does not prove device execution;
use the separate iPhone/iPad acceptance workflow for that evidence.

## Build the production app with the embedded engine

After `build-embedded-probe.sh` has composed the matching runtime and OCR
artifacts, use its `embedding` directory to build the actual NoteLite app:

```sh
bash tools/audiveris-port/build-embedded-app.sh iphonesimulator \
  build/embedded-probe/iphonesimulator-arm64/embedding \
  build/embedded-app/iphonesimulator-arm64
```

Use `iphoneos` and its matching embedding directory for a device build. Keep the
downloaded runtime and OCR archives in place: the generated configuration uses
their absolute paths. Xcode, XcodeGen, and Python 3 are required.

The script creates an isolated XcodeGen overlay over `apple/project.yml`.
It adds the shared bridge, generated native symbol references, and the complete
`OMRResources` bundle. The `EMBEDDED_OMR_RUNTIME` compilation flag enables the
production recognition service. Original app screens, icons, document types,
and practice files remain part of the build. No source project or signing
setting is modified.

The output contains `NoteLite.app` and an `evidence` directory with the build
log, generated overlay, native link configuration, Mach-O platform check, and
SHA-256 resource inventory. The script verifies the JNI entry points and every
engine resource against the probe's copy. Device output is unsigned; simulator
output is signed locally for installation. This is a build artifact, not a
distribution archive.

The embedded acceptance workflow builds this app after the probe's simulator
recognition and semantic comparisons pass. Device composition follows a
successful device probe build. The production app inventory records recognition
execution separately; compiling it does not claim that its UI flow was run.

Run the production UI acceptance test on the same iPhone and iPad simulators:

```sh
bash tools/audiveris-port/run-embedded-app-tests.sh \
  build/embedded-app/iphonesimulator-arm64 SIMULATOR_UDID \
  build/embedded-app/iphonesimulator-arm64/ui-results/iphone
```

The generated `NoteLiteOffline` scheme runs only `NoteLiteOfflineUITests` against
the real app with its embedded engine enabled. It builds Debug to enable the
fixture import hook, then exercises library recognition and practice without a
server configuration. The runner preserves the Xcode result bundle, screenshots,
test log, and app Documents/Application Support data. Each test has a 2400-second
limit to accommodate interpreted execution. The acceptance workflow runs this
flow for both iPhone and iPad after the probe comparisons pass.
