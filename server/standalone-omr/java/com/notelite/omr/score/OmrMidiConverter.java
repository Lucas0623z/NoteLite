package com.notelite.omr.score;

import jakarta.xml.bind.JAXBContext;
import jakarta.xml.bind.JAXBElement;
import org.audiveris.proxymusic.ScorePartwise;

import javax.xml.stream.XMLInputFactory;
import javax.xml.stream.XMLStreamReader;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;

/** Standalone MusicXML-to-MIDI adapter for the extracted NoteLite exporter. */
public final class OmrMidiConverter {
    public static void main(String[] args) throws Exception {
        if (args.length != 2) throw new IllegalArgumentException("Usage: omr-midi input.musicxml output.mid");
        Path source = Path.of(args[0]);
        Path target = Path.of(args[1]);
        XMLInputFactory factory = XMLInputFactory.newFactory();
        factory.setProperty(XMLInputFactory.SUPPORT_DTD, false);
        factory.setProperty(XMLInputFactory.IS_SUPPORTING_EXTERNAL_ENTITIES, false);
        factory.setXMLResolver((publicId, systemId, base, namespace) -> {
            throw new IllegalArgumentException("External XML resources are disabled");
        });
        try (InputStream input = Files.newInputStream(source)) {
            XMLStreamReader reader = factory.createXMLStreamReader(input);
            try {
                Object model = JAXBContext.newInstance(ScorePartwise.class).createUnmarshaller().unmarshal(reader);
                if (model instanceof JAXBElement<?> element) model = element.getValue();
                if (!(model instanceof ScorePartwise score)) {
                    throw new IllegalArgumentException("Expected score-partwise MusicXML");
                }
                if (score.getPart().isEmpty()) throw new IllegalArgumentException("MusicXML has no parts");
                if (score.getPart().stream().anyMatch(part -> part.getMeasure().isEmpty())) {
                    throw new IllegalArgumentException("MusicXML contains a part with no measures");
                }
                MidiExporter.write(score, target);
                if (!Files.isRegularFile(target) || Files.size(target) < 22) {
                    throw new IllegalStateException("MIDI export produced no usable file");
                }
                System.out.println("MIDI_EXPORTED " + target.getFileName() + " " + Files.size(target));
            } finally {
                reader.close();
            }
        }
    }
}
