/* Copyright © NoteLite 2026. GNU Affero General Public License, version 3 or later. */
package com.notelite.omr.practice;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Owns one explicitly requested microphone capture and its optional temporary WAV. */
final class LocalAudioCapture implements AutoCloseable {
    private final ArrayBlockingQueue<String> frames = new ArrayBlockingQueue<>(256);
    private Process process;
    private Thread readerThread;
    private Path recording;
    private volatile String failure;
    private volatile boolean ended;

    static Path executable () {
        if (!System.getProperty("os.name", "").toLowerCase(Locale.ROOT).startsWith("windows")) return null;
        String configured = System.getProperty("notelite.audio.executable");
        if (configured != null) return Path.of(configured).toAbsolutePath().normalize();
        List<Path> candidates = new ArrayList<>();
        try {
            Path container = Path.of(LocalAudioCapture.class.getProtectionDomain().getCodeSource().getLocation().toURI());
            if (Files.isRegularFile(container)) candidates.add(container.getParent().getParent().resolve("bin/NoteLiteAudio.exe"));
        } catch (Exception ignored) {}
        candidates.add(Path.of("native/audio/build/NoteLiteAudio.exe"));
        candidates.add(Path.of("../native/audio/build/NoteLiteAudio.exe"));
        return candidates.stream().filter(Files::isRegularFile).findFirst().orElse(null);
    }

    static boolean available () { Path path = executable(); return path != null && Files.isRegularFile(path); }

    synchronized void start (double min, double max, int window, boolean record) throws IOException {
        if (!Double.isFinite(min) || !Double.isFinite(max) || min < 15 || max > 10000 || min >= max
                || (window != 4096 && window != 8192)) throw new IOException("听音参数无效。");
        stop(); deleteRecording(); frames.clear(); failure = null; ended = false;
        Path binary = executable();
        if (binary == null || !Files.isRegularFile(binary)) throw new IOException("此安装包没有 Windows 本地听音组件。");
        List<String> command = new ArrayList<>(List.of(binary.toString(), "--min-frequency", Double.toString(min),
                "--max-frequency", Double.toString(max), "--window", Integer.toString(window)));
        if (record) { recording = Files.createTempFile("notelite-performance-", ".wav"); command.add("--record"); command.add(recording.toString()); }
        CountDownLatch ready = new CountDownLatch(1);
        try {
            process = new ProcessBuilder(command).redirectError(ProcessBuilder.Redirect.DISCARD).start();
        } catch (IOException ex) { deleteRecording(); throw ex; }
        Process capture = process;
        readerThread = Thread.ofVirtual().start(() -> {
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(capture.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    if (line.length() > 16384) throw new IOException("听音组件输出过长。");
                    if (line.contains("\"type\":\"ready\"") || line.contains("\"type\": \"ready\"")) ready.countDown();
                    if (line.contains("\"type\":\"error\"") || line.contains("\"type\": \"error\"")) { failure = line; ready.countDown(); }
                    if (!frames.offer(line)) {
                        failure = "听音数据处理不及时，请结束后重试。";
                        frames.clear(); frames.offer("{\"type\":\"error\",\"code\":\"consumer-overflow\"}");
                        capture.destroy(); break;
                    }
                }
            } catch (IOException ex) { failure = ex.getMessage(); capture.destroy(); }
            finally { ended = true; ready.countDown(); }
        });
        try {
            if (!ready.await(8, TimeUnit.SECONDS) || ended || failure != null) {
                stop(); deleteRecording();
                throw new IOException(failure == null ? "无法启动麦克风，请检查 Windows 麦克风权限与输入设备。" : failure);
            }
        } catch (InterruptedException ex) { Thread.currentThread().interrupt(); stop(); throw new IOException("听音连接已取消。", ex); }
    }

    String nextFrame () throws InterruptedException { return frames.poll(1, TimeUnit.SECONDS); }
    boolean ended () { return ended && frames.isEmpty(); }
    synchronized Path recording () throws IOException {
        checkFailure();
        if (process != null && process.isAlive()) throw new IOException("请先结束录音。");
        if (recording == null || !Files.isRegularFile(recording) || Files.size(recording) <= 44) throw new IOException("没有可分析的录音。");
        return recording;
    }
    void checkFailure () throws IOException { if (failure != null) throw new IOException("录音或听音中断，请重新录音。" ); }

    synchronized void stop () {
        Process current = process; process = null;
        Thread reader = readerThread; readerThread = null;
        if (current == null) return;
        // Keep cancellation set for our caller, while still completing process
        // and reader cleanup when stop is invoked by an interrupted request.
        boolean interrupted = Thread.interrupted();
        try {
            if (current.isAlive()) {
                current.getOutputStream().write("STOP\n".getBytes(StandardCharsets.US_ASCII));
                current.getOutputStream().flush();
                current.getOutputStream().close();
            }
            if (!current.waitFor(4, TimeUnit.SECONDS)) {
                failure = "录音未正常结束，请重新录音。";
                current.destroyForcibly();
            }
        } catch (IOException ex) {
            if (current.isAlive()) {
                failure = "录音控制连接中断，请重新录音。";
                current.destroyForcibly();
            }
        } catch (InterruptedException ex) {
            interrupted = true;
            failure = "录音已取消，请重新录音。";
            current.destroyForcibly();
        }
        try {
            if (current.isAlive() && !current.waitFor(2, TimeUnit.SECONDS))
                failure = "录音进程未能退出，请重新启动陪练。";
            if (!current.isAlive() && current.exitValue() != 0 && failure == null)
                failure = "本地听音组件异常退出，请重新录音。";
            // The reader does not acquire this object's monitor. Drain terminal
            // error/stopped lines before recording() or checkFailure() can run.
            if (reader != null && reader != Thread.currentThread()) {
                reader.join(2000);
                if (reader.isAlive()) {
                    failure = "录音结果未能完整读取，请重新录音。";
                    current.getInputStream().close();
                    reader.join(1000);
                }
            }
        } catch (IOException ex) { failure = "录音结果读取中断，请重新录音。"; }
        catch (InterruptedException ex) { interrupted = true; failure = "录音已取消，请重新录音。"; }
        finally {
            try { current.getOutputStream().close(); } catch (IOException ignored) {}
            ended = true;
            if (interrupted) Thread.currentThread().interrupt();
        }
    }
    synchronized void deleteRecording () { if (recording != null) { try { Files.deleteIfExists(recording); } catch (IOException ignored) {} recording = null; } }
    @Override public void close () { stop(); deleteRecording(); }
}
