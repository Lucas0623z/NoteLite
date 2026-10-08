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

/** Runs bundled audio detectors, score normalization and offline baselines locally. */
public final class LocalAudioAnalysis
{
    public static final int MAX_INPUT_BYTES = 64 * 1024 * 1024;
    public static final int MAX_OUTPUT_BYTES = 32 * 1024 * 1024;
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
        return analyze(wav, Map.of());
    }

    public static byte[] analyze (byte[] wav, Map<String, ?> options) throws IOException {
        validateWav(wav);
        return run(wav, "analyze", options);
    }

    /** Partitura normalization retains source XML identity and distinct repeat occurrences. */
    public static byte[] normalize (byte[] musicXml, Map<String, ?> options) throws IOException {
        if (musicXml == null || musicXml.length == 0 || musicXml.length > 15 * 1024 * 1024)
            throw new IOException("请选择不超过 15 MB 的 MusicXML 或 MXL 乐谱。");
        return run(musicXml, "normalize", options);
    }

    /** Run an actual shipped offline baseline; no algorithm names are simulated. */
    public static byte[] align (Map<String, ?> normalizedScore, List<?> performanceNotes, Map<String, ?> options) throws IOException {
        byte[] payload = encode(Map.of("score", normalizedScore, "performance", performanceNotes, "options", options));
        if (payload.length > MAX_OUTPUT_BYTES) throw new IOException("对齐数据过大，请选择较短的练习段落。");
        return run(payload, "align", options);
    }

    public static Map<String, Boolean> capabilities () {
        Optional<Runtime> installed = findRuntime();
        if (installed.isEmpty()) return Map.of("basic-pitch", false, "pyin", false, "crepe", false, "aubio", false, "partitura", false, "parangonar", false, "nakamura", false);
        Map<String, Boolean> result = new LinkedHashMap<>();
        Path home = installed.get().helper().getParent();
        for (String engine : List.of("basic-pitch", "pyin", "crepe", "aubio", "partitura", "parangonar", "nakamura"))
            result.put(engine, smokePassed(installed.get().marker(), engine) && switch (engine) {
                case "pyin" -> Files.isRegularFile(home.resolve("mono_analysis.py"));
                case "crepe" -> Files.isRegularFile(home.resolve("models/crepe-tiny.onnx"));
                case "aubio" -> Files.isRegularFile(home.resolve("native/AubioMono.exe"));
                case "partitura", "parangonar" -> Files.isRegularFile(home.resolve("score_tools.py"));
                case "nakamura" -> List.of("SprToFmt3x", "Fmt3xToHmm", "ScorePerfmMatcher", "ErrorDetection", "RealignmentMOHMM", "MatchToCorresp")
                        .stream().allMatch(name -> Files.isRegularFile(home.resolve("native/nakamura/"+name+".exe")));
                default -> true;
            });
        return result;
    }

    private static byte[] run (byte[] input, String operation, Map<String, ?> options) throws IOException {
        Runtime runtime = findRuntime().orElseThrow(() -> new IOException(availabilityMessage()));
        if (!SLOT.tryAcquire()) throw new IOException("正在分析另一段录音，请完成后重试。");
        try { return execute(input, runtime, TIMEOUT, operation, options == null ? Map.of() : options); }
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
                && smokePassed(runtime.marker(), "basic-pitch")
                ? Optional.of(runtime) : Optional.empty();
    }

    private static boolean smokePassed (Path marker, String engine) {
        try {
            if (Files.size(marker) > 65536) return false;
            Object parsed = new Json(Files.readString(marker, StandardCharsets.UTF_8)).parse();
            return parsed instanceof Map<?,?> metadata && metadata.get("smoke") instanceof Map<?,?> smoke
                    && smoke.get(engine) instanceof Map<?,?> proof && Boolean.TRUE.equals(proof.get("passed"));
        } catch (IOException | RuntimeException ex) { return false; }
    }

    static byte[] analyze (byte[] wav, Runtime runtime, Duration timeout) throws IOException {
        validateWav(wav);
        return execute(wav, runtime, timeout, "analyze", Map.of());
    }

    private static byte[] execute (byte[] data, Runtime runtime, Duration timeout, String operation, Map<String, ?> options) throws IOException {
        Path directory = Files.createTempDirectory("notelite-audio-");
        Process process = null;
        try {
            Path input = directory.resolve(operation.equals("analyze") ? "recording.wav" : operation.equals("normalize") ? "score.musicxml" : "alignment.json");
            Path output = directory.resolve("result.json"), log = directory.resolve("analysis.log"), configuration = directory.resolve("options.json");
            Files.write(input, data); Files.write(configuration, encode(options));
            ProcessBuilder builder = new ProcessBuilder(runtime.python.toString(), runtime.helper.toString(),
                    "--input", input.toString(), "--output", output.toString(), "--operation", operation, "--options", configuration.toString());
            builder.directory(directory.toFile()).redirectErrorStream(true).redirectOutput(log.toFile());
            // Numba caches compilation beside the disposable take rather than
            // requiring write access to the installed application directory.
            builder.environment().put("NUMBA_CACHE_DIR", directory.resolve("numba-cache").toString());
            builder.environment().put("OMP_NUM_THREADS", "2");
            builder.environment().put("NUMBA_NUM_THREADS", "2");
            process = builder.start();
            if (!process.waitFor(timeout.toMillis(), TimeUnit.MILLISECONDS)) {
                try { stop(process); }
                catch (RuntimeException ignored) { /* Preserve the timeout. */ }
                throw new IOException("本地录音分析超时，请缩短录音后重试。");
            }
            if (process.exitValue() != 0) throw new IOException("本地听音分析失败：" + diagnostic(log));
            if (!Files.isRegularFile(output) || Files.size(output) > MAX_OUTPUT_BYTES)
                throw new IOException("本地听音引擎没有返回有效结果。");
            byte[] result = Files.readAllBytes(output);
            if (operation.equals("analyze")) validateResult(result);
            else validateOperationResult(result, operation);
            return result;
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new IOException("本地录音分析已取消。", ex);
        } finally {
            try { if (process != null && process.isAlive()) stop(process); }
            catch (RuntimeException ignored) { /* Keep the primary result/error. */ }
            cleanup(directory);
        }
    }

    /** A Windows process can retain a log handle briefly after termination. */
    static void cleanup (Path directory) {
        // This method only receives our newly created analysis directory. Walk
        // without FOLLOW_LINKS, and never replace a result/timeout with cleanup.
        List<Path> deferred = new ArrayList<>();
        try (var paths = Files.walk(directory)) {
            for (Path path : paths.sorted(Comparator.reverseOrder()).toList()) {
                try { Files.deleteIfExists(path); }
                catch (IOException | RuntimeException ignored) { deferred.add(path); }
            }
        } catch (IOException | RuntimeException ignored) { deferred.add(directory); }
        // deleteOnExit runs registrations in reverse order. Register parents
        // first so any unlocked children are removed before their directories.
        deferred.sort(Comparator.comparingInt(Path::getNameCount));
        for (Path path : deferred) {
            try { path.toFile().deleteOnExit(); }
            catch (RuntimeException ignored) { /* Safely retain an owned temp. */ }
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
                    || !List.of("basic-pitch", "pyin", "crepe", "aubio").contains(root.get("engine")) || !(root.get("notes") instanceof List<?> notes) || notes.size() > 20000)
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
                if (note.containsKey("cents") && Math.abs(number(note.get("cents"))) > 100) throw new IllegalArgumentException("Cents");
            }
        } catch (IllegalArgumentException ex) { throw new IOException("本地听音引擎返回了无效的音符结果。", ex); }
    }

    private static void validateOperationResult (byte[] result, String operation) throws IOException {
        try {
            Object parsed = new Json(new String(result, StandardCharsets.UTF_8)).parse();
            if (!(parsed instanceof Map<?, ?> root) || integer(root.get("schemaVersion")) != 1) throw new IllegalArgumentException("Schema");
            if (operation.equals("normalize")) {
                if (!"partitura".equals(root.get("engine")) || !(root.get("groups") instanceof List<?>) || !(root.get("notes") instanceof List<?> notes)) throw new IllegalArgumentException("Score");
                for (Object value : notes) {
                    if (!(value instanceof Map<?, ?> note) || !(note.get("sourceNoteId") instanceof String) || !(note.get("occurrenceId") instanceof String)
                            || number(note.get("onset")) < 0 || number(note.get("duration")) <= 0 || integer(note.get("midi")) < 0 || integer(note.get("midi")) > 127)
                        throw new IllegalArgumentException("Score note identity");
                }
            } else if (!List.of("parangonar", "nakamura").contains(root.get("engine")) || !(root.get("pairs") instanceof List<?>)
                    || !(root.get("missing") instanceof List<?>) || !(root.get("extra") instanceof List<?>)) throw new IllegalArgumentException("Baseline");
        } catch (IllegalArgumentException ex) { throw new IOException("本地规范化或对齐结果无效。", ex); }
    }

    private static byte[] encode (Object value) throws IOException {
        StringBuilder output = new StringBuilder();
        encode(value, output, 0);
        return output.toString().getBytes(StandardCharsets.UTF_8);
    }

    private static void encode (Object value, StringBuilder out, int depth) throws IOException {
        if (depth > 16) throw new IOException("分析参数嵌套过深。");
        if (value == null) out.append("null");
        else if (value instanceof Number n) { if (!Double.isFinite(n.doubleValue())) throw new IOException("无效的数字参数。"); out.append(n); }
        else if (value instanceof Boolean b) out.append(b);
        else if (value instanceof String string) {
            out.append('"');
            for (char c : string.toCharArray()) switch (c) {
                case '"' -> out.append("\\\""); case '\\' -> out.append("\\\\");
                case '\n' -> out.append("\\n"); case '\r' -> out.append("\\r"); case '\t' -> out.append("\\t");
                default -> { if (c < 32) out.append(String.format("\\u%04x", (int) c)); else out.append(c); }
            }
            out.append('"');
        } else if (value instanceof Map<?, ?> map) {
            out.append('{'); boolean first = true;
            for (var entry : map.entrySet()) {
                if (!(entry.getKey() instanceof String)) throw new IOException("分析参数须使用文本键。");
                if (!first) out.append(','); first = false; encode(entry.getKey(), out, depth+1); out.append(':'); encode(entry.getValue(), out, depth+1);
            }
            out.append('}');
        } else if (value instanceof List<?> list) {
            out.append('['); boolean first = true;
            for (Object item : list) { if (!first) out.append(','); first = false; encode(item, out, depth+1); }
            out.append(']');
        } else throw new IOException("不支持的分析参数类型。");
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
                do { values.add(value(depth + 1)); if (values.size() > 100000) fail(); } while (take(','));
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
