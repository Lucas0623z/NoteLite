// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 NoteLite contributors.
import com.notelite.omr.EmbeddedOmrEngine;
import com.notelite.omr.Main;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.zip.ZipFile;
import javax.sound.midi.MidiSystem;
import javax.sound.midi.ShortMessage;
import javax.xml.XMLConstants;
import javax.xml.parsers.DocumentBuilderFactory;
import org.w3c.dom.Document;

/** Entry called from JNI inside the iOS process. Every gate executes real dependency code. */
public final class EmbeddedNativeProbe {
    /** Desktop validation uses the same Java probe; it is not evidence of iOS execution. */
    public static void main(String[] args) throws Exception {
        if (args.length != 2) throw new IllegalArgumentException("resources sandbox required");
        System.out.println(run(args[0], args[1]));
    }

    public static String run(String resourceDirectory, String sandboxDirectory) throws Exception {
        long started = System.nanoTime();
        Path resources = Path.of(resourceDirectory);
        Path sandbox = Path.of(sandboxDirectory);
        // Establish sandbox/headless state before PortabilityProbe touches AWT or fonts.
        EmbeddedOmrEngine engine = EmbeddedOmrEngine.open(sandbox);
        String components = PortabilityProbe.run(resources.resolve("assets").toString(),
                sandbox.resolve("component-probe").toString(), resources.resolve("tessdata").toString());
        Path input = sandbox.resolve("chula.png");
        Files.copy(resources.resolve("examples/chula.png"), input, StandardCopyOption.REPLACE_EXISTING);
        var result = engine.recognize(input);
        if (result.batch().status() != Main.BatchStatus.SUCCESS) {
            throw new IllegalStateException("Full recognition failed: " + result.batch().errors());
        }
        int pitchedNotes = 0;
        int midiNoteOnEvents = 0;
        for (Path xml : result.musicXML()) pitchedNotes += countPitchedNotes(xml);
        for (Path midi : result.midi()) {
            var sequence = MidiSystem.getSequence(midi.toFile());
            for (var track : sequence.getTracks()) {
                for (int index = 0; index < track.size(); index++) {
                    if (track.get(index).getMessage() instanceof ShortMessage message
                            && message.getCommand() == ShortMessage.NOTE_ON && message.getData2() > 0) {
                        midiNoteOnEvents++;
                    }
                }
            }
        }
        if (pitchedNotes == 0 || midiNoteOnEvents == 0) {
            throw new IllegalStateException("Exports did not contain pitched notes and sounding MIDI events");
        }
        String json = "{\"status\":\"SUCCESS\",\"sameProcessJNI\":" + Boolean.getBoolean("notelite.omr.jniHost")
                + ",\"fullScoreRecognitionTested\":true"
                + ",\"javaVersion\":" + quote(System.getProperty("java.version"))
                + ",\"javaVM\":" + quote(System.getProperty("java.vm.name"))
                + ",\"elapsedMilliseconds\":" + (System.nanoTime() - started) / 1_000_000
                + ",\"pitchedNotes\":" + pitchedNotes + ",\"midiNoteOnEvents\":" + midiNoteOnEvents
                + ",\"musicXMLCount\":" + result.musicXML().size() + ",\"midiCount\":" + result.midi().size()
                + ",\"outputDirectory\":" + quote(result.outputDirectory().toString())
                + ",\"components\":" + components + "}";
        Files.writeString(sandbox.resolve("probe-report.json"), json);
        Files.writeString(result.outputDirectory().resolve("embedded-result.json"), json);
        System.out.println("EMBEDDED_OMR_PROBE_RESULT " + json);
        return json;
    }

    private static int countPitchedNotes(Path path) throws Exception {
        if (path.toString().endsWith(".mxl")) {
            try (ZipFile archive = new ZipFile(path.toFile())) {
                var entries = archive.entries();
                while (entries.hasMoreElements()) {
                    var entry = entries.nextElement();
                    if (entry.getName().endsWith(".xml") && !entry.getName().startsWith("META-INF/")) {
                        try (InputStream input = archive.getInputStream(entry)) {
                            return parseXML(input).getElementsByTagName("pitch").getLength();
                        }
                    }
                }
                throw new IllegalStateException("MXL has no score XML: " + path);
            }
        }
        try (InputStream input = Files.newInputStream(path)) {
            return parseXML(input).getElementsByTagName("pitch").getLength();
        }
    }

    private static Document parseXML(InputStream input) throws Exception {
        var factory = DocumentBuilderFactory.newInstance();
        factory.setAttribute(XMLConstants.ACCESS_EXTERNAL_DTD, "");
        factory.setAttribute(XMLConstants.ACCESS_EXTERNAL_SCHEMA, "");
        factory.setFeature("http://apache.org/xml/features/nonvalidating/load-external-dtd", false);
        return factory.newDocumentBuilder().parse(input);
    }

    private static String quote(String value) {
        return "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"")
                .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t") + "\"";
    }
}
