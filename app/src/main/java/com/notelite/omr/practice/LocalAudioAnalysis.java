/* Copyright © NoteLite 2026. Licensed under the GNU Affero General Public License. */
package com.notelite.omr.practice;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;

/** Runs the bundled Basic Pitch ONNX transcription process on this computer only. */
public final class LocalAudioAnalysis
{
    public static final int MAX_INPUT_BYTES = 64 * 1024 * 1024;
    public static final int MAX_OUTPUT_BYTES = 4 * 1024 * 1024;
    public static final Duration TIMEOUT = Duration.ofMinutes(5);
    private static final Semaphore SLOT = new Semaphore(1);

    private LocalAudioAnalysis () {}

    public static boolean available () { return findRuntime().isPresent(); }

    public static String availabilityMessage () {
        return available() ? "Basic Pitch 本地录音分析已就绪。"
                : "未安装 Basic Pitch 本地分析组件，请安装包含本地听音引擎的 Windows 版本。";
    }

    /** Return validated UTF-8 schemaVersion 1 JSON, retaining all actual onset timestamps. */
    public static byte[] analyze (byte[] wav) throws IOException {
        validateWav(wav);
        Runtime runtime = findRuntime().orElseThrow(() -> new IOException(availabilityMessage()));
        if (!SLOT.tryAcquire()) throw new IOException("正在分析另一段录音，请完成后重试。");
        try { return analyze(wav, runtime, TIMEOUT); }
        finally { SLOT.release(); }
    }

    static record Runtime (Path python, Path helper, Path model, Path marker) {}

    static Optional<Runtime> findRuntime () {
        String configured = System.getProperty("notelite.analysis.home");
        if (configured == null || configured.isBlank()) configured = System.getenv("NOTELITE_ANALYSIS_HOME");
        // An explicit override is authoritative, including when it is invalid.
        if (configured != null && !configured.isBlank()) {
            try { return at(Path.of(configured)); }
            catch (RuntimeException ex) { return Optional.empty(); }
        }
        List<Path> homes = new ArrayList<>();
        String appHome = System.getProperty("notelite.home");
        if (appHome != null && !appHome.isBlank()) homes.add(Path.of(appHome).resolve("tools/local-analysis"));
        try {
            Path source = Path.of(LocalAudioAnalysis.class.getProtectionDomain().getCodeSource().getLocation().toURI());
            Path directory = Files.isDirectory(source) ? source : source.getParent();
            for (int i = 0; i < 5 && directory != null; i++, directory = directory.getParent()) {
                homes.add(directory.resolve("tools/local-analysis"));
                homes.add(directory.resolve("local-analysis/runtime"));
                homes.add(directory.resolve("build/local-analysis"));
            }
        } catch (Exception ignored) { /* An explicit property remains available to restricted launchers. */ }
        Path cwd = Path.of(System.getProperty("user.dir", "."));
        homes.add(cwd.resolve("tools/local-analysis"));
        homes.add(cwd.resolve("local-analysis/runtime"));
        return homes.stream().map(LocalAudioAnalysis::at).flatMap(Optional::stream).findFirst();
    }

    private static Optional<Runtime> at (Path home) {
        home = home.toAbsolutePath().normalize();
        Runtime runtime = new Runtime(home.resolve("python/python.exe"), home.resolve("analyze.py"),
                home.resolve("models/basic-pitch.onnx"), home.resolve("runtime-ready.json"));
        return List.of(runtime.python, runtime.helper, runtime.model, runtime.marker).stream().allMatch(Files::isRegularFile)
                ? Optional.of(runtime) : Optional.empty();
    }

