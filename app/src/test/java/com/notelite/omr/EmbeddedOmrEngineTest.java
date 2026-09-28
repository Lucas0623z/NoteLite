// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 NoteLite contributors.
package com.notelite.omr;

import com.notelite.omr.text.tesseract.TesseractOCR;
import com.notelite.omr.constant.Constant;
import com.notelite.omr.image.ImageLoading;
import com.notelite.omr.util.OmrExecutors;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.zip.ZipFile;
import javax.imageio.IIOImage;
import javax.imageio.ImageIO;
import javax.sound.midi.MidiEvent;
import javax.sound.midi.MidiSystem;
import javax.sound.midi.Sequence;
import javax.sound.midi.ShortMessage;
import javax.sound.midi.Track;
import javax.xml.XMLConstants;
import javax.xml.parsers.DocumentBuilderFactory;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.PDPage;
import org.apache.pdfbox.pdmodel.PDPageContentStream;
import org.apache.pdfbox.pdmodel.common.PDRectangle;
import org.apache.pdfbox.pdmodel.graphics.image.LosslessFactory;
import org.junit.BeforeClass;
import org.junit.Assume;
import org.junit.Test;
import org.w3c.dom.Document;
import static org.junit.Assert.*;

/** Opt-in integration tests: ./gradlew :app:embeddedOmrTest with bundled OCR data available. */
public class EmbeddedOmrEngineTest
{
    private static EmbeddedOmrEngine engine;
    private static Path input;

    @BeforeClass
    public static void setUp () throws Exception
    {
        final Path base = Path.of(System.getProperty("notelite.embeddedTestRoot"));
        Files.createDirectories(base);
        final Path sandbox = Files.createTempDirectory(base, "sandbox-");
        // Simulate an existing desktop/custom setting in this isolated embedded
        // sandbox, before ConstantManager is initialized. No user config is touched.
        Files.createDirectories(sandbox.resolve("config"));
        Files.writeString(sandbox.resolve("config/run.properties"),
                "com.notelite.omr.image.ImageLoading.pdfResolution=600\n");
        // Match the native host, which supplies the sandbox as a VM property.
        System.setProperty("notelite.appHome", sandbox.toString());
        engine = EmbeddedOmrEngine.open(sandbox);
        input = engine.appHome().resolve("chula.png");
        Files.copy(Path.of(System.getProperty("notelite.embeddedTestInput")), input,
                StandardCopyOption.REPLACE_EXISTING);
    }

    @Test
    public void usesExplicitSandboxBeforeHeadlessInitialization () throws Exception
    {
        assertEquals("true", System.getProperty("java.awt.headless"));
        assertEquals(engine.appHome(), WellKnowns.APP_HOME);
        assertEquals(engine.appHome().resolve("config"), WellKnowns.CONFIG_FOLDER);
        assertEquals(engine.appHome().resolve("data"), WellKnowns.DATA_FOLDER);
        assertEquals(engine.appHome().resolve("log"), WellKnowns.LOG_FOLDER);
        assertEquals(engine.appHome(), EmbeddedOmrEngine.open(engine.appHome()).appHome());
        assertThrows(IllegalStateException.class,
                () -> EmbeddedOmrEngine.open(engine.appHome().resolve("different")));
    }

    @Test
    public void nativeStepBudgetLeavesHostSettingUnchanged ()
    {
        final String previous = System.getProperty("notelite.omr.jniHost");
        try {
            System.clearProperty("notelite.omr.jniHost");
            final int desktop = Main.getSheetStepTimeOut();
            System.setProperty("notelite.omr.jniHost", "true");
            assertEquals(300, Main.getSheetStepTimeOut());
            System.clearProperty("notelite.omr.jniHost");
            assertEquals(desktop, Main.getSheetStepTimeOut());
        } finally {
            if (previous == null) System.clearProperty("notelite.omr.jniHost");
            else System.setProperty("notelite.omr.jniHost", previous);
        }
    }

