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
    private static volatile PracticeRuntime runtime;
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
        runtime = new PracticeRuntime(scoreSnapshot,metadata);
        instrumentInfo=metadata;
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
                if (dynamic(exchange,file,origin)) return;
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
        if(runtime!=null){runtime.stopPlayback();try{runtime.keepCapture(localAudio);runtime.finish();}catch(IOException ignored){/* Shutdown still closes all local devices. */}}
        if (localAudio != null) { localAudio.close(); localAudio = null; }
        if (runtime != null) { runtime.close(); runtime=null; }
        if (server != null) {server.stop(0);server = null;currentUri = null;}
        if (executor != null) {executor.shutdownNow();executor = null;}
    }

    /** Local native services. Mutations require explicit same-origin browser requests. */
    private static boolean dynamic(com.sun.net.httpserver.HttpExchange exchange,String file,String origin) throws IOException {
        boolean known=file.equals("engines.json")||file.equals("score-info.json")||file.equals("analysis")
                ||file.startsWith("audio/")||file.startsWith("practice/")||file.startsWith("takes")||file.startsWith("playback/")||file.equals("score/prepare");
        if(!known)return false;
        String requestOrigin=exchange.getRequestHeaders().getFirst("Origin");
        if(requestOrigin!=null&&!origin.equals(requestOrigin)){exchange.sendResponseHeaders(403,-1);return true;}
        boolean get="GET".equals(exchange.getRequestMethod());
        boolean read=file.equals("engines.json")||file.equals("score-info.json")||file.equals("audio/events")||file.equals("audio/devices")||file.equals("practice/state")||file.equals("playback/state")||file.equals("takes")||file.startsWith("takes/")&&!List.of("takes/open","takes/recheck","takes/remove","takes/restore").contains(file);
        if(get!=read||!get&&!"POST".equals(exchange.getRequestMethod())){exchange.sendResponseHeaders(405,-1);return true;}
        if(!get&&!origin.equals(requestOrigin)){exchange.sendResponseHeaders(403,-1);return true;}
        PracticeRuntime practice=runtime;Map<String,String> query=query(exchange.getRequestURI());
        try{
            if(file.equals("engines.json")){Map<String,Boolean> capabilities=LocalAudioAnalysis.capabilities();sendJson(exchange,Map.of("windows",System.getProperty("os.name").startsWith("Windows"),"nativeAudio",LocalAudioCapture.available(),"basicPitch",capabilities.getOrDefault("basic-pitch",false),"localPractice",true,"capabilities",capabilities,"recordedEngines",List.of("basic-pitch","pyin","crepe","aubio").stream().filter(name->capabilities.getOrDefault(name,false)).toList(),"baselines",List.of("parangonar","nakamura").stream().filter(name->capabilities.getOrDefault(name,false)).toList()));return true;}
            if(file.equals("score-info.json")){json(exchange,200,instrumentInfo);return true;}
            if(file.equals("practice/state")){sendJson(exchange,practice.liveSnapshot());return true;}
            if(file.equals("playback/state")){sendJson(exchange,practice.playbackState());return true;}
            if(file.equals("takes")){sendJson(exchange,practice.store().list());return true;}
            if(file.equals("takes/trash")){sendJson(exchange,practice.store().trash());return true;}
            if(file.equals("takes/report")){sendJson(exchange,practice.store().report(query.get("id")));return true;}
            if(file.equals("takes/plan")){sendJson(exchange,practice.store().timeline(query.get("id")));return true;}
            if(file.equals("takes/score")){binary(exchange,"application/xml",practice.store().score(query.get("id")),null);return true;}
            if(file.equals("takes/recording")){binary(exchange,"audio/wav",Files.readAllBytes(practice.store().recording(query.get("id"))),"NoteLite-recording.wav");return true;}
            if(file.equals("takes/package")){binary(exchange,"application/zip",practice.store().bundle(query.get("id")),"NoteLite-practice.zip");return true;}
            if(file.equals("audio/devices")){
                Path executable=LocalAudioCapture.executable();if(executable==null)throw new IOException("本地听音组件未安装。");
                Process child=new ProcessBuilder(executable.toString(),"--list-devices").redirectError(ProcessBuilder.Redirect.DISCARD).start();
                byte[] output=child.getInputStream().readNBytes(65537);if(!child.waitFor(8,java.util.concurrent.TimeUnit.SECONDS)){child.destroyForcibly();throw new IOException("设备查询超时。");}
                if(child.exitValue()!=0||output.length>65536)throw new IOException("无法读取音频设备。");
                Object devices=PracticeJson.parse(new String(output,StandardCharsets.UTF_8));sendJson(exchange,devices);return true;
            }
            if(file.equals("audio/events")){
                LocalAudioCapture capture=localAudio;if(capture==null){json(exchange,409,"{\"error\":\"尚未启动听音。\"}");return true;}
                exchange.getResponseHeaders().set("Content-Type","text/event-stream; charset=utf-8");exchange.getResponseHeaders().set("Cache-Control","no-store");exchange.sendResponseHeaders(200,0);
                while(!capture.ended()){String frame=capture.nextFrame();exchange.getResponseBody().write((frame==null?": keepalive\n\n":"data: "+frame+"\n\n").getBytes(StandardCharsets.UTF_8));exchange.getResponseBody().flush();}
                return true;
            }
            if(file.equals("audio/start")){
                double min=Double.parseDouble(query.getOrDefault("min","27.5")),max=Double.parseDouble(query.getOrDefault("max","4200")),a4=Double.parseDouble(query.getOrDefault("a4","440"));
                int window=Integer.parseInt(query.getOrDefault("window","4096")),device=Integer.parseInt(query.getOrDefault("device","-1"));
                boolean record=!"false".equals(query.get("record"));
                synchronized(PracticeStudio.class){if(localAudio!=null){LocalAudioCapture old=localAudio;localAudio=null;try{practice.keepCapture(old);}finally{old.close();}}LocalAudioCapture capture=new LocalAudioCapture();capture.listen(practice::nativeEvent);try{capture.start(min,max,window,record,a4,device);localAudio=capture;}catch(IOException ex){capture.close();throw ex;}}
                if(practice.inputReady())practice.playCountIn(PracticeWave.number(practice.snapshot().get("bpm"),100),-1);
                sendJson(exchange,Map.of("started",true));return true;
            }
            if(file.equals("audio/stop")){synchronized(PracticeStudio.class){practice.keepCapture(localAudio);}sendJson(exchange,Map.of("stopped",true));return true;}
            if(file.equals("audio/discard")){synchronized(PracticeStudio.class){if(localAudio!=null)localAudio.close();}sendJson(exchange,Map.of("discarded",true));return true;}
            if(file.equals("analysis")){
                Map<String,Object> options=query.containsKey("options")?PracticeJson.object(PracticeJson.parse(query.get("options"))):Map.of();byte[] wav;
                if("true".equals(query.get("recorded"))){synchronized(PracticeStudio.class){practice.keepCapture(localAudio);}wav=practice.capturedWav();}
                else{if(!"application/octet-stream".equals(exchange.getRequestHeaders().getFirst("Content-Type"))){exchange.sendResponseHeaders(415,-1);return true;}synchronized(PracticeStudio.class){practice.keepCapture(localAudio);}wav=exchange.getRequestBody().readNBytes(LocalAudioAnalysis.MAX_INPUT_BYTES+1);}
                sendJson(exchange,practice.analyze(wav,options));return true;
            }
            Map<String,Object> request=body(exchange);
            if(file.equals("score/prepare")){sendJson(exchange,practice.prepare(request));return true;}
            if(file.equals("practice/start")){practice.stopPlayback();Map<String,Object> snapshot=practice.start(request);if(!List.of("microphone","recording").contains(request.get("input"))&&String.valueOf(request.get("mode")).matches("tempo|strict"))practice.playCountIn(PracticeWave.number(request.get("bpm"),100),(int)PracticeWave.number(request.get("playbackDevice"),-1));sendJson(exchange,snapshot);return true;}
            if(file.equals("practice/event")){sendJson(exchange,practice.event(request));return true;}
            if(file.equals("practice/finish")){practice.stopPlayback();synchronized(PracticeStudio.class){practice.keepCapture(localAudio);}sendJson(exchange,practice.finish());return true;}
            if(file.startsWith("practice/")&&List.of("pause","resume","restart","skip").contains(file.substring(9))){String action=file.substring(9);if(action.equals("pause"))practice.stopPlayback();Map<String,Object> snapshot=practice.command(action,request);if(action.equals("resume")&&"strict".equals(snapshot.get("mode")))practice.resumeMetronome();sendJson(exchange,snapshot);return true;}
            if(file.equals("playback/reference")){sendJson(exchange,practice.playReference(request));return true;}
            if(file.equals("playback/stop")){practice.stopPlayback();sendJson(exchange,Map.of("playing",false));return true;}
            if(file.equals("playback/take")){sendJson(exchange,practice.replay(String.valueOf(request.get("id")),PracticeWave.number(request.get("startMs"),0),PracticeWave.number(request.get("endMs"),0),(int)PracticeWave.number(request.get("device"),-1)));return true;}
            if(file.equals("takes/open")){sendJson(exchange,practice.openTake(String.valueOf(request.get("id"))));return true;}
            if(file.equals("takes/recheck")){sendJson(exchange,practice.recheck(String.valueOf(request.get("id")),request));return true;}
            if(file.equals("takes/remove")){practice.store().remove(String.valueOf(request.get("id")));sendJson(exchange,Map.of("removed",true));return true;}
            if(file.equals("takes/restore")){practice.store().restore(String.valueOf(request.get("key")));sendJson(exchange,Map.of("restored",true));return true;}
            exchange.sendResponseHeaders(404,-1);
        }catch(InterruptedException ex){Thread.currentThread().interrupt();json(exchange,400,"{\"error\":\"本地操作已取消。\"}");}
        catch(Exception ex){json(exchange,400,"{\"error\":"+quote(ex.getMessage())+"}");}
        return true;
    }
    private static String instrumentInfo="{}";
    private static Map<String,Object> body(com.sun.net.httpserver.HttpExchange exchange) throws IOException {
        byte[] bytes=exchange.getRequestBody().readNBytes(20*1024*1024+1);if(bytes.length>20*1024*1024)throw new IOException("请求过大。");
        if(bytes.length==0)return Map.of();if(!String.valueOf(exchange.getRequestHeaders().getFirst("Content-Type")).startsWith("application/json"))throw new IOException("需要 JSON 请求。");
        return PracticeJson.object(PracticeJson.parse(new String(bytes,StandardCharsets.UTF_8)));
    }
    private static void sendJson(com.sun.net.httpserver.HttpExchange exchange,Object value) throws IOException{json(exchange,200,PracticeJson.stringify(value));}
    private static void binary(com.sun.net.httpserver.HttpExchange exchange,String type,byte[] bytes,String name) throws IOException {
        exchange.getResponseHeaders().set("Content-Type",type);exchange.getResponseHeaders().set("Cache-Control","no-store");exchange.getResponseHeaders().set("X-Content-Type-Options","nosniff");
        if(name!=null)exchange.getResponseHeaders().set("Content-Disposition","attachment; filename=\""+name+"\"");exchange.sendResponseHeaders(200,bytes.length);exchange.getResponseBody().write(bytes);
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
