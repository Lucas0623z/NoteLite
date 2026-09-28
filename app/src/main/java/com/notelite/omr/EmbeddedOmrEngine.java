// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 NoteLite contributors.
// Uses the Audiveris-derived engine. This program comes WITHOUT ANY WARRANTY.
package com.notelite.omr;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.BooleanSupplier;
import java.util.stream.Stream;

/**
 * In-process, offline entry point to the complete existing recognition pipeline.
 * The host must bundle the JVM, Java desktop/font support, OCR native libraries,
 * fonts, classifiers and traineddata. This class never starts a process or downloads them.
 * Input files must have been imported into the application's writable sandbox.
 */
public final class EmbeddedOmrEngine
{
    private final Path appHome;

    private static volatile Cancellation activeNativeCancellation;

    private EmbeddedOmrEngine (Path appHome)
    {
        this.appHome = appHome;
    }

    /**
     * Call before any other engine class or AWT is initialized. One sandbox is supported per JVM.
     * Desktop folder selection remains unchanged when notelite.appHome is absent.
     */
    public static EmbeddedOmrEngine open (Path appHome) throws IOException
    {
        if (appHome == null || !appHome.isAbsolute()) {
            throw new IllegalArgumentException("An absolute application sandbox is required");
        }
        synchronized (Main.class) {
            Files.createDirectories(appHome);
            final Path root = appHome.toRealPath();
            final String previous = System.getProperty("notelite.appHome");
            // Apple exposes the same sandbox through /var and /private/var. Resolve
            // both identities before enforcing the one-sandbox-per-JVM boundary.
            if (previous != null && !Path.of(previous).toRealPath().equals(root)) {
                throw new IllegalStateException("This JVM is already configured for a different appHome");
            }
            for (String folder : List.of("config", "data", "log", "tmp", "jobs")) {
                final Path directory = Files.createDirectories(root.resolve(folder)).toRealPath();
                if (!directory.startsWith(root)) {
                    throw new IllegalArgumentException("Sandbox subdirectory escapes appHome: " + folder);
                }
            }
            System.setProperty("java.awt.headless", "true");
            System.setProperty("notelite.appHome", root.toString());
            System.setProperty("java.io.tmpdir", root.resolve("tmp").toString());
            WellKnowns.ensureLoaded();
            if (!root.equals(WellKnowns.APP_HOME)) {
                throw new IllegalStateException("The OMR engine was initialized before its sandbox");
            }
            return new EmbeddedOmrEngine(root);
        }
    }

    public RecognitionResult recognize (Path input) throws IOException
    {
        return recognize(input, new Cancellation());
    }

    /**
     * Run transcription, MusicXML export and MIDI export on the real engine.
     * Cancellation is observed before and after a complete image job. It deliberately does
     * not kill an active OCR call or interrupt book persistence, so the JVM remains reusable.
     */
    public RecognitionResult recognize (Path input, Cancellation cancellation) throws IOException
    {
        if (input == null || cancellation == null) {
            throw new IllegalArgumentException("Input and cancellation must not be null");
        }
        synchronized (Main.class) {
            final Path source = input.toRealPath();
            if (!source.startsWith(appHome) || !Files.isRegularFile(source)) {
                throw new IllegalArgumentException("Input must be a file inside appHome");
            }
            final Path jobs = appHome.resolve("jobs").toRealPath();
            if (!jobs.startsWith(appHome)) {
                throw new IllegalArgumentException("Job folder escapes appHome");
            }
            final Path output = Files.createTempDirectory(jobs, "job-");
            Main.BatchResult batch = Main.runEmbeddedBatch(new String[] {
                    "-batch", "-transcribe", "-export", "-export-midi", "-output",
                    output.toString(), "--", source.toString()
            }, cancellation::isCancelled);
            final List<Path> xml = new ArrayList<>();
            final List<Path> midi = new ArrayList<>();
            if (batch.status() == Main.BatchStatus.SUCCESS) {
                try (Stream<Path> files = Files.walk(output)) {
                    for (Path file : files.filter(Files::isRegularFile).sorted().toList()) {
                        if (!file.toRealPath().startsWith(output)) {
                            throw new IOException("Export escaped its job directory");
                        }
                        final String name = file.getFileName().toString().toLowerCase(Locale.ROOT);
                        if (name.endsWith(".mxl") || name.endsWith(".musicxml")) {
                            if (Files.size(file) > 0) {
                                xml.add(file);
                            }
                        } else if (name.endsWith(".mid") && Files.size(file) > 0) {
                            midi.add(file);
                        }
                    }
                }
                if (xml.isEmpty() || midi.isEmpty()) {
                    batch = new Main.BatchResult(Main.BatchStatus.FAILED, batch.completedTasks(),
                            List.of("Recognition did not produce both MusicXML and MIDI"));
                    xml.clear();
                    midi.clear();
                }
            }
            return new RecognitionResult(batch, output, xml, midi);
        }
    }

