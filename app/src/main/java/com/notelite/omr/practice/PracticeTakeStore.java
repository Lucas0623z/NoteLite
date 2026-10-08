/* Copyright © NoteLite 2026. Licensed under the GNU Affero General Public License. */
package com.notelite.omr.practice;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Persistent local practice packages. HTTP accepts opaque IDs rather than user paths. */
final class PracticeTakeStore {
    private final Path root;
    PracticeTakeStore() throws IOException {
        String configured=System.getProperty("notelite.practice.home");
        String local=System.getenv("LOCALAPPDATA");
        root=(configured!=null?Path.of(configured):local!=null?Path.of(local,"NoteLite","practice"):Path.of(System.getProperty("user.home"),".notelite","practice")).toAbsolutePath().normalize();
        Files.createDirectories(root);
    }
    Path root(){return root;}
    synchronized Map<String,Object> save(String existingId,byte[] xml,Map<String,Object> timeline,Map<String,Object> snapshot,byte[] wav) throws IOException {
        String id=existingId==null?UUID.randomUUID().toString():validId(existingId);
        if(wav!=null)LocalAudioAnalysis.validateWav(wav);
        Path directory=directory(id);Files.createDirectories(directory);
        Map<String,Object> report=new LinkedHashMap<>(snapshot);
        report.put("takeId",id);report.put("savedAt",Instant.now().toString());
        report.put("hasRecording",wav!=null||Files.isRegularFile(directory.resolve("recording.wav")));
        atomic(directory.resolve("source.musicxml"),xml);
        atomic(directory.resolve("practice.json"),PracticeJson.stringify(timeline).getBytes(StandardCharsets.UTF_8));
        if(wav!=null)atomic(directory.resolve("recording.wav"),wav);
        atomic(directory.resolve("report.json"),PracticeJson.stringify(report).getBytes(StandardCharsets.UTF_8));
        return report;
    }
    synchronized List<Map<String,Object>> list() throws IOException {
        List<Map<String,Object>> result=new ArrayList<>();
        try(var paths=Files.list(root)){for(Path path:paths.filter(Files::isDirectory).toList()){
            if(!path.getFileName().toString().matches("[a-f0-9-]{36}"))continue;
            Path report=path.resolve("report.json");if(!Files.isRegularFile(report))continue;
            try{Map<String,Object> saved=readJson(report);Map<String,Object> summary=new LinkedHashMap<>();
                for(String key:List.of("takeId","savedAt","createdAt","title","durationSeconds","hasRecording","completed","total","input","engine"))if(saved.containsKey(key))summary.put(key,saved.get(key));
                summary.put("errorCount",saved.get("errors") instanceof List<?> errors?errors.stream().filter(error->!(error instanceof Map<?,?> item&&Boolean.TRUE.equals(item.get("resolved")))).count():0);result.add(summary);
            }catch(RuntimeException ignored){/* A damaged take does not hide other practice records. */}
        }}
        result.sort(Comparator.comparing((Map<String,Object> item)->String.valueOf(item.getOrDefault("savedAt",""))).reversed());
        return result.stream().limit(200).toList();
    }
    Map<String,Object> report(String id) throws IOException{return readJson(directory(id).resolve("report.json"));}
    Map<String,Object> timeline(String id) throws IOException{return readJson(directory(id).resolve("practice.json"));}
    byte[] score(String id) throws IOException{return Files.readAllBytes(directory(id).resolve("source.musicxml"));}
    Path recording(String id) throws IOException{Path path=directory(id).resolve("recording.wav");if(!Files.isRegularFile(path))throw new IOException("这次练习没有保存录音。");return path;}
    synchronized void remove(String id) throws IOException {
        // Moving to our own trash is reversible and never follows a client-provided path.
        Path source=directory(id),trash=root.resolve("trash");Files.createDirectories(trash);
        if(!Files.isDirectory(source))throw new IOException("找不到这次练习。");
        Files.move(source,trash.resolve(validId(id)+"-"+Instant.now().toEpochMilli()));
    }
    synchronized List<Map<String,Object>> saveRecoveryRecordings(String id,List<PracticeWave.Segment> segments) throws IOException {
        Path target=directory(id);Files.createDirectories(target);List<Map<String,Object>> files=new ArrayList<>();int index=0;
        for(PracticeWave.Segment segment:segments){String name="recovery-"+String.format("%03d",++index)+".wav";atomic(target.resolve(name),segment.wav());files.add(Map.of("file",name,"onsetMs",segment.onsetMs()));}
        return files;
    }
    synchronized List<Map<String,Object>> trash() throws IOException {
        Path trash=root.resolve("trash");if(!Files.isDirectory(trash))return List.of();List<Map<String,Object>> items=new ArrayList<>();
        try(var paths=Files.list(trash)){for(Path path:paths.filter(Files::isDirectory).toList()){String key=path.getFileName().toString();if(!key.matches("[a-f0-9-]{36}-[0-9]{13}"))continue;try{Map<String,Object> saved=readJson(path.resolve("report.json"));items.add(Map.of("key",key,"title",String.valueOf(saved.getOrDefault("title","练习记录"))));}catch(IOException|RuntimeException ignored){}}}
        return items;
    }
    synchronized void restore(String key) throws IOException {
        if(key==null||!key.matches("[a-f0-9-]{36}-[0-9]{13}"))throw new IOException("回收记录编号无效。");Path source=root.resolve("trash").resolve(key),target=directory(key.substring(0,36));
        if(Files.exists(target))throw new IOException("本机已有同一练习记录。");Files.move(source,target);
    }
    byte[] bundle(String id) throws IOException {
        Path directory=directory(id);ByteArrayOutputStream bytes=new ByteArrayOutputStream();
        try(ZipOutputStream zip=new ZipOutputStream(bytes,StandardCharsets.UTF_8)){
            for(String name:List.of("source.musicxml","practice.json","report.json","recording.wav")){
                Path file=directory.resolve(name);if(!Files.isRegularFile(file))continue;
                if(Files.size(file)>LocalAudioAnalysis.MAX_INPUT_BYTES)throw new IOException("练习包过大。");
                zip.putNextEntry(new ZipEntry(name));Files.copy(file,zip);zip.closeEntry();
            }
            try(var files=Files.list(directory)){for(Path file:files.filter(p->p.getFileName().toString().matches("recovery-[0-9]{3}\\.wav")).toList()){zip.putNextEntry(new ZipEntry(file.getFileName().toString()));Files.copy(file,zip);zip.closeEntry();}}
        }
        return bytes.toByteArray();
    }
    private Path directory(String id) throws IOException {Path path=root.resolve(validId(id)).normalize();if(!path.getParent().equals(root))throw new IOException("练习记录编号无效。");return path;}
    private static String validId(String id) throws IOException{if(id==null||!id.matches("[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"))throw new IOException("练习记录编号无效。");return id;}
    private static Map<String,Object> readJson(Path path) throws IOException {if(!Files.isRegularFile(path)||Files.size(path)>16*1024*1024)throw new IOException("练习记录缺失或过大。");return PracticeJson.object(PracticeJson.parse(Files.readString(path,StandardCharsets.UTF_8)));}
    private static void atomic(Path destination,byte[] bytes) throws IOException {
        Path temporary=Files.createTempFile(destination.getParent(),".save-",".tmp");
        try{Files.write(temporary,bytes);try{Files.move(temporary,destination,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);}catch(java.nio.file.AtomicMoveNotSupportedException ex){Files.move(temporary,destination,StandardCopyOption.REPLACE_EXISTING);}}
        finally{Files.deleteIfExists(temporary);}
    }
}
