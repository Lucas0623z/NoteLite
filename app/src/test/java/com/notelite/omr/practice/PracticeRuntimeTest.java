/* Copyright © NoteLite 2026. GNU Affero General Public License, version 3 or later. */
package com.notelite.omr.practice;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.lang.reflect.Field;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.zip.ZipInputStream;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import static org.junit.Assert.*;
import static org.junit.Assume.assumeTrue;

/** Exercises failed recording joins and real local score preparation at the session boundary. */
public class PracticeRuntimeTest {
    private Path directory;
    private String previousHome;

    @Before public void isolateStore() throws Exception {
        Path base=Path.of(Files.isDirectory(Path.of("app","src"))?"app/build/test-tmp":"build/test-tmp").toAbsolutePath().normalize();
        Files.createDirectories(base);
        directory=Files.createTempDirectory(base,"practice-runtime-");
        previousHome=System.getProperty("notelite.practice.home");
        System.setProperty("notelite.practice.home",directory.resolve("takes").toString());
    }
    @After public void cleanup() throws Exception {
        if(previousHome==null)System.clearProperty("notelite.practice.home");
        else System.setProperty("notelite.practice.home",previousHome);
        if(directory!=null)try(var paths=Files.walk(directory)){
            for(Path path:paths.sorted(Comparator.reverseOrder()).toList())Files.deleteIfExists(path);
        }
    }

    @Test public void overlappingCapturesPreserveJudgmentAndBothOriginalSegments() throws Exception {
        assertRecoveryAfterFailedJoin(List.of(new PracticeWave.Segment(audio(8000,800,1000),0),
                new PracticeWave.Segment(audio(8000,800,2000),50)));
    }
    @Test public void captureDeviceFormatChangePreservesJudgmentAndBothOriginalSegments() throws Exception {
        assertRecoveryAfterFailedJoin(List.of(new PracticeWave.Segment(audio(8000,800,1000),0),
                new PracticeWave.Segment(audio(16000,1600,2000),150)));
    }
    @Test public void failedRecordedJoinSavesRecoveryBeforeTheNextStartClearsCaptureSegments() throws Exception {
        assumeTrue("Install Partitura to start the next real prepared session",LocalAudioAnalysis.capabilities().getOrDefault("partitura",false));
        PracticeRuntime runtime=new PracticeRuntime(score(false,false),"{}");
        byte[] first=audio(8000,800,1000),second=audio(16000,1600,2000);
        try{
            installScoredSession(runtime,List.of(new PracticeWave.Segment(first,0),new PracticeWave.Segment(second,150)));
            IOException failure=assertThrows(IOException.class,runtime::capturedWav);assertTrue(failure.getMessage().contains("设备格式"));
            Map<String,Object> saved=runtime.snapshot();String id=(String)saved.get("takeId");assertNotNull(id);assertEquals("corrected",row(saved,"results").get("status"));
            assertEquals(2,((List<?>)saved.get("recoveryRecordings")).size());byte[] originalReport=reportBytes(runtime.store(),id);
            // Retry the same failed join after finish removed the live engine.
            assertThrows(IOException.class,runtime::capturedWav);assertEquals(id,runtime.snapshot().get("takeId"));
            originalReport=reportBytes(runtime.store(),id);
            Map<String,Object> next=runtime.start(Map.of("verified",true,"mode","wait","bpm",100,"input","keyboard","part","all","from",1,"to",1,"a4",440));
            assertEquals(Boolean.TRUE,next.get("active"));assertEquals(Boolean.FALSE,next.get("hasRecording"));
            assertArrayEquals(originalReport,reportBytes(runtime.store(),id));assertEquals(2,((List<?>)runtime.store().report(id).get("recoveryRecordings")).size());
            assertArrayEquals(first,Files.readAllBytes(runtime.store().root().resolve(id).resolve("recovery-001.wav")));
            assertArrayEquals(second,Files.readAllBytes(runtime.store().root().resolve(id).resolve("recovery-002.wav")));
        }finally{runtime.close();}
    }

