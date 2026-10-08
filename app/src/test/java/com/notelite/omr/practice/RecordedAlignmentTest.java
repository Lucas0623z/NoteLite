/* Copyright © NoteLite 2026. GNU Affero General Public License, version 3 or later. */
package com.notelite.omr.practice;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.junit.Test;
import static org.junit.Assert.*;

public class RecordedAlignmentTest {
    private static Map<String,Object> data(Object... fields){return PracticeEngine.fields(fields);}
    private static PracticeTimeline line(int... pitches){
        List<Map<String,Object>> groups=new ArrayList<>();
        for(int i=0;i<pitches.length;i++)groups.add(data("onset",i,"mi",0,"notes",List.of(data("id","P1:"+i,"occurrenceId","P1:"+i+"@0","midi",pitches[i],"duration",1))));
        return PracticeTimeline.fromGroups(groups,120);
    }
    private static Map<String,Object> note(String id,int midi,double onset){return data("id",id,"midi",midi,"onset",onset,"duration",.25,"confidence",.95);}
    private static PracticeEngine.Config config(String mode){return PracticeEngine.Config.fromMap(data("mode",mode,"bpm",120,"gradeDuration",false));}
    @SuppressWarnings("unchecked") private static List<Map<String,Object>> rows(Map<String,Object> report,String key){return (List<Map<String,Object>>)report.get(key);}
    @SuppressWarnings("unchecked") private static Map<String,Object> location(Map<String,Object> report,int index){return ((List<Map<String,Object>>)((Map<?,?>)report.get("alignment")).get("expectedTimeMapping")).get(index);}
    private static Map<String,Object> error(Map<String,Object> report,String kind){return rows(report,"errors").stream().filter(e->kind.equals(e.get("kind"))&&!Boolean.TRUE.equals(e.get("resolved"))).findFirst().orElseThrow();}
    private static long count(Map<String,Object> report,String kind){return rows(report,"errors").stream().filter(e->kind.equals(e.get("kind"))&&!Boolean.TRUE.equals(e.get("resolved"))).count();}
    private static Map<?,?> resultNote(Map<String,Object> report,int index,int midi){return ((List<?>)rows(report,"results").get(index).get("notes")).stream().map(v->(Map<?,?>)v).filter(n->Integer.valueOf(midi).equals(n.get("midi"))).findFirst().orElseThrow();}

    @Test public void freeSlowingPerformanceMapsWeakEvidenceBetweenActualAcceptedNeighbors(){
        List<Map<String,Object>> notes=List.of(note("c",60,0),note("d",62,1),note("f",65,4),note("g",67,5));
        Map<String,Object> report=RecordedAlignment.analyze(line(60,62,64,65,67),config("free"),data("notes",notes,
                "uncertaintyIntervals",List.of(data("onset",2.4,"duration",.2,"reason","aperiodic"))));
        assertEquals(0,count(report,"missing"));assertEquals(0,count(report,"wrong"));assertEquals(0,count(report,"late"));assertEquals(1,count(report,"uncertain"));
        assertEquals(2500d,error(report,"uncertain").get("expectedTimeMs"));assertEquals(List.of("P1:2"),error(report,"uncertain").get("sourceNoteIds"));
        assertEquals(List.of(1,3),location(report,2).get("anchorIndices"));assertEquals("interpolated-neighbors",location(report,2).get("basis"));
        assertEquals("unjudged",resultNote(report,2,64).get("judgment"));assertNull(resultNote(report,2,64).get("actual"));
        assertEquals(1000d,rows(report,"groups").get(2).get("onsetMs"));assertEquals(4,rows(report,"played").size());
        assertEquals(List.of(0d,1000d,4000d,5000d),rows(report,"played").stream().map(p->p.get("time")).toList());
        Map<String,Object> raw=rows(report,"events").stream().filter(e->"uncertainty".equals(e.get("type"))).findFirst().orElseThrow();
        assertEquals(2400d,raw.get("onsetMs"));assertEquals(2600d,raw.get("offsetMs"));assertEquals("aperiodic",raw.get("reason"));
    }

    @Test public void freeAcceleratingPerformanceAlsoUsesActualWeakTimeRatherThanNominalBeat(){
        Map<String,Object> report=RecordedAlignment.analyze(line(60,62,64,65,67),config("free"),data("notes",
                List.of(note("c",60,0),note("d",62,1),note("f",65,1.8),note("g",67,2.1)),
                "uncertaintyIntervals",List.of(data("onset",1.35,"duration",.1,"reason","weak-signal"))));
        assertEquals(1,count(report,"uncertain"));assertEquals(0,count(report,"missing"));assertEquals(0,count(report,"wrong"));
        assertEquals(1400d,((Number)error(report,"uncertain").get("expectedTimeMs")).doubleValue(),.001);
        assertEquals(4L,report.get("firstTryCorrect"));assertEquals(false,((Map<?,?>)report.get("alignment")).get("timingGraded"));
    }

