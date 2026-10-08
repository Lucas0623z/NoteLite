/* Copyright © NoteLite 2026. GNU Affero General Public License, version 3 or later. */
package com.notelite.omr.practice;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;

/** Recorded replay uses the same judge; strict mode removes one constant offset only. */
public final class RecordedAlignment {
    private record Anchor(int index,double scoreMs,double recordedMs) {}
    private record TimeMapping(Map<Integer,Double> times,List<Map<String,Object>> locations) {}
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
        Map<String,Object> result=judge(timeline,config,events,range,strong.isEmpty(),offset,Map.of());
        if(config.mode().equals("free")){
            // The first common-judge pass supplies only genuinely accepted pitch
            // identities. Its timing estimates never alter the acoustic trace.
            TimeMapping mapping=freeTimes(timeline,config,result);
            if(!mapping.times.isEmpty())result=judge(timeline,config,events,range,strong.isEmpty(),offset,mapping.times);
            @SuppressWarnings("unchecked") Map<String,Object> alignment=(Map<String,Object>)result.get("alignment");
            alignment.put("expectedTimeBasis",mapping.times.isEmpty()?"no-accepted-anchors":"accepted-neighbor-anchors");
            alignment.put("expectedTimeMapping",mapping.locations);
        }
        return result;
    }
    private static Map<String,Object> judge(PracticeTimeline timeline,PracticeEngine.Config config,List<Map<String,Object>> events,
                                           Map<?,?> range,boolean noReliableNotes,double offset,Map<Integer,Double> expectedTimes){
        PracticeEngine engine=new PracticeEngine(timeline,config);engine.begin(offset);engine.setAlignment(config.mode().equals("strict")?"constant-offset":"free-following");
        engine.recordingEvidence(range,noReliableNotes);engine.recordedExpectedTimes(expectedTimes);
        for(Map<String,Object> event:events)engine.receive(event);
        engine.finish();engine.completeRecorded();return engine.snapshot();
    }
    /** Missing positions are estimates between actual accepted attacks, never played notes. */
    private static TimeMapping freeTimes(PracticeTimeline timeline,PracticeEngine.Config config,Map<String,Object> report){
        List<Anchor> anchors=new ArrayList<>();
        for(Object row:(List<?>)report.get("results")){
            Map<?,?> result=PracticeTimeline.map(row);int index=(int)PracticeTimeline.number(result,"index",-1);
            if(index<0||index>=timeline.groups().size())continue;
            List<Double> times=new ArrayList<>();java.util.Set<String> ids=new java.util.HashSet<>();
            for(Object value:(List<?>)result.get("notes")){
                Map<?,?> note=PracticeTimeline.map(value);
                if(!Boolean.TRUE.equals(note.get("matched"))||!(note.get("actual") instanceof Map<?,?> actual)
                        ||PracticeTimeline.number(actual,"confidence",0)<config.confidenceThreshold()
                        ||PracticeTimeline.number(actual,"midi",-1)!=PracticeTimeline.number(note,"midi",-2)
                        ||!(actual.get("sourceNoteIds") instanceof List<?> sources)||!sources.contains(note.get("sourceNoteId"))
                        ||!(actual.get("occurrenceIds") instanceof List<?> occurrences)||!occurrences.contains(note.get("occurrenceId")))continue;
                if(actual.get("recordedNote") instanceof Map<?,?> original&&(Boolean.TRUE.equals(original.get("reviewRequired"))||Boolean.FALSE.equals(original.get("onsetReliable"))))continue;
                double time=PracticeTimeline.number(actual,"time",Double.NaN);
                if(Double.isFinite(time)&&time>=0&&ids.add(String.valueOf(actual.get("id"))))times.add(time);
            }
            if(times.isEmpty())continue;
            times.sort(Double::compare);double median=times.get(times.size()/2);
            if(anchors.isEmpty()||median>=anchors.getLast().recordedMs)anchors.add(new Anchor(index,timeline.groups().get(index).onsetMs(),median));
        }
        Map<Integer,Double> times=new java.util.LinkedHashMap<>();List<Map<String,Object>> locations=new ArrayList<>();
        if(anchors.isEmpty())return new TimeMapping(times,locations);
        for(PracticeTimeline.Group group:timeline.groups()){
            Anchor previous=null,next=null;
            for(Anchor anchor:anchors){if(anchor.index<=group.index())previous=anchor;if(anchor.index>=group.index()){next=anchor;break;}}
            double time;String basis;List<Integer> neighbors;
            if(previous!=null&&previous.index==group.index()){
                time=previous.recordedMs;basis="accepted-attack";neighbors=List.of(previous.index);
            } else if(previous!=null&&next!=null&&next.scoreMs>previous.scoreMs){
                time=previous.recordedMs+(group.onsetMs()-previous.scoreMs)/(next.scoreMs-previous.scoreMs)*(next.recordedMs-previous.recordedMs);
                basis="interpolated-neighbors";neighbors=List.of(previous.index,next.index);
            } else if(previous!=null&&next!=null){
                time=previous.recordedMs;basis="coincident-score-neighbors";neighbors=List.of(previous.index,next.index);
            } else {
                Anchor edge=previous==null?anchors.getFirst():anchors.getLast();double ratio=1;
                basis="single-anchor-default-tempo";neighbors=List.of(edge.index);
                if(anchors.size()>1){
                    Anchor first=previous==null?anchors.getFirst():anchors.get(anchors.size()-2),last=previous==null?anchors.get(1):anchors.getLast();
                    if(last.scoreMs>first.scoreMs&&last.recordedMs>first.recordedMs){
                        ratio=Math.max(config.bpm()/400,Math.min(config.bpm()/20,(last.recordedMs-first.recordedMs)/(last.scoreMs-first.scoreMs)));
                        basis="extrapolated-local-tempo";neighbors=List.of(first.index,last.index);
                    }
                }
                time=edge.recordedMs+(group.onsetMs()-edge.scoreMs)*ratio;
            }
            time=Math.max(0,time);times.put(group.index(),time);
            Map<String,Object> location=new java.util.LinkedHashMap<>(group.location());
            location.putAll(PracticeEngine.fields("expectedTimeMs",time,"basis",basis,"anchorIndices",neighbors,"estimated",true));locations.add(location);
        }
        return new TimeMapping(times,locations);
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
