/* Copyright © NoteLite 2026. Licensed under the GNU Affero General Public License. */
package com.notelite.omr.practice;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.List;
import java.util.Map;

/** Native-ready reference PCM and bounded joining of paused recording segments. */
final class PracticeWave {
    private PracticeWave(){}
    record Segment(byte[] wav,double onsetMs){}
    record Pcm(byte[] data,int rate,int channels){}
    static Pcm pcm(byte[] wav) throws IOException {
        LocalAudioAnalysis.validateWav(wav);ByteBuffer b=ByteBuffer.wrap(wav).order(ByteOrder.LITTLE_ENDIAN);
        int rate=0,channels=0;byte[] data=null;
        for(int p=12;p+8<=wav.length;){int n=b.getInt(p+4);if(n<0||p+8L+n>wav.length)throw new IOException("WAV 长度无效。");
            if(b.getInt(p)==0x20746d66){channels=Short.toUnsignedInt(b.getShort(p+10));rate=b.getInt(p+12);}
            if(b.getInt(p)==0x61746164)data=java.util.Arrays.copyOfRange(wav,p+8,p+8+n);
            p+=8+n+(n&1);}
        if(data==null)throw new IOException("WAV 没有音频数据。");return new Pcm(data,rate,channels);
    }
    static byte[] wrap(byte[] data,int rate,int channels){
        ByteBuffer b=ByteBuffer.allocate(44+data.length).order(ByteOrder.LITTLE_ENDIAN);
        b.putInt(0x46464952).putInt(36+data.length).putInt(0x45564157).putInt(0x20746d66).putInt(16);
        b.putShort((short)1).putShort((short)channels).putInt(rate).putInt(rate*channels*2).putShort((short)(channels*2)).putShort((short)16);
        b.putInt(0x61746164).putInt(data.length).put(data);return b.array();
    }
    static byte[] join(List<Segment> segments) throws IOException {
        if(segments.isEmpty())return null;Pcm first=pcm(segments.getFirst().wav);ByteArrayOutputStream out=new ByteArrayOutputStream();
        int frameBytes=first.channels*2;double previousEnd=-1;
        for(Segment segment:segments){Pcm part=pcm(segment.wav);if(part.rate!=first.rate||part.channels!=first.channels)throw new IOException("录音设备格式发生变化，请分开保存。");
            if(!Double.isFinite(segment.onsetMs)||segment.onsetMs<0||segment.onsetMs+1<previousEnd)throw new IOException("录音片段发生重叠，不能可靠回放。");
            previousEnd=segment.onsetMs+part.data.length*1000.0/(first.rate*frameBytes);
            long desired=Math.max(0,Math.round(segment.onsetMs*first.rate/1000))*frameBytes;
            if(Math.max(desired,out.size())+part.data.length>LocalAudioAnalysis.MAX_INPUT_BYTES-44)throw new IOException("录音超过 64 MB，请缩短练习时间。");
            while(out.size()<desired){int n=(int)Math.min(8192,desired-out.size());out.write(new byte[n]);}out.write(part.data);}
        return wrap(out.toByteArray(),first.rate,first.channels);
    }
    static byte[] reference(List<?> groups,double bpm,double a4,int countIn) throws IOException {
        int rate=48000;double beat=60/bpm,base=groups.isEmpty()?0:number(map(groups.getFirst()).get("onset"),0),end=countIn*beat+.15;
        for(Object g:groups)for(Object n:(List<?>)map(g).getOrDefault("notes",List.of())){Map<String,Object> note=map(n);end=Math.max(end,countIn*beat+(number(note.get("onset"),base)-base+number(note.get("duration"),1))*beat+.1);}
        if(end>600||end*rate*2>LocalAudioAnalysis.MAX_INPUT_BYTES-44)throw new IOException("请缩小试听范围。");
        float[] samples=new float[(int)Math.ceil(end*rate)];
        for(int k=0;k<countIn;k++)tone(samples,rate,k*beat,.055,880,.12);
        for(Object g:groups)for(Object n:(List<?>)map(g).getOrDefault("notes",List.of())){Map<String,Object> note=map(n);double midi=number(note.get("midi"),60);
            tone(samples,rate,countIn*beat+(number(note.get("onset"),base)-base)*beat,Math.max(.05,number(note.get("duration"),1)*beat-.02),a4*Math.pow(2,(midi-69)/12),.065);}
        ByteBuffer bytes=ByteBuffer.allocate(samples.length*2).order(ByteOrder.LITTLE_ENDIAN);for(float sample:samples)bytes.putShort((short)Math.round(Math.max(-.85,Math.min(.85,sample))*32767));return wrap(bytes.array(),rate,1);
    }
    static byte[] countIn(double bpm) throws IOException{return reference(List.of(),bpm,440,4);}
    private static void tone(float[] samples,int rate,double onset,double duration,double hz,double volume){int start=Math.max(0,(int)Math.round(onset*rate)),length=(int)Math.round(duration*rate);
        for(int i=0;i<length&&start+i<samples.length;i++){double t=i/(double)rate,envelope=Math.min(1,t/.012)*Math.min(1,(duration-t)/.05);samples[start+i]+=(float)(volume*envelope*(Math.sin(2*Math.PI*hz*t)+.15*Math.sin(6*Math.PI*hz*t)));}}
    @SuppressWarnings("unchecked") static Map<String,Object> map(Object o){return (Map<String,Object>)o;}
    static double number(Object value,double fallback){return value instanceof Number n&&Double.isFinite(n.doubleValue())?n.doubleValue():fallback;}
}
