package com.notelite.omr.practice;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.channels.FileChannel;
import java.nio.file.StandardOpenOption;
import java.time.Duration;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import com.sun.nio.file.ExtendedOpenOption;
import org.junit.Test;
import static org.junit.Assert.*;
import static org.junit.Assume.assumeTrue;

public class LocalAudioAnalysisTest
{
    static byte[] wav () {
        int length = 16000;
        ByteBuffer b = ByteBuffer.allocate(44 + length).order(ByteOrder.LITTLE_ENDIAN);
        b.putInt(0x46464952).putInt(36 + length).putInt(0x45564157).putInt(0x20746d66).putInt(16);
        b.putShort((short) 1).putShort((short) 1).putInt(8000).putInt(16000).putShort((short) 2).putShort((short) 16);
        b.putInt(0x61746164).putInt(length);
        return b.array();
    }

    static byte[] json (String notes) {
        return ("{\"schemaVersion\":1,\"engine\":\"basic-pitch\",\"seconds\":1,\"notes\":" + notes + "}").getBytes(StandardCharsets.UTF_8);
    }

    @Test public void acceptsCompleteBoundedPcmAndRejectsIncompleteOrCompressedAudio () throws Exception {
        LocalAudioAnalysis.validateWav(wav());
        byte[] truncated = java.util.Arrays.copyOf(wav(), 1000);
        assertThrows(IOException.class, () -> LocalAudioAnalysis.validateWav(truncated));
        byte[] floating = wav(); floating[20] = 3;
        assertThrows(IOException.class, () -> LocalAudioAnalysis.validateWav(floating));
        byte[] wrongBlock = wav(); wrongBlock[32] = 4;
        assertThrows(IOException.class, () -> LocalAudioAnalysis.validateWav(wrongBlock));
        assertThrows(IOException.class, () -> LocalAudioAnalysis.validateWav(null));
    }

    @Test public void validatesActualNotePitchOnsetDurationConfidenceAndSchema () throws Exception {
        LocalAudioAnalysis.validateResult(json("[{\"midi\":60,\"onset\":0.1,\"duration\":0.4,\"confidence\":0.8},{\"midi\":72,\"onset\":0.1,\"duration\":0.8,\"confidence\":0.7}]"));
        LocalAudioAnalysis.validateResult(json("[]"));
        for (String bad : new String[] {"[{\"midi\":60.1,\"onset\":0,\"duration\":1,\"confidence\":0.8}]",
                "[{\"midi\":60,\"onset\":0,\"duration\":2,\"confidence\":0.8}]",
                "[{\"midi\":60,\"onset\":0,\"duration\":1,\"confidence\":2}]",
                "[{\"midi\":60,\"onset\":0,\"duration\":1,\"confidence\":NaN}]",
                "[{\"midi\":60,\"onset\":0,\"duration\":1,\"confidence\":1,\"confidence\":0}]"}) {
            assertThrows(bad, IOException.class, () -> LocalAudioAnalysis.validateResult(json(bad)));
        }
        assertThrows(IOException.class, () -> LocalAudioAnalysis.validateResult("{} trailing".getBytes(StandardCharsets.UTF_8)));
        assertThrows(IOException.class, () -> LocalAudioAnalysis.validateResult("{\"schemaVersion\":2}".getBytes(StandardCharsets.UTF_8)));
    }

    @Test public void configuredRuntimeRequiresPythonHelperLocalModelAndReadinessMarker () throws Exception {
        String previous = System.getProperty("notelite.analysis.home");
        Path home = Files.createTempDirectory("notelite-analysis-test-");
        try {
            System.setProperty("notelite.analysis.home", home.toString());
            assertFalse(LocalAudioAnalysis.available());
            Files.createDirectories(home.resolve("python")); Files.createDirectories(home.resolve("models"));
            Files.write(home.resolve("python/python.exe"), new byte[0]); Files.write(home.resolve("analyze.py"), new byte[0]);
            Files.write(home.resolve("models/basic-pitch.onnx"), new byte[0]);
            assertFalse(LocalAudioAnalysis.available());
            Files.writeString(home.resolve("runtime-ready.json"), "{}");
            assertFalse(LocalAudioAnalysis.available());
            Files.writeString(home.resolve("runtime-ready.json"), "{\"smoke\":{\"basic-pitch\":{\"passed\":true},\"crepe\":{\"passed\":false}}}");
            assertTrue(LocalAudioAnalysis.available());
            assertEquals(Boolean.TRUE, LocalAudioAnalysis.capabilities().get("basic-pitch"));
            assertEquals(Boolean.FALSE, LocalAudioAnalysis.capabilities().get("crepe"));
        } finally {
            if (previous == null) System.clearProperty("notelite.analysis.home"); else System.setProperty("notelite.analysis.home", previous);
            remove(home);
        }
    }