    @Test(timeout = 10_000)
    public void totalDeadlineRetainsUncooperativeWorkersAndRejectsOverlap () throws Exception
    {
        final CountDownLatch started = new CountDownLatch(1);
        final CountDownLatch release = new CountDownLatch(1);
        OmrExecutors.restartForEmbedded();
        try {
            assertThrows(TimeoutException.class, () -> Main.runWithEmbeddedDeadline(() -> {
                started.countDown();
                // Model a native/image call that does not stop at interruption.
                while (release.getCount() != 0) {
                    try { release.await(); }
                    catch (InterruptedException ignored) { }
                }
                return "late success must not be returned";
            }, 500));
            assertTrue(started.await(1, TimeUnit.SECONDS));
            assertFalse(OmrExecutors.shutdownForEmbedded(true, 0));
            assertThrows(IllegalStateException.class, OmrExecutors::restartForEmbedded);
        } finally {
            release.countDown();
            assertTrue(OmrExecutors.shutdownForEmbedded(true, 2_000));
            OmrExecutors.restartForEmbedded();
        }
        assertEquals("next independent job", Main.runWithEmbeddedDeadline(() -> "next independent job", 1_000));
        assertTrue(OmrExecutors.shutdownForEmbedded(false, 2_000));
    }

    @Test(timeout = 10_000)
    public void deadlineRejectsInvalidBudgetsAndPreservesWorkerExceptions () throws Exception
    {
        assertThrows(IllegalArgumentException.class, () -> Main.runWithEmbeddedDeadline(() -> "", 0));
        assertThrows(IllegalArgumentException.class, () -> Main.runWithEmbeddedDeadline(() -> "", 900_001));
        OmrExecutors.restartForEmbedded();
        try {
            final IOException expected = new IOException("original worker failure");
            final IOException actual = assertThrows(IOException.class,
                    () -> Main.runWithEmbeddedDeadline(() -> { throw expected; }, 1_000));
            assertSame(expected, actual);
        } finally {
            assertTrue(OmrExecutors.shutdownForEmbedded(true, 2_000));
        }
    }

    @Test(timeout = 10_000)
    public void closedCancellationNeverTouchesTheReleasedNativeCallback () throws Exception
    {
        final AtomicInteger calls = new AtomicInteger();
        final Main.ScopedCancellation scoped = new Main.ScopedCancellation(() -> {
            calls.incrementAndGet();
            return false;
        });
        assertFalse(scoped.getAsBoolean());
        scoped.close();
        final var worker = Executors.newSingleThreadExecutor();
        try {
            assertTrue(worker.submit(scoped::getAsBoolean).get(1, TimeUnit.SECONDS));
            assertEquals("The late worker must not use a released JNI token", 1, calls.get());
            final Main.ScopedCancellation next = new Main.ScopedCancellation(() -> false);
            assertFalse("A fresh job has independent cancellation", next.getAsBoolean());
            next.close();
        } finally {
            worker.shutdownNow();
            assertTrue(worker.awaitTermination(1, TimeUnit.SECONDS));
        }
    }

    @Test(timeout = 600_000)
    public void nativeDeadlineSchedulingPreservesRealScoreAndRecordsStepTiming () throws Exception
    {
        final String previous = System.getProperty("notelite.omr.jniHost");
        try {
            // Exercises the native scheduling/budget path with real host OCR.
            // It is not evidence of Zero or iOS performance.
            System.setProperty("notelite.omr.jniHost", "true");
            final var result = engine.recognize(input);
            assertEquals(result.batch().errors().toString(), Main.BatchStatus.SUCCESS, result.batch().status());
            assertEquals(151, countPitchedNotes(result.musicXML().get(0)));
            assertEquals(220, countNoteOnEvents(result.midi().get(0)));
            final String timing = Files.readString(result.outputDirectory().resolve("embedded-step-timing.jsonl"));
            assertTrue(timing.contains("\"event\":\"completed\""));
            assertTrue(timing.contains("\"step\":\"BEAMS\""));
            assertTrue(timing.contains("\"workerCPUMilliseconds\":"));
            assertTrue(timing.contains("\"processGCMilliseconds\":"));
            assertNull(Main.getCli());
        } finally {
            if (previous == null) System.clearProperty("notelite.omr.jniHost");
            else System.setProperty("notelite.omr.jniHost", previous);
        }
    }

