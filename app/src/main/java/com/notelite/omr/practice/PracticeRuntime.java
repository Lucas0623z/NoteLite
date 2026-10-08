/* Copyright © NoteLite 2026. Licensed under the GNU Affero General Public License. */
package com.notelite.omr.practice;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.time.Instant;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Windows session coordinator: score preparation, clocks, common judge and persistent takes. */
final class PracticeRuntime {
    private byte[] xml;
    private Map<String,Object> metadata;
    private Map<String,Object> prepared=Map.of(),config=Map.of(),last=Map.of();
    private PracticeEngine engine;
    private final PracticeTakeStore store;
    private final LocalAudioPlayback playback=new LocalAudioPlayback();
    private final List<PracticeWave.Segment> segments=new ArrayList<>();
    private double captureEpoch,captureOffset,sessionEpoch;
    private int captureSerial;
    private String takeId,title="当前曲谱",createdAt;
    private byte[] importedRecording;
    private String recordingWarning;
    private double pausedAt=-1,pausedMilliseconds;
    PracticeRuntime(byte[] xml,String metadata) throws IOException {
        this.xml=xml.clone();this.metadata=PracticeJson.object(PracticeJson.parse(metadata));store=new PracticeTakeStore();
    }
    static double clock(){return System.nanoTime()/1_000_000.0;}
    synchronized Map<String,Object> prepare(Map<String,Object> request) throws IOException {
        if(engine!=null&&Boolean.TRUE.equals(engine.snapshot().get("active")))throw new IOException("请先结束当前练习。");
        if(request.get("xml") instanceof String source){if(source.getBytes(StandardCharsets.UTF_8).length>15*1024*1024)throw new IOException("乐谱不能超过 15 MB。");xml=source.getBytes(StandardCharsets.UTF_8);}
        if(request.get("metadata") instanceof Map<?,?> m)metadata=PracticeJson.object(m);
        if(request.get("title") instanceof String s)title=s;
        prepared=Map.of();engine=null;last=Map.of();takeId=null;segments.clear();importedRecording=null;
        // Partitura preparation also verifies navigation before the first input connects.
        Map<String,Object> options=new LinkedHashMap<>(request);options.remove("xml");options.put("metadata",metadata);
        prepared=PracticeJson.object(PracticeJson.parse(new String(LocalAudioAnalysis.normalize(xml,options),StandardCharsets.UTF_8)));
        return prepared;
    }
    synchronized Map<String,Object> start(Map<String,Object> request) throws IOException {
        if(!Boolean.TRUE.equals(request.get("verified")))throw new IOException("请先试听或校对乐谱，并勾选确认。");
        double bpm=PracticeWave.number(request.get("bpm"),100),a4=PracticeWave.number(request.get("a4"),440);
        if(bpm<30||bpm>240||a4<415||a4>466)throw new IOException("请使用 30–240 BPM，调音 A4 范围 415–466 Hz。");
        Map<String,Object> options=new LinkedHashMap<>(request);options.put("metadata",metadata);
        prepared=PracticeJson.object(PracticeJson.parse(new String(LocalAudioAnalysis.normalize(xml,options),StandardCharsets.UTF_8)));
        List<?> groups=groups(prepared);if(groups.isEmpty())throw new IOException("所选范围没有可练习的音符。");
        if(prepared.get("warnings") instanceof List<?> warnings&&!warnings.isEmpty())options.put("scoreWarnings",warnings);
        config=options;engine=new PracticeEngine(PracticeTimeline.fromGroups(groups,bpm),PracticeEngine.Config.fromMap(options));
        sessionEpoch=clock();createdAt=Instant.now().toString();takeId=null;segments.clear();importedRecording=null;captureOffset=0;
        if(String.valueOf(request.get("mode")).matches("tempo|strict"))engine.begin(sessionEpoch+4*60000/bpm);
        last=Map.of();recordingWarning=null;pausedAt=-1;pausedMilliseconds=0;return snapshot();
    }
    synchronized void captureReady(){captureSerial++;captureEpoch=clock();captureOffset=Math.max(0,captureEpoch-sessionEpoch);}
    synchronized boolean inputReady(){if(engine!=null&&!Boolean.TRUE.equals(engine.snapshot().get("paused"))&&String.valueOf(config.get("mode")).matches("tempo|strict")){engine.begin(clock()+4*60000/PracticeWave.number(config.get("bpm"),100));return true;}return false;}
    synchronized void nativeEvent(String line){
        try{Map<String,Object> event=PracticeJson.object(PracticeJson.parse(line));String type=String.valueOf(event.get("type"));
            if(type.equals("ready")){captureReady();return;}
            if(!List.of("note-on","note-off","note-update","uncertainty").contains(type)||engine==null)return;
            Map<String,Object> converted=new LinkedHashMap<>(event);converted.put("input","microphone");
            converted.put("id","capture"+captureSerial+":"+event.get("id"));
            for(String key:List.of("timeMs","onsetMs","offsetMs"))if(event.get(key) instanceof Number n)converted.put(key,captureEpoch+n.doubleValue());
            converted.put("recordingOnsetMs",captureOffset+PracticeWave.number(event.get("onsetMs"),0));
            engine.receive(converted);
        }catch(RuntimeException ignored){/* Malformed native events never advance the score. */}
    }
    void keepCapture(LocalAudioCapture capture) throws IOException {
        if(capture==null)return;capture.stop();try{capture.checkFailure();}catch(IOException ex){synchronized(this){recordingWarning=ex.getMessage();}}
        byte[] wav;try{wav=Files.readAllBytes(capture.recording());}catch(IOException ex){if(capture.hasRecording())synchronized(this){recordingWarning="录音读取失败："+ex.getMessage();}return;}
        synchronized(this){segments.add(new PracticeWave.Segment(wav,captureOffset));}
        capture.deleteRecording();
    }
    synchronized Map<String,Object> event(Map<String,Object> request) throws IOException {
        requireEngine();Map<String,Object> event=new LinkedHashMap<>(request);
        // Browser delivers MIDI/keyboard events only; the server owns the practice clock.
        double time=clock();double delay=PracticeWave.number(request.get("delayMs"),0);time-=Math.max(0,Math.min(500,delay));
        event.put("timeMs",time);if("note-on".equals(event.get("type")))event.put("onsetMs",time);
        event.put("confidence",1);event.put("voiced",!"note-off".equals(event.get("type")));
        engine.receive(event);return liveSnapshot();
    }
    synchronized Map<String,Object> command(String action,Map<String,Object> request) throws IOException {
        requireEngine();switch(action){
            case "pause"->{double now=clock();engine.pause(now);if(pausedAt<0)pausedAt=now;}case "resume"->{double now=clock();engine.resume(now);if(pausedAt>=0){pausedMilliseconds+=now-pausedAt;pausedAt=-1;}}
            case "restart"->engine.restart((int)PracticeWave.number(request.get("index"),0),clock());
            case "skip"->{Map<String,Object> snap=engine.snapshot();int next=(int)PracticeWave.number(snap.get("currentIndex"),0)+1;if(next<groups(prepared).size())engine.restart(next,clock());else engine.finish();}
            default->throw new IOException("练习操作无效。");}
        return snapshot();
    }
    synchronized Map<String,Object> snapshot(){
        if(engine==null)return last;
        engine.tick(clock());return enrich(engine.snapshot());
    }
    synchronized Map<String,Object> liveSnapshot(){if(engine==null)return last;engine.tick(clock());return enrich(engine.liveSnapshot());}
    private Map<String,Object> enrich(Map<String,Object> source){
        Map<String,Object> snapshot=new LinkedHashMap<>(source);
        snapshot.put("title",title);snapshot.put("createdAt",createdAt);snapshot.put("durationSeconds",Math.max(0,((pausedAt>=0?pausedAt:clock())-sessionEpoch-pausedMilliseconds)/1000));
        snapshot.put("metadata",config);snapshot.put("input",config.getOrDefault("input","keyboard"));snapshot.put("engine",config.getOrDefault("input","keyboard").equals("microphone")?"native-mpm-yin":"local-events");
        snapshot.put("scope",Map.of("part",config.getOrDefault("part","all"),"from",config.getOrDefault("from",1),"to",config.getOrDefault("to",1)));
        snapshot.put("completed",PracticeWave.number(snapshot.get("currentIndex"),0)>=PracticeWave.number(snapshot.get("total"),1)&&!Boolean.TRUE.equals(snapshot.get("active")));
        if(takeId!=null)snapshot.put("takeId",takeId);snapshot.put("hasRecording",!segments.isEmpty()||importedRecording!=null);
        return snapshot;
    }
    synchronized Map<String,Object> finish() throws IOException {
        if(engine==null)return last;engine.finish();Map<String,Object> snapshot=snapshot();
        byte[] wav=null;
        try{wav=importedRecording!=null?importedRecording:PracticeWave.join(segments);}
        catch(IOException ex){recordingWarning=ex.getMessage();if(takeId==null)takeId=java.util.UUID.randomUUID().toString();snapshot.put("recoveryRecordings",store.saveRecoveryRecordings(takeId,segments));}
        if(recordingWarning!=null)snapshot.put("warning","练习报告已保存；录音需要复核。"+recordingWarning+(snapshot.containsKey("recoveryRecordings")?" 原始片段随练习包保留。":""));
        Map<String,Object> result=store.save(takeId,xml,packageData(),withReplayPositions(snapshot),wav);takeId=String.valueOf(result.get("takeId"));last=result;engine=null;return result;
    }
    synchronized Map<String,Object> analyze(byte[] wav,Map<String,Object> request) throws IOException {
        return analyze(wav,request,false);
    }
    private Map<String,Object> analyze(byte[] wav,Map<String,Object> request,boolean rechecking) throws IOException {
        LocalAudioAnalysis.validateWav(wav);if(engine!=null)engine.finish();
        Map<String,Object> options=new LinkedHashMap<>(request);options.put("metadata",metadata);
        prepared=PracticeJson.object(PracticeJson.parse(new String(LocalAudioAnalysis.normalize(xml,options),StandardCharsets.UTF_8)));
        List<?> groups=groups(prepared);if(groups.isEmpty())throw new IOException("所选范围没有可练习的音符。");
        if(!"basic-pitch".equals(options.getOrDefault("engine","basic-pitch"))&&polyphonic(groups))throw new IOException("所选声部含和弦或重叠音，请选择“单音与和弦”检测，或只练单音声部。");
        config=options;engine=null;importedRecording=wav;segments.clear();
        if(!rechecking){
            takeId=null;
            Map<String,Object> pending=new LinkedHashMap<>(RecordedAlignment.analyze(PracticeTimeline.fromGroups(groups,PracticeWave.number(options.get("bpm"),100)),PracticeEngine.Config.fromMap(options),Map.of("notes",List.of())));
            pending.put("title",title);pending.put("createdAt",Instant.now().toString());pending.put("input","recording");pending.put("metadata",options);pending.put("engine",options.getOrDefault("engine","basic-pitch"));pending.put("completed",false);
            PracticeWave.Pcm pcm=PracticeWave.pcm(wav);pending.put("durationSeconds",pcm.data().length/(double)(pcm.rate()*pcm.channels()*2));pending.put("scope",Map.of("part",options.getOrDefault("part","all"),"from",options.getOrDefault("from",1),"to",options.getOrDefault("to",1)));
            pending.put("analysisPending",true);pending.put("warning","录音已保存；录后复核尚未完成，可在本机记录中重新复核。");
            last=store.save(null,xml,packageData(),withReplayPositions(pending),wav);takeId=String.valueOf(last.get("takeId"));
        }
        Map<String,Object> transcription=PracticeJson.object(PracticeJson.parse(new String(LocalAudioAnalysis.analyze(wav,options),StandardCharsets.UTF_8)));
        List<?> notes=transcription.get("notes") instanceof List<?> n?n:List.of();
        // Even a silent take is retained with an explicit unjudged report, never invented success.
        Map<String,Object> judgeOptions=new LinkedHashMap<>(options);if("wait".equals(options.get("mode")))judgeOptions.put("mode","free");
        double bpm=PracticeWave.number(options.get("bpm"),100);
        Map<String,Object> judged=new LinkedHashMap<>(RecordedAlignment.analyze(PracticeTimeline.fromGroups(groups,bpm),PracticeEngine.Config.fromMap(judgeOptions),transcription));
        String baseline=String.valueOf(options.getOrDefault("baseline","parangonar"));
        if(!notes.isEmpty())judged.put("baseline",PracticeJson.parse(new String(LocalAudioAnalysis.align(prepared,notes,Map.of("backend",baseline)),StandardCharsets.UTF_8)));
        judged.put("transcription",transcription);judged.put("engine",transcription.getOrDefault("engine","recorded"));
        judged.put("title",title);judged.put("createdAt",Instant.now().toString());judged.put("durationSeconds",transcription.getOrDefault("seconds",0));
        judged.put("metadata",options);judged.put("input","recording");judged.put("scope",Map.of("part",options.getOrDefault("part","all"),"from",options.getOrDefault("from",1),"to",options.getOrDefault("to",1)));
        judged.put("completed",!notes.isEmpty()&&PracticeWave.number(judged.get("currentIndex"),0)>=groups.size());
        if(notes.isEmpty())judged.put("warning","没有检测到可靠音符；录音已保存，请回听、检查输入设备后重录。");
        Map<String,Object> result=store.save(takeId,xml,packageData(),withReplayPositions(judged),wav);takeId=String.valueOf(result.get("takeId"));last=result;return result;
    }
    synchronized byte[] capturedWav() throws IOException {
        try{byte[] wav=PracticeWave.join(segments);if(wav==null)throw new IOException("没有本地录音。");return wav;}
        catch(IOException ex){
            // Recorded review joins before analysis can save its pending take.
            // Preserve this take before a subsequent start clears the segments.
            if(!segments.isEmpty()){
                if(engine!=null)finish();
                else{
                    if(takeId==null)takeId=java.util.UUID.randomUUID().toString();
                    Map<String,Object> saved=new LinkedHashMap<>(last);
                    saved.put("recoveryRecordings",store.saveRecoveryRecordings(takeId,segments));
                    saved.put("warning","录音未能合成为完整文件，原始片段已随练习包保留。"+ex.getMessage());
                    saved.putIfAbsent("title",title);saved.putIfAbsent("createdAt",createdAt==null?Instant.now().toString():createdAt);saved.putIfAbsent("metadata",config);saved.putIfAbsent("completed",false);
                    last=store.save(takeId,xml,packageData(),saved,null);
                }
            }
            throw ex;
        }
    }
    synchronized Map<String,Object> recheck(String id,Map<String,Object> request) throws IOException {
        xml=store.score(id);var pack=store.timeline(id);metadata=pack.get("omrMetadata") instanceof Map<?,?> m?PracticeJson.object(m):Map.of();
        var previous=store.report(id);Map<String,Object> options=new LinkedHashMap<>(previous.get("metadata") instanceof Map<?,?> m?PracticeJson.object(m):Map.of());options.putAll(request);title=String.valueOf(previous.getOrDefault("title","当前曲谱"));takeId=id;
        return analyze(Files.readAllBytes(store.recording(id)),options,true);
    }
    synchronized Map<String,Object> openTake(String id) throws IOException {last=store.report(id);xml=store.score(id);prepared=store.timeline(id);metadata=prepared.get("omrMetadata") instanceof Map<?,?> m?PracticeJson.object(m):Map.of();config=last.get("metadata") instanceof Map<?,?> m?PracticeJson.object(m):Map.of();sessionEpoch=0;segments.clear();importedRecording=null;takeId=id;engine=null;title=String.valueOf(last.getOrDefault("title","当前曲谱"));return last;}
    synchronized Map<String,Object> playReference(Map<String,Object> request) throws IOException {
        Map<String,Object> options=new LinkedHashMap<>(request);options.put("metadata",metadata);
        Map<String,Object> normalized=PracticeJson.object(PracticeJson.parse(new String(LocalAudioAnalysis.normalize(xml,options),StandardCharsets.UTF_8)));
        playback.play(PracticeWave.reference(groups(normalized),PracticeWave.number(request.get("bpm"),100),PracticeWave.number(request.get("a4"),440),0),(int)PracticeWave.number(request.get("playbackDevice"),-1));return playback.state();
    }
    void playCountIn(double bpm,int device) throws IOException {playback.metronome(bpm,device>=0?device:(int)PracticeWave.number(config.get("playbackDevice"),-1));synchronized(this){if(engine!=null)engine.begin(playback.readyEpoch()+4*60000/bpm);}}
    synchronized void resumeMetronome() throws IOException {double bpm=PracticeWave.number(config.get("bpm"),100),beat=60000/bpm;double before=clock(),origin=engine==null?before:PracticeWave.number(PracticeJson.object(engine.liveSnapshot().get("alignment")).get("offsetMs"),before);double phase=((before-origin)%beat+beat)%beat;playback.metronome(bpm,(int)PracticeWave.number(config.get("playbackDevice"),-1),phase);if(engine!=null)engine.shiftClock(Math.max(0,playback.readyEpoch()-before));}
    Map<String,Object> playbackState(){return playback.state();}
    Map<String,Object> replay(String id,double start,double end,int device) throws IOException {playback.play(store.recording(id),start,end,device);return playback.state();}
    void stopPlayback(){playback.stop();}
    PracticeTakeStore store(){return store;}
    void close(){playback.close();}
    private Map<String,Object> packageData(){Map<String,Object> pack=new LinkedHashMap<>(prepared);pack.put("schemaVersion",1);pack.put("format","notelite-practice-package");pack.put("omrMetadata",metadata);pack.put("selection",config);pack.put("scoreSha256",digest(xml));return pack;}
    private Map<String,Object> withReplayPositions(Map<String,Object> snapshot){
        Map<String,Object> result=new LinkedHashMap<>(snapshot);List<Map<String,Object>> errors=new ArrayList<>();
        List<Map<String,Object>> playedEvents=new ArrayList<>();
        for(Object sound:(List<?>)snapshot.getOrDefault("played",List.of())){Map<String,Object> played=new LinkedHashMap<>(PracticeJson.object(sound));double time=PracticeWave.number(played.get("time"),0);played.put("replayMs",Math.max(0,time>sessionEpoch&&sessionEpoch>0?time-sessionEpoch:time));playedEvents.add(played);}
        result.put("played",playedEvents);
        for(Object object:(List<?>)snapshot.getOrDefault("errors",List.of())){Map<String,Object> error=new LinkedHashMap<>(PracticeJson.object(object));
            double replay=PracticeWave.number(error.get("expectedTimeMs"),0);if(replay>sessionEpoch&&sessionEpoch>0)replay-=sessionEpoch;Object eventId=error.get("eventId");
            for(Object sound:(List<?>)snapshot.getOrDefault("played",List.of())){Map<String,Object> played=PracticeJson.object(sound);if(eventId!=null&&eventId.equals(played.get("id"))||eventId==null&&error.get("index")!=null&&error.get("index").equals(played.get("index"))){replay=PracticeWave.number(played.get("time"),0);if(replay>sessionEpoch&&sessionEpoch>0)replay-=sessionEpoch;break;}}
            if(replay==0&&error.get("index") instanceof Number i&&i.intValue()<groups(prepared).size()){
                int target=i.intValue();double bpm=PracticeWave.number(config.get("bpm"),100),base=PracticeWave.number(PracticeJson.object(groups(prepared).getFirst()).get("onset"),0);
                double scoreTime=(PracticeWave.number(PracticeJson.object(groups(prepared).get(target)).get("onset"),0)-base)*60000/bpm;
                Map<String,Object> previous=null,next=null;
                for(Map<String,Object> played:playedEvents){int index=(int)PracticeWave.number(played.get("index"),0);if(index<=target&&(previous==null||index>(int)PracticeWave.number(previous.get("index"),0)))previous=played;if(index>=target&&(next==null||index<(int)PracticeWave.number(next.get("index"),0)))next=played;}
                if(previous!=null){int pi=(int)PracticeWave.number(previous.get("index"),0);double pscore=(PracticeWave.number(PracticeJson.object(groups(prepared).get(pi)).get("onset"),0)-base)*60000/bpm;replay=PracticeWave.number(previous.get("replayMs"),0)+scoreTime-pscore;
                    if(next!=null){int ni=(int)PracticeWave.number(next.get("index"),0);double nscore=(PracticeWave.number(PracticeJson.object(groups(prepared).get(ni)).get("onset"),0)-base)*60000/bpm;if(nscore>pscore)replay=PracticeWave.number(previous.get("replayMs"),0)+(scoreTime-pscore)/(nscore-pscore)*(PracticeWave.number(next.get("replayMs"),0)-PracticeWave.number(previous.get("replayMs"),0));}}
                else if(next!=null){int ni=(int)PracticeWave.number(next.get("index"),0);double nscore=(PracticeWave.number(PracticeJson.object(groups(prepared).get(ni)).get("onset"),0)-base)*60000/bpm;replay=PracticeWave.number(next.get("replayMs"),0)+scoreTime-nscore;}else replay=scoreTime;
            }
            error.put("replayMs",Math.max(0,replay));errors.add(error);
        }
        result.put("errors",errors);return result;
    }
    private void requireEngine() throws IOException {if(engine==null)throw new IOException("尚未启动练习。");}
    private static List<?> groups(Map<String,Object> normalized){return normalized.get("groups") instanceof List<?> list?list:List.of();}
    private static boolean polyphonic(List<?> groups){double previousEnd=-1;for(Object item:groups){Map<String,Object> group=PracticeJson.object(item);List<?> notes=(List<?>)group.getOrDefault("notes",List.of());double onset=PracticeWave.number(group.get("onset"),0);if(notes.stream().map(n->PracticeJson.object(n).get("midi")).distinct().count()>1||onset<previousEnd-.0001)return true;for(Object note:notes){Map<String,Object> n=PracticeJson.object(note);previousEnd=Math.max(previousEnd,PracticeWave.number(n.get("onset"),onset)+PracticeWave.number(n.get("duration"),0));}}return false;}
    private static String digest(byte[] bytes){try{return java.util.HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));}catch(Exception ex){throw new IllegalStateException(ex);}}
}