    private void assertRecoveryAfterFailedJoin(List<PracticeWave.Segment> captured) throws Exception {
        // Two 100 ms clips exercise the actual join failure without allocating a long take.
        PracticeRuntime runtime=new PracticeRuntime(score(false,false),"{}");
        try {
            installScoredSession(runtime,captured);
            Map<String,Object> saved=runtime.finish();String id=(String)saved.get("takeId");
            assertNotNull(id);assertEquals(Boolean.TRUE,saved.get("completed"));
            assertEquals("corrected",row(saved,"results").get("status"));
            assertEquals("wrong",row(saved,"errors").get("kind"));
            assertEquals(List.of("P1:0@0"),row(saved,"errors").get("occurrenceIds"));
            assertTrue(String.valueOf(saved.get("warning")).contains("原始片段"));
            assertEquals(Boolean.FALSE,saved.get("hasRecording"));
            assertThrows(IOException.class,()->runtime.store().recording(id));
            List<?> recovery=(List<?>)saved.get("recoveryRecordings");assertEquals(2,recovery.size());
            for(int i=0;i<captured.size();i++){
                Map<String,Object> entry=PracticeJson.object(recovery.get(i));
                assertEquals(captured.get(i).onsetMs(),((Number)entry.get("onsetMs")).doubleValue(),0);
                assertArrayEquals(captured.get(i).wav(),Files.readAllBytes(runtime.store().root().resolve(id).resolve((String)entry.get("file"))));
            }
            Map<String,Object> reloaded=runtime.store().report(id);
            assertEquals(saved.get("warning"),reloaded.get("warning"));
            assertEquals("corrected",row(reloaded,"results").get("status"));
            assertEquals("wrong",row(reloaded,"errors").get("kind"));
            Map<String,byte[]> packageFiles=unzip(runtime.store().bundle(id));
            assertArrayEquals(captured.get(0).wav(),packageFiles.get("recovery-001.wav"));
            assertArrayEquals(captured.get(1).wav(),packageFiles.get("recovery-002.wav"));
            assertTrue(packageFiles.containsKey("report.json"));assertTrue(packageFiles.containsKey("practice.json"));
            assertFalse(packageFiles.containsKey("recording.wav"));
            assertEquals(id,runtime.finish().get("takeId"));assertEquals(1,runtime.store().list().size());
        } finally {runtime.close();}
    }

    @Test public void actualNormalizerRejectsChordAndOverlappingVoicesForAllMonoEngines() throws Exception {
        assumeTrue("Install the full local analysis runtime to exercise Partitura",LocalAudioAnalysis.capabilities().getOrDefault("partitura",false));
        for(boolean overlap:List.of(false,true)) {
            byte[] xml=score(!overlap,overlap);
            Map<String,Object> prepared=PracticeJson.object(PracticeJson.parse(new String(LocalAudioAnalysis.normalize(xml,Map.of("part","all","from",1,"to",1)),StandardCharsets.UTF_8)));
            List<?> groups=(List<?>)prepared.get("groups");
            assertEquals(overlap?2:1,groups.size());
            if(!overlap)assertEquals(2,((List<?>)PracticeJson.object(groups.getFirst()).get("notes")).size());
            for(String detector:List.of("pyin","crepe","aubio")) {
                PracticeRuntime runtime=new PracticeRuntime(xml,"{}");
                try {
                    IOException failure=assertThrows(IOException.class,()->runtime.analyze(audio(8000,800,0),
                            Map.of("engine",detector,"mode","free","bpm",100,"a4",440,"part","all","from",1,"to",1)));
                    assertTrue(detector+": "+failure.getMessage(),failure.getMessage().contains("和弦或重叠音"));
                    assertTrue("Rejected mono takes must not create a scored report",runtime.store().list().isEmpty());
                } finally {runtime.close();}
            }
        }
    }

