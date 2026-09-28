// SPDX-License-Identifier: AGPL-3.0-or-later
// Run inside the embedded VM before enabling full local recognition.
import java.awt.Color;
import java.awt.Font;
import java.awt.Graphics2D;
import java.awt.GraphicsEnvironment;
import java.awt.font.TextLayout;
import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.PrintWriter;
import java.io.StringReader;
import java.io.StringWriter;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import javax.imageio.ImageIO;
import javax.imageio.spi.IIORegistry;
import javax.xml.bind.JAXBContext;
import javax.xml.bind.annotation.XmlRootElement;
import org.bytedeco.javacpp.BytePointer;
import org.bytedeco.leptonica.PIX;
import org.bytedeco.tesseract.TessBaseAPI;
import static org.bytedeco.leptonica.global.leptonica.*;
import static org.bytedeco.tesseract.global.tesseract.*;

/** No HTTP, process launch or downloaded code. Every component must pass. */
public final class PortabilityProbe {
    // Registered by the probe host only. Narrow arguments after the arm64
    // register limit exercise the real Zero -> libffi -> C stack ABI.
    private static native boolean mixedPrimitiveArguments(Object leadingObject,
            int a, int b, int c, int d, int e, int f, int g, int h,
            boolean first, boolean second, boolean third, int trailingInt, Object trailingObject,
            byte negativeByte, short negativeShort, char highChar,
            byte positiveByte, short positiveShort, char maxChar, long wide, byte[] payload);

    private native boolean mixedInstanceArguments(Object leadingObject,
            int a, int b, int c, int d, int e, int f, int g, int h,
            boolean first, boolean second, boolean third, int trailingInt, Object trailingObject,
            byte negativeByte, short negativeShort, char highChar,
            byte positiveByte, short positiveShort, char maxChar, long wide, byte[] payload);

    @XmlRootElement
    public static final class Payload {
        public String value;
        public Payload() { }
    }

    @FunctionalInterface
    private interface CheckedStage { void run() throws Exception; }

    private record Stage(String name, long milliseconds, Throwable failure) {
        boolean passed() { return failure == null; }
    }

    private static final class Gates {
        final List<Stage> stages = new ArrayList<>();

        void run(String name, CheckedStage action) {
            long started = System.nanoTime();
            Throwable failure = null;
            System.err.println("PORTABILITY_PROBE_STAGE " + name + " START");
            try {
                action.run();
            } catch (VirtualMachineError | ThreadDeath fatal) {
                // The VM cannot safely continue collecting diagnostics after these failures.
                throw fatal;
            } catch (Throwable error) {
                failure = error;
                error.printStackTrace(System.err);
            }
            stages.add(new Stage(name, (System.nanoTime() - started) / 1_000_000, failure));
            System.err.println("PORTABILITY_PROBE_STAGE " + name + (failure == null ? " SUCCESS" : " FAILED"));
        }

        boolean passed(String name) {
            return stages.stream().anyMatch(stage -> stage.name().equals(name) && stage.passed());
        }

        boolean passed() { return stages.stream().allMatch(Stage::passed); }

        String json() {
            List<String> values = new ArrayList<>();
            for (Stage stage : stages) {
                String value = "{\"name\":" + quote(stage.name()) + ",\"status\":"
                        + quote(stage.passed() ? "SUCCESS" : "FAILED")
                        + ",\"elapsedMilliseconds\":" + stage.milliseconds();
                if (!stage.passed()) {
                    StringWriter stack = new StringWriter();
                    stage.failure().printStackTrace(new PrintWriter(stack));
                    value += ",\"error\":" + quote(stage.failure().toString())
                            + ",\"stackTrace\":" + quote(stack.toString());
                }
                values.add(value + "}");
            }
            return "[" + String.join(",", values) + "]";
        }

        void requireSuccess() throws Exception {
            if (passed()) return;
            String failed = String.join(", ", stages.stream().filter(stage -> !stage.passed())
                    .map(Stage::name).toList());
            Exception aggregate = new Exception("Component probe failed: " + failed);
            for (Stage stage : stages) {
                if (!stage.passed()) aggregate.addSuppressed(new Exception(stage.name(), stage.failure()));
            }
            throw aggregate;
        }
    }

