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
import java.io.StringReader;
import java.io.StringWriter;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HexFormat;
import javax.imageio.ImageIO;
import javax.imageio.spi.IIORegistry;
import javax.xml.bind.JAXBContext;
import javax.xml.bind.annotation.XmlRootElement;
import org.bytedeco.javacpp.BytePointer;
import org.bytedeco.leptonica.PIX;
import org.bytedeco.tesseract.TessBaseAPI;
import static org.bytedeco.leptonica.global.leptonica.*;
import static org.bytedeco.tesseract.global.tesseract.*;

/** No HTTP, no process launch, no downloaded executable code. Failure is fatal to the probe. */
public final class PortabilityProbe {
    @XmlRootElement
    public static final class Payload {
        public String value;
        public Payload() { }
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 3) throw new IllegalArgumentException("resources output tessdata required");
        System.setProperty("java.awt.headless", "true");
        String report = run(args[0], args[1], args[2]);
        Files.createDirectories(Path.of(args[1]));
        Files.writeString(Path.of(args[1], "portability-probe.json"), report);
        System.out.println(report);
    }

    public static String run(String resourceDirectory, String outputDirectory, String tessdataDirectory) throws Exception {
        if (!GraphicsEnvironment.isHeadless()) throw new IllegalStateException("Headless mode required");
        Path resources = Path.of(resourceDirectory);
        Path output = Path.of(outputDirectory);
        Files.createDirectories(output);
        Font music;
        try (var input = Files.newInputStream(resources.resolve("Bravura.otf"))) {
            music = Font.createFont(Font.TRUETYPE_FONT, input).deriveFont(60f);
        }
        if (!music.canDisplay(0xe0a4)) throw new IllegalStateException("Bravura notehead glyph unavailable");
        GraphicsEnvironment.getLocalGraphicsEnvironment().registerFont(music);
        BufferedImage image = new BufferedImage(256, 128, BufferedImage.TYPE_BYTE_GRAY);
        Graphics2D graphics = image.createGraphics();
        graphics.setColor(Color.WHITE);
        graphics.fillRect(0, 0, image.getWidth(), image.getHeight());
        graphics.setColor(Color.BLACK);
        new TextLayout("\ue0a4", music, graphics.getFontRenderContext()).draw(graphics, 60, 80);
        graphics.dispose();
        byte[] pixels = ((java.awt.image.DataBufferByte)image.getRaster().getDataBuffer()).getData();
        long foreground = 0;
        for (byte pixel : pixels) if ((pixel & 255) < 128) foreground++;
        if (foreground < 10 || foreground >= pixels.length / 2) {
            throw new IllegalStateException("Font rasterization produced invalid foreground: " + foreground);
        }
        if (!ImageIO.write(image, "PNG", output.resolve("bravura-notehead.png").toFile())) {
            throw new IllegalStateException("PNG encoder unavailable");
        }
        IIORegistry registry = IIORegistry.getDefaultInstance();
        registry.registerServiceProvider(new com.github.jaiimageio.impl.plugins.tiff.TIFFImageWriterSpi());
        registry.registerServiceProvider(new com.github.jaiimageio.impl.plugins.tiff.TIFFImageReaderSpi());
        ByteArrayOutputStream encoded = new ByteArrayOutputStream();
        if (!ImageIO.write(image, "TIFF", encoded)) throw new IllegalStateException("TIFF encoder unavailable");
        BufferedImage decoded = ImageIO.read(new ByteArrayInputStream(encoded.toByteArray()));
        if (decoded == null || decoded.getWidth() != image.getWidth() || decoded.getHeight() != image.getHeight()) {
            throw new IllegalStateException("TIFF roundtrip failed");
        }
        JAXBContext binding = JAXBContext.newInstance(Payload.class);
        Payload source = new Payload(); source.value = "音伴-𝄞";
        StringWriter xml = new StringWriter();
        binding.createMarshaller().marshal(source, xml);
        Payload restored = (Payload)binding.createUnmarshaller().unmarshal(new StringReader(xml.toString()));
        if (!source.value.equals(restored.value)) throw new IllegalStateException("JAXB Unicode roundtrip failed");
        // Also build the actual MusicXML model's binding context, including its reflection graph.
        JAXBContext.newInstance(org.audiveris.proxymusic.ScorePartwise.class);
        // Exercise the exact TIFF bridge and legacy OCR initialization the engine uses.
        org.bytedeco.javacpp.Loader.load(org.bytedeco.leptonica.global.leptonica.class);
        org.bytedeco.javacpp.Loader.load(org.bytedeco.tesseract.global.tesseract.class);
        try (BytePointer data = new BytePointer(encoded.toByteArray()); TessBaseAPI ocr = new TessBaseAPI()) {
            PIX pix = pixReadMemTiff(data, encoded.size(), 0);
            if (pix == null || pix.isNull()) throw new IllegalStateException("Leptonica TIFF decoder failed");
            try {
                if (ocr.Init(tessdataDirectory, "eng", OEM_TESSERACT_ONLY) != 0) {
                    throw new IllegalStateException("Legacy Tesseract model initialization failed");
                }
                ocr.SetImage(pix);
                if (ocr.Recognize(null) != 0) throw new IllegalStateException("Tesseract call failed");
                ocr.End();
            } finally { pixDestroy(pix); }
        }
        String hash = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(pixels));
        return "{\"awtFontRaster\":true,\"foregroundPixels\":" + foreground
            + ",\"fontRasterSHA256\":\"" + hash + "\",\"imageIOTiff\":true,\"jaxbUnicode\":true"
            + ",\"musicXMLBinding\":true,\"javaCPPTiffBridge\":true,\"legacyOCRCall\":true"
            + ",\"fullScoreRecognitionTested\":false}";
    }
}
