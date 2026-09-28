// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 NoteLite contributors.
package com.notelite.omr;

import com.notelite.omr.text.tesseract.TesseractOCR;
import com.notelite.omr.util.OmrExecutors;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.Executors;
import java.util.zip.ZipFile;
import javax.sound.midi.MidiEvent;
import javax.sound.midi.MidiSystem;
import javax.sound.midi.Sequence;
import javax.sound.midi.ShortMessage;
import javax.sound.midi.Track;
import javax.xml.XMLConstants;
import javax.xml.parsers.DocumentBuilderFactory;
import org.junit.BeforeClass;
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
        engine = EmbeddedOmrEngine.open(Files.createTempDirectory(base, "sandbox-"));
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
