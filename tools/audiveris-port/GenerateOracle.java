// SPDX-License-Identifier: AGPL-3.0-or-later
// Reference fixtures call the unchanged NoteLite/Audiveris Java implementations.
import com.notelite.omr.image.GlobalFilter;
import com.notelite.omr.image.VerticalFilter;
import com.notelite.omr.run.Orientation;
import com.notelite.omr.run.Run;
import com.notelite.omr.run.RunTable;
import com.notelite.omr.run.RunTableFactory;
import com.notelite.omr.util.OmrExecutors;
import ij.process.ByteProcessor;
import java.awt.image.BufferedImage;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.Base64;
import java.util.HexFormat;
import java.util.Iterator;
import java.util.Random;
import javax.imageio.ImageIO;

public final class GenerateOracle {
    private static Path output;
    private static int cases;

    public static void main(String[] args) throws Exception {
        output = Path.of(args[0]);
        Files.createDirectories(output);
        OmrExecutors.defaultParallelism.setSpecific(false);
        for (int gray : new int[]{0, 127, 255}) {
            emit("single-" + gray, 1, 1, new byte[]{(byte)gray}, "adaptive", .7, .9, 127);
        }
        for (int[] size : new int[][]{{1,83},{83,1},{13,11},{37,37},{38,38},{81,59},{129,5}}) {
            byte[] pixels = new byte[size[0] * size[1]];
            new Random(0xA0D1L + size[0] * 1000 + size[1]).nextBytes(pixels);
            emit("random-" + size[0] + "x" + size[1], size[0], size[1], pixels, "adaptive", .7, .9, 127);
        }
        byte[] white = new byte[41 * 43];
        Arrays.fill(white, (byte)255);
        emit("white", 41, 43, white, "adaptive", .7, .9, 127);
        emit("black", 41, 43, new byte[41 * 43], "adaptive", .7, .9, 127);
        byte[] gradient = new byte[256 * 7];
        for (int y = 0; y < 7; y++) for (int x = 0; x < 256; x++) gradient[y * 256 + x] = (byte)x;
        for (int threshold : new int[]{0,127,255}) {
            emit("global-" + threshold, 256, 7, gradient, "global", .7, .9, threshold);
        }
        byte[] staff = new byte[128 * 93];
        for (int y = 0; y < 93; y++) for (int x = 0; x < 128; x++) {
            int pixel = 150 + x * 100 / 127;
            if ((y >= 18 && y <= 50 && (y - 18) % 8 == 0 && x >= 8 && x <= 119)
                    || (x >= 60 && x <= 62 && y >= 25 && y <= 51)
                    || ((x - 57) * (x - 57) + (y - 49) * (y - 49) <= 18)) pixel = 20;
            staff[y * 128 + x] = (byte)pixel;
        }
        emit("shadow-staff", 128, 93, staff, "adaptive", .7, .9, 127);
        emit("custom-coefficients", 128, 93, staff, "adaptive", .65, 1.0, 127);
        emit("zero-coefficients", 128, 93, staff, "adaptive", 0, 0, 127);
        // A real score already distributed with the repository. The small sampled
        // image validates port equivalence, not OMR quality at recognition resolution.
        Path sample = Path.of("data/examples/chula.png");
        BufferedImage image = ImageIO.read(sample.toFile());
        int width = 384, height = Math.max(1, image.getHeight() * width / image.getWidth());
        byte[] score = new byte[width * height];
        for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
            int rgb = image.getRGB(x * image.getWidth() / width, y * image.getHeight() / height);
            score[y * width + x] = (byte)((77 * ((rgb >> 16) & 255)
                    + 150 * ((rgb >> 8) & 255) + 29 * (rgb & 255)) >> 8);
        }
        emit("real-score-chula", width, height, score, "adaptive", .7, .9, 127);
        StringBuilder manifest = new StringBuilder("{\n  \"formatVersion\": 1,\n  \"caseCount\": " + cases + ",\n  \"sourceSHA256\": {\n");
        String[] sources = {"app/src/main/java/com/notelite/omr/image/AdaptiveFilter.java",
                "app/src/main/java/com/notelite/omr/image/VerticalFilter.java",
                "app/src/main/java/com/notelite/omr/image/GlobalFilter.java",
                "app/src/main/java/com/notelite/omr/run/RunsRetriever.java",
                "app/src/main/java/com/notelite/omr/run/RunTableFactory.java",
                "app/src/main/java/com/notelite/omr/run/RunTable.java", "data/examples/chula.png"};
        for (int i = 0; i < sources.length; i++) {
            // Normalize source line endings so Windows and macOS fixtures match.
            byte[] bytes = sources[i].endsWith(".java")
                ? Files.readString(Path.of(sources[i])).replace("\r\n", "\n").getBytes(StandardCharsets.UTF_8)
                : Files.readAllBytes(Path.of(sources[i]));
            manifest.append("    \"").append(sources[i]).append("\": \"")
                .append(HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)))
                .append(i + 1 == sources.length ? "\"\n" : "\",\n");
        }
        manifest.append("  }\n}\n");
        Files.writeString(output.resolve("manifest.json"), manifest);
        System.out.println("Generated " + cases + " reference cases from the real Java engine at " + output);
    }

    private static void emit(String name, int width, int height, byte[] pixels,
            String mode, double mean, double std, int threshold) throws Exception {
        ByteProcessor source = new ByteProcessor(width, height, pixels.clone());
        ByteProcessor binary = mode.equals("adaptive")
            ? new VerticalFilter(source, mean, std).filteredImage()
            : new GlobalFilter(source, threshold).filteredImage();
        String json = "{\n  \"name\": \"" + name + "\",\n  \"width\": " + width
            + ",\n  \"height\": " + height + ",\n  \"mode\": \"" + mode
            + "\",\n  \"halfWindowSize\": 18,\n  \"meanCoefficient\": " + mean
            + ",\n  \"standardDeviationCoefficient\": " + std + ",\n  \"threshold\": " + threshold
            + ",\n  \"grayBase64\": \"" + Base64.getEncoder().encodeToString(pixels)
            + "\",\n  \"binaryBase64\": \"" + Base64.getEncoder().encodeToString((byte[])binary.getPixels())
            + "\",\n  \"horizontalRuns\": " + runs(binary, Orientation.HORIZONTAL)
            + ",\n  \"verticalRuns\": " + runs(binary, Orientation.VERTICAL) + "\n}\n";
        Files.writeString(output.resolve(name + ".json"), json, StandardCharsets.UTF_8);
        cases++;
    }

    private static String runs(ByteProcessor source, Orientation orientation) {
        RunTable table = new RunTableFactory(orientation).createTable(source);
        StringBuilder json = new StringBuilder("[");
        for (int position = 0; position < table.getSize(); position++) {
            if (position > 0) json.append(',');
            json.append('[');
            Iterator<Run> runs = table.iterator(position);
            boolean first = true;
            while (runs.hasNext()) {
                Run run = runs.next();
                if (!first) json.append(',');
                first = false;
                json.append('[').append(run.getStart()).append(',').append(run.getLength()).append(']');
            }
            json.append(']');
        }
        return json.append(']').toString();
    }
}