    @Test public void restoredTakeReopensWithItsScoreRecordingAndResultIdentity() throws Exception {
        PracticeRuntime runtime=new PracticeRuntime(score(false,false),"{}");
        try {
            byte[] wav=audio(8000,800,1000);installScoredSession(runtime,List.of(new PracticeWave.Segment(wav,0)));
            String id=(String)runtime.finish().get("takeId");runtime.store().remove(id);
            assertTrue(runtime.store().list().isEmpty());assertThrows(IOException.class,()->runtime.store().report(id));
            String key=(String)runtime.store().trash().getFirst().get("key");runtime.store().restore(key);
            assertTrue(runtime.store().trash().isEmpty());assertEquals(1,runtime.store().list().size());
            Map<String,Object> restored=runtime.openTake(id);
            assertEquals(id,restored.get("takeId"));assertEquals("corrected",row(restored,"results").get("status"));
            assertEquals(List.of("P1:0@0"),row(restored,"errors").get("occurrenceIds"));
            assertArrayEquals(score(false,false),runtime.store().score(id));
            assertArrayEquals(wav,Files.readAllBytes(runtime.store().recording(id)));
        } finally {runtime.close();}
    }

    @Test public void everyNewImportedRecordingGetsItsOwnTakeWithoutOverwritingPreviousHistory() throws Exception {
        requireActualRecordedRuntime();
        PracticeRuntime runtime=new PracticeRuntime(score(false,false),"{}");
        try {
            byte[] originalWav=audio(8000,800,1000);
            installScoredSession(runtime,List.of(new PracticeWave.Segment(originalWav,0)));
            String originalId=(String)runtime.finish().get("takeId");
            byte[] originalReport=reportBytes(runtime.store(),originalId);
            byte[] firstWav=audio(8000,800,0),secondWav=audio(8000,1600,0);
            Map<String,Object> first=runtime.analyze(firstWav,analysisOptions("aubio"));
            String firstId=(String)first.get("takeId");byte[] firstReport=reportBytes(runtime.store(),firstId);
            Map<String,Object> second=runtime.analyze(secondWav,analysisOptions("aubio"));
            String secondId=(String)second.get("takeId");
            assertNotEquals(originalId,firstId);assertNotEquals(originalId,secondId);assertNotEquals(firstId,secondId);
            assertEquals(3,runtime.store().list().size());
            assertArrayEquals(originalReport,reportBytes(runtime.store(),originalId));
            assertArrayEquals(firstReport,reportBytes(runtime.store(),firstId));
            assertArrayEquals(originalWav,Files.readAllBytes(runtime.store().recording(originalId)));
            assertArrayEquals(firstWav,Files.readAllBytes(runtime.store().recording(firstId)));
            assertArrayEquals(secondWav,Files.readAllBytes(runtime.store().recording(secondId)));
            assertEquals("corrected",row(runtime.store().report(originalId),"results").get("status"));
            assertFalse(first.containsKey("analysisPending"));assertFalse(second.containsKey("analysisPending"));
        } finally {runtime.close();}
    }