    @Test(timeout = 10_000)
    public void stepDiagnosticsPreserveTimingAndAsynchronousThreadEvidence () throws Exception
    {
        final Path directory = Files.createTempDirectory(engine.appHome(), "diagnostics-");
        EmbeddedStepDiagnostics.beginJob(directory);
        try {
            final var step = EmbeddedStepDiagnostics.beginStep("diagnostic-fixture", "WAITING");
            assertNotNull(step);
            step.sample("running", true);
            step.timedOut();
            step.sample("completed", false);
        } finally {
            EmbeddedStepDiagnostics.endJob();
        }
        final long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(3);
        boolean captured = false;
        while (!captured && System.nanoTime() < deadline) {
            try (var paths = Files.list(directory)) {
                captured = paths.anyMatch(path -> path.getFileName().toString().startsWith("embedded-threads-"));
            }
            if (!captured) Thread.sleep(20);
        }
        assertTrue("The daemon sampler must preserve the thread dump", captured);
        final String timing = Files.readString(directory.resolve("embedded-step-timing.jsonl"));
        assertTrue(timing.contains("\"workerCPUMilliseconds\":"));
        assertTrue(timing.contains("\"wallMilliseconds\":"));
        assertTrue(timing.contains("\"cpuTimeStatus\":"));
        assertTrue(timing.contains("\"event\":\"completed\""));
    }

    @Test
    public void acceptsAliasesOfTheSameSandboxButRejectsOtherDirectories () throws Exception
    {
        final Path links = Files.createTempDirectory(engine.appHome().getParent(), "aliases-");
        final Path alias = links.resolve("sandbox");
        final String previous = System.getProperty("notelite.appHome");
        try {
            try {
                Files.createSymbolicLink(alias, engine.appHome());
            } catch (IOException | UnsupportedOperationException ex) {
                // Windows may require an administrator to create a symlink. On
                // macOS/Linux this regression must run, including the iOS host CI.
                if (!System.getProperty("os.name").startsWith("Windows")) {
                    throw ex;
                }
                Assume.assumeNoException("Windows symlink creation is unavailable", ex);
            }
            // The native host sets this property before open() first runs. The
            // textual path may differ from the real path passed by the caller.
            System.setProperty("notelite.appHome", alias.toString());
            assertEquals(engine.appHome(), EmbeddedOmrEngine.open(engine.appHome()).appHome());
            assertEquals(engine.appHome(), EmbeddedOmrEngine.open(alias).appHome());
            assertThrows(IllegalStateException.class,
                    () -> EmbeddedOmrEngine.open(links.resolve("different")));
            assertEquals(engine.appHome().toString(), System.getProperty("notelite.appHome"));
        } finally {
            System.setProperty("notelite.appHome", previous);
            Files.deleteIfExists(alias);
            Files.deleteIfExists(links.resolve("different"));
            Files.delete(links);
        }
    }

    @Test
    public void invalidArgumentsDoNotExitOrPoisonNextCall ()
    {
        assertThrows(IllegalArgumentException.class,
                () -> Main.runEmbeddedBatch(new String[] { "-batch", "-not-a-real-option" }));
        assertThrows(IllegalArgumentException.class,
                () -> Main.runEmbeddedBatch(new String[] { "-batch", "@external.args" }));
        assertThrows(IllegalArgumentException.class,
                () -> Main.runEmbeddedBatch(new String[] { "-batch", "-run", "java.lang.System" }));
        assertEquals(Main.BatchStatus.SUCCESS,
                Main.runEmbeddedBatch(new String[] { "-batch", "-help" }).status());
        assertEquals(Main.BatchStatus.SUCCESS,
                Main.runEmbeddedBatch(new String[] { "-batch", "-help" }).status());
    }

    @Test
    public void rejectsInputOutsideSandbox () throws Exception
    {
        final Path external = Path.of(System.getProperty("notelite.embeddedTestInput"));
        assertThrows(IllegalArgumentException.class, () -> engine.recognize(external));
        assertThrows(IllegalArgumentException.class, () -> Main.runEmbeddedBatch(new String[] {
                "-batch", "-transcribe", "-output", engine.appHome().toString(),
                "--", external.toString()
        }));
    }

