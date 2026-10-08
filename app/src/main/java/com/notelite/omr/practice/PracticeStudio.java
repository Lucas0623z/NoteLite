package com.notelite.omr.practice;

import com.notelite.omr.OMR;
import com.notelite.omr.score.Score;
import com.notelite.omr.score.ScoreExporter;
import com.notelite.omr.sheet.Book;
import com.notelite.omr.ui.util.WebBrowser;
import com.sun.net.httpserver.HttpServer;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.charset.StandardCharsets;
import java.net.URLDecoder;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import javax.swing.JOptionPane;
import javax.swing.SwingUtilities;
import javax.swing.SwingWorker;

/** Local-only practice studio. Scores and microphone audio never leave this computer. */
public final class PracticeStudio {
    private static HttpServer server;
    private static ExecutorService executor;
    private static URI currentUri;
    private static volatile LocalAudioCapture localAudio;
    private PracticeStudio () {}

    /** Open an existing MusicXML/MXL from a score editor or independent OMR product. */
    public static void openImported (Path path) {
        new SwingWorker<URI, Void>() {
            @Override protected URI doInBackground () throws Exception {
                if (!Files.isRegularFile(path) || Files.size(path) > 15 * 1024 * 1024)
                    throw new IOException("请选择不超过 15 MB 的 MusicXML 或 MXL 乐谱。");
                return start(Files.readAllBytes(path));
            }
            @Override protected void done () {
                try { WebBrowser.getBrowser().launch(get()); }
                catch (Exception ex) { showError(ex); }
            }
        }.execute();
    }

    /** Transcribe the current book off the UI thread, select a movement, and open practice. */
    public static void open (Book book) {
        if (book == null) return;
        new SwingWorker<List<Score>, Void>() {
            @Override protected List<Score> doInBackground () throws Exception {
                if (!book.transcribe(book.getValidSelectedStubs(), book.getScores(), false))
                    throw new IOException("乐谱识别未完成，请先在音伴中完成识谱并校对。");
                return List.copyOf(book.getScores());
            }
            @Override protected void done () {
                try {
                    List<Score> scores = get();
                    if (scores.isEmpty()) throw new IOException("没有可练习的乐章。");
                    int index = 0;
                    if (scores.size() > 1) {
                        String[] labels = scores.stream().map(s -> "乐章 " + s.getId()).toArray(String[]::new);
                        Object selected = JOptionPane.showInputDialog(OMR.gui.getFrame(), "选择练习乐章", "音伴陪练", JOptionPane.QUESTION_MESSAGE, null, labels, labels[0]);
                        if (selected == null) return;
                        index = java.util.Arrays.asList(labels).indexOf(selected);
                    }
                    Score score = scores.get(index);
                    new SwingWorker<URI, Void>() {
                        @Override protected URI doInBackground () throws Exception {
                            ByteArrayOutputStream out = new ByteArrayOutputStream();
                            new ScoreExporter(score).export(out, false, "practice", false);
                            return start(out.toByteArray(), instrumentMetadata(score));
                        }
                        @Override protected void done () {
                            try { WebBrowser.getBrowser().launch(get()); }
                            catch (Exception ex) { showError(ex); }
                        }
                    }.execute();
                } catch (Exception ex) { showError(ex); }
            }
        }.execute();
    }

    private static void showError (Exception ex) {
        Throwable cause = ex.getCause() == null ? ex : ex.getCause();
        SwingUtilities.invokeLater(() -> JOptionPane.showMessageDialog(OMR.gui.getFrame(),
                "无法打开陪练：" + cause.getMessage(), "音伴陪练", JOptionPane.ERROR_MESSAGE));
    }

    /** Start an isolated loopback session with bundled assets and one immutable score. */
    public static synchronized URI start (byte[] musicXml) throws IOException {
        return start(musicXml, "{}");
    }

