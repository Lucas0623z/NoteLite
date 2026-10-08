/* Copyright © NoteLite 2026. GNU Affero General Public License, version 3 or later. */
package com.notelite.omr.practice;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;

/** Recorded replay uses the same judge; strict mode removes one constant offset only. */
public final class RecordedAlignment {
    private RecordedAlignment() {}
    public static Map<String,Object> analyze(PracticeTimeline timeline,PracticeEngine.Config config,List<?> input){
        return analyze(timeline,config,input,Map.of(),List.of());
    }
    /** Retain a model's real limitations and unvoiced intervals in the common judgment. */
    public static Map<String,Object> analyze(PracticeTimeline timeline,PracticeEngine.Config config,Map<String,?> transcription){
        List<?> notes=transcription.get("notes") instanceof List<?> n?n:List.of();
        Map<?,?> range=transcription.get("supportedPitchRange") instanceof Map<?,?> r?r:Map.of();
        List<?> uncertainty=transcription.get("uncertaintyIntervals") instanceof List<?> u?u:List.of();
        Map<String,Object> result=new java.util.LinkedHashMap<>(analyze(timeline,config,notes,range,uncertainty));
        result.put("supportedPitchRange",range);return result;
    }
    private static Map<String,Object> analyze(PracticeTimeline timeline,PracticeEngine.Config config,List<?> input,Map<?,?> range,List<?> uncertainty){
        List<Map<String,Object>> events=new ArrayList<>();int serial=0;
        for(Object value:input){
            Map<?,?> n=PracticeTimeline.map(value);
            String type=PracticeTimeline.string(n,"type","");
            if(!type.isEmpty()){
                Map<String,Object> e=new java.util.LinkedHashMap<>();n.forEach((k,v)->e.put(String.valueOf(k),v));events.add(e);continue;
            }
            double onset=PracticeTimeline.number(n,"onsetMs",PracticeTimeline.number(n,"onset",0)*1000);
            double duration=PracticeTimeline.number(n,"durationMs",PracticeTimeline.number(n,"duration",0)*1000);
            if(!Double.isFinite(onset)||onset<0||!Double.isFinite(duration)||duration<=0)throw new IllegalArgumentException("录音音符时间无效。");
            String id=PracticeTimeline.string(n,"id","recorded"+(++serial));
            double confidence=PracticeTimeline.number(n,"confidence",1),cents=PracticeTimeline.number(n,"cents",0);
            Map<String,Object> attack=PracticeEngine.fields("type","note-on","id",id,"midi",n.get("midi"),"onsetMs",onset,"timeMs",onset,"cents",cents,"confidence",confidence,"voiced",true);
            Map<String,Object> original=new java.util.LinkedHashMap<>();n.forEach((key,item)->original.put(String.valueOf(key),item));attack.put("recordedNote",original);
            for(String key:List.of("reviewRequired","onsetReliable","reason","onsetEvidence"))if(n.containsKey(key))attack.put(key,n.get(key));
            if(n.containsKey("cents")&&n.get("engine") instanceof String source){
                String reliability=PracticeTimeline.string(n,"centsReliability","");
                boolean reliable=List.of("pyin","crepe","aubio").contains(source)||List.of("aggregate-median","spectral-estimate").contains(reliability);
                attack.put("intonationEvidence",PracticeEngine.fields("kind","aggregate-median","source",source,"cents",cents,"confidence",confidence,"reliable",reliable,
                        "sampleCount",n.get("centsSampleCount"),"spreadCents",n.get("centsSpread"),"spreadStatistic",n.get("centsSpreadStatistic"),"resolutionCents",n.get("centsResolution"),"reliability",reliability));
            }
            events.add(attack);
            events.add(PracticeEngine.fields("type","note-off","id",id,"midi",n.get("midi"),"onsetMs",onset,"offsetMs",onset+duration,"timeMs",onset+duration,"durationMs",duration,"confidence",confidence,"cents",cents,"voiced",false));
        }
        for(Object value:uncertainty){Map<?,?> interval=PracticeTimeline.map(value);
            double onset=PracticeTimeline.number(interval,"onsetMs",PracticeTimeline.number(interval,"onset",0)*1000);
            double duration=PracticeTimeline.number(interval,"durationMs",PracticeTimeline.number(interval,"duration",0)*1000);
            if(!Double.isFinite(onset)||onset<0||!Double.isFinite(duration)||duration<=0)throw new IllegalArgumentException("录音不确定区间无效。");
            events.add(PracticeEngine.fields("type","uncertainty","id","recorded-uncertainty"+(++serial),"onsetMs",onset,"offsetMs",onset+duration,"timeMs",onset,
                    "durationMs",duration,"confidence",PracticeTimeline.number(interval,"confidence",0),"voiced",null,"reason",PracticeTimeline.string(interval,"reason","uncertain-acoustic-evidence")));
        }
        events.sort(Comparator.comparingDouble(e->PracticeTimeline.number(e,"timeMs",PracticeTimeline.number(e,"onsetMs",0))));
        List<Map<String,Object>> strong=events.stream().filter(e->e.get("type").equals("note-on")&&PracticeTimeline.number(e,"confidence",1)>=config.confidenceThreshold()
                &&!Boolean.TRUE.equals(e.get("reviewRequired"))&&!Boolean.FALSE.equals(e.get("onsetReliable"))).toList();
        double offset=0;
        if(config.startTimeMs()!=null)offset=config.startTimeMs();
        else {
            Map<String,Object> anchor=strong.stream().limit(8).filter(e->timeline.groups().getFirst().pitches().contains(((Number)e.get("midi")).intValue())).findFirst().orElse(null);
            if(anchor!=null)offset=PracticeTimeline.number(anchor,"onsetMs",PracticeTimeline.number(anchor,"timeMs",0));
            else if(!strong.isEmpty()) {
                Map<String,Object> first=strong.getFirst();int midi=((Number)first.get("midi")).intValue();
                double scoreOnset=timeline.groups().stream().limit(8).filter(g->g.pitches().contains(midi)).mapToDouble(PracticeTimeline.Group::onsetMs).findFirst().orElse(0);
                offset=PracticeTimeline.number(first,"onsetMs",PracticeTimeline.number(first,"timeMs",0))-scoreOnset;
            } else offset=events.stream().filter(e->e.get("type").equals("note-on")).mapToDouble(e->PracticeTimeline.number(e,"onsetMs",PracticeTimeline.number(e,"timeMs",0))).findFirst().orElse(0);
            if(config.mode().equals("strict")&&strong.size()>1)offset=contextOffset(timeline,config,strong,offset);
        }
        PracticeEngine engine=new PracticeEngine(timeline,config);engine.begin(offset);engine.setAlignment(config.mode().equals("strict")?"constant-offset":"free-following");engine.recordingEvidence(range,strong.isEmpty());
        for(Map<String,Object> event:events)engine.receive(event);
        engine.finish();engine.completeRecorded();return engine.snapshot();
    }
    /** Choose one clock offset from a pitch/time context; never warp individual notes. */
    private static double contextOffset(PracticeTimeline timeline,PracticeEngine.Config config,List<Map<String,Object>> strong,double initial){
        List<Map<String,Object>> prefix=strong.stream().limit(24).toList();
        List<PracticeTimeline.Group> groups=timeline.groups().stream().limit(32).toList();
        java.util.Set<Double> candidates=new java.util.LinkedHashSet<>();candidates.add(initial);
        for(Map<String,Object> event:prefix){int midi=((Number)event.get("midi")).intValue();double onset=PracticeTimeline.number(event,"onsetMs",PracticeTimeline.number(event,"timeMs",0));
            for(PracticeTimeline.Group group:groups)if(group.pitches().contains(midi))candidates.add(onset-group.onsetMs());}
        double selected=initial;int best=contextMatches(groups,prefix,initial,config.toleranceMs());
        // Retain the earliest original anchor for ties: this keeps an isolated
        // real late attack from moving the clock to forgive that timing error.
        for(double candidate:candidates){int matched=contextMatches(groups,prefix,candidate,config.toleranceMs());if(matched>best){best=matched;selected=candidate;}}
        return selected;
    }
    private static int contextMatches(List<PracticeTimeline.Group> groups,List<Map<String,Object>> events,double offset,double tolerance){
        java.util.Set<String> used=new java.util.HashSet<>();int matched=0;
        for(Map<String,Object> event:events){int midi=((Number)event.get("midi")).intValue();double onset=PracticeTimeline.number(event,"onsetMs",PracticeTimeline.number(event,"timeMs",0));
            PracticeTimeline.Group best=null;double distance=Double.POSITIVE_INFINITY;
            for(PracticeTimeline.Group group:groups){double difference=Math.abs(onset-offset-group.onsetMs());if(difference<=tolerance&&difference<distance&&group.pitches().contains(midi)&&!used.contains(group.index()+":"+midi)){best=group;distance=difference;}}
            if(best!=null){used.add(best.index()+":"+midi);matched++;}}
        return matched;
    }
}