    @Test
    public void cancelledJobReturnsWithoutExportAndJvmCanBeReused () throws Exception
    {
        final EmbeddedOmrEngine.Cancellation cancellation = new EmbeddedOmrEngine.Cancellation();
        cancellation.cancel();
        final var result = engine.recognize(input, cancellation);
        assertEquals(Main.BatchStatus.CANCELLED, result.batch().status());
        assertEquals(0, result.batch().completedTasks());
        assertTrue(result.musicXML().isEmpty());
        assertTrue(result.midi().isEmpty());
        assertEquals(Main.BatchStatus.SUCCESS,
                Main.runEmbeddedBatch(new String[] { "-batch", "-help" }).status());
    }

    @Test(timeout = 120_000)
    public void ownedCancellationBeforeEntryCannotCancelFollowingJob () throws Exception
    {
        final AtomicBoolean signal = new AtomicBoolean(true);
        final var old = new EmbeddedOmrEngine.Cancellation(signal::get);
        final String cancelled = EmbeddedOmrEngine.recognizeToJSON(
                engine.appHome().toString(), input.toString(), old);
        assertTrue(cancelled.contains("\"status\":\"CANCELLED\""));
        assertTrue(cancelled.contains("\"completedTasks\":0"));
        // A late cancellation of the old token while the following job polls
        // must never act on the following job's cancellation state.
        final var next = new EmbeddedOmrEngine.Cancellation(() -> {
            old.cancel();
            return false;
        });
        final String success = EmbeddedOmrEngine.recognizeToJSON(
                engine.appHome().toString(), input.toString(), next);
        assertTrue(success.contains("\"status\":\"SUCCESS\""));
        assertFalse(next.isCancelled());
        assertThrows(IllegalArgumentException.class, () ->
                EmbeddedOmrEngine.recognizeToJSONWithNativeCancellation(
                        engine.appHome().toString(), input.toString(), 0));
    }

    @Test
    public void cancellationAfterEntryIsPolledBeforeRecognitionStarts () throws Exception
    {
        final AtomicInteger polls = new AtomicInteger();
        // The first batch boundary succeeds. Cancellation arrives during
        // initialization and must be observed again before the CLI task runs.
        final var cancellation = new EmbeddedOmrEngine.Cancellation(() -> polls.incrementAndGet() >= 2);
        final String json = EmbeddedOmrEngine.recognizeToJSON(
                engine.appHome().toString(), input.toString(), cancellation);
        assertTrue(polls.get() >= 2);
        assertTrue(json.contains("\"status\":\"CANCELLED\""));
        assertTrue(json.contains("\"completedTasks\":0"));
        assertTrue(json.contains("\"musicXML\":[]"));
        assertTrue(json.contains("\"midi\":[]"));
    }

    @Test(timeout = 120_000)
    public void nativeCancellationEntryCanBeCalledFromAnotherThread () throws Exception
    {
        assertNull(Main.getCli());
        final var worker = Executors.newSingleThreadExecutor();
        try {
            final var result = worker.submit(() -> EmbeddedOmrEngine.recognizeToJSON(
                    engine.appHome().toString(), input.toString()));
            final long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(15);
            while (Main.getCli() == null && !result.isDone() && System.nanoTime() < deadline) {
                Thread.sleep(2);
            }
            assertNotNull("The job must start before the cancellation request", Main.getCli());
            EmbeddedOmrEngine.cancelCurrentRecognition();
            assertTrue(result.get(90, TimeUnit.SECONDS).contains("\"status\":\"CANCELLED\""));
            assertNull(Main.getCli());
            assertEquals(Main.BatchStatus.SUCCESS,
                    Main.runEmbeddedBatch(new String[] { "-batch", "-help" }).status());
        } finally {
            worker.shutdown();
            assertTrue(worker.awaitTermination(10, TimeUnit.SECONDS));
        }
    }

