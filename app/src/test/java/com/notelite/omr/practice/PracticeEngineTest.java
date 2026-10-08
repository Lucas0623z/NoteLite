/* Copyright © NoteLite 2026. GNU Affero General Public License, version 3 or later. */
package com.notelite.omr.practice;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.junit.Test;
import static org.junit.Assert.*;

public class PracticeEngineTest {
    private static Map<String,Object> data(Object... fields){return PracticeEngine.fields(fields);}
    private static PracticeTimeline line(int... pitches){
        List<Map<String,Object>> groups=new ArrayList<>();for(int i=0;i<pitches.length;i++)groups.add(data("onset",i,"measure","12","mi",11,"beat",i+1,"notes",List.of(data("id","P1:"+i,"occurrenceId","P1:"+i+"@0","midi",pitches[i],"duration",1))));
        return PracticeTimeline.fromGroups(groups,120);
    }
    private static PracticeEngine engine(String mode,int... pitches){return new PracticeEngine(line(pitches),PracticeEngine.Config.fromMap(data("mode",mode,"bpm",120,"startTimeMs",0)));}
    private static Map<String,Object> on(String id,int midi,double time){return data("type","note-on","id",id,"midi",midi,"onsetMs",time,"timeMs",time,"confidence",.95,"cents",0,"voiced",true);}
    private static Map<String,Object> off(String id,int midi,double onset,double end){return data("type","note-off","id",id,"midi",midi,"onsetMs",onset,"offsetMs",end,"timeMs",end,"durationMs",end-onset,"confidence",.95,"cents",0,"voiced",false);}
    @SuppressWarnings("unchecked") private static List<Map<String,Object>> rows(Map<String,Object> snapshot,String key){return (List<Map<String,Object>>)snapshot.get(key);}
    private static long count(Map<String,Object> snapshot,String kind){return rows(snapshot,"errors").stream().filter(e->e.get("kind").equals(kind)).count();}
    private static long visibleCount(Map<String,Object> snapshot,String kind){return rows(snapshot,"errors").stream().filter(e->e.get("kind").equals(kind)&&!Boolean.TRUE.equals(e.get("resolved"))).count();}
    private static PracticeTimeline chord(int... pitches){List<Map<String,Object>> notes=new ArrayList<>();for(int i=0;i<pitches.length;i++)notes.add(data("id","P1:"+i,"midi",pitches[i],"duration",1));return PracticeTimeline.fromGroups(List.of(data("onset",0,"mi",0,"notes",notes)),120);}

