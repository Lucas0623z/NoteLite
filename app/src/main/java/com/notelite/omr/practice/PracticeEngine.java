/* Copyright © NoteLite 2026. GNU Affero General Public License, version 3 or later. */
package com.notelite.omr.practice;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** One local teaching policy for MIDI, keyboard, acoustic input and completed takes. */
public final class PracticeEngine {
    public record Config(String mode, double bpm, double toleranceMs, double confidenceThreshold,
                         double intonationToleranceCents, boolean gradeDuration, boolean autoReposition,
                         double restartSilenceMs, Double startTimeMs, String feedbackPolicy) {
        public Config {
            mode = switch(mode == null ? "free" : mode) { case "tempo", "fixed", "strict" -> "strict"; case "wait" -> "wait"; case "follow", "free" -> "free"; default -> throw new IllegalArgumentException("练习模式无效。"); };
            feedbackPolicy=feedbackPolicy==null?"active":feedbackPolicy;
            if(!List.of("active","conservative").contains(feedbackPolicy))throw new IllegalArgumentException("反馈方式无效。");
            if (!Double.isFinite(bpm) || bpm < 20 || bpm > 400 || !Double.isFinite(toleranceMs) || toleranceMs < 0 || toleranceMs > 2000
                    || !Double.isFinite(confidenceThreshold) || confidenceThreshold < 0 || confidenceThreshold > 1
                    || !Double.isFinite(intonationToleranceCents) || intonationToleranceCents < 0 || intonationToleranceCents > 100
                    || !Double.isFinite(restartSilenceMs) || restartSilenceMs < 300 || restartSilenceMs > 10000
                    || startTimeMs != null && !Double.isFinite(startTimeMs)) throw new IllegalArgumentException("练习判断参数无效。");
        }
        public static Config fromMap(Map<?,?> m) {
            return new Config(PracticeTimeline.string(m,"mode","free"), PracticeTimeline.number(m,"bpm",100),
                    PracticeTimeline.number(m,"toleranceMs",180),PracticeTimeline.number(m,"confidenceThreshold",.4),
                    PracticeTimeline.number(m,"intonationToleranceCents",35), !Boolean.FALSE.equals(m.get("gradeDuration")),
                    !Boolean.FALSE.equals(m.get("autoReposition")),PracticeTimeline.number(m,"restartSilenceMs",1600),
                    m.get("startTimeMs") instanceof Number n ? n.doubleValue() : null,PracticeTimeline.string(m,"feedbackPolicy","active"));
        }
    }
    private record Attack(String id, int group, int midi, double onset, double confidence, Map<String,Object> played) {}
    private record Pending(int index, Map<String,Object> event) {}
    private final PracticeTimeline timeline;
    private final Config config;
    private final Map<Integer,Map<String,Object>> results = new LinkedHashMap<>();
    private final List<Map<String,Object>> errors = new ArrayList<>(), played = new ArrayList<>(), unjudged = new ArrayList<>(), eventLog = new ArrayList<>();
    private final Map<String,Attack> attacks = new HashMap<>();
    private final Set<String> sounding = new HashSet<>(), errorKeys = new HashSet<>();
    private final Map<String,Map<String,Object>> uncertain = new LinkedHashMap<>();
    private final Map<String,Map<String,Object>> released = new HashMap<>();
    private final Map<String,List<Double>> centsSamples = new HashMap<>();
    private final Set<Integer> matched = new LinkedHashSet<>();
    private int index, serial, attempt;
    private boolean active = true, paused;
    private Double startedAt, pausedAt;
    private double lastAttack = Double.NaN, lastMatchedTime = Double.NaN, lastMatchedScore = Double.NaN, localBpm;
    private Pending pending;
    private String alignment = "live";
    private Double detectorMinMidi, detectorMaxMidi;
    private boolean noReliableRecordingEvidence;
    private Map<Integer,Double> recordedExpectedTimes=Map.of();