    @Test
    public void timedOutWorkersPreventOverlappingJobsUntilTheyFinish () throws Exception
    {
        final CountDownLatch entered = new CountDownLatch(1);
        final CountDownLatch release = new CountDownLatch(1);
        final CountDownLatch done = new CountDownLatch(1);
        OmrExecutors.restartForEmbedded();
        OmrExecutors.getHighExecutor().submit(() -> {
            entered.countDown();
            try {
                while (release.getCount() != 0) {
                    try {
                        release.await();
                    } catch (InterruptedException ignored) {
                        // Simulate a native call that does not respond to interrupt immediately.
                    }
                }
            } finally {
                done.countDown();
            }
        });
        try {
            assertTrue(entered.await(10, TimeUnit.SECONDS));
            assertFalse(OmrExecutors.shutdownForEmbedded(true, 20));
            assertThrows(IllegalStateException.class, OmrExecutors::restartForEmbedded);
        } finally {
            release.countDown();
            assertTrue(done.await(10, TimeUnit.SECONDS));
            assertTrue(OmrExecutors.shutdownForEmbedded(true, 10_000));
        }
        OmrExecutors.restartForEmbedded();
        assertTrue(OmrExecutors.shutdownForEmbedded(false, 10_000));
    }

    @Test(timeout = 600_000)
    public void embeddedPdfRasterIgnoresPersistedDesktopResolution () throws Exception
    {
        final var field = ImageLoading.class.getDeclaredField("constants");
        field.setAccessible(true);
        final Object settings = field.get(null);
        final var resolutionField = settings.getClass().getDeclaredField("pdfResolution");
        resolutionField.setAccessible(true);
        final Constant.Integer resolution = (Constant.Integer) resolutionField.get(settings);
        assertEquals("The stored override must really be loaded", 600, resolution.getValue().intValue());
        final Path pdf = engine.appHome().resolve("resolution-check.pdf");
        try (var document = new PDDocument()) {
            document.addPage(new PDPage(new PDRectangle(72, 72)));
            document.save(pdf.toFile());
        }
        final var loader = ImageLoading.getLoader(pdf);
        assertNotNull(loader);
        try {
            final var image = loader.getImage(1);
            assertEquals(300, image.getWidth());
            assertEquals(300, image.getHeight());
            // The configurable value itself remains unchanged for ordinary
            // desktop sessions; only the explicit embedded session fixes DPI.
            assertEquals(600, resolution.getValue().intValue());
        } finally {
            loader.dispose();
            Files.deleteIfExists(pdf);
        }
    }

    @Test(timeout = 600_000)
    public void everyPageOfTiffAndScannedPdfReachesMusicXmlAndMidi () throws Exception
    {
        final var image = ImageIO.read(input.toFile());
        assertNotNull(image);
        final Path tiff = engine.appHome().resolve("multipage.tiff");
        final var writers = ImageIO.getImageWritersByFormatName("TIFF");
        assertTrue("The embedded Java image stack must include a TIFF writer", writers.hasNext());
        final var writer = writers.next();
        try (var output = ImageIO.createImageOutputStream(tiff.toFile())) {
            writer.setOutput(output);
            writer.prepareWriteSequence(null);
            for (int page = 0; page < 2; page++) {
                writer.writeToSequence(new IIOImage(image, null, null), null);
            }
            writer.endWriteSequence();
        } finally {
            writer.dispose();
        }
        final Path pdf = engine.appHome().resolve("multipage.pdf");
        try (var document = new PDDocument()) {
            final float width = image.getWidth() * 72f / 300f;
            final float height = image.getHeight() * 72f / 300f;
            final var raster = LosslessFactory.createFromImage(document, image);
            for (int index = 0; index < 2; index++) {
                final var page = new PDPage(new PDRectangle(width, height));
                document.addPage(page);
                try (var content = new PDPageContentStream(document, page)) {
                    content.drawImage(raster, 0, 0, width, height);
                }
            }
            document.save(pdf.toFile());
        }
        for (Path document : List.of(tiff, pdf)) {
            final var result = engine.recognize(document);
            assertEquals(result.batch().errors().toString(), Main.BatchStatus.SUCCESS, result.batch().status());
            int notes = 0;
            for (Path xml : result.musicXML()) notes += countPitchedNotes(xml);
            int events = 0;
            for (Path midi : result.midi()) events += countNoteOnEvents(midi);
            // The PNG baseline has 151 pitches and 220 note-on events. A result
            // containing only one imported page must fail this document test.
            assertEquals("Both scanned pages must reach MusicXML", 302, notes);
            assertEquals("Both scanned pages must reach MIDI", 440, events);
            System.out.printf("EMBEDDED_MULTIPAGE_RESULT input=%s notes=%d noteOnEvents=%d output=%s%n",
                    document.getFileName(), notes, events, result.outputDirectory());
            assertNull(Main.getCli());
        }
    }