    @Test public void freeMissingReplayEstimateIgnoresWrongAndLowConfidenceAttacksAsAnchors(){
        Map<String,Object> weak=note("weak-e",64,2.1);weak.put("confidence",.3);weak.put("duration",.05);
        List<Map<String,Object>> notes=List.of(note("c",60,0),note("d",62,1),note("wrong-a",69,2),weak,note("f",65,4),note("g",67,5));
        Map<String,Object> report=RecordedAlignment.analyze(line(60,62,64,65,67),config("free"),notes);
        assertEquals(1,count(report,"missing"));assertEquals(1,count(report,"wrong"));assertEquals(2500d,error(report,"missing").get("expectedTimeMs"));
        assertEquals(2500d,location(report,2).get("expectedTimeMs"));assertEquals(List.of(1,3),location(report,2).get("anchorIndices"));
        assertEquals(List.of("P1:2"),error(report,"missing").get("sourceNoteIds"));assertEquals(1000d,error(report,"missing").get("onsetMs"));
        assertNull(resultNote(report,2,64).get("actual"));assertFalse(Boolean.TRUE.equals(resultNote(report,2,64).get("matched")));
        assertEquals(.3,rows(report,"unjudged").stream().filter(e->"weak-e".equals(e.get("id"))).findFirst().orElseThrow().get("confidence"));
    }

    @Test public void freeRepeatAndPartialChordKeepOriginalIdentitiesAndOnlyUnjudgeTheUnheardPitch(){
        PracticeTimeline timeline=PracticeTimeline.fromGroups(List.of(
                data("onset",0,"notes",List.of(data("id","P1:0","occurrenceId","P1:0@0","midi",60,"duration",1))),
                data("onset",1,"notes",List.of(data("id","P1:1","midi",62,"duration",1))),
                data("onset",2,"notes",List.of(data("id","P1:0","occurrenceId","P1:0@1","midi",60,"duration",1))),
                data("onset",3,"notes",List.of(data("id","P1:2","midi",64,"duration",1),data("id","P1:3","midi",67,"duration",1))),
                data("onset",4,"notes",List.of(data("id","P1:4","midi",65,"duration",1))),
                data("onset",5,"notes",List.of(data("id","P1:5","midi",69,"duration",1)))),120);
        Map<String,Object> report=RecordedAlignment.analyze(timeline,config("free"),data("notes",
                List.of(note("c1",60,0),note("d",62,1),note("c2",60,3),note("e",64,4.5),note("f",65,6),note("a",69,7)),
                "uncertaintyIntervals",List.of(data("onset",4.4,"duration",.2,"reason","unstable"))));
        assertEquals(1,count(report,"uncertain"));assertEquals(0,count(report,"missing"));assertEquals(List.of(67),error(report,"uncertain").get("expected"));
        assertEquals(List.of("P1:3"),error(report,"uncertain").get("sourceNoteIds"));assertEquals(4500d,error(report,"uncertain").get("expectedTimeMs"));
        assertEquals(true,resultNote(report,3,64).get("matched"));assertNotNull(resultNote(report,3,64).get("actual"));
        assertEquals("unjudged",resultNote(report,3,67).get("judgment"));assertNull(resultNote(report,3,67).get("actual"));
        assertEquals("P1:0@0",resultNote(report,0,60).get("occurrenceId"));assertEquals("P1:0@1",resultNote(report,2,60).get("occurrenceId"));
        assertEquals("P1:0",resultNote(report,2,60).get("sourceNoteId"));assertEquals(1500d,rows(report,"groups").get(3).get("onsetMs"));
    }

    @Test public void aSingleAcceptedAnchorUsesAnExplicitDefaultTempoEstimateWithoutInventingNotes(){
        Map<String,Object> report=RecordedAlignment.analyze(line(60,62,64),config("free"),data("notes",List.of(note("c",60,2)),
                "uncertaintyIntervals",List.of(data("onset",2.45,"duration",.1,"reason","weak-signal"))));
        assertEquals(1,count(report,"uncertain"));assertEquals(1,count(report,"missing"));assertEquals(1,rows(report,"played").size());
        assertEquals(2500d,error(report,"uncertain").get("expectedTimeMs"));assertEquals(3000d,error(report,"missing").get("expectedTimeMs"));
        assertEquals("single-anchor-default-tempo",location(report,1).get("basis"));assertEquals(true,location(report,1).get("estimated"));
        assertNull(resultNote(report,1,62).get("actual"));assertNull(resultNote(report,2,64).get("actual"));
    }

    @Test public void strictRecordedTimingStillUsesOneGlobalOffsetAndDoesNotUseTheFreeMap(){
        Map<String,Object> report=RecordedAlignment.analyze(line(60,62,64,65,67),config("strict"),data("notes",
                List.of(note("c",60,2),note("d",62,2.5),note("f",65,3.5),note("g",67,4)),
                "uncertaintyIntervals",List.of(data("onset",2.8,"duration",.4,"reason","aperiodic"))));
        assertEquals(1,count(report,"uncertain"));assertEquals(0,count(report,"missing"));assertEquals(0,count(report,"late"));assertEquals(0,count(report,"wrong"));
        assertEquals(3000d,error(report,"uncertain").get("expectedTimeMs"));assertEquals(2000d,((Map<?,?>)report.get("alignment")).get("offsetMs"));
        assertEquals(true,((Map<?,?>)report.get("alignment")).get("timingGraded"));assertFalse(((Map<?,?>)report.get("alignment")).containsKey("expectedTimeMapping"));
    }
}