    @Test public void failedActualAnalysisRetainsNewRecordingAndFailedRecheckPreservesExistingReport() throws Exception {
        requireActualRecordedRuntime();
        PracticeRuntime runtime=new PracticeRuntime(score(false,false),"{}");
        try {
            byte[] originalWav=audio(8000,800,1000);
            installScoredSession(runtime,List.of(new PracticeWave.Segment(originalWav,0)));
            String originalId=(String)runtime.finish().get("takeId");byte[] originalReport=reportBytes(runtime.store(),originalId);
            byte[] newWav=audio(8000,1600,0);
            IOException failure=assertThrows(IOException.class,()->runtime.analyze(newWav,analysisOptions("unknown-test-engine")));
            assertTrue(failure.getMessage(),failure.getMessage().contains("Unknown monophonic review engine"));
            Map<String,Object> pending=runtime.snapshot();String pendingId=(String)pending.get("takeId");
            assertNotNull(pendingId);assertNotEquals(originalId,pendingId);
            assertEquals(Boolean.TRUE,pending.get("analysisPending"));assertEquals(Boolean.TRUE,pending.get("hasRecording"));
            assertEquals(Boolean.FALSE,pending.get("completed"));assertNotNull(pending.get("warning"));
            assertEquals(2,runtime.store().list().size());
            assertArrayEquals(newWav,Files.readAllBytes(runtime.store().recording(pendingId)));
            assertEquals(Boolean.TRUE,runtime.openTake(pendingId).get("analysisPending"));
            assertArrayEquals(score(false,false),runtime.store().score(pendingId));
            // Retry really invokes the shipped aubio helper and updates this take in place.
            Map<String,Object> reviewed=runtime.recheck(pendingId,Map.of("engine","aubio","verified",true));
            assertEquals(pendingId,reviewed.get("takeId"));assertFalse(reviewed.containsKey("analysisPending"));
            byte[] reviewedReport=reportBytes(runtime.store(),pendingId);
            IOException recheckFailure=assertThrows(IOException.class,()->runtime.recheck(pendingId,Map.of("engine","unknown-test-engine")));
            assertTrue(recheckFailure.getMessage(),recheckFailure.getMessage().contains("Unknown monophonic review engine"));
            assertArrayEquals(reviewedReport,reportBytes(runtime.store(),pendingId));
            assertArrayEquals(newWav,Files.readAllBytes(runtime.store().recording(pendingId)));
            assertFalse(runtime.openTake(pendingId).containsKey("analysisPending"));
            assertArrayEquals(originalReport,reportBytes(runtime.store(),originalId));
            assertArrayEquals(originalWav,Files.readAllBytes(runtime.store().recording(originalId)));
            assertEquals(2,runtime.store().list().size());
        } finally {runtime.close();}
    }

    @Test public void successfulStoredTakeRecheckRoundTripsJsonNumbersAndChangesActualEngineAndBaseline() throws Exception {
        requireActualRecordedRuntime();Map<String,Boolean> capabilities=LocalAudioAnalysis.capabilities();
        assumeTrue("Install actual pYIN and native Nakamura for stored-take recheck",capabilities.getOrDefault("pyin",false)&&capabilities.getOrDefault("nakamura",false));
        byte[] sourceScore=recheckMelody();PracticeRuntime runtime=new PracticeRuntime(sourceScore,"{}");
        java.util.ArrayList<Map<String,Object>> performed=new java.util.ArrayList<>();int[] pitches={60,62,64};
        for(int i=0;i<pitches.length;i++)performed.add(PracticeEngine.fields("onset",i,"notes",List.of(PracticeEngine.fields("midi",pitches[i],"onset",i,"duration",1))));
        byte[] wav=PracticeWave.reference(performed,100,440,0);
        try{
            Map<String,Object> options=new LinkedHashMap<>(analysisOptions("aubio"));options.put("baseline","parangonar");
            Map<String,Object> first=runtime.analyze(wav,options);String id=(String)first.get("takeId");
            Map<String,Object> archived=runtime.store().report(id);Map<String,Object> archivedMetadata=PracticeJson.object(archived.get("metadata"));
            assertTrue("Practice JSON reads numeric selection values as doubles",archivedMetadata.get("from") instanceof Double);
            assertTrue(archivedMetadata.get("to") instanceof Double);assertTrue(archivedMetadata.get("bpm") instanceof Double);
            assertEquals("aubio",PracticeJson.object(archived.get("transcription")).get("engine"));assertEquals("parangonar",PracticeJson.object(archived.get("baseline")).get("engine"));
            List<?> sourceIds=((List<?>)archived.get("groups")).stream().map(PracticeJson::object).flatMap(group->((List<?>)group.get("sourceNoteIds")).stream()).toList();assertEquals(3,sourceIds.size());
            Map<String,Object> reviewed=runtime.recheck(id,Map.of("engine","pyin","baseline","nakamura"));
            assertEquals(id,reviewed.get("takeId"));assertEquals("pyin",reviewed.get("engine"));
            assertEquals("pyin",PracticeJson.object(reviewed.get("transcription")).get("engine"));assertEquals("nakamura",PracticeJson.object(reviewed.get("baseline")).get("engine"));
            assertTrue(((List<?>)PracticeJson.object(reviewed.get("transcription")).get("notes")).size()>=3);assertTrue(((List<?>)PracticeJson.object(reviewed.get("baseline")).get("pairs")).size()>=3);
            assertEquals(Boolean.TRUE,PracticeJson.object(PracticeJson.object(reviewed.get("baseline")).get("metadata")).get("evaluated"));
            assertEquals(sourceIds,((List<?>)reviewed.get("groups")).stream().map(PracticeJson::object).flatMap(group->((List<?>)group.get("sourceNoteIds")).stream()).toList());
            assertEquals(sourceIds,((List<?>)runtime.store().report(id).get("groups")).stream().map(PracticeJson::object).flatMap(group->((List<?>)group.get("sourceNoteIds")).stream()).toList());
            assertArrayEquals(wav,Files.readAllBytes(runtime.store().recording(id)));assertArrayEquals(sourceScore,runtime.store().score(id));assertEquals(1,runtime.store().list().size());
            assertEquals("pyin",PracticeJson.object(runtime.openTake(id).get("metadata")).get("engine"));
        }finally{runtime.close();}
    }