    private static final class State {
        BufferedImage fontImage;
        long foreground;
        String fontHash;
        byte[] jpeg;
        byte[] tiff;
        long[] nativeScoring = new long[4];
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 3) throw new IllegalArgumentException("resources output tessdata required");
        System.setProperty("java.awt.headless", "true");
        System.out.println(run(args[0], args[1], args[2]));
    }

    public static String run(String resourceDirectory, String outputDirectory, String tessdataDirectory) throws Exception {
        Path resources = Path.of(resourceDirectory);
        Path output = Path.of(outputDirectory);
        Files.createDirectories(output);
        Gates gates = new Gates();
        State state = new State();
        // Codec diagnostics must remain executable if font initialization fails.
        BufferedImage fixture = codecFixture();
        boolean nativeHost = Boolean.getBoolean("notelite.omr.jniHost");
        if (nativeHost) gates.run("jni-mixed-primitives", () -> {
            Object marker = new Object();
            PortabilityProbe receiver = new PortabilityProbe();
            byte[] payload = {(byte)-128, 0, 127};
            for (int trailing : new int[] {0x13579bdf, 0}) {
                boolean expected = trailing != 0;
                if (mixedPrimitiveArguments(marker, 1, 2, 3, 4, 5, 6, 7, 8,
                        true, false, true, trailing, marker,
                        (byte)-128, (short)-32768, '\ufedc', (byte)127, (short)32767, '\uffff',
                        0x0123456789abcdefL, payload) != expected
                        || receiver.mixedInstanceArguments(receiver, 1, 2, 3, 4, 5, 6, 7, 8,
                        true, false, true, trailing, receiver,
                        (byte)-128, (short)-32768, '\ufedc', (byte)127, (short)32767, '\uffff',
                        0x0123456789abcdefL, payload) != expected) {
                    throw new IllegalStateException("JNI static/instance mixed arguments or boolean return changed across the native ABI");
                }
            }
        });

        if (nativeHost) gates.run("native-template-scoring", () -> {
            state.nativeScoring = checkNativeTemplateScoring();
        });

        gates.run("midi-file-roundtrip", () -> checkMidiRoundtrip(output));

        gates.run("awt-font-raster", () -> {
            if (!GraphicsEnvironment.isHeadless()) throw new IllegalStateException("Headless mode required");
            Font music;
            try (var input = Files.newInputStream(resources.resolve("Bravura.otf"))) {
                music = Font.createFont(Font.TRUETYPE_FONT, input).deriveFont(60f);
            }
            if (!music.canDisplay(0xe0a4)) throw new IllegalStateException("Bravura notehead glyph unavailable");
            GraphicsEnvironment.getLocalGraphicsEnvironment().registerFont(music);
            BufferedImage image = new BufferedImage(256, 128, BufferedImage.TYPE_BYTE_GRAY);
            Graphics2D graphics = image.createGraphics();
            try {
                graphics.setColor(Color.WHITE);
                graphics.fillRect(0, 0, image.getWidth(), image.getHeight());
                graphics.setColor(Color.BLACK);
                new TextLayout("\ue0a4", music, graphics.getFontRenderContext()).draw(graphics, 60, 80);
            } finally { graphics.dispose(); }
            byte[] pixels = ((java.awt.image.DataBufferByte)image.getRaster().getDataBuffer()).getData();
            long foreground = 0;
            for (byte pixel : pixels) if ((pixel & 255) < 128) foreground++;
            if (foreground < 10 || foreground >= pixels.length / 2) {
                throw new IllegalStateException("Font rasterization produced invalid foreground: " + foreground);
            }
            state.fontImage = image;
            state.foreground = foreground;
            state.fontHash = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(pixels));
        });
        gates.run("imageio-png", () -> {
            roundtripPNG(fixture, output.resolve("codec-fixture.png"));
            if (state.fontImage != null) roundtripPNG(state.fontImage, output.resolve("bravura-notehead.png"));
        });
        gates.run("imageio-jpeg", () -> {
            state.jpeg = encode(fixture, "JPEG");
            requireDimensions(ImageIO.read(new ByteArrayInputStream(state.jpeg)), fixture, "ImageIO JPEG");
        });
        gates.run("imageio-tiff", () -> {
            IIORegistry registry = IIORegistry.getDefaultInstance();
            registry.registerServiceProvider(new com.github.jaiimageio.impl.plugins.tiff.TIFFImageWriterSpi());
            registry.registerServiceProvider(new com.github.jaiimageio.impl.plugins.tiff.TIFFImageReaderSpi());
            state.tiff = encode(fixture, "TIFF");
            requireDimensions(ImageIO.read(new ByteArrayInputStream(state.tiff)), fixture, "ImageIO TIFF");
        });
        gates.run("engine-pdf-raster", () -> {
            // A diagnostic raster does not satisfy the separate font gate.
            BufferedImage image = state.fontImage != null ? state.fontImage : fixture;
            Path pdfFile = output.resolve(state.fontImage != null ? "scanned-notehead.pdf" : "scanned-fixture.pdf");
            try (var document = new org.apache.pdfbox.pdmodel.PDDocument()) {
                var bounds = new org.apache.pdfbox.pdmodel.common.PDRectangle(
                        image.getWidth() * 72f / 300f, image.getHeight() * 72f / 300f);
                var page = new org.apache.pdfbox.pdmodel.PDPage(bounds);
                document.addPage(page);
                try (var stream = new org.apache.pdfbox.pdmodel.PDPageContentStream(document, page)) {
                    stream.drawImage(org.apache.pdfbox.pdmodel.graphics.image.LosslessFactory.createFromImage(document, image),
                            0, 0, bounds.getWidth(), bounds.getHeight());
                }
                document.save(pdfFile.toFile());
            }
            var pdfLoader = com.notelite.omr.image.ImageLoading.getLoader(pdfFile);
            if (pdfLoader == null) throw new IllegalStateException("Engine PDF loader unavailable");
            try {
                BufferedImage pdfImage = pdfLoader.getImage(1);
                if (pdfLoader.getImageCount() != 1 || pdfImage == null
                        || Math.abs(pdfImage.getWidth() - image.getWidth()) > 1
                        || Math.abs(pdfImage.getHeight() - image.getHeight()) > 1) {
                    throw new IllegalStateException("PDFBox engine rasterization failed");
                }
                long dark = countDark(pdfImage);
                long foreground = state.fontImage != null ? state.foreground : countDark(fixture);
                if (dark < foreground / 2 || dark > foreground * 2) {
                    throw new IllegalStateException("PDF renderer lost or corrupted the source raster");
                }
            } finally { pdfLoader.dispose(); }
        });
        gates.run("jaxb-unicode", () -> {
            JAXBContext binding = JAXBContext.newInstance(Payload.class);
            Payload source = new Payload(); source.value = "音伴-𝄞";
            StringWriter xml = new StringWriter();
            binding.createMarshaller().marshal(source, xml);
            Payload restored = (Payload)binding.createUnmarshaller().unmarshal(new StringReader(xml.toString()));
            if (!source.value.equals(restored.value)) throw new IllegalStateException("JAXB Unicode roundtrip failed");
        });
        gates.run("musicxml-binding", () -> JAXBContext.newInstance(org.audiveris.proxymusic.ScorePartwise.class));
        gates.run("javacpp-leptonica-load", () -> org.bytedeco.javacpp.Loader.load(org.bytedeco.leptonica.global.leptonica.class));
        gates.run("javacpp-tesseract-load", () -> org.bytedeco.javacpp.Loader.load(org.bytedeco.tesseract.global.tesseract.class));
        gates.run("javacpp-jpeg", () -> {
            if (state.jpeg == null) throw new IllegalStateException("JPEG fixture unavailable: ImageIO encoding failed");
            try (BytePointer data = new BytePointer(state.jpeg)) {
                PIX pix = pixReadMem(data, state.jpeg.length);
                if (pix == null || pix.isNull()) throw new IllegalStateException("Leptonica JPEG decoder failed");
                try { requireDimensions(pix, fixture, "Leptonica JPEG"); }
                finally { pixDestroy(pix); }
            }
            // Exercise both JPEG implementations in one process to detect symbol collisions.
            requireDimensions(ImageIO.read(new ByteArrayInputStream(state.jpeg)), fixture, "JDK JPEG after native codec");
        });
        gates.run("javacpp-tiff", () -> {
            if (state.tiff == null) throw new IllegalStateException("TIFF fixture unavailable: ImageIO encoding failed");
            try (BytePointer data = new BytePointer(state.tiff)) {
                PIX pix = pixReadMemTiff(data, state.tiff.length, 0);
                if (pix == null || pix.isNull()) throw new IllegalStateException("Leptonica TIFF decoder failed");
                try { requireDimensions(pix, fixture, "Leptonica TIFF"); }
                finally { pixDestroy(pix); }
            }
        });
        gates.run("legacy-ocr", () -> {
            // Transfer a real native raster so OCR remains testable if an encoder fails.
            // This checks the actual OCR call and makes no text-accuracy claim.
            BufferedImage image = state.fontImage != null ? state.fontImage : fixture;
            PIX pix = pixCreate(image.getWidth(), image.getHeight(), 8);
            if (pix == null || pix.isNull()) throw new IllegalStateException("Leptonica raster allocation failed");
            try (TessBaseAPI ocr = new TessBaseAPI()) {
                for (int y = 0; y < image.getHeight(); y++) {
                    for (int x = 0; x < image.getWidth(); x++) {
                        if (pixSetPixel(pix, x, y, image.getRaster().getSample(x, y, 0)) != 0) {
                            throw new IllegalStateException("Leptonica raster transfer failed");
                        }
                    }
                }
                if (ocr.Init(tessdataDirectory, "eng", OEM_TESSERACT_ONLY) != 0) {
                    throw new IllegalStateException("Legacy Tesseract model initialization failed");
                }
                try {
                    ocr.SetImage(pix);
                    if (ocr.Recognize(null) != 0) throw new IllegalStateException("Tesseract call failed");
                } finally { ocr.End(); }
            } finally { pixDestroy(pix); }
        });

        String report = "{\"status\":" + quote(gates.passed() ? "SUCCESS" : "FAILED")
                + ",\"jniMixedPrimitiveArgumentsRequired\":" + nativeHost
                + ",\"jniMixedPrimitiveArguments\":" + gates.passed("jni-mixed-primitives")
                + ",\"nativeTemplateScoringRequired\":" + nativeHost
                + ",\"nativeTemplateScoring\":" + gates.passed("native-template-scoring")
                + ",\"nativeTemplateScoringCalls\":" + state.nativeScoring[0]
                + ",\"nativeTemplatePins\":" + state.nativeScoring[1]
                + ",\"nativeTemplateReleases\":" + state.nativeScoring[2]
                + ",\"nativeTemplateCopiedPins\":" + state.nativeScoring[3]
                + ",\"midiFileRoundtrip\":" + gates.passed("midi-file-roundtrip")
                + ",\"awtFontRaster\":" + gates.passed("awt-font-raster")
                + ",\"foregroundPixels\":" + state.foreground
                + ",\"fontRasterSHA256\":" + (state.fontHash == null ? "null" : quote(state.fontHash))
                + ",\"imageIOPng\":" + gates.passed("imageio-png")
                + ",\"imageIOTiff\":" + gates.passed("imageio-tiff")
                + ",\"jaxbUnicode\":" + gates.passed("jaxb-unicode")
                + ",\"musicXMLBinding\":" + gates.passed("musicxml-binding")
                + ",\"javaCPPTiffBridge\":" + gates.passed("javacpp-tiff")
                + ",\"legacyOCRCall\":" + gates.passed("legacy-ocr")
                + ",\"imageIOJpeg\":" + gates.passed("imageio-jpeg")
                + ",\"javaCPPJpegBridge\":" + gates.passed("javacpp-jpeg")
                + ",\"enginePDFRaster\":" + gates.passed("engine-pdf-raster")
                + ",\"pdfRasterSource\":" + quote(state.fontImage == null ? "diagnostic-fixture" : "bravura-notehead")
                + ",\"stages\":" + gates.json() + ",\"fullScoreRecognitionTested\":false}";
        Files.writeString(output.resolve("portability-probe.json"), report);
        gates.requireSuccess(); // Never enter score recognition after a component failure.
        return report;
    }

    private static BufferedImage codecFixture() {
        BufferedImage image = new BufferedImage(256, 128, BufferedImage.TYPE_BYTE_GRAY);
        for (int y = 0; y < image.getHeight(); y++) {
            for (int x = 0; x < image.getWidth(); x++) {
                int value = (x >= 24 && x < 232 && y >= 24 && y < 104 && ((x / 16 + y / 16) & 1) == 0) ? 0 : 255;
                image.getRaster().setSample(x, y, 0, value);
            }
        }
        return image;
    }

    private static long[] checkNativeTemplateScoring() throws Exception {
        if (!com.notelite.omr.image.NativeTemplateScorer.isEnabled()) {
            throw new IllegalStateException("Native template scoring was not registered");
        }
        long[] before = com.notelite.omr.image.NativeTemplateScorer.statistics();
        var table = new com.notelite.omr.image.DistanceTable.Short(1, 1, 3);
        var template = new com.notelite.omr.image.Template(com.notelite.omr.glyph.Shape.NOTEHEAD_BLACK,
                com.notelite.omr.ui.symbol.MusicFamily.Bravura, 20, 1, 1,
                new ArrayList<>(List.of(new com.notelite.omr.image.PixelDistance(0, 0, 0))),
                new java.awt.Rectangle(0, 0, 1, 1));
        var field = com.notelite.omr.image.Template.class.getDeclaredField("constants");
        field.setAccessible(true);
        Object constants = field.get(null);
        double[] weights = new double[3];
        String[] names = {"foreWeight", "backWeight", "holeWeight"};
        for (int i = 0; i < names.length; i++) {
            var weightField = constants.getClass().getDeclaredField(names[i]);
            weightField.setAccessible(true);
            weights[i] = ((com.notelite.omr.constant.Constant.Double) weightField.get(constants)).getValue();
        }
        for (double expectedDistance : new double[]{-3, -0.0, 0, 2}) {
            template.getKeyPoints().set(0, new com.notelite.omr.image.PixelDistance(0, 0, expectedDistance));
            for (int actualDistance : new int[]{-32768, -2, -1, 0, 1, 32767}) {
                table.setValue(0, 0, actualDistance);
                double weight = expectedDistance == 0 ? weights[0]
                        : expectedDistance > 0 ? weights[1] : weights[2];
                double binaryDistance = Math.abs((actualDistance == 0 ? 0.0 : 1.0)
                        - (expectedDistance == 0 ? 0.0 : 1.0));
                double score = actualDistance == -1 || weight == 0 ? Double.MAX_VALUE
                        : (weight * binaryDistance) / weight;
                double hole = expectedDistance < 0 && actualDistance != -1 && actualDistance != 0 ? 1.0 : 0.0;
                if (Double.doubleToRawLongBits(template.evaluate(0, 0, null, table)) != Double.doubleToRawLongBits(score)
                        || Double.doubleToRawLongBits(template.evaluateHole(0, 0, null, table)) != Double.doubleToRawLongBits(hole)) {
                    throw new IllegalStateException("Native template signed-distance or mutation result differs");
                }
            }
        }
        template.getKeyPoints().clear();
        if (template.evaluate(0, 0, null, table) != Double.MAX_VALUE
                || Double.doubleToRawLongBits(template.evaluateHole(0, 0, null, table)) != 0) {
            throw new IllegalStateException("Native empty template result differs");
        }
        long[] after = com.notelite.omr.image.NativeTemplateScorer.statistics();
        long[] delta = new long[4];
        for (int i = 0; i < delta.length; i++) delta[i] = after[i] - before[i];
        if (delta[0] < 50 || delta[1] == 0 || delta[1] != delta[2] || delta[3] != 0) {
            throw new IllegalStateException("Native template path, balanced releases, or zero-copy storage not proven");
        }
        return delta;
    }

    private static void checkMidiRoundtrip(Path output) throws Exception {
        var sequence = new javax.sound.midi.Sequence(javax.sound.midi.Sequence.PPQ, 480);
        var tempoTrack = sequence.createTrack();
        var tempo = new javax.sound.midi.MetaMessage();
        tempo.setMessage(0x51, new byte[]{7, (byte)0xa1, 0x20}, 3);
        tempoTrack.add(new javax.sound.midi.MidiEvent(tempo, 0));
        var notes = sequence.createTrack();
        for (int index = 0; index < 2; index++) {
            var on = new javax.sound.midi.ShortMessage(javax.sound.midi.ShortMessage.NOTE_ON, 3, 60 + 4 * index, 90);
            var off = new javax.sound.midi.ShortMessage(javax.sound.midi.ShortMessage.NOTE_OFF, 3, 60 + 4 * index, 0);
            notes.add(new javax.sound.midi.MidiEvent(on, 960L * index));
            notes.add(new javax.sound.midi.MidiEvent(off, 960L * index + 480));
        }
        Path midi = output.resolve("diagnostic-midi.mid");
        if (javax.sound.midi.MidiSystem.write(sequence, 1, midi.toFile()) <= 0) {
            throw new IllegalStateException("MIDI type-1 writer unavailable");
        }
        var decoded = javax.sound.midi.MidiSystem.getSequence(midi.toFile());
        if (decoded.getDivisionType() != sequence.getDivisionType()
                || decoded.getResolution() != sequence.getResolution()
                || !midiEvents(decoded).equals(midiEvents(sequence))) {
            throw new IllegalStateException("MIDI roundtrip changed track, tick or message bytes");
        }
    }

    private static List<String> midiEvents(javax.sound.midi.Sequence sequence) {
        List<String> events = new ArrayList<>();
        var tracks = sequence.getTracks();
        for (int index = 0; index < tracks.length; index++) {
            events.add("track:" + index);
            for (int item = 0; item < tracks[index].size(); item++) {
                var event = tracks[index].get(item);
                if (event.getMessage() instanceof javax.sound.midi.MetaMessage meta && meta.getType() == 0x2f) continue;
                events.add(index + ":" + event.getTick() + ":" + HexFormat.of().formatHex(event.getMessage().getMessage()));
            }
        }
        return events;
    }

    private static long countDark(BufferedImage image) {
        long count = 0;
        for (int y = 0; y < image.getHeight(); y++) {
            for (int x = 0; x < image.getWidth(); x++) {
                if ((image.getRGB(x, y) & 255) < 128) count++;
            }
        }
        return count;
    }

    private static void roundtripPNG(BufferedImage image, Path path) throws Exception {
        if (!ImageIO.write(image, "PNG", path.toFile())) throw new IllegalStateException("PNG encoder unavailable");
        requireDimensions(ImageIO.read(path.toFile()), image, "PNG");
    }

    private static byte[] encode(BufferedImage image, String format) throws Exception {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        if (!ImageIO.write(image, format, bytes)) throw new IllegalStateException(format + " encoder unavailable");
        return bytes.toByteArray();
    }

    private static void requireDimensions(BufferedImage image, BufferedImage expected, String stage) {
        if (image == null || image.getWidth() != expected.getWidth() || image.getHeight() != expected.getHeight()) {
            throw new IllegalStateException(stage + " roundtrip dimensions changed");
        }
    }

    private static void requireDimensions(PIX image, BufferedImage expected, String stage) {
        if (pixGetWidth(image) != expected.getWidth() || pixGetHeight(image) != expected.getHeight()) {
            throw new IllegalStateException(stage + " dimensions changed");
        }
    }

    private static String quote(String value) {
        StringBuilder result = new StringBuilder("\"");
        for (char character : value.toCharArray()) {
            if (character == '"' || character == '\\') result.append('\\').append(character);
            else if (character < 32) result.append(String.format("\\u%04x", (int)character));
            else result.append(character);
        }
        return result.append('"').toString();
    }
}