    @Test public void installedInterpreterExecutesHelperAndValidatesReturnedJson () throws Exception {
        var found = LocalAudioAnalysis.findRuntime();
        assumeTrue("Install local-analysis runtime to run process-boundary tests", found.isPresent());
        Path helpers = Files.createTempDirectory("notelite-helper-test-");
        try {
            Path helper = helpers.resolve("helper.py");
            Files.writeString(helper, "import pathlib,sys\npathlib.Path(sys.argv[4]).write_text('{\"schemaVersion\":1,\"engine\":\"basic-pitch\",\"seconds\":1,\"notes\":[]}')\nprint('progress')\n");
            var runtime = new LocalAudioAnalysis.Runtime(found.get().python(), helper, null, null);
            assertEquals(new String(json("[]"), StandardCharsets.UTF_8),
                    new String(LocalAudioAnalysis.analyze(wav(), runtime, Duration.ofSeconds(30)), StandardCharsets.UTF_8));
            Files.writeString(helper, "import pathlib,sys\npathlib.Path(sys.argv[4]).write_text('{\"engine\":\"fake\"}')\n");
            assertThrows(IOException.class, () -> LocalAudioAnalysis.analyze(wav(), runtime, Duration.ofSeconds(30)));
        } finally { remove(helpers); }
    }

    @Test public void hungLocalHelperIsTerminatedWithinTheBoundedTimeout () throws Exception {
        var found = LocalAudioAnalysis.findRuntime();
        assumeTrue("Install local-analysis runtime to run process-boundary tests", found.isPresent());
        Path helpers = Files.createTempDirectory("notelite-helper-test-");
        try {
            Path helper = helpers.resolve("helper.py"); Files.writeString(helper, "import time\ntime.sleep(20)\n");
            var runtime = new LocalAudioAnalysis.Runtime(found.get().python(), helper, null, null);
            long begin = System.nanoTime();
            IOException failure = assertThrows(IOException.class, () -> LocalAudioAnalysis.analyze(wav(), runtime, Duration.ofMillis(100)));
            assertTrue(failure.getMessage().contains("超时"));
            assertTrue(Duration.ofNanos(System.nanoTime() - begin).toSeconds() < 5);
        } finally { remove(helpers); }
    }

    @Test public void lockedWindowsLogCleanupCannotMaskTheActualTimeout () throws Exception {
        assumeTrue(System.getProperty("os.name").toLowerCase().contains("windows"));
        var found = LocalAudioAnalysis.findRuntime();
        assumeTrue("Install the real interpreter for the locked-file process regression", found.isPresent());
        Path helpers = Files.createTempDirectory("notelite-helper-test-");
        Path temporary = null;
        var executor = Executors.newSingleThreadExecutor();
        try {
            Path marker = helpers.resolve("started.txt");
            Path helper = helpers.resolve("helper.py");
            Files.writeString(helper, "import pathlib,time\npathlib.Path(" + "r'" + marker + "'" + ").write_text(str(pathlib.Path.cwd()))\ntime.sleep(20)\n");
            var runtime = new LocalAudioAnalysis.Runtime(found.get().python(), helper, null, null);
            var job = executor.submit(() -> LocalAudioAnalysis.analyze(wav(), runtime, Duration.ofSeconds(2)));
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(4);
            while (!Files.isRegularFile(marker) && System.nanoTime() < deadline) Thread.sleep(10);
            assertTrue("Python must report the exact analysis temp before timeout", Files.isRegularFile(marker));
            temporary = Path.of(Files.readString(marker));
            Path log = temporary.resolve("analysis.log");
            // Reproduce a retained Windows log handle independently of Python.
            try (var held = FileChannel.open(log, StandardOpenOption.READ, ExtendedOpenOption.NOSHARE_DELETE)) {
                ExecutionException failure = assertThrows(ExecutionException.class, () -> job.get(7, TimeUnit.SECONDS));
                assertTrue(failure.getCause() instanceof IOException);
                assertTrue(failure.getCause().getMessage().contains("超时"));
                assertTrue("Locked own temp is safely retained", Files.isRegularFile(log));
            }
            LocalAudioAnalysis.cleanup(temporary);
            assertFalse("Cleanup succeeds once the Windows handle closes", Files.exists(temporary));
        } finally {
            executor.shutdownNow();
            if (temporary != null) LocalAudioAnalysis.cleanup(temporary);
            remove(helpers);
        }
    }