    @Test public void invalidIdsAndTrashKeysCannotReachAnOutsideFileOrOverwriteARestoredTake() throws Exception {
        PracticeTakeStore store=new PracticeTakeStore();byte[] outside="preserve me".getBytes(StandardCharsets.UTF_8);
        Path sentinel=directory.resolve("outside.txt");Files.write(sentinel,outside);
        String id=(String)store.save(null,score(false,false),Map.of(),Map.of("title","Original"),null).get("takeId");
        for(String invalid:List.of("../outside.txt","..\\outside.txt",sentinel.toString(),id+"/../outside.txt",id+"\\..\\outside.txt","")){
            assertThrows(IOException.class,()->store.score(invalid));
            assertThrows(IOException.class,()->store.remove(invalid));
            assertThrows(IOException.class,()->store.restore(invalid));
        }
        assertThrows(IOException.class,()->store.restore(null));
        store.remove(id);String key=(String)store.trash().getFirst().get("key");
        for(String invalid:List.of("../"+key,key+"/../outside.txt",key+"\\..\\outside.txt"))assertThrows(IOException.class,()->store.restore(invalid));
        // A same-ID replacement must never be overwritten by a trash restore.
        store.save(id,score(false,false),Map.of(),Map.of("title","Replacement"),null);
        assertThrows(IOException.class,()->store.restore(key));
        assertEquals("Replacement",store.report(id).get("title"));assertEquals(1,store.trash().size());
        assertArrayEquals(outside,Files.readAllBytes(sentinel));
    }

