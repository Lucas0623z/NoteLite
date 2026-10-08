package com.notelite.omr.practice;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Comparator;
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
            assertTrue(LocalAudioAnalysis.available());
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
            assertThrows(IOException.class, () -> LocalAudioAnalysis.analyze(wav(), runtime, Duration.ofMillis(100)));
            assertTrue(Duration.ofNanos(System.nanoTime() - begin).toSeconds() < 5);
        } finally { remove(helpers); }
    }

    private static void remove (Path home) throws IOException {
        try (var paths = Files.walk(home)) {
            for (Path path : paths.sorted(Comparator.reverseOrder()).toList()) Files.deleteIfExists(path);
        }
    }
}
