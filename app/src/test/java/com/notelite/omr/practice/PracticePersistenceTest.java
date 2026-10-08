/* Copyright © NoteLite 2026. GNU Affero General Public License, version 3 or later. */
package com.notelite.omr.practice;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.zip.ZipInputStream;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import static org.junit.Assert.*;

/** Real local save/reload/export and PCM alignment, without UI or model inference. */
public class PracticePersistenceTest {
    private Path directory;
    private String previousHome;
    @Before public void isolateStore() throws Exception {
        directory=Files.createTempDirectory("notelite-persistence-test-");
        previousHome=System.getProperty("notelite.practice.home");System.setProperty("notelite.practice.home",directory.toString());
    }
    @After public void cleanup() throws Exception {
        if(previousHome==null)System.clearProperty("notelite.practice.home");else System.setProperty("notelite.practice.home",previousHome);
        if(directory!=null)try(var paths=Files.walk(directory)){for(Path path:paths.sorted(Comparator.reverseOrder()).toList())Files.deleteIfExists(path);}
    }
    private static byte[] audio(int frames,int amplitude){ByteBuffer data=ByteBuffer.allocate(frames*2).order(ByteOrder.LITTLE_ENDIAN);for(int i=0;i<frames;i++)data.putShort((short)amplitude);return PracticeWave.wrap(data.array(),8000,1);}
    private static byte[] score(String title){return ("<score-partwise><work><work-title>"+title+"</work-title></work></score-partwise>").getBytes(StandardCharsets.UTF_8);}
    private static Map<String,Object> report(String title){return Map.of("title",title,"createdAt","2026-10-08T12:00:00Z","input","microphone","currentIndex",1,"total",2,"completed",false,
            "errors",List.of(Map.of("kind","wrong","sourceNoteIds",List.of("P1:3"),"occurrenceIds",List.of("P1:3@1"),"played",61,"expected",List.of(60))),
            "events",List.of(Map.of("type","note-on","id","capture1:n1","midi",61,"onsetMs",100d,"confidence",.95)));
    }
    @Test public void savedTakeRoundTripsOriginalScoreAudioIdentityAndRawEvents() throws Exception {
        PracticeTakeStore store=new PracticeTakeStore();byte[] xml=score("练习与重奏"),wav=audio(800,1000);
        Map<String,Object> pack=Map.of("format","notelite-practice-package","omrMetadata",Map.of("origin","local-omr"),"sourceIds",List.of("P1:3"));
        Map<String,Object> saved=store.save(null,xml,pack,report("练习与重奏"),wav);String id=(String)saved.get("takeId");
        assertArrayEquals(xml,store.score(id));assertArrayEquals(wav,Files.readAllBytes(store.recording(id)));
        Map<String,Object> restored=store.report(id);assertEquals("练习与重奏",restored.get("title"));assertEquals(Boolean.TRUE,restored.get("hasRecording"));
        assertEquals(List.of("P1:3"),store.timeline(id).get("sourceIds"));
        Map<?,?> error=(Map<?,?>)((List<?>)restored.get("errors")).getFirst();assertEquals(List.of("P1:3@1"),error.get("occurrenceIds"));
        assertEquals(1,((List<?>)restored.get("events")).size());assertEquals(1,store.list().size());
    }
    @Test public void updatingJudgmentKeepsTheOriginalRecordingAndExportsACompletePortablePackage() throws Exception {
        PracticeTakeStore store=new PracticeTakeStore();byte[] xml=score("First"),wav=audio(800,1000);
        String id=(String)store.save(null,xml,Map.of("groups",List.of()),report("First"),wav).get("takeId");
        store.save(id,xml,Map.of("groups",List.of()),report("Rechecked"),null);
        assertArrayEquals(wav,Files.readAllBytes(store.recording(id)));assertEquals(Boolean.TRUE,store.report(id).get("hasRecording"));
        Set<String> entries=new HashSet<>();try(ZipInputStream zip=new ZipInputStream(new ByteArrayInputStream(store.bundle(id)),StandardCharsets.UTF_8)){
            java.util.zip.ZipEntry entry;while((entry=zip.getNextEntry())!=null){entries.add(entry.getName());if(entry.getName().equals("recording.wav"))assertArrayEquals(wav,zip.readAllBytes());}
        }
        assertEquals(Set.of("source.musicxml","practice.json","report.json","recording.wav"),entries);
    }
    @Test public void malformedNewRecordingCannotPartiallyOverwriteAnExistingTake() throws Exception {
        PracticeTakeStore store=new PracticeTakeStore();byte[] original=score("Keep me"),wav=audio(800,1000);
        String id=(String)store.save(null,original,Map.of("revision","original"),report("Original"),wav).get("takeId");
        assertThrows(IOException.class,()->store.save(id,score("Bad replacement"),Map.of("revision","changed"),report("Changed"),new byte[]{1,2,3}));
        assertArrayEquals(original,store.score(id));assertEquals("original",store.timeline(id).get("revision"));assertEquals("Original",store.report(id).get("title"));
        assertArrayEquals(wav,Files.readAllBytes(store.recording(id)));
    }
    @Test public void removingOneTakeIsReversibleAndMalformedIdsCannotNameFilesystemPaths() throws Exception {
        PracticeTakeStore store=new PracticeTakeStore();String a=(String)store.save(null,score("A"),Map.of(),report("A"),null).get("takeId");
        String b=(String)store.save(null,score("B"),Map.of(),report("B"),null).get("takeId");store.remove(a);
        assertEquals(1,store.list().size());assertEquals(b,store.list().getFirst().get("takeId"));
        try(var trash=Files.list(directory.resolve("trash"))){Path moved=trash.findFirst().orElseThrow();assertTrue(moved.getFileName().toString().startsWith(a));assertTrue(Files.isRegularFile(moved.resolve("source.musicxml")));}
        for(String id:List.of("../..","C:/Windows","",b+"/../.."))assertThrows(IOException.class,()->store.score(id));
    }
    @Test public void joiningPausedSegmentsPreservesEverySampleAndTheRealSilenceGap() throws Exception {
        byte[] joined=PracticeWave.join(List.of(new PracticeWave.Segment(audio(32,1000),0),new PracticeWave.Segment(audio(32,2000),10)));
        PracticeWave.Pcm pcm=PracticeWave.pcm(joined);assertEquals(8000,pcm.rate());assertEquals(1,pcm.channels());assertEquals(112*2,pcm.data().length);
        ByteBuffer values=ByteBuffer.wrap(pcm.data()).order(ByteOrder.LITTLE_ENDIAN);
        for(int frame=0;frame<112;frame++)assertEquals(frame<32?1000:frame<80?0:2000,values.getShort());
    }
    @Test public void overlappingOrInvalidSegmentOffsetsNeverSilentlyRetimingTheSavedAudio() throws Exception {
        assertThrows(IOException.class,()->PracticeWave.join(List.of(new PracticeWave.Segment(audio(32,1000),0),new PracticeWave.Segment(audio(32,2000),2))));
        assertThrows(IOException.class,()->PracticeWave.join(List.of(new PracticeWave.Segment(audio(32,1000),Double.NaN))));
        assertThrows(IOException.class,()->PracticeWave.join(List.of(new PracticeWave.Segment(audio(32,1000),-1))));
        assertThrows(IOException.class,()->PracticeWave.join(List.of(new PracticeWave.Segment(audio(32,1000),10000000))));
    }
    @Test public void nativeReferenceContainsSoundingPitchAtChosenTuningAndCountInIsSeparate() throws Exception {
        List<?> groups=List.of(Map.of("onset",0,"notes",List.of(Map.of("midi",69,"onset",0,"duration",1))));
        PracticeWave.Pcm pcm=PracticeWave.pcm(PracticeWave.reference(groups,120,442,0));assertEquals(48000,pcm.rate());
        ByteBuffer bytes=ByteBuffer.wrap(pcm.data()).order(ByteOrder.LITTLE_ENDIAN);int previous=bytes.getShort(4800*2),crossings=0;
        for(int frame=4801;frame<19200;frame++){int value=bytes.getShort(frame*2);if(previous<=0&&value>0)crossings++;previous=value;}
        assertEquals(442,crossings/.3,5);
        PracticeWave.Pcm count=PracticeWave.pcm(PracticeWave.countIn(120));assertTrue(count.data().length>48000*2*2);assertEquals(1,count.channels());
    }
}