    private static synchronized URI start (byte[] musicXml, String metadata) throws IOException {
        byte[] scoreSnapshot = Objects.requireNonNull(musicXml, "musicXml").clone();
        stop();
        HttpServer next = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        String prefix = "/" + UUID.randomUUID() + "/";
        Map<String, String> assets = Map.of("index.html", "text/html; charset=utf-8",
                "app.js", "text/javascript; charset=utf-8", "style.css", "text/css; charset=utf-8",
                "demo.musicxml", "application/xml", "THIRD-PARTY.txt", "text/plain; charset=utf-8",
                "app.js.LEGAL.txt", "text/plain; charset=utf-8");
        int port = next.getAddress().getPort();
        next.createContext(prefix, exchange -> {
            try (exchange) {
                // Reject unexpected Host values and never grant cross-origin access.
                if (!("127.0.0.1:" + port).equals(exchange.getRequestHeaders().getFirst("Host"))) {
                    exchange.sendResponseHeaders(403, -1); return;
                }
                String file = exchange.getRequestURI().getPath().substring(prefix.length());
                if (file.isEmpty()) file = "index.html";
                String origin = "http://127.0.0.1:" + port;
                if (file.equals("engines.json")) {
                    if (!"GET".equals(exchange.getRequestMethod())) { exchange.sendResponseHeaders(405, -1); return; }
                    json(exchange, 200, "{\"windows\":" + System.getProperty("os.name").startsWith("Windows")
                            + ",\"nativeAudio\":" + LocalAudioCapture.available() + ",\"basicPitch\":" + LocalAudioAnalysis.available() + "}"); return;
                }
                if (file.equals("score-info.json")) {
                    if (!"GET".equals(exchange.getRequestMethod())) { exchange.sendResponseHeaders(405, -1); return; }
                    json(exchange, 200, metadata); return;
                }
                if (file.startsWith("audio/") || file.equals("analysis")) {
                    String requestOrigin = exchange.getRequestHeaders().getFirst("Origin");
                    if (requestOrigin != null && !origin.equals(requestOrigin)) { exchange.sendResponseHeaders(403, -1); return; }
                    if (file.equals("audio/events")) {
                        if (!"GET".equals(exchange.getRequestMethod())) { exchange.sendResponseHeaders(405, -1); return; }
                        LocalAudioCapture capture = localAudio;
                        if (capture == null) { json(exchange, 409, "{\"error\":\"尚未启动听音。\"}"); return; }
                        exchange.getResponseHeaders().set("Content-Type", "text/event-stream; charset=utf-8");
                        exchange.getResponseHeaders().set("Cache-Control", "no-store");
                        exchange.sendResponseHeaders(200, 0);
                        try {
                            while (!capture.ended()) {
                                String frame = capture.nextFrame();
                                exchange.getResponseBody().write((frame == null ? ": keepalive\n\n" : "data: " + frame + "\n\n").getBytes(StandardCharsets.UTF_8));
                                exchange.getResponseBody().flush();
                            }
                        } catch (InterruptedException ex) { Thread.currentThread().interrupt(); }
                        finally { capture.stop(); }
                        return;
                    }
                    if (!"POST".equals(exchange.getRequestMethod())) { exchange.sendResponseHeaders(405, -1); return; }
                    // State-changing routes require a same-origin browser request. File uploads use
                    // a non-simple MIME type, so unrelated sites cannot submit a form to this port.
                    if (!origin.equals(requestOrigin)) { exchange.sendResponseHeaders(403, -1); return; }
                    try {
                        if (file.equals("audio/start")) {
                            Map<String, String> query = query(exchange.getRequestURI());
                            double min = Double.parseDouble(query.getOrDefault("min", "27.5"));
                            double max = Double.parseDouble(query.getOrDefault("max", "4200"));
                            int window = Integer.parseInt(query.getOrDefault("window", "4096"));
                            boolean recording = "true".equals(query.get("record"));
                            synchronized (PracticeStudio.class) {
                                if (localAudio != null) localAudio.close();
                                LocalAudioCapture capture = new LocalAudioCapture();
                                capture.start(min, max, window, recording); localAudio = capture;
                            }
                            json(exchange, 200, "{\"started\":true}"); return;
                        }
                        if (file.equals("audio/stop")) { synchronized (PracticeStudio.class) { LocalAudioCapture capture = localAudio; if (capture != null) { capture.stop(); capture.checkFailure(); } } json(exchange, 200, "{\"stopped\":true}"); return; }
                        if (file.equals("audio/discard")) { synchronized (PracticeStudio.class) { LocalAudioCapture capture = localAudio; if (capture != null) capture.close(); } json(exchange, 200, "{\"discarded\":true}"); return; }
                        if (file.equals("analysis")) {
                            byte[] wav;
                            LocalAudioCapture capture = localAudio;
                            if ("true".equals(query(exchange.getRequestURI()).get("recorded"))) {
                                if (capture == null) throw new IOException("没有本地录音。");
                                Path recording = capture.recording();
                                if (Files.size(recording) > LocalAudioAnalysis.MAX_INPUT_BYTES) throw new IOException("录音过长，请分段练习。");
                                wav = Files.readAllBytes(recording);
                            } else {
                                if (!"application/octet-stream".equals(exchange.getRequestHeaders().getFirst("Content-Type"))) { exchange.sendResponseHeaders(415, -1); return; }
                                wav = exchange.getRequestBody().readNBytes(LocalAudioAnalysis.MAX_INPUT_BYTES + 1);
                                if (wav.length > LocalAudioAnalysis.MAX_INPUT_BYTES) throw new IOException("录音不能超过 64 MB。");
                            }
                            byte[] result = LocalAudioAnalysis.analyze(wav);
                            exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
                            exchange.getResponseHeaders().set("Cache-Control", "no-store");
                            exchange.sendResponseHeaders(200, result.length); exchange.getResponseBody().write(result);
                            if ("true".equals(query(exchange.getRequestURI()).get("recorded")) && capture != null) capture.deleteRecording();
                            return;
                        }
                        exchange.sendResponseHeaders(404, -1); return;
                    } catch (Exception ex) { json(exchange, 400, "{\"error\":" + quote(ex.getMessage()) + "}"); return; }
                }
                if (!"GET".equals(exchange.getRequestMethod())) { exchange.sendResponseHeaders(405, -1); return; }
                byte[] bytes;
                String type;
                if (file.equals("score.musicxml")) {bytes = scoreSnapshot; type = "application/xml";}
                else if (assets.containsKey(file) || file.matches("icons/[a-z0-9-]+\\.svg") || file.equals("icons/LICENSE.txt")) {
                    try (var stream = PracticeStudio.class.getResourceAsStream("/res/practice/" + file)) {
                        if (stream == null) {exchange.sendResponseHeaders(404, -1);return;}
                        bytes = stream.readAllBytes();
                        type = assets.getOrDefault(file, file.endsWith(".svg") ? "image/svg+xml" : "text/plain; charset=utf-8");
                    }
                } else { exchange.sendResponseHeaders(404, -1); return; }
                exchange.getResponseHeaders().set("Content-Type", type);
                exchange.getResponseHeaders().set("Cache-Control", "no-store");
                exchange.getResponseHeaders().set("X-Content-Type-Options", "nosniff");
                exchange.getResponseHeaders().set("Referrer-Policy", "no-referrer");
                exchange.getResponseHeaders().set("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; media-src 'self' blob:; object-src 'none'; frame-ancestors 'none'");
                exchange.sendResponseHeaders(200, bytes.length);
                exchange.getResponseBody().write(bytes);
            }
        });
        ExecutorService nextExecutor = Executors.newThreadPerTaskExecutor(Thread.ofVirtual().factory());
        next.setExecutor(nextExecutor);
        try {
            next.start();
        } catch (RuntimeException ex) {
            next.stop(0);
            nextExecutor.shutdownNow();
            throw ex;
        }
        server = next;
        executor = nextExecutor;
        currentUri = URI.create("http://127.0.0.1:" + port + prefix);
        return currentUri;
    }

