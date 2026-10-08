/* Copyright © NoteLite 2026. Licensed under the GNU Affero General Public License. */
package com.notelite.omr.practice;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** PCM playback lives in the native audio process, including stop and segment boundaries. */
final class LocalAudioPlayback implements AutoCloseable {
    private Process process;
    private Path temporary;
    private volatile String failure;
    private volatile double positionMs;
    private volatile double readyEpochMs;
    private volatile long generation;
    private Thread readerThread;
    synchronized void play(Path wav,double startMs,double endMs,int device) throws IOException {
        stop();
        if(!Double.isFinite(startMs)||!Double.isFinite(endMs)||startMs<0||endMs<0||(endMs>0&&endMs<=startMs))throw new IOException("回放范围无效。");
        Path binary=LocalAudioCapture.executable();if(binary==null)throw new IOException("本地播放组件未安装。");
        List<String> command=new ArrayList<>(List.of(binary.toString(),"--play",wav.toAbsolutePath().toString(),"--start-ms",Double.toString(startMs)));
        if(endMs>0){command.add("--end-ms");command.add(Double.toString(endMs));}
        if(device>=0){command.add("--playback-device");command.add(Integer.toString(device));}
        launch(command,startMs);
    }
    synchronized void metronome(double bpm,int device) throws IOException {
        metronome(bpm,device,0);
    }
    synchronized void metronome(double bpm,int device,double phaseMs) throws IOException {
        stop();if(!Double.isFinite(bpm)||bpm<30||bpm>240)throw new IOException("节拍器速度无效。");
        Path binary=LocalAudioCapture.executable();if(binary==null)throw new IOException("本地播放组件未安装。");
        List<String> command=new ArrayList<>(List.of(binary.toString(),"--metronome",Double.toString(bpm)));
        if(phaseMs>0){command.add("--start-ms");command.add(Double.toString(phaseMs));}
        if(device>=0){command.add("--playback-device");command.add(Integer.toString(device));}launch(command,0);
    }
    private void launch(List<String> command,double startMs) throws IOException {
        long launched=++generation;failure=null;positionMs=startMs;CountDownLatch ready=new CountDownLatch(1);
        Process child=process=new ProcessBuilder(command).redirectError(ProcessBuilder.Redirect.DISCARD).start();
        readerThread=Thread.ofVirtual().start(()->{
            try(BufferedReader reader=new BufferedReader(new InputStreamReader(child.getInputStream(),StandardCharsets.UTF_8))){String line;
                while((line=reader.readLine())!=null){MapResult result=parse(line);
                    if(launched!=generation)continue;
                    if(result.type.equals("ready")){readyEpochMs=PracticeRuntime.clock();ready.countDown();}
                    if(result.type.equals("error")){failure=result.message;ready.countDown();}
                    if(result.time!=null)positionMs=result.time;
                }
            }catch(Exception ex){if(launched==generation)failure=ex.getMessage();}finally{ready.countDown();}
        });
        try{if(!ready.await(8,TimeUnit.SECONDS)||failure!=null||!child.isAlive()){String why=failure;stop();throw new IOException(why==null?"无法开始本地播放，请检查输出设备。":why);}}
        catch(InterruptedException ex){Thread.currentThread().interrupt();stop();throw new IOException("播放已取消。",ex);}
    }
    synchronized void play(byte[] wav,int device) throws IOException {
        stop();Path path=Files.createTempFile("notelite-reference-",".wav");Files.write(path,wav);
        try{play(path,0,0,device);temporary=path;}catch(IOException ex){Files.deleteIfExists(path);throw ex;}
    }
    synchronized java.util.Map<String,Object> state(){return java.util.Map.of("playing",process!=null&&process.isAlive(),"timeMs",positionMs,"error",failure==null?"":failure);}
    double readyEpoch(){return readyEpochMs;}
    synchronized void stop(){++generation;Process child=process;process=null;Thread reader=readerThread;readerThread=null;
        if(child!=null){boolean interrupted=Thread.interrupted();try{
            if(child.isAlive()){child.getOutputStream().write("STOP\n".getBytes(StandardCharsets.US_ASCII));child.getOutputStream().flush();child.getOutputStream().close();}
            if(!child.waitFor(3,TimeUnit.SECONDS))child.destroyForcibly();
            if(reader!=null&&reader!=Thread.currentThread())reader.join(2000);
        }catch(IOException ex){child.destroyForcibly();}catch(InterruptedException ex){interrupted=true;child.destroyForcibly();}finally{if(interrupted)Thread.currentThread().interrupt();}}
        if(temporary!=null){try{Files.deleteIfExists(temporary);}catch(IOException ignored){}temporary=null;}
    }
    private record MapResult(String type,Double time,String message){}
    private static MapResult parse(String line){try{var map=PracticeJson.object(PracticeJson.parse(line));Object time=map.getOrDefault("positionMs",map.getOrDefault("startMs",map.get("timeMs")));return new MapResult(String.valueOf(map.getOrDefault("type","")),time instanceof Number n?n.doubleValue():null,String.valueOf(map.getOrDefault("message","本地播放失败。")));}catch(Exception ignored){return new MapResult("",null,"");}}
    @Override public void close(){stop();}
}