    @Test public void wrongSemitoneAndOctaveDoNotAdvanceOrBecomeIntonationCorrections(){
        PracticeEngine e=engine("wait",60,62);
        assertEquals(0,e.note(on("wrong",61,0)).get("currentIndex"));
        assertEquals(0,e.note(on("octave",72,200)).get("currentIndex"));
        assertEquals(2,count(e.snapshot(),"wrong"));
        assertEquals(1,e.note(on("right",60,400)).get("currentIndex"));
        assertEquals("corrected",rows(e.snapshot(),"results").getFirst().get("status"));
    }
    @Test public void heldNotesNeverSatisfyRepeatedAttacksButNewAttacksDo(){
        PracticeEngine e=engine("wait",60,60);
        assertEquals(1,e.note(on("held",60,0)).get("currentIndex"));
        assertEquals(1,e.note(on("held",60,20)).get("currentIndex"));
        e.note(off("held",60,0,400));
        assertEquals(2,e.note(on("second",60,500)).get("currentIndex"));
        assertEquals(true,e.snapshot().get("awaitingRelease"));
        assertEquals(false,e.note(off("second",60,500,1000)).get("active"));
    }
    @Test public void chordRequiresAllPitchesAndUnisonIdentitiesSurvive(){
        PracticeTimeline t=PracticeTimeline.fromGroups(List.of(data("onset",0,"measure","3","mi",2,"beat",1,"notes",List.of(
                data("id","P1:0","occurrenceId","P1:0@0","midi",60,"duration",1),data("id","P2:0","occurrenceId","P2:0@0","midi",60,"duration",1),data("id","P1:1","midi",64,"duration",1)))),120);
        PracticeEngine e=new PracticeEngine(t,PracticeEngine.Config.fromMap(data("mode","wait","bpm",120)));
        assertEquals(0,e.note(on("c",60,0)).get("currentIndex"));
        assertEquals(1,e.note(on("e",64,40)).get("currentIndex"));
        assertEquals(3,((List<?>)rows(e.snapshot(),"results").getFirst().get("sourceNoteIds")).size());
        assertEquals(2,rows(e.snapshot(),"results").getFirst().get("expected"));
    }
    @Test public void fixedTempoKeepsClockThroughMissingAndLateAttacks(){
        PracticeEngine e=engine("strict",60,62,64,65);
        e.note(on("c",60,0));e.note(off("c",60,0,500));
        e.note(on("e",64,1000));
        assertEquals(3,e.snapshot().get("currentIndex"));
        assertEquals(1,count(e.snapshot(),"missing"));
        Map<String,Object> missing=rows(e.snapshot(),"errors").stream().filter(r->r.get("kind").equals("missing")).findFirst().orElseThrow();
        assertEquals(List.of(62),missing.get("expected"));
        e.note(on("f",65,1720));assertEquals(1,count(e.snapshot(),"late"));
    }
    @Test public void explicitPauseShiftsClockWithoutGradingTheGap(){
        PracticeEngine e=engine("strict",60,62);
        e.note(on("c",60,0));e.note(off("c",60,0,500));e.pause(500);e.tick(2000);
        assertEquals(1,e.snapshot().get("currentIndex"));
        e.resume(2000);e.note(on("d",62,2000));
        assertEquals(0,count(e.snapshot(),"late"));assertEquals(0,count(e.snapshot(),"missing"));
    }
    @Test public void freeFollowingAcceptsSlowOrFastTempoWithoutTimingGrades(){
        PracticeEngine e=engine("free",60,62,64);
        e.note(on("c",60,0));e.note(off("c",60,0,700));e.note(on("d",62,1000));e.note(off("d",62,1000,1500));e.note(on("e",64,2200));
        assertEquals(3,e.snapshot().get("currentIndex"));assertEquals(0,count(e.snapshot(),"late"));assertEquals(0,count(e.snapshot(),"short"));
        assertTrue((double)e.snapshot().get("localBpm")<120);
    }
    @Test public void stoppingThenRestartingEarlierRepositionsWithoutNewSessions(){
        PracticeEngine e=engine("free",60,62,64,65);
        e.note(on("c",60,0));e.note(off("c",60,0,400));e.note(on("d",62,500));e.note(off("d",62,500,900));
        assertEquals(1,e.note(on("restart",60,2500)).get("currentIndex"));
        assertEquals(1,rows(e.snapshot(),"results").size());assertEquals(0,count(e.snapshot(),"wrong"));
    }
    @Test public void backtrackingNeedsTwoConsecutiveScoreMatchesAndPreservesReleasedCandidates(){
        PracticeEngine e=engine("free",60,62,64,65);
        for(int i=0;i<3;i++){int p=new int[]{60,62,64}[i];e.note(on("n"+i,p,i*500));e.note(off("n"+i,p,i*500,i*500+300));}
        assertEquals(3,e.note(on("back-d",62,1400)).get("currentIndex"));
        assertEquals("backtrack",((Map<?,?>)e.liveSnapshot().get("pendingFollowing")).get("direction"));assertEquals(List.of("P1:1"),((Map<?,?>)e.liveSnapshot().get("pendingFollowing")).get("sourceNoteIds"));
        e.note(off("back-d",62,1400,1700));
        assertEquals(3,e.note(on("back-e",64,1900)).get("currentIndex"));
        assertNull(e.liveSnapshot().get("pendingFollowing"));
        assertEquals(0,count(e.snapshot(),"wrong"));
        e.note(off("back-e",64,1900,2200));e.note(on("f",65,2400));e.note(off("f",65,2400,2700));
        assertEquals(false,e.snapshot().get("awaitingRelease"));
    }
    @Test public void finalReleaseCanReportShortDurationAfterTheLastCorrectAttack(){
        PracticeEngine e=engine("strict",60);
        assertEquals(true,e.note(on("c",60,0)).get("active"));
        e.note(off("c",60,0,100));assertEquals(1,count(e.snapshot(),"short"));
        assertEquals("corrected",rows(e.snapshot(),"results").getFirst().get("status"));assertEquals(false,e.snapshot().get("active"));
    }
    @Test public void activeFeedbackPromptsForWeakEvidenceThenRecoversWithoutHardWrongOrMissing(){
        PracticeEngine e=engine("strict",60,62);
        Map<String,Object> weak=on("weak",61,0);weak.put("confidence",.3);
        e.note(weak);assertEquals(1,rows(e.snapshot(),"pendingReview").size());assertEquals(0,e.snapshot().get("currentIndex"));
        e.note(on("c",60,80));e.note(off("c",60,80,550));e.note(on("d",62,500));
        assertEquals(0,count(e.snapshot(),"wrong"));assertEquals(0,count(e.snapshot(),"missing"));
        assertEquals(0,rows(e.snapshot(),"pendingReview").size());assertEquals("correct",rows(e.snapshot(),"results").getFirst().get("status"));
    }
    @Test public void weakAcousticEvidenceCreatesUncertainRatherThanMissingAndDoesNotMaskLaterSilence(){
        PracticeEngine e=engine("strict",60,62);
        e.note(data("type","uncertainty","id","u1","onsetMs",0,"offsetMs",180,"durationMs",180,"timeMs",180,"confidence",.2));
        e.tick(310);assertEquals(1,count(e.snapshot(),"uncertain"));assertEquals(0,count(e.snapshot(),"missing"));
        e.tick(810);assertEquals(1,count(e.snapshot(),"missing"));
    }
    @Test public void actualOnsetTimestampWinsOverLaterAnalysisFrameTimestamp(){
        PracticeEngine e=engine("strict",60);
        Map<String,Object> event=on("c",60,0);event.put("timeMs",220);
        e.note(event);assertEquals(0,count(e.snapshot(),"late"));assertEquals(0d,rows(e.snapshot(),"played").getFirst().get("time"));
    }
    @Test public void repeatOccurrencesHaveSeparateResultsButOriginalSourceIdentity(){
        PracticeTimeline t=PracticeTimeline.fromGroups(List.of(data("onset",0,"notes",List.of(data("id","P1:0","occurrenceId","P1:0@0","midi",60,"duration",1))),data("onset",1,"notes",List.of(data("id","P1:0","occurrenceId","P1:0@1","midi",60,"duration",1)))),120);
        PracticeEngine e=new PracticeEngine(t,PracticeEngine.Config.fromMap(data("mode","wait","bpm",120)));e.note(on("a",60,0));e.note(off("a",60,0,300));e.note(on("b",60,500));
        assertEquals(List.of("P1:0@0"),rows(e.snapshot(),"results").get(0).get("occurrenceIds"));assertEquals(List.of("P1:0@1"),rows(e.snapshot(),"results").get(1).get("occurrenceIds"));
    }
    @Test public void recordedStrictComparisonRemovesOnlyConstantOffsetAndFreeModeDoesNotGradeTempo(){
        List<Map<String,Object>> notes=List.of(data("midi",60,"onset",1,"duration",.5,"confidence",.9),data("midi",62,"onset",1.72,"duration",.5,"confidence",.9));
        PracticeEngine.Config strict=PracticeEngine.Config.fromMap(data("mode","strict","bpm",120));
        Map<String,Object> fixed=RecordedAlignment.analyze(line(60,62),strict,notes);
        assertEquals(1,count(fixed,"late"));assertEquals("constant-offset",((Map<?,?>)fixed.get("alignment")).get("kind"));
        Map<String,Object> free=RecordedAlignment.analyze(line(60,62),PracticeEngine.Config.fromMap(data("mode","free","bpm",120)),notes);
        assertEquals(0,count(free,"late"));assertEquals(0,count(free,"short"));
    }
    @Test public void sustainedMedianIntonationDoesNotPenalizeIndividualVibratoExcursions(){
        PracticeEngine e=engine("free",60);
        Map<String,Object> first=on("bow",60,0);first.put("cents",48);e.note(first);
        double[] vibrato={-46,10,44,-45,0};
        for(int i=0;i<vibrato.length;i++){Map<String,Object> update=on("bow",60,0);update.put("type","note-update");update.put("timeMs",100d*(i+1));update.put("cents",vibrato[i]);e.note(update);}
        assertEquals(500d,rows(e.snapshot(),"played").getFirst().get("duration"));
        assertEquals(1,rows(e.snapshot(),"played").size());assertEquals(0,count(e.snapshot(),"intonation"));
        e.note(off("bow",60,0,600));assertEquals(0,rows(e.snapshot(),"pendingReview").size());
    }
    @Test public void stableSustainedDetuningProducesOneIntonationJudgmentAtTheSamePitch(){
        PracticeEngine e=engine("free",60);Map<String,Object> first=on("voice",60,0);first.put("cents",43);e.note(first);
        for(int i=1;i<=6;i++){Map<String,Object> update=on("voice",60,0);update.put("type","note-update");update.put("timeMs",100d*i);update.put("cents",42d+i%2);e.note(update);}
        assertEquals(1,count(e.snapshot(),"intonation"));assertEquals(0,count(e.snapshot(),"wrong"));assertEquals(1,rows(e.snapshot(),"played").size());
        assertEquals("corrected",rows(e.snapshot(),"results").getFirst().get("status"));e.note(off("voice",60,0,700));assertEquals(false,e.snapshot().get("active"));
    }
    @Test public void anotherAttackWhileTheFinalCorrectNoteIsHeldIsExtra(){
        PracticeEngine e=engine("strict",60);e.note(on("c",60,0));e.note(on("extra",64,120));
        assertEquals(1,count(e.snapshot(),"extra"));assertEquals(true,e.snapshot().get("awaitingRelease"));e.note(off("c",60,0,500));assertEquals(false,e.snapshot().get("active"));
    }
    @Test public void ambiguousNeighborPitchIsNotHardMissingAndRecordedEvidenceRecoversTheOriginalClock(){
        PracticeEngine e=engine("strict",60,62);Map<String,Object> weak=on("weak",61,0);weak.put("confidence",.3);e.note(weak);e.tick(310);
        assertEquals(1,count(e.snapshot(),"uncertain"));assertEquals(0,count(e.snapshot(),"missing"));
        List<Map<String,Object>> notes=List.of(data("midi",61,"onset",0,"duration",.4,"confidence",.3),data("midi",62,"onset",.5,"duration",.5,"confidence",.95),data("midi",64,"onset",1,"duration",.5,"confidence",.95));
        Map<String,Object> recorded=RecordedAlignment.analyze(line(60,62,64),PracticeEngine.Config.fromMap(data("mode","strict","bpm",120)),notes);
        assertEquals(0,count(recorded,"missing"));assertEquals(0,count(recorded,"wrong"));assertEquals(0,count(recorded,"late"));assertEquals(1,count(recorded,"uncertain"));
    }
    @Test public void keyboardIdsMayBeReusedAfterReleaseWithoutReplayingThePreviousNoteOff(){
        PracticeEngine e=engine("strict",60,60);e.note(on("key-c",60,0));e.note(off("key-c",60,0,450));
        e.note(on("key-c",60,500));assertEquals(true,e.snapshot().get("awaitingRelease"));assertEquals(true,e.snapshot().get("active"));
        e.note(off("key-c",60,500,1000));assertEquals(false,e.snapshot().get("active"));assertEquals(0,count(e.snapshot(),"short"));
    }
    @Test public void aSilentRecordedTakeHasNoInventedNotesOrHardMissingJudgments(){
        Map<String,Object> report=RecordedAlignment.analyze(line(60,62),PracticeEngine.Config.fromMap(data("mode","strict","bpm",120)),data("notes",List.of(),"seconds",1.5));
        assertEquals(0,count(report,"missing"));assertEquals(0L,report.get("firstTryCorrect"));assertTrue(rows(report,"played").isEmpty());
        assertEquals(2,count(report,"uncertain"));assertEquals("no-reliable-note-events",rows(report,"unjudged").getFirst().get("reason"));
        for(Map<String,Object> result:rows(report,"results")){assertEquals("uncertain",result.get("status"));Map<?,?> note=(Map<?,?>)((List<?>)result.get("notes")).getFirst();assertEquals("unjudged",note.get("judgment"));assertNull(note.get("actual"));}
    }
    @Test public void recordedDetectorLimitsProtectLowNotesWithoutProtectingInRangeMissingNotes(){
        List<Map<String,Object>> notes=List.of(data("midi",48,"onset",1,"duration",.5,"confidence",.95));
        Map<String,Object> report=RecordedAlignment.analyze(line(24,40,48),PracticeEngine.Config.fromMap(data("mode","strict","bpm",120)),data("notes",notes,"supportedPitchRange",data("minMidi",36,"maxMidi",96)));
        assertEquals(1,count(report,"uncertain"));assertEquals(1,count(report,"missing"));
        Map<String,Object> weak=rows(report,"errors").stream().filter(e->e.get("kind").equals("uncertain")).findFirst().orElseThrow();
        assertEquals("outside-detector-range",weak.get("reason"));assertEquals(List.of(24),weak.get("expected"));assertEquals(0d,weak.get("expectedTimeMs"));
        assertEquals(List.of(40),rows(report,"errors").stream().filter(e->e.get("kind").equals("missing")).findFirst().orElseThrow().get("expected"));
    }
    @Test public void recordedUnvoicedIntervalsDoNotInventHardMissingButLaterSilenceDoes(){
        List<Map<String,Object>> notes=List.of(data("midi",60,"onset",0,"duration",.5,"confidence",.95),data("midi",65,"onset",1.5,"duration",.5,"confidence",.95));
        Map<String,Object> report=RecordedAlignment.analyze(line(60,62,64,65),PracticeEngine.Config.fromMap(data("mode","strict","bpm",120)),data("notes",notes,"uncertaintyIntervals",List.of(data("onset",.45,"duration",.2,"reason","unvoiced"))));
        assertEquals(1,count(report,"uncertain"));assertEquals(1,count(report,"missing"));
        assertEquals(List.of(62),rows(report,"errors").stream().filter(e->e.get("kind").equals("uncertain")).findFirst().orElseThrow().get("expected"));
        assertEquals(List.of(64),rows(report,"errors").stream().filter(e->e.get("kind").equals("missing")).findFirst().orElseThrow().get("expected"));
    }
    @Test public void missingReplayTimeUsesTheShiftedPracticeClockAfterPause(){
        PracticeEngine e=engine("strict",60,62);e.note(on("c",60,0));e.note(off("c",60,0,450));e.pause(500);e.resume(2000);e.tick(2310);
        Map<String,Object> missing=rows(e.snapshot(),"errors").stream().filter(r->r.get("kind").equals("missing")).findFirst().orElseThrow();assertEquals(2000d,missing.get("expectedTimeMs"));assertEquals(500d,missing.get("onsetMs"));
    }
    @Test public void measuredPlaybackStartupShiftsResumedDueTimesWithoutRecountingPause(){
        PracticeEngine e=engine("strict",60,62);e.note(on("c",60,0));e.note(off("c",60,0,450));e.pause(500);e.resume(2000);e.shiftClock(260);
        e.note(on("d",62,2260));assertEquals(0,count(e.snapshot(),"late"));assertEquals(0,count(e.snapshot(),"missing"));assertEquals(1760d,((Map<?,?>)e.snapshot().get("alignment")).get("offsetMs"));
        assertThrows(IllegalArgumentException.class,()->e.shiftClock(-1));assertThrows(IllegalArgumentException.class,()->e.shiftClock(Double.NaN));
    }
    @Test public void nativeReleasesCannotMutateAnEarlierHttpSnapshotDuringSerialization(){
        PracticeEngine e=engine("strict",60);e.note(on("c",60,0));Map<String,Object> before=e.liveSnapshot();
        e.note(off("c",60,0,100));assertEquals("corrected",rows(e.snapshot(),"results").getFirst().get("status"));
        assertEquals("correct",rows(before,"results").getFirst().get("status"));assertFalse(rows(before,"played").getFirst().containsKey("duration"));
        Map<?,?> note=(Map<?,?>)((List<?>)rows(before,"results").getFirst().get("notes")).getFirst();assertFalse(((Map<?,?>)note.get("actual")).containsKey("duration"));
        assertTrue(rows(before,"errors").isEmpty());assertFalse(before.containsKey("groups"));assertFalse(before.containsKey("events"));
    }
    @Test public void recordedStableAggregateDetuningIsGradedOnceWithoutInventingLiveUpdates(){
        List<Map<String,Object>> notes=List.of(data("midi",60,"onset",0,"duration",.7,"confidence",.9,"engine","pyin","cents",43,"centsReliability","aggregate-median","centsSampleCount",54));
        Map<String,Object> report=RecordedAlignment.analyze(line(60),PracticeEngine.Config.fromMap(data("mode","free","bpm",120)),notes);
        assertEquals(1,count(report,"intonation"));assertEquals(0,count(report,"wrong"));assertEquals(0,rows(report,"pendingReview").size());assertEquals(2,rows(report,"events").size());
        assertEquals("recorded-aggregate",rows(report,"played").getFirst().get("intonationJudgmentSource"));assertEquals(43d,rows(report,"played").getFirst().get("cents"));
        Map<String,Object> octave=new java.util.LinkedHashMap<>(notes.getFirst());octave.put("midi",72);octave.put("cents",0);
        Map<String,Object> wrongOctave=RecordedAlignment.analyze(line(60),PracticeEngine.Config.fromMap(data("mode","free","bpm",120)),List.of(octave));assertEquals(1,count(wrongOctave,"wrong"));assertEquals(0,count(wrongOctave,"intonation"));assertEquals(72,rows(wrongOctave,"played").getFirst().get("midi"));
    }
    @Test public void coarseBasicPitchContourRemainsPendingWhileWaveformRefinementCanJudgeIntonation(){
        Map<String,Object> coarse=data("midi",60,"onset",0,"duration",.7,"confidence",.9,"engine","basic-pitch","cents",43,"centsResolution",100d/3);
        PracticeEngine.Config config=PracticeEngine.Config.fromMap(data("mode","free","bpm",120));Map<String,Object> pending=RecordedAlignment.analyze(line(60),config,List.of(coarse));
        assertEquals(0,count(pending,"intonation"));assertEquals(1,rows(pending,"pendingReview").size());
        Map<String,Object> refined=new java.util.LinkedHashMap<>(coarse);refined.put("centsReliability","spectral-estimate");refined.put("centsSampleCount",3);
        Map<String,Object> report=RecordedAlignment.analyze(line(60),config,List.of(refined));assertEquals(1,count(report,"intonation"));assertEquals(0,rows(report,"pendingReview").size());
    }
    @Test public void recordedStrictContextKeepsMissingFirstNoteSeparateFromLaterSamePitch(){
        List<Map<String,Object>> notes=List.of(data("midi",62,"onset",.5,"duration",.45,"confidence",.95),data("midi",60,"onset",1,"duration",.45,"confidence",.95),data("midi",64,"onset",1.5,"duration",.45,"confidence",.95));
        Map<String,Object> report=RecordedAlignment.analyze(line(60,62,60,64),PracticeEngine.Config.fromMap(data("mode","strict","bpm",120)),notes);
        assertEquals(0d,((Map<?,?>)report.get("alignment")).get("offsetMs"));assertEquals(1,count(report,"missing"));assertEquals(0,count(report,"wrong"));assertEquals(0,count(report,"late"));assertEquals(0,count(report,"extra"));assertEquals(3L,report.get("firstTryCorrect"));
        assertEquals(List.of("P1:0"),rows(report,"errors").stream().filter(e->e.get("kind").equals("missing")).findFirst().orElseThrow().get("sourceNoteIds"));
    }
    @Test public void recordedStrictContextAllowsOnlyOneWholePerformanceDelayAndStillGradesOneSlowBeat(){
        List<Map<String,Object>> notes=List.of(data("midi",60,"onset",1,"duration",.45,"confidence",.95),data("midi",62,"onset",1.72,"duration",.45,"confidence",.95),data("midi",60,"onset",2,"duration",.45,"confidence",.95),data("midi",64,"onset",2.5,"duration",.45,"confidence",.95));
        PracticeEngine.Config config=PracticeEngine.Config.fromMap(data("mode","strict","bpm",120));Map<String,Object> report=RecordedAlignment.analyze(line(60,62,60,64),config,notes);
        assertEquals(1000d,((Map<?,?>)report.get("alignment")).get("offsetMs"));assertEquals(1,count(report,"late"));assertEquals(0,count(report,"missing"));assertEquals(0,count(report,"wrong"));
        List<Map<String,Object>> delayed=notes.stream().map(n->{Map<String,Object> moved=new java.util.LinkedHashMap<>(n);moved.put("onset",((Number)n.get("onset")).doubleValue()+3);return moved;}).toList();
        Map<String,Object> later=RecordedAlignment.analyze(line(60,62,60,64),config,delayed);assertEquals(4000d,((Map<?,?>)later.get("alignment")).get("offsetMs"));assertEquals(1,count(later,"late"));
    }
    @Test public void highModelConfidenceCannotMakeAnUnprovedFragmentAdvanceARepeatedScoreNote(){
        Map<String,Object> fragment=data("midi",60,"onset",.5,"duration",.2,"confidence",.96,"engine","basic-pitch","cents",0,
                "reviewRequired",true,"onsetReliable",false,"reason","unconfirmed-repeated-onset","onsetEvidence",data("waveformAttack",false));
        Map<String,Object> report=RecordedAlignment.analyze(line(60,60),PracticeEngine.Config.fromMap(data("mode","strict","bpm",120,"gradeDuration",false)),
                List.of(data("midi",60,"onset",0,"duration",1,"confidence",.95),fragment));
        assertEquals(1L,report.get("firstTryCorrect"));assertEquals(1,rows(report,"played").size());assertEquals(0,count(report,"extra"));assertEquals(0,count(report,"wrong"));assertEquals(0,count(report,"missing"));assertEquals("uncertain",rows(report,"results").get(1).get("status"));
        Map<String,Object> originalEvent=rows(report,"unjudged").stream().filter(e->Boolean.TRUE.equals(e.get("reviewRequired"))).findFirst().orElseThrow();
        assertEquals(.96,originalEvent.get("confidence"));assertEquals("unconfirmed-repeated-onset",originalEvent.get("reason"));assertEquals(fragment,originalEvent.get("recordedNote"));
    }
    @Test public void correctedFourNotePracticeCountsOneWrittenMeasureInLiveAndRecordedReports(){
        PracticeEngine e=engine("wait",60,62,64,67);assertEquals(0,e.liveSnapshot().get("measureCount"));assertEquals(1,e.liveSnapshot().get("totalMeasureCount"));
        e.note(on("c",60,0));e.note(on("d",62,500));e.note(on("wrong-f",65,1000));e.note(on("e",64,1100));e.note(on("g",67,1500));assertEquals(1,e.liveSnapshot().get("measureCount"));
        Map<String,Object> report=RecordedAlignment.analyze(line(60,62,64,67),PracticeEngine.Config.fromMap(data("mode","free","bpm",120)),
                List.of(data("midi",60,"onset",0,"duration",.3),data("midi",62,"onset",.5,"duration",.3),data("midi",64,"onset",1,"duration",.3),data("midi",67,"onset",1.5,"duration",.3)));
        assertEquals(1,report.get("measureCount"));assertEquals(1,report.get("totalMeasureCount"));
    }
    @Test public void skippedUnplayedMeasuresDoNotCountAndRepeatVisitsCountOnlyOnce(){
        PracticeTimeline t=PracticeTimeline.fromGroups(List.of(data("onset",0,"mi",0,"notes",List.of(data("id","P1:0","midi",60,"duration",1))),
                data("onset",1,"mi",1,"notes",List.of(data("id","P1:1","midi",62,"duration",1))),data("onset",2,"mi",1,"notes",List.of(data("id","P1:1","occurrenceId","P1:1@1","midi",62,"duration",1)))),120);
        PracticeEngine e=new PracticeEngine(t,PracticeEngine.Config.fromMap(data("mode","wait","bpm",120)));e.restart(1,0);assertEquals(0,e.snapshot().get("measureCount"));
        e.note(on("d1",62,0));e.note(off("d1",62,0,400));e.note(on("d2",62,500));assertEquals(1,e.snapshot().get("measureCount"));assertEquals(2,e.snapshot().get("totalMeasureCount"));
    }
    @Test public void recordedWrongOctaveHasOneVisibleIdentityErrorAndRetainsTheMissingTrace(){
        Map<String,Object> report=RecordedAlignment.analyze(line(60,62,84,65),PracticeEngine.Config.fromMap(data("mode","strict","bpm",120,"startTimeMs",0)),
                List.of(data("midi",60,"onset",0,"duration",.45),data("midi",62,"onset",.5,"duration",.45),data("midi",72,"onset",1,"duration",.45),data("midi",65,"onset",1.5,"duration",.45)));
        assertEquals(1,visibleCount(report,"wrong"));assertEquals(0,visibleCount(report,"missing"));assertEquals(1,count(report,"missing"));
        Map<String,Object> wrong=rows(report,"errors").stream().filter(e->e.get("kind").equals("wrong")).findFirst().orElseThrow();
        Map<String,Object> missing=rows(report,"errors").stream().filter(e->e.get("kind").equals("missing")).findFirst().orElseThrow();
        assertEquals(List.of(84),wrong.get("expected"));assertEquals(wrong.get("eventId"),missing.get("coveredByWrong"));assertEquals(true,missing.get("resolved"));
        Map<?,?> note=(Map<?,?>)((List<?>)rows(report,"results").get(2).get("notes")).getFirst();assertEquals(false,note.get("matched"));assertNull(note.get("actual"));assertEquals(3L,report.get("firstTryCorrect"));
    }
    @Test public void genuinelyMissingRecordedNoteRemainsAVisibleMissingError(){
        Map<String,Object> report=RecordedAlignment.analyze(line(60,62,64),PracticeEngine.Config.fromMap(data("mode","strict","bpm",120,"startTimeMs",0)),
                List.of(data("midi",60,"onset",0,"duration",.45),data("midi",64,"onset",1,"duration",.45)));
        assertEquals(0,visibleCount(report,"wrong"));assertEquals(1,visibleCount(report,"missing"));
        assertEquals(List.of(62),rows(report,"errors").stream().filter(e->e.get("kind").equals("missing")).findFirst().orElseThrow().get("expected"));
    }
    @Test public void playingOnlyOneChordPitchDoesNotHideTheOtherMissingPitch(){
        Map<String,Object> report=RecordedAlignment.analyze(chord(60,64),PracticeEngine.Config.fromMap(data("mode","strict","bpm",120,"startTimeMs",0)),List.of(data("midi",60,"onset",0,"duration",.45)));
        assertEquals(0,visibleCount(report,"wrong"));assertEquals(1,visibleCount(report,"missing"));assertEquals(List.of(64),rows(report,"errors").getFirst().get("expected"));
    }
    @Test public void aCorrectedWrongChordPitchCannotSuppressOtherUnplayedPitches(){
        Map<String,Object> report=RecordedAlignment.analyze(chord(60,64,67),PracticeEngine.Config.fromMap(data("mode","strict","bpm",120,"startTimeMs",0)),
                List.of(data("midi",61,"onset",0,"duration",.45),data("midi",60,"onset",.04,"duration",.45)));
        assertEquals(1,visibleCount(report,"wrong"));assertEquals(1,visibleCount(report,"missing"));assertEquals(1,count(report,"missing"));
        assertEquals(List.of(64,67),rows(report,"errors").stream().filter(e->e.get("kind").equals("missing")).findFirst().orElseThrow().get("expected"));
    }
    @Test public void oneWrongChordSubstitutionSuppressesOnlyOneMissingIdentity(){
        Map<String,Object> report=RecordedAlignment.analyze(chord(60,64,67),PracticeEngine.Config.fromMap(data("mode","strict","bpm",120,"startTimeMs",0)),
                List.of(data("midi",65,"onset",0,"duration",.45),data("midi",60,"onset",.04,"duration",.45)));
        assertEquals(1,visibleCount(report,"wrong"));assertEquals(1,visibleCount(report,"missing"));assertEquals(2,count(report,"missing"));
        Map<String,Object> uncovered=rows(report,"errors").stream().filter(e->e.get("kind").equals("missing")&&!Boolean.TRUE.equals(e.get("resolved"))).findFirst().orElseThrow();
        assertEquals(List.of(67),uncovered.get("expected"));assertEquals(List.of("P1:2"),uncovered.get("sourceNoteIds"));
        Map<String,Object> covered=rows(report,"errors").stream().filter(e->e.get("kind").equals("missing")&&Boolean.TRUE.equals(e.get("resolved"))).findFirst().orElseThrow();assertEquals(List.of(64),covered.get("expected"));
    }
    @Test public void aReliableRecordedTailAttackAfterFinalReleaseIsExtraButLiveStaysFinished(){
        PracticeEngine.Config config=PracticeEngine.Config.fromMap(data("mode","strict","bpm",120,"startTimeMs",0));
        Map<String,Object> report=RecordedAlignment.analyze(line(60),config,List.of(data("midi",60,"onset",0,"duration",.5),data("midi",64,"onset",.7,"duration",.3)));
        assertEquals(1,visibleCount(report,"extra"));assertEquals(2,rows(report,"played").size());assertEquals(64,rows(report,"played").get(1).get("midi"));assertEquals(false,report.get("active"));
        Map<?,?> correct=(Map<?,?>)((List<?>)rows(report,"results").getFirst().get("notes")).getFirst();assertEquals(true,correct.get("matched"));assertNotNull(correct.get("actual"));
        PracticeEngine live=engine("strict",60);live.note(on("c",60,0));live.note(off("c",60,0,500));live.note(on("later",64,700));
        assertEquals(false,live.snapshot().get("active"));assertEquals(0,count(live.snapshot(),"extra"));assertEquals(1,rows(live.snapshot(),"played").size());
    }
    @Test public void uncertainRecordedTailFragmentsStayUnjudgedWithTheirActualConfidence(){
        Map<String,Object> fragment=data("midi",64,"onset",.7,"duration",.2,"confidence",.96,"reviewRequired",true,"onsetReliable",false,"reason","unconfirmed-tail-onset");
        Map<String,Object> report=RecordedAlignment.analyze(line(60),PracticeEngine.Config.fromMap(data("mode","strict","bpm",120,"startTimeMs",0)),
                List.of(data("midi",60,"onset",0,"duration",.5),fragment,data("midi",67,"onset",1,"duration",.2,"confidence",.3)));
        assertEquals(0,count(report,"extra"));assertEquals(0,count(report,"wrong"));assertEquals(1,rows(report,"played").size());assertEquals(2,rows(report,"unjudged").size());assertEquals(false,report.get("active"));
        assertEquals(.96,rows(report,"unjudged").getFirst().get("confidence"));assertEquals(fragment,rows(report,"unjudged").getFirst().get("recordedNote"));assertEquals(1L,report.get("firstTryCorrect"));
    }
}