    /** Stop the active studio, useful for application shutdown and tests. */
    public static synchronized void stop () {
        if (localAudio != null) { localAudio.close(); localAudio = null; }
        if (server != null) {server.stop(0);server = null;currentUri = null;}
        if (executor != null) {executor.shutdownNow();executor = null;}
    }

    private static Map<String, String> query (URI uri) {
        Map<String, String> result = new HashMap<>();
        if (uri.getRawQuery() != null) for (String pair : uri.getRawQuery().split("&")) {
            String[] parts = pair.split("=", 2);
            if (parts.length == 2) result.put(URLDecoder.decode(parts[0], StandardCharsets.UTF_8), URLDecoder.decode(parts[1], StandardCharsets.UTF_8));
        }
        return result;
    }
    /** Exporter defaults are playback conveniences, not identified instruments. */
    static String instrumentMetadata (Score score) {
        var parts = score.getLogicalParts();
        if (parts == null) return "{\"origin\":\"local-omr\",\"parts\":[]}";
        StringBuilder json = new StringBuilder("{\"origin\":\"local-omr\",\"parts\":[");
        for (int i = 0; i < parts.size(); i++) {
            var part = parts.get(i);
            if (i > 0) json.append(',');
            boolean confirmed = (part.getName() != null && !part.getName().isBlank())
                    || (part.getAbbreviation() != null && !part.getAbbreviation().isBlank());
            json.append("{\"id\":").append(quote(part.getPid())).append(",\"name\":").append(quote(part.getName() == null ? "" : part.getName()))
                    .append(",\"abbreviation\":").append(quote(part.getAbbreviation() == null ? "" : part.getAbbreviation()))
                    .append(",\"program\":").append(part.getMidiProgram() == null ? 0 : part.getMidiProgram())
                    .append(",\"confirmed\":").append(confirmed).append('}');
        }
        return json.append("]}").toString();
    }
    private static String quote (String value) {
        if (value == null) return "\"无法完成本地音频操作。\"";
        StringBuilder out = new StringBuilder("\"");
        for (char c : value.toCharArray()) {
            if (c == '"' || c == '\\') out.append('\\').append(c);
            else if (c < 32) out.append(String.format("\\u%04x", (int)c));
            else out.append(c);
        }
        return out.append('"').toString();
    }
    private static void json (com.sun.net.httpserver.HttpExchange exchange, int status, String content) throws IOException {
        byte[] bytes = content.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.getResponseHeaders().set("Cache-Control", "no-store");
        exchange.getResponseHeaders().set("X-Content-Type-Options", "nosniff");
        exchange.sendResponseHeaders(status, bytes.length); exchange.getResponseBody().write(bytes);
    }

    /** Standalone diagnostic entry: pass a MusicXML file, or use the bundled demonstration. */
    public static void main (String[] args) throws Exception {
        List<String> inputs = java.util.Arrays.stream(args).filter(a -> !a.equals("--browse")).toList();
        if (inputs.size() > 1) throw new IllegalArgumentException("Pass one MusicXML/MXL file and optionally --browse");
        byte[] xml;
        if (!inputs.isEmpty()) {
            Path path = Path.of(inputs.getFirst());
            if (Files.size(path) > 15 * 1024 * 1024) throw new IOException("Score exceeds 15 MB");
            xml = Files.readAllBytes(path);
        }
        else try (var input = PracticeStudio.class.getResourceAsStream("/res/practice/demo.musicxml")) {
            if (input == null) throw new IOException("Bundled practice demonstration is missing");
            xml = input.readAllBytes();
        }
        URI uri = start(xml);
        System.out.println(uri);
        if (java.util.Arrays.asList(args).contains("--browse")) WebBrowser.getBrowser().launch(uri);
        Runtime.getRuntime().addShutdownHook(new Thread(PracticeStudio::stop));
    }
}