    static byte[] analyze (byte[] wav, Runtime runtime, Duration timeout) throws IOException {
        validateWav(wav);
        Path directory = Files.createTempDirectory("notelite-audio-");
        Process process = null;
        try {
            Path input = directory.resolve("recording.wav"), output = directory.resolve("notes.json"), log = directory.resolve("analysis.log");
            Files.write(input, wav);
            ProcessBuilder builder = new ProcessBuilder(runtime.python.toString(), runtime.helper.toString(),
                    "--input", input.toString(), "--output", output.toString());
            builder.directory(directory.toFile()).redirectErrorStream(true).redirectOutput(log.toFile());
            // Numba caches compilation beside the disposable take rather than
            // requiring write access to the installed application directory.
            builder.environment().put("NUMBA_CACHE_DIR", directory.resolve("numba-cache").toString());
            builder.environment().put("OMP_NUM_THREADS", "2");
            builder.environment().put("NUMBA_NUM_THREADS", "2");
            process = builder.start();
            if (!process.waitFor(timeout.toMillis(), TimeUnit.MILLISECONDS)) {
                stop(process);
                throw new IOException("本地录音分析超时，请缩短录音后重试。");
            }
            if (process.exitValue() != 0) throw new IOException("Basic Pitch 本地分析失败：" + diagnostic(log));
            if (!Files.isRegularFile(output) || Files.size(output) > MAX_OUTPUT_BYTES)
                throw new IOException("本地听音引擎没有返回有效结果。");
            byte[] result = Files.readAllBytes(output);
            validateResult(result);
            return result;
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new IOException("本地录音分析已取消。", ex);
        } finally {
            if (process != null && process.isAlive()) stop(process);
            // All paths originate under our own newly created directory. Never
            // remove a user path or follow symlinks during cleanup.
            try (var paths = Files.walk(directory)) {
                for (Path path : paths.sorted(Comparator.reverseOrder()).toList()) Files.deleteIfExists(path);
            }
        }
    }

    private static void stop (Process process) {
        boolean interrupted = Thread.interrupted();
        process.descendants().forEach(child -> child.destroyForcibly());
        process.destroyForcibly();
        try { process.waitFor(5, TimeUnit.SECONDS); }
        catch (InterruptedException ex) { interrupted = true; }
        finally { if (interrupted) Thread.currentThread().interrupt(); }
    }

    private static String diagnostic (Path log) throws IOException {
        if (!Files.isRegularFile(log)) return "未提供错误信息";
        try (var input = Files.newInputStream(log)) {
            String text = new String(input.readNBytes(8192), StandardCharsets.UTF_8).strip();
            return text.length() > 1000 ? text.substring(text.length() - 1000) : text;
        }
    }

    /** Accept only bounded, complete 16-bit mono/stereo PCM WAV recordings. */
    static void validateWav (byte[] wav) throws IOException {
        if (wav == null || wav.length < 44 || wav.length > MAX_INPUT_BYTES) throw new IOException("录音为空或超过 64 MB。");
        ByteBuffer b = ByteBuffer.wrap(wav).order(ByteOrder.LITTLE_ENDIAN);
        if (b.getInt(0) != 0x46464952 || b.getInt(8) != 0x45564157 || Integer.toUnsignedLong(b.getInt(4)) != wav.length - 8L)
            throw new IOException("请提交完整的 PCM WAV 录音。");
        int channels = 0, rate = 0, block = 0;
        long data = -1;
        boolean format = false;
        for (long pos = 12; pos + 8 <= wav.length;) {
            int offset = (int) pos, kind = b.getInt(offset);
            long length = Integer.toUnsignedLong(b.getInt(offset + 4));
            if (pos + 8 + length > wav.length) throw new IOException("WAV 录音数据不完整。");
            if (kind == 0x20746d66) {
                if (format || length < 16 || b.getShort(offset + 8) != 1 || b.getShort(offset + 22) != 16)
                    throw new IOException("仅支持 16 位 PCM WAV。");
                format = true;
                channels = Short.toUnsignedInt(b.getShort(offset + 10));
                rate = b.getInt(offset + 12);
                block = Short.toUnsignedInt(b.getShort(offset + 20));
                if ((channels != 1 && channels != 2) || rate < 8000 || rate > 96000 || block != channels * 2
                        || Integer.toUnsignedLong(b.getInt(offset + 16)) != (long) rate * block)
                    throw new IOException("WAV 应为 8000–96000 Hz 的单声道或立体声录音。");
            } else if (kind == 0x61746164) {
                if (data >= 0) throw new IOException("WAV 中包含重复的声音数据。");
                data = length;
            }
            pos += 8 + length + (length & 1);
            if (pos > wav.length) throw new IOException("WAV 录音数据不完整。");
        }
        if (!format || data <= 0 || data % block != 0 || data / (double) (rate * block) > 600)
            throw new IOException("录音时长须在 0–600 秒内。");
    }