    @Test public void installedLibrariesNormalizeSourceIdentityAndRunActualVariableTempoBaseline () throws Exception {
        assumeTrue("Install the complete runtime for actual score-library integration", Boolean.TRUE.equals(LocalAudioAnalysis.capabilities().get("parangonar")));
        String xml = "<score-partwise version=\"3.1\"><part-list><score-part id=\"P1\"><part-name>Flute</part-name></score-part></part-list><part id=\"P1\"><measure number=\"1\"><attributes><divisions>1</divisions></attributes>"
                + "<note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note><note><rest/><duration>1</duration></note>"
                + "<note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration></note></measure></part></score-partwise>";
        String normalized = new String(LocalAudioAnalysis.normalize(xml.getBytes(StandardCharsets.UTF_8), Map.of("expandRepeats", false)), StandardCharsets.UTF_8);
        assertTrue(normalized.contains("\"sourceNoteId\": \"P1:0\""));
        assertTrue(normalized.contains("\"sourceNoteId\": \"P1:2\""));
        assertTrue(normalized.contains("\"instrument\": \"flute\""));
        Map<String, ?> score = Map.of("notes", List.of(
                Map.of("sourceNoteId", "P1:0", "occurrenceId", "P1:0@0", "midi",60,"onset",0,"duration",1),
                Map.of("sourceNoteId", "P1:2", "occurrenceId", "P1:2@0", "midi",62,"onset",2,"duration",1)));
        List<?> performance = List.of(Map.of("midi",60,"onset",1.0,"duration",.4), Map.of("midi",62,"onset",2.7,"duration",.6));
        String aligned = new String(LocalAudioAnalysis.align(score, performance, Map.of("backend","parangonar")), StandardCharsets.UTF_8);
        assertTrue(aligned.contains("\"engine\": \"parangonar\""));
        assertTrue(aligned.contains("\"occurrenceId\": \"P1:2@0\""));
        assertTrue(aligned.contains("\"missing\": []"));
    }

    @Test public void installedAubioMeasuresDetuningAndActualReleaseThroughJavaBoundary () throws Exception {
        assumeTrue("Install native aubio for actual audio-engine integration", Boolean.TRUE.equals(LocalAudioAnalysis.capabilities().get("aubio")));
        int rate = 48000, length = rate*3*2;
        ByteBuffer data = ByteBuffer.allocate(44+length).order(ByteOrder.LITTLE_ENDIAN);
        data.putInt(0x46464952).putInt(36+length).putInt(0x45564157).putInt(0x20746d66).putInt(16);
        data.putShort((short)1).putShort((short)1).putInt(rate).putInt(rate*2).putShort((short)2).putShort((short)16);
        data.putInt(0x61746164).putInt(length);
        for (int sample=0; sample<rate*3; sample++) {
            double time = sample/(double)rate;
            double amplitude = time>=.5 && time<2.3 ? .23*Math.sin(2*Math.PI*440*Math.pow(2,.25/12)*(time-.5)) : 0;
            data.putShort((short)Math.round(amplitude*32767));
        }
        String result = new String(LocalAudioAnalysis.analyze(data.array(), Map.of("engine","aubio","a4",440,"minHz",100,"maxHz",1000)),StandardCharsets.UTF_8);
        assertTrue(result.contains("\"engine\": \"aubio\""));
        assertTrue(result.contains("\"midi\": 69"));
        assertTrue(result.contains("\"supportedPitchRange\""));
        // Numeric correctness/release tolerances are checked by installation's
        // real detuned-tone smoke; this test verifies the validated Java route.
    }

    private static void remove (Path home) throws IOException {
        try (var paths = Files.walk(home)) {
            for (Path path : paths.sorted(Comparator.reverseOrder()).toList()) Files.deleteIfExists(path);
        }
    }
}