    @Test(timeout = 600_000)
    public void realScannedScoreExportsNotesAndMidiTwiceAfterFailedInput () throws Exception
    {
        assertTrue("Bundle eng.traineddata before running this offline integration test",
                TesseractOCR.getInstance().getSupportedLanguages().contains("eng"));
        final Path corrupt = engine.appHome().resolve("corrupt.png");
        Files.writeString(corrupt, "This is deliberately not a raster image");
        final var failed = engine.recognize(corrupt);
        assertEquals(Main.BatchStatus.FAILED, failed.batch().status());
        assertTrue(failed.musicXML().isEmpty());

        final List<Integer> noteCounts = new ArrayList<>();
        for (int index = 0; index < 2; index++) {
            final long started = System.nanoTime();
            final var result = engine.recognize(input);
            assertEquals(result.batch().errors().toString(), Main.BatchStatus.SUCCESS, result.batch().status());
            assertEquals(1, result.batch().completedTasks());
            assertFalse(result.musicXML().isEmpty());
            assertFalse(result.midi().isEmpty());
            int notes = 0;
            for (Path xml : result.musicXML()) {
                notes += countPitchedNotes(xml);
            }
            int events = 0;
            for (Path midi : result.midi()) {
                events += countNoteOnEvents(midi);
            }
            assertTrue("MusicXML must contain real pitched notes", notes > 0);
            assertTrue("MIDI must contain sounding note-on events", events > 0);
            noteCounts.add(notes);
            System.out.printf("EMBEDDED_OMR_RESULT run=%d notes=%d noteOnEvents=%d seconds=%.3f output=%s%n",
                    index + 1, notes, events, (System.nanoTime() - started) / 1_000_000_000.0,
                    result.outputDirectory());
            assertNull("CLI state must be restored between jobs", Main.getCli());
        }
        assertEquals("Repeated in-process recognition must keep the same note count",
                noteCounts.get(0), noteCounts.get(1));
        final String nativeReport = EmbeddedOmrEngine.recognizeToJSON(
                engine.appHome().toString(), input.toString());
        assertTrue(nativeReport, nativeReport.contains("\"status\":\"SUCCESS\""));
        assertTrue(nativeReport, nativeReport.contains(".mxl\"") && nativeReport.contains(".mid\""));
        System.out.println("EMBEDDED_JNI_JSON " + nativeReport);
    }

    private static int countPitchedNotes (Path path) throws Exception
    {
        if (path.toString().endsWith(".mxl")) {
            try (ZipFile archive = new ZipFile(path.toFile())) {
                final var entries = archive.entries();
                while (entries.hasMoreElements()) {
                    final var entry = entries.nextElement();
                    if (entry.getName().endsWith(".xml") && !entry.getName().startsWith("META-INF/")) {
                        try (InputStream stream = archive.getInputStream(entry)) {
                            return parseXML(stream).getElementsByTagName("pitch").getLength();
                        }
                    }
                }
                throw new AssertionError("No score XML in " + path);
            }
        }
        try (InputStream stream = Files.newInputStream(path)) {
            return parseXML(stream).getElementsByTagName("pitch").getLength();
        }
    }

    private static Document parseXML (InputStream stream) throws Exception
    {
        final DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
        factory.setAttribute(XMLConstants.ACCESS_EXTERNAL_DTD, "");
        factory.setAttribute(XMLConstants.ACCESS_EXTERNAL_SCHEMA, "");
        factory.setFeature("http://apache.org/xml/features/nonvalidating/load-external-dtd", false);
        return factory.newDocumentBuilder().parse(stream);
    }

    private static int countNoteOnEvents (Path path) throws Exception
    {
        final Sequence sequence = MidiSystem.getSequence(path.toFile());
        int count = 0;
        for (Track track : sequence.getTracks()) {
            for (int index = 0; index < track.size(); index++) {
                final MidiEvent event = track.get(index);
                if (event.getMessage() instanceof ShortMessage message
                        && message.getCommand() == ShortMessage.NOTE_ON && message.getData2() > 0) {
                    count++;
                }
            }
        }
        return count;
    }
}