    public PracticeEngine(PracticeTimeline timeline, Config config) {
        this.timeline=timeline; this.config=config; this.startedAt=config.startTimeMs; this.localBpm=config.bpm;
    }
    public synchronized void begin(double timeMs) { finite(timeMs); startedAt=timeMs; }
    /** Compensate measured native playback startup without re-counting the pause. */
    public synchronized void shiftClock(double delayMs) {finite(delayMs);if(delayMs<0)throw new IllegalArgumentException("音频启动延迟无效。");if(startedAt!=null)startedAt+=delayMs;}
    public synchronized void pause(double timeMs) { finite(timeMs); if(active&&!paused){paused=true;pausedAt=timeMs;sounding.clear();pending=null;for(Map<String,Object> e:uncertain.values())if(e.get("offsetMs")==null)e.put("offsetMs",timeMs);} }
    public synchronized void resume(double timeMs) {
        finite(timeMs); if(!paused)return;
        if(startedAt!=null)startedAt+=Math.max(0,timeMs-pausedAt); paused=false;pausedAt=null;
        lastAttack=Double.NaN; lastMatchedTime=Double.NaN;
    }
    public synchronized void restart(int position, double timeMs) {
        finite(timeMs); if(position<0||position>=timeline.groups().size())throw new IllegalArgumentException("练习位置无效。");
        reposition(position); active=true;paused=false;pausedAt=null;startedAt=timeMs-timeline.groups().get(position).onsetMs();lastAttack=Double.NaN;lastMatchedTime=Double.NaN;
    }
    private PracticeTimeline.Group current(){return index<timeline.groups().size()?timeline.groups().get(index):null;}
    private double due(PracticeTimeline.Group g){return startedAt+g.onsetMs();}
    private Double expectedTime(PracticeTimeline.Group g){
        if(config.mode.equals("free")&&!alignment.equals("live")&&recordedExpectedTimes.containsKey(g.index()))return recordedExpectedTimes.get(g.index());
        return startedAt==null?null:due(g);
    }
    public synchronized Map<String,Object> note(Map<?,?> raw) { receive(raw); return snapshot(); }
    /** Feed native/recorded events without repeatedly allocating an entire take snapshot. */
    public synchronized void receive(Map<?,?> raw) {
        Map<String,Object> event = canonical(raw); eventLog.add(event);
        String type=(String)event.get("type"); double time=(double)event.get("timeMs");
        // A completed recording still contains audible evidence after the last
        // release. Live sessions retain their automatic end/save boundary.
        boolean recordedTail=current()==null&&!alignment.equals("live");
        if(type.equals("uncertainty")){if((active||recordedTail)&&!paused){event.put("index",index);uncertain.put((String)event.get("id"),event);unjudged.add(event);}return;}
        if(type.equals("note-update")){noteUpdate(event);return;}
        if(type.equals("note-off")){released.put((String)event.get("id"),event);noteOff(event);return;}
        if(!type.equals("note-on"))throw new IllegalArgumentException("输入音符事件类型无效。");
        if(!active&&!recordedTail||paused)return;
        if(config.mode.equals("strict")&&startedAt!=null&&time<startedAt&&alignment.equals("live"))return;
        if(!(event.get("midi") instanceof Integer midi))throw new IllegalArgumentException("输入音高无效。");
        double confidence=(double)event.get("confidence");
        tick(time);
        if(confidence<config.confidenceThreshold || Boolean.FALSE.equals(event.get("voiced"))||Boolean.TRUE.equals(event.get("reviewRequired"))||Boolean.FALSE.equals(event.get("onsetReliable"))){
            event.put("index",index);uncertain.put((String)event.get("id"),event);unjudged.add(event);
            if(current()!=null&&config.feedbackPolicy.equals("active")&&confidence>=.25&&!Boolean.FALSE.equals(event.get("voiced")))
                error("uncertain",current(),fields("expected",current().pitches(),"played",midi,"confidence",confidence,"eventId",event.get("id"),"pendingReview",true,"resolved",false,"reason",event.getOrDefault("reason","uncertain-note-evidence")));
            return;
        }
        String id=(String)event.get("id"); if(sounding.contains(id))return;
        sounding.add(id);
        if(startedAt==null)startedAt=time-(current()==null?0:current().onsetMs());
        tick(time);
        if(!active&&!recordedTail)return;
        if(current()==null){PracticeTimeline.Group last=timeline.groups().getLast();
            played.add(fields("id",id,"midi",midi,"time",time,"cents",event.get("cents"),"confidence",confidence,"index",last.index(),"attempt",attempt));
            error("extra",last,fields("played",midi,"delta",time-due(last),"expected",List.of(),"eventId",id));return;}
        if(config.mode.equals("strict")&&time<startedAt){played.add(fields("id",id,"midi",midi,"time",time,"cents",event.get("cents"),"confidence",confidence,"index",index,"attempt",attempt));
            error("extra",current(),fields("played",midi,"delta",time-due(current()),"expected",List.of(),"eventId",id));return;}
        boolean stopped=Double.isFinite(lastAttack)&&time-lastAttack>=config.restartSilenceMs;
        lastAttack=time;
        if(!config.mode.equals("strict")&&config.autoReposition&&stopped&&!current().pitches().contains(midi)) {
            int target=nearest(midi,index); if(target>=0){skipForwardOrRewind(target);pending=null;}
        }
        if(pending!=null){
            Pending p=pending;pending=null;
            if(p.index+1<timeline.groups().size()&&timeline.groups().get(p.index+1).pitches().contains(midi)){
                skipForwardOrRewind(p.index); accept(p.event); accept(event); return;
            }
            wrong(p.event);
        }
        if(!current().pitches().contains(midi)&&config.mode.equals("free")&&config.autoReposition) {
            int target=nearest(midi,index); if(target>=0&&target!=index){pending=new Pending(target,event);return;}
        }
        accept(event); return;
    }
    private int nearest(int midi,int position){
        int best=-1,distance=Integer.MAX_VALUE;
        for(int i=Math.max(0,position-16);i<Math.min(timeline.groups().size(),position+17);i++){
            if(timeline.groups().get(i).pitches().contains(midi)&&Math.abs(i-position)<distance){best=i;distance=Math.abs(i-position);}
        }
        return best;
    }
    private void skipForwardOrRewind(int position){
        if(position<index)reposition(position);
        else while(index<position&&current()!=null)advance(true);
    }
    private void reposition(int position){
        index=position;matched.clear();pending=null;results.keySet().removeIf(i->i>=position);attacks.clear();sounding.clear();attempt++;active=true;lastMatchedTime=Double.NaN;
    }
    private void accept(Map<String,Object> event){
        if(current()==null)return;
        int midi=(int)event.get("midi"); double time=(double)event.get("timeMs"), cents=(double)event.get("cents");
        PracticeTimeline.Group g=current();
        if(!g.pitches().contains(midi)){wrong(event);return;}
        if(matched.contains(midi))return;
        double delta=time-due(g);
        if(config.mode.equals("strict")&&delta < -Math.max(300,config.toleranceMs)){error("extra",g,fields("played",midi,"delta",delta,"eventId",event.get("id")));return;}
        matched.add(midi);
        for(Map<String,Object> error:errors)if((int)error.get("index")==g.index()&&error.get("kind").equals("uncertain")&&Boolean.TRUE.equals(error.get("pendingReview")))error.put("resolved",true);
        Map<String,Object> sound=fields("id",event.get("id"),"midi",midi,"time",time,"cents",cents,"confidence",event.get("confidence"),"index",g.index(),"attempt",attempt,
                "sourceNoteIds",g.notes().stream().filter(n->n.midi()==midi).map(PracticeTimeline.Note::sourceNoteId).toList(),
                "occurrenceIds",g.notes().stream().filter(n->n.midi()==midi).map(PracticeTimeline.Note::occurrenceId).toList());
        if(event.get("intonationEvidence") instanceof Map<?,?> evidence)sound.put("intonationEvidence",evidence);
        if(event.get("recordedNote") instanceof Map<?,?> original)sound.put("recordedNote",original);
        played.add(sound);attacks.put((String)event.get("id"),new Attack((String)event.get("id"),g.index(),midi,time,(double)event.get("confidence"),sound));
        sounding.add((String)event.get("id"));
        centsSamples.put((String)event.get("id"),new ArrayList<>(List.of(cents)));
        if(Math.abs(cents)>config.intonationToleranceCents&&config.feedbackPolicy.equals("active"))
            error("uncertain",g,fields("expected",List.of(midi),"played",midi,"cents",cents,"eventId",event.get("id"),"pendingReview",true,"resolved",false,"reason","intonation-candidate"));
        if(config.mode.equals("strict")&&Math.abs(delta)>config.toleranceMs)error(delta<0?"early":"late",g,fields("played",midi,"delta",delta,"eventId",event.get("id")));
        if(matched.containsAll(g.pitches())){
            if(!config.mode.equals("strict")&&Double.isFinite(lastMatchedTime)&&time>lastMatchedTime&&g.onsetMs()>lastMatchedScore)
                localBpm=.7*localBpm+.3*Math.max(20,Math.min(400,config.bpm*(g.onsetMs()-lastMatchedScore)/(time-lastMatchedTime)));
            lastMatchedTime=time;lastMatchedScore=g.onsetMs();advance(false);
        }
        Map<String,Object> release=released.get((String)event.get("id"));if(release!=null){if((double)release.get("timeMs")>=time)noteOff(release);else released.remove((String)event.get("id"));}
    }
    private void wrong(Map<String,Object> event){
        if(current()==null)return;
        int midi=(int)event.get("midi");
        List<Integer> remaining=current().pitches().stream().filter(p->!matched.contains(p)).toList();
        Integer target=remaining.stream().min(java.util.Comparator.comparingInt((Integer p)->Math.floorMod(p-midi,12)==0?0:1)
                .thenComparingInt(p->Math.abs(p-midi)).thenComparingInt(p->p)).orElse(null);
        Map<String,Object> sound=fields("id",event.get("id"),"midi",midi,"time",event.get("timeMs"),"cents",event.get("cents"),"confidence",event.get("confidence"),"index",index,"attempt",attempt);
        played.add(sound);
        Map<String,Object> feedback=fields("played",midi,"expected",target==null?List.of():List.of(target),"remainingExpected",remaining,"eventId",event.get("id"),"confidence",event.get("confidence"));
        // Associate the substitution at the attack, before any later correction.
        // A corrected wrong C must never suppress a still-missing E in a chord.
        if(target!=null&&config.mode.equals("strict")&&Math.abs((double)event.get("timeMs")-due(current()))<=Math.max(300,config.toleranceMs))feedback.put("substitutedPitch",target);
        error("wrong",current(),feedback);
    }
    private void noteOff(Map<String,Object> event){
        Map<String,Object> weak=uncertain.get((String)event.get("id"));
        if(weak!=null){weak.put("offsetMs",event.get("timeMs"));weak.put("durationMs",Math.max(0,(double)event.get("timeMs")-(double)weak.get("onsetMs")));}
        String id=(String)event.get("id"); Attack attack=attacks.get(id);
        if(attack==null&&event.get("midi") instanceof Integer pitch)attack=attacks.values().stream().filter(a->a.midi==pitch&&sounding.contains(a.id)).max(java.util.Comparator.comparingDouble(Attack::onset)).orElse(null);
        sounding.remove(id); if(attack==null)return;sounding.remove(attack.id);attacks.remove(attack.id);
        if(current()==null&&attacks.isEmpty())active=false;
        double duration=PracticeTimeline.number(event,"durationMs",0);
        if(duration<=0)duration=Math.max(0,(double)event.get("timeMs")-attack.onset);
        attack.played.put("duration",duration);
        judgeIntonation(attack,true);
        if(paused||!config.gradeDuration||!config.mode.equals("strict"))return;
        PracticeTimeline.Group g=timeline.groups().get(attack.group);
        int pitch=attack.midi;
        double expected=g.notes().stream().filter(n->n.midi()==pitch).mapToDouble(PracticeTimeline.Note::durationMs).max().orElse(0);
        double shortAllowance=Math.max(120,expected*.35),longAllowance=Math.max(180,expected*.6);
        if(expected>=240&&(duration<expected-shortAllowance||duration>expected+longAllowance))
            error(duration<expected?"short":"long",g,fields("played",attack.midi,"durationMs",duration,"expectedDurationMs",expected,"eventId",attack.id));
    }
    private void noteUpdate(Map<String,Object> event){
        Attack attack=attacks.get((String)event.get("id"));if(attack==null||paused)return;
        if((double)event.get("confidence")<config.confidenceThreshold||Boolean.FALSE.equals(event.get("voiced"))){unjudged.add(event);return;}
        if(event.get("midi") instanceof Integer midi&&midi!=attack.midi){unjudged.add(event);return;}
        List<Double> samples=centsSamples.computeIfAbsent(attack.id,k->new ArrayList<>());
        samples.add((double)event.get("cents"));if(samples.size()>7)samples.removeFirst();
        attack.played.put("duration",Math.max(0,(double)event.get("timeMs")-attack.onset));
        judgeIntonation(attack,false);
    }
    private void judgeIntonation(Attack attack,boolean finalSample){
        if(finalSample&&attack.played.get("intonationEvidence") instanceof Map<?,?> evidence&&Boolean.TRUE.equals(evidence.get("reliable"))){
            double median=PracticeTimeline.number(evidence,"cents",Double.NaN),confidence=PracticeTimeline.number(evidence,"confidence",0);
            if(Double.isFinite(median)&&confidence>=config.confidenceThreshold){
                attack.played.put("cents",median);attack.played.put("intonationJudgmentSource","recorded-aggregate");
                if(Math.abs(median)>config.intonationToleranceCents)error("intonation",timeline.groups().get(attack.group),fields("played",attack.midi,"cents",median,"eventId",attack.id,"evidence",evidence));
                for(Map<String,Object> e:errors)if(e.get("kind").equals("uncertain")&&attack.id.equals(e.get("eventId"))&&"intonation-candidate".equals(e.get("reason")))e.put("resolved",true);
                centsSamples.remove(attack.id);return;
            }
        }
        List<Double> samples=centsSamples.get(attack.id);if(samples==null||samples.size()<3)return;
        List<Double> ordered=samples.stream().sorted().toList();double median=ordered.get(ordered.size()/2);
        attack.played.put("cents",median);attack.played.put("intonationSampleCount",samples.size());
        long stable=samples.stream().filter(c->Math.abs(c)>config.intonationToleranceCents&&Math.signum(c)==Math.signum(median)).count();
        if(Math.abs(median)>config.intonationToleranceCents&&stable>=3)
            error("intonation",timeline.groups().get(attack.group),fields("played",attack.midi,"cents",median,"eventId",attack.id,"sampleCount",samples.size()));
        if(finalSample||Math.abs(median)<=config.intonationToleranceCents)for(Map<String,Object> e:errors)
            if(e.get("kind").equals("uncertain")&&attack.id.equals(e.get("eventId"))&&"intonation-candidate".equals(e.get("reason")))e.put("resolved",true);
        if(finalSample)centsSamples.remove(attack.id);
    }
    public synchronized void tick(double timeMs){
        finite(timeMs); if(!active||paused||!config.mode.equals("strict")||startedAt==null)return;
        while(current()!=null){
            PracticeTimeline.Group g=current();double gap=index+1<timeline.groups().size()?timeline.groups().get(index+1).onsetMs()-g.onsetMs():Double.POSITIVE_INFINITY;
            double deadline=due(g)+Math.min(Math.max(300,config.toleranceMs),gap*.6);
            if(timeMs<=deadline)break;advance(true);
        }
    }
    private boolean weakAt(int midi,double due){
        return uncertain.values().stream().anyMatch(e->{
            double onset=(double)e.get("onsetMs"),duration=PracticeTimeline.number(e,"durationMs",0);
            double end=PracticeTimeline.number(e,"offsetMs",onset+(duration>0?duration:config.toleranceMs));
            // Open uncertainty intervals cover capture until their matching close.
            if(e.get("type").equals("uncertainty")&&e.get("offsetMs")==null)end=Double.POSITIVE_INFINITY;
            return onset<=due+config.toleranceMs&&end>=due-config.toleranceMs;
        });
    }
    /** Detector limits describe missing evidence, never the performer's actual pitch. */
    synchronized void recordingEvidence(Map<?,?> range,boolean noReliableNotes){
        detectorMinMidi=range.get("minMidi") instanceof Number n&&Double.isFinite(n.doubleValue())?n.doubleValue():null;
        detectorMaxMidi=range.get("maxMidi") instanceof Number n&&Double.isFinite(n.doubleValue())?n.doubleValue():null;
        if(detectorMinMidi!=null&&detectorMaxMidi!=null&&detectorMinMidi>detectorMaxMidi)throw new IllegalArgumentException("听音引擎音域无效。");
        noReliableRecordingEvidence=noReliableNotes;
    }
    /** Estimated recorded locations are separate from score and actual-event clocks. */
    synchronized void recordedExpectedTimes(Map<Integer,Double> times){
        for(Map.Entry<Integer,Double> time:times.entrySet())if(time.getKey()<0||time.getKey()>=timeline.groups().size()
                ||time.getValue()==null||!Double.isFinite(time.getValue())||time.getValue()<0)throw new IllegalArgumentException("录音位置估计无效。");
        recordedExpectedTimes=Map.copyOf(times);
    }
    private String unjudgedReason(int midi,PracticeTimeline.Group g){
        if(detectorMinMidi!=null&&midi<detectorMinMidi||detectorMaxMidi!=null&&midi>detectorMaxMidi)return "outside-detector-range";
        if(noReliableRecordingEvidence)return "no-reliable-note-events";
        if(startedAt!=null&&(config.mode.equals("strict")||!alignment.equals("live")?weakAt(midi,expectedTime(g)):
                uncertain.values().stream().anyMatch(e->e.get("index") instanceof Integer i&&i==g.index())))return "uncertain-acoustic-evidence";
        return null;
    }
    private void advance(boolean missed){
        PracticeTimeline.Group g=current();if(g==null)return;
        List<Integer> remaining=g.pitches().stream().filter(p->!matched.contains(p)).toList();
        List<Integer> weak=remaining.stream().filter(p->unjudgedReason(p,g)!=null).toList();
        List<Integer> missing=remaining.stream().filter(p->!weak.contains(p)).toList();
        Map<String,Object> expectedTiming=fields("expectedTimeMs",expectedTime(g));
        if(missed&&!missing.isEmpty()){
            Map<Integer,Map<String,Object>> substitutions=new LinkedHashMap<>();
            for(Map<String,Object> wrong:errors)if(wrong.get("kind").equals("wrong")&&(int)wrong.get("index")==g.index()&&(int)wrong.get("attempt")==attempt
                    &&wrong.get("substitutedPitch") instanceof Integer pitch&&missing.contains(pitch))substitutions.putIfAbsent(pitch,wrong);
            // Keep raw missing provenance, but count one reliable wrong identity
            // once. Other missing chord pitches remain independent judgments.
            for(Map.Entry<Integer,Map<String,Object>> substitution:substitutions.entrySet())error("missing",g,fields("expectedTimeMs",expectedTime(g),
                    "expected",List.of(substitution.getKey()),"eventId",substitution.getValue().get("eventId"),"coveredByWrong",substitution.getValue().get("eventId"),"resolved",true,"reason","same-position-wrong-note"));
            List<Integer> uncovered=missing.stream().filter(p->!substitutions.containsKey(p)).toList();
            if(!uncovered.isEmpty()){expectedTiming.put("expected",uncovered);error("missing",g,expectedTiming);}
        }
        if(missed&&!weak.isEmpty()&&errors.stream().noneMatch(e->(int)e.get("index")==g.index()&&(int)e.get("attempt")==attempt&&e.get("kind").equals("uncertain"))){
            Map<String,Object> evidence=fields("expected",weak,"expectedTimeMs",expectedTime(g),"reason",unjudgedReason(weak.getFirst(),g));error("uncertain",g,evidence);
            unjudged.add(fields("type","unjudged","index",g.index(),"expected",weak,"reason",evidence.get("reason"),"sourceNoteIds",g.location().get("sourceNoteIds"),"occurrenceIds",g.location().get("occurrenceIds")));
        }
        boolean bad=errors.stream().anyMatch(e->(int)e.get("index")==g.index()&&(int)e.get("attempt")==attempt&&!e.get("kind").equals("uncertain"));
        String status=missed&&!missing.isEmpty()?"missing":missed&&!weak.isEmpty()?"uncertain":bad?"corrected":"correct";
        Map<String,Object> r=new LinkedHashMap<>(g.location());r.put("correct",matched.size());r.put("expected",g.pitches().size());r.put("status",status);
        r.put("notes",g.notes().stream().map(n->{Map<String,Object> v=n.snapshot();v.put("matched",matched.contains(n.midi()));
            if(!matched.contains(n.midi())&&weak.contains(n.midi())){v.put("judgment","unjudged");v.put("reason",unjudgedReason(n.midi(),g));}
            v.put("actual",played.stream().filter(p->p.get("index").equals(g.index())&&p.get("midi").equals(n.midi())&&Integer.valueOf(attempt).equals(p.get("attempt"))).reduce((a,b)->b).orElse(null));return v;}).toList());results.put(g.index(),r);
        index++;matched.clear();if(current()==null)active=!attacks.isEmpty();
    }
    private void error(String kind,PracticeTimeline.Group g,Map<String,Object> data){
        String key=attempt+":"+g.index()+":"+kind+":"+data.getOrDefault("eventId","");if(!errorKeys.add(key))return;
        Map<String,Object> e=new LinkedHashMap<>(g.location());e.put("kind",kind);e.put("attempt",attempt);e.put("onsetMs",g.onsetMs());e.put("durationMs",g.notes().stream().mapToDouble(PracticeTimeline.Note::durationMs).max().orElse(0));e.putAll(data);errors.add(e);
        if(data.get("expected") instanceof List<?> expected){List<PracticeTimeline.Note> notes=g.notes().stream().filter(n->expected.contains(n.midi())).toList();
            e.put("notes",notes.stream().map(PracticeTimeline.Note::snapshot).toList());e.put("sourceNoteIds",notes.stream().map(PracticeTimeline.Note::sourceNoteId).toList());e.put("occurrenceIds",notes.stream().map(PracticeTimeline.Note::occurrenceId).toList());}
        Map<String,Object> result=results.get(g.index());if(result!=null&&result.get("status").equals("correct"))result.put("status","corrected");
    }
    public synchronized Map<String,Object> finish(){
        if(pending!=null){wrong(pending.event);pending=null;}active=false;paused=false;return snapshot();
    }
    /** Finish a full recorded segment, counting uncovered remaining score attacks. */
    synchronized void completeRecorded(){while(current()!=null)advance(true);active=false;paused=false;}
    public synchronized Map<String,Object> recorded(List<?> events){return RecordedAlignment.analyze(timeline,config,events);}
    synchronized void setAlignment(String kind){alignment=kind;}
    public synchronized Map<String,Object> snapshot(){return snapshot(true);}
    /** Polling state omits immutable groups and the growing raw event trace. */
    public synchronized Map<String,Object> liveSnapshot(){return snapshot(false);}
    private Map<String,Object> snapshot(boolean archive){
        Map<String,Object> out=fields("schemaVersion",1,"mode",config.mode,"bpm",config.bpm,"localBpm",localBpm,"currentIndex",index,
                "active",active,"paused",paused,"matched",List.copyOf(matched),"completed",index,"completedPositions",index,"total",timeline.groups().size(),
                "firstTryCorrect",results.values().stream().filter(r->r.get("status").equals("correct")).count(),
                "measureCount",practicedMeasures(),"totalMeasureCount",(int)timeline.groups().stream().map(PracticeTimeline.Group::mi).distinct().count(),
                "results",new ArrayList<>(results.values()),"errors",new ArrayList<>(errors),"played",new ArrayList<>(played),"unjudged",new ArrayList<>(archive?unjudged:unjudged.subList(Math.max(0,unjudged.size()-50),unjudged.size())),"unjudgedCount",unjudged.size(),
                "cursor",current()==null?null:current().location(),"current",current()==null?null:current().snapshot(),
                "awaitingRelease",active&&current()==null&&!attacks.isEmpty(),"alignment",fields("kind",alignment,"offsetMs",startedAt==null?0:startedAt,"timingGraded",config.mode.equals("strict")),
                "feedbackPolicy",config.feedbackPolicy);
        if(archive){out.put("groups",timeline.groups().stream().map(PracticeTimeline.Group::snapshot).toList());out.put("events",new ArrayList<>(eventLog));}
        out.put("pendingReview",errors.stream().filter(e->e.get("kind").equals("uncertain")&&!Boolean.TRUE.equals(e.get("resolved"))).toList());
        if(pending!=null){Map<String,Object> following=new LinkedHashMap<>(timeline.groups().get(pending.index).location());following.put("played",pending.event.get("midi"));following.put("timeMs",pending.event.get("timeMs"));following.put("direction",pending.index<index?"backtrack":"skip-forward");out.put("pendingFollowing",following);}else out.put("pendingFollowing",null);
        out.put("feedbackPolicy",config.feedbackPolicy);
        out.put("colors",results.values().stream().map(r->fields("index",r.get("index"),"status",r.get("status"),"sourceNoteIds",r.get("sourceNoteIds"),"occurrenceIds",r.get("occurrenceIds"))).toList());
        // Native sustain/release may arrive while HTTP serializes this snapshot.
        // Copy the nested JSON values while holding the judge lock.
        Map<String,Object> stable=new LinkedHashMap<>();out.forEach((key,value)->stable.put(key,snapshotValue(value)));return stable;
    }
    private int practicedMeasures(){
        Set<Integer> measures=new HashSet<>();
        for(Map<String,Object> event:played)addMeasure(measures,event);
        for(Map<String,Object> result:results.values())if(PracticeTimeline.number(result,"correct",0)>0)addMeasure(measures,result);
        for(Map<String,Object> error:errors)if(error.get("eventId")!=null)addMeasure(measures,error);
        for(Map<String,Object> event:unjudged)if("note-on".equals(event.get("type")))addMeasure(measures,event);
        return measures.size();
    }
    private void addMeasure(Set<Integer> measures,Map<?,?> event){if(event.get("index") instanceof Number n&&n.intValue()>=0&&n.intValue()<timeline.groups().size())measures.add(timeline.groups().get(n.intValue()).mi());}
    private static Object snapshotValue(Object value){
        if(value instanceof Map<?,?> map){Map<String,Object> copied=new LinkedHashMap<>();map.forEach((key,item)->copied.put(String.valueOf(key),snapshotValue(item)));return copied;}
        if(value instanceof List<?> list)return list.stream().map(PracticeEngine::snapshotValue).toList();return value;
    }
    private Map<String,Object> canonical(Map<?,?> e){
        String type=PracticeTimeline.string(e,"type","note-on");
        double onset=PracticeTimeline.number(e,"onsetMs",PracticeTimeline.number(e,"timeMs",Double.NaN));
        double time=type.equals("note-off")?PracticeTimeline.number(e,"offsetMs",PracticeTimeline.number(e,"timeMs",onset)):type.equals("note-update")?PracticeTimeline.number(e,"timeMs",onset):onset;
        finite(onset);finite(time);double confidence=PracticeTimeline.number(e,"confidence",1),cents=PracticeTimeline.number(e,"cents",0);
        if(!Double.isFinite(confidence)||confidence<0||confidence>1||!Double.isFinite(cents))throw new IllegalArgumentException("输入音符置信度或音准无效。");
        Map<String,Object> out=fields("type",type,"schemaVersion",1,"id",PracticeTimeline.string(e,"id","event"+(++serial)),"onsetMs",onset,"timeMs",time,
                "offsetMs",e.get("offsetMs"),"durationMs",PracticeTimeline.number(e,"durationMs",0),"cents",cents,"confidence",confidence,"voiced",e.getOrDefault("voiced",null));
        if(e.get("midi") instanceof Number n){double pitch=n.doubleValue();if(pitch!=Math.rint(pitch)||pitch<0||pitch>127||!Double.isFinite(pitch))throw new IllegalArgumentException("输入音高须为 MIDI 整数。");out.put("midi",(int)pitch);}
        if(e.get("frequency") instanceof Number frequency&&Double.isFinite(frequency.doubleValue()))out.put("frequency",frequency.doubleValue());
        if(e.get("sampleCount") instanceof Number samples)out.put("sampleCount",samples.longValue());
        if(e.get("recordingOnsetMs") instanceof Number recording&&Double.isFinite(recording.doubleValue()))out.put("recordingOnsetMs",recording.doubleValue());
        if(e.get("input") instanceof String input)out.put("input",input);
        if(e.get("intonationEvidence") instanceof Map<?,?> evidence)out.put("intonationEvidence",snapshotValue(evidence));
        if(e.get("recordedNote") instanceof Map<?,?> original)out.put("recordedNote",snapshotValue(original));
        for(String key:List.of("reviewRequired","onsetReliable","onsetEvidence"))if(e.containsKey(key))out.put(key,snapshotValue(e.get(key)));
        double duration=(double)out.get("durationMs");if(!Double.isFinite(duration)||duration<0)throw new IllegalArgumentException("输入音符时值无效。");
        if(out.get("offsetMs")!=null&&(!(out.get("offsetMs") instanceof Number offset)||!Double.isFinite(offset.doubleValue())||offset.doubleValue()<onset))throw new IllegalArgumentException("输入音符结束时间无效。");
        if(e.get("reason") instanceof String reason)out.put("reason",reason); return out;
    }
    static Map<String,Object> fields(Object... pairs){Map<String,Object> m=new LinkedHashMap<>();for(int i=0;i<pairs.length;i+=2)m.put((String)pairs[i],pairs[i+1]);return m;}
    static void finite(double n){if(!Double.isFinite(n))throw new IllegalArgumentException("输入时间无效。");}
}