    public Path appHome ()
    {
        return appHome;
    }

    /** Simple JNI entry: no Java Path/record marshalling is required in the native host. */
    public static String recognizeToJSON (String appHome, String input) throws IOException
    {
        return recognizeToJSON(appHome, input, new Cancellation());
    }

    /** The native token is owned by this synchronous call and is never retained by engine workers. */
    public static String recognizeToJSONWithNativeCancellation (String appHome, String input, long token)
            throws IOException
    {
        if (token == 0) {
            throw new IllegalArgumentException("A native request cancellation token is required");
        }
        return recognizeToJSON(appHome, input, new Cancellation(() -> nativeCancellationRequested(token)));
    }

    // Registered by the in-process host. The callback only reads that request's atomic flag.
    private static native boolean nativeCancellationRequested (long token);

    /** Explicit cancellation ownership, also used to test the JNI entry's boundary semantics. */
    public static String recognizeToJSON (String appHome, String input, Cancellation cancellation) throws IOException
    {
        if (cancellation == null) {
            throw new IllegalArgumentException("Cancellation must not be null");
        }
        synchronized (Main.class) {
            final long started = System.nanoTime();
            activeNativeCancellation = cancellation;
            final RecognitionResult result;
            try {
                result = open(Path.of(appHome)).recognize(Path.of(input), cancellation);
            } finally {
                activeNativeCancellation = null;
            }
            final String json = "{\"status\":" + jsonString(result.batch().status().name())
                + ",\"completedTasks\":" + result.batch().completedTasks()
                + ",\"elapsedMilliseconds\":" + (System.nanoTime() - started) / 1_000_000
                + ",\"outputDirectory\":" + jsonString(result.outputDirectory().toString())
                + ",\"musicXML\":" + jsonStrings(result.musicXML().stream().map(Path::toString).toList())
                + ",\"midi\":" + jsonStrings(result.midi().stream().map(Path::toString).toList())
                + ",\"errors\":" + jsonStrings(result.batch().errors()) + "}";
            Files.writeString(result.outputDirectory().resolve("embedded-result.json"), json);
            return json;
        }
    }

    /** Called from another JNI thread; cancellation is observed at a safe image-job boundary. */
    public static void cancelCurrentRecognition ()
    {
        final Cancellation cancellation = activeNativeCancellation;
        if (cancellation != null) {
            cancellation.cancel();
        }
    }

    private static String jsonStrings (List<String> values)
    {
        return "[" + String.join(",", values.stream().map(EmbeddedOmrEngine::jsonString).toList()) + "]";
    }

    private static String jsonString (String value)
    {
        final StringBuilder result = new StringBuilder("\"");
        for (int index = 0; index < value.length(); index++) {
            final char character = value.charAt(index);
            switch (character) {
                case '"' -> result.append("\\\"");
                case '\\' -> result.append("\\\\");
                case '\n' -> result.append("\\n");
                case '\r' -> result.append("\\r");
                case '\t' -> result.append("\\t");
                default -> {
                    if (character < 32) {
                        result.append(String.format(Locale.ROOT, "\\u%04x", (int) character));
                    } else {
                        result.append(character);
                    }
                }
            }
        }
        return result.append('"').toString();
    }

    public record RecognitionResult(Main.BatchResult batch, Path outputDirectory,
                                    List<Path> musicXML, List<Path> midi)
    {
        public RecognitionResult {
            musicXML = List.copyOf(musicXML);
            midi = List.copyOf(midi);
        }
    }

    public static final class Cancellation
    {
        private final AtomicBoolean cancelled = new AtomicBoolean();
        private final BooleanSupplier externalSignal;

        public Cancellation ()
        {
            this(() -> false);
        }

        Cancellation (BooleanSupplier externalSignal)
        {
            this.externalSignal = java.util.Objects.requireNonNull(externalSignal);
        }

        public void cancel ()
        {
            cancelled.set(true);
        }

        public boolean isCancelled ()
        {
            return cancelled.get() || externalSignal.getAsBoolean();
        }
    }
}