    static void validateResult (byte[] result) throws IOException {
        try {
            Object parsed = new Json(new String(result, StandardCharsets.UTF_8)).parse();
            if (!(parsed instanceof Map<?, ?> root) || !Integer.valueOf(1).equals(integer(root.get("schemaVersion")))
                    || !"basic-pitch".equals(root.get("engine")) || !(root.get("notes") instanceof List<?> notes) || notes.size() > 20000)
                throw new IllegalArgumentException("Unsupported schema");
            double seconds = number(root.get("seconds"));
            if (seconds <= 0 || seconds > 600) throw new IllegalArgumentException("Duration");
            double last = -1;
            for (Object value : notes) {
                if (!(value instanceof Map<?, ?> note)) throw new IllegalArgumentException("Note");
                int midi = integer(note.get("midi"));
                double onset = number(note.get("onset")), duration = number(note.get("duration")), confidence = number(note.get("confidence"));
                if (midi < 0 || midi > 127 || onset < last || onset < 0 || duration <= 0 || onset + duration > seconds + .001
                        || confidence < 0 || confidence > 1) throw new IllegalArgumentException("Invalid note event");
                last = onset;
            }
        } catch (IllegalArgumentException ex) { throw new IOException("本地听音引擎返回了无效的音符结果。", ex); }
    }

    private static int integer (Object value) {
        double n = number(value);
        if (n != Math.rint(n) || n < Integer.MIN_VALUE || n > Integer.MAX_VALUE) throw new IllegalArgumentException("Integer");
        return (int) n;
    }

    private static double number (Object value) {
        if (!(value instanceof Number n) || !Double.isFinite(n.doubleValue())) throw new IllegalArgumentException("Number");
        return n.doubleValue();
    }

    /** Small strict parser keeps this subprocess boundary independent of optional JSON libraries. */
    private static final class Json {
        final String text; int position;
        Json (String text) { this.text = text; }
        Object parse () { Object value = value(0); whitespace(); if (position != text.length()) fail(); return value; }
        void whitespace () { while (position < text.length() && " \r\n\t".indexOf(text.charAt(position)) >= 0) position++; }
        boolean take (char c) { whitespace(); if (position < text.length() && text.charAt(position) == c) { position++; return true; } return false; }
        void need (char c) { if (!take(c)) fail(); }
        Object value (int depth) {
            whitespace(); if (depth > 16 || position >= text.length()) fail();
            char c = text.charAt(position);
            if (c == '"') return string();
            if (take('{')) {
                Map<String, Object> values = new LinkedHashMap<>();
                if (take('}')) return values;
                do { String key = string(); need(':'); Object item = value(depth + 1);
                    if (values.containsKey(key)) fail(); values.put(key, item);
                } while (take(','));
                need('}'); return values;
            }
            if (take('[')) {
                List<Object> values = new ArrayList<>(); if (take(']')) return values;
                do { values.add(value(depth + 1)); if (values.size() > 20000) fail(); } while (take(','));
                need(']'); return values;
            }
            for (String literal : List.of("null", "true", "false")) {
                if (text.startsWith(literal, position)) { position += literal.length(); return literal.equals("null") ? null : Boolean.valueOf(literal); }
            }
            int start = position;
            if (text.charAt(position) == '-') position++;
            if (position >= text.length() || !Character.isDigit(text.charAt(position))) fail();
            if (text.charAt(position) == '0') position++;
            else while (position < text.length() && text.charAt(position) >= '0' && text.charAt(position) <= '9') position++;
            if (position < text.length() && text.charAt(position) == '.') {
                position++; int digits = position;
                while (position < text.length() && text.charAt(position) >= '0' && text.charAt(position) <= '9') position++;
                if (digits == position) fail();
            }
            if (position < text.length() && "eE".indexOf(text.charAt(position)) >= 0) {
                position++; if (position < text.length() && "+-".indexOf(text.charAt(position)) >= 0) position++;
                int digits = position;
                while (position < text.length() && text.charAt(position) >= '0' && text.charAt(position) <= '9') position++;
                if (digits == position) fail();
            }
            return Double.valueOf(text.substring(start, position));
        }
        String string () {
            need('"'); StringBuilder value = new StringBuilder();
            while (position < text.length()) {
                char c = text.charAt(position++);
                if (c == '"') return value.toString();
                if (c < 32) fail();
                if (c == '\\') {
                    if (position >= text.length()) fail(); c = text.charAt(position++);
                    switch (c) {
                        case '"', '\\', '/' -> value.append(c);
                        case 'b' -> value.append('\b'); case 'f' -> value.append('\f');
                        case 'n' -> value.append('\n'); case 'r' -> value.append('\r'); case 't' -> value.append('\t');
                        case 'u' -> { if (position + 4 > text.length()) fail(); value.append((char) Integer.parseInt(text.substring(position, position + 4), 16)); position += 4; }
                        default -> fail();
                    }
                } else value.append(c);
            }
            fail(); return null;
        }
        void fail () { throw new IllegalArgumentException("Invalid JSON at " + position); }
    }
}
