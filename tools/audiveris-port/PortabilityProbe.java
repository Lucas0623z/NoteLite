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
        BufferedImage png = ImageIO.read(output.resolve("bravura-notehead.png").toFile());
        if (png == null || png.getWidth() != image.getWidth() || png.getHeight() != image.getHeight()) {
            throw new IllegalStateException("PNG roundtrip failed");
        }
        ByteArrayOutputStream jpeg = new ByteArrayOutputStream();
        if (!ImageIO.write(image, "JPEG", jpeg)) throw new IllegalStateException("JPEG encoder unavailable");
        BufferedImage jpegImage = ImageIO.read(new ByteArrayInputStream(jpeg.toByteArray()));
        if (jpegImage == null || jpegImage.getWidth() != image.getWidth() || jpegImage.getHeight() != image.getHeight()) {
            throw new IllegalStateException("ImageIO JPEG roundtrip failed");
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
        Path pdfFile = output.resolve("scanned-notehead.pdf");
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
            int dark = 0;
            for (int y = 0; y < pdfImage.getHeight(); y++) {
                for (int x = 0; x < pdfImage.getWidth(); x++) {
                    if ((pdfImage.getRGB(x, y) & 255) < 128) dark++;
                }
            }
            if (dark < foreground / 2 || dark > foreground * 2) {
                throw new IllegalStateException("PDF renderer lost or corrupted the actual notehead");
            }
        } finally { pdfLoader.dispose(); }
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
        // Exercise both JPEG implementations in the same process. The JDK's
        // private IJG symbols must not collide with Leptonica's libjpeg-turbo.
        try (BytePointer data = new BytePointer(jpeg.toByteArray())) {
            PIX pix = pixReadMem(data, jpeg.size());
            if (pix == null || pix.isNull()) throw new IllegalStateException("Leptonica JPEG decoder failed");
            try {
                if (pixGetWidth(pix) != image.getWidth() || pixGetHeight(pix) != image.getHeight()) {
                    throw new IllegalStateException("Leptonica JPEG dimensions changed");
                }
            } finally { pixDestroy(pix); }
        }
        if (ImageIO.read(new ByteArrayInputStream(jpeg.toByteArray())) == null) {
            throw new IllegalStateException("JDK JPEG decoder failed after native OCR codec use");
        }
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
            + ",\"imageIOJpeg\":true,\"javaCPPJpegBridge\":true"
            + ",\"enginePDFRaster\":true"
            + ",\"fullScoreRecognitionTested\":false}";
    }
}