    private static void installScoredSession(PracticeRuntime runtime,List<PracticeWave.Segment> segments) throws Exception {
        List<?> groups=List.of(PracticeEngine.fields("onset",0,"measure","1","mi",0,"beat",1,"notes",List.of(
                PracticeEngine.fields("id","P1:0","sourceNoteId","P1:0","occurrenceId","P1:0@0","part","P1","staff","1","midi",60,"duration",1))));
        Map<String,Object> config=Map.of("mode","wait","bpm",100,"input","microphone");
        PracticeEngine engine=new PracticeEngine(PracticeTimeline.fromGroups(groups,100),PracticeEngine.Config.fromMap(config));
        engine.note(PracticeEngine.fields("type","note-on","id","wrong","midi",61,"onsetMs",0,"timeMs",0,"confidence",1,"cents",0,"voiced",true));
        engine.note(PracticeEngine.fields("type","note-off","id","wrong","midi",61,"onsetMs",0,"offsetMs",40,"durationMs",40,"timeMs",40,"confidence",1,"cents",0,"voiced",false));
        engine.note(PracticeEngine.fields("type","note-on","id","correct","midi",60,"onsetMs",50,"timeMs",50,"confidence",1,"cents",0,"voiced",true));
        engine.note(PracticeEngine.fields("type","note-off","id","correct","midi",60,"onsetMs",50,"offsetMs",150,"durationMs",100,"timeMs",150,"confidence",1,"cents",0,"voiced",false));
        set(runtime,"prepared",Map.of("groups",groups));set(runtime,"config",config);set(runtime,"engine",engine);
        set(runtime,"sessionEpoch",PracticeRuntime.clock()-200);set(runtime,"createdAt",Instant.now().toString());
        @SuppressWarnings("unchecked") List<PracticeWave.Segment> actual=(List<PracticeWave.Segment>)field("segments").get(runtime);actual.addAll(segments);
    }
    private static Field field(String name) throws Exception {Field field=PracticeRuntime.class.getDeclaredField(name);field.setAccessible(true);return field;}
    private static void set(PracticeRuntime runtime,String name,Object value) throws Exception {field(name).set(runtime,value);}
    private static Map<String,Object> row(Map<String,Object> report,String name){return PracticeJson.object(((List<?>)report.get(name)).getFirst());}
    private static void requireActualRecordedRuntime(){Map<String,Boolean> capabilities=LocalAudioAnalysis.capabilities();assumeTrue("Install Partitura and actual aubio for recorded persistence regression",capabilities.getOrDefault("partitura",false)&&capabilities.getOrDefault("aubio",false));}
    private static Map<String,Object> analysisOptions(String engine){return Map.of("engine",engine,"mode","free","bpm",100,"a4",440,"part","all","from",1,"to",1,"input","recording","verified",true);}
    private static byte[] reportBytes(PracticeTakeStore store,String id) throws IOException {return Files.readAllBytes(store.root().resolve(id).resolve("report.json"));}
    private static Map<String,byte[]> unzip(byte[] bytes) throws IOException {
        Map<String,byte[]> entries=new LinkedHashMap<>();try(ZipInputStream zip=new ZipInputStream(new ByteArrayInputStream(bytes),StandardCharsets.UTF_8)){
            java.util.zip.ZipEntry entry;while((entry=zip.getNextEntry())!=null)entries.put(entry.getName(),zip.readAllBytes());
        }return entries;
    }
    private static byte[] audio(int rate,int frames,int amplitude){ByteBuffer data=ByteBuffer.allocate(frames*2).order(ByteOrder.LITTLE_ENDIAN);for(int i=0;i<frames;i++)data.putShort((short)amplitude);return PracticeWave.wrap(data.array(),rate,1);}
    private static byte[] recheckMelody(){
        StringBuilder xml=new StringBuilder("<?xml version=\"1.0\" encoding=\"UTF-8\"?><score-partwise version=\"4.0\"><part-list><score-part id=\"P1\"><part-name>Flute</part-name></score-part></part-list><part id=\"P1\"><measure number=\"1\"><attributes><divisions>1</divisions><key><fifths>0</fifths></key><time><beats>3</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes>");
        for(String step:List.of("C","D","E"))xml.append("<note id=\"").append(step.toLowerCase()).append("\"><pitch><step>").append(step).append("</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice><type>quarter</type><staff>1</staff></note>");
        return xml.append("</measure></part></score-partwise>").toString().getBytes(StandardCharsets.UTF_8);
    }
    private static byte[] score(boolean chord,boolean overlap){
        String extra=chord?"<note id=\"e\"><chord/><pitch><step>E</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice><type>whole</type></note>":
                overlap?"<backup><duration>2</duration></backup><note><rest/><duration>1</duration><voice>2</voice><type>quarter</type></note><note id=\"e\"><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><voice>2</voice><type>quarter</type></note>":"";
        String duration=overlap?"2":"4",type=overlap?"half":"whole";
        return ("<?xml version=\"1.0\" encoding=\"UTF-8\"?><score-partwise version=\"4.0\"><part-list><score-part id=\"P1\"><part-name>Piano</part-name></score-part></part-list><part id=\"P1\"><measure number=\"1\"><attributes><divisions>1</divisions><key><fifths>0</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes><note id=\"c\"><pitch><step>C</step><octave>4</octave></pitch><duration>"+duration+"</duration><voice>1</voice><type>"+type+"</type></note>"+extra+"</measure></part></score-partwise>").getBytes(StandardCharsets.UTF_8);
    }
}
