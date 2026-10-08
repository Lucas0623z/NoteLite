/** Local Windows capture bridge. PCM stays in miniaudio; only acoustic estimates cross HTTP. */
export class NativePitchGate {
  constructor(){this.reset();}
  reset(){this.candidate=null;this.frames=0;this.last=null;this.silentFrames=0;this.candidateTime=0;}
  push(frame,a4=440){
    const {frequency,clarity,rms,timeMs,onset}=frame;
    if(!Number.isFinite(timeMs)||!Number.isFinite(rms))return null;
    if(rms<.008){this.candidate=null;this.frames=0;if(++this.silentFrames>=3)this.last=null;return null;}
    this.silentFrames=0;
    if(onset){this.last=null;this.candidate=null;this.frames=0;}
    if(!(frequency>0)||!Number.isFinite(clarity)||clarity<.9){this.candidate=null;this.frames=0;return null;}
    const raw=69+12*Math.log2(frequency/a4),midi=Math.round(raw),cents=(raw-midi)*100;
    if(midi<0||midi>127)return null;
    if(this.candidate!==midi){this.candidate=midi;this.frames=1;this.candidateTime=Number.isFinite(frame.onsetTimeMs)?frame.onsetTimeMs:Number.isFinite(frame.pitchTimeMs)?frame.pitchTimeMs:timeMs;return null;}
    if(++this.frames<3||this.last===midi)return null;
    this.last=midi;return{midi,cents,timeMs:this.candidateTime};
  }
}

export class WindowsAudioBridge {
  constructor({onFrame,onError}={}){this.onFrame=onFrame;this.onError=onError;this.events=null;this.pending=Promise.resolve();this.generation=0;this.origin=0;this.cancelStart=null;}
  async start(profile,{record=false}={}){
    const generation=++this.generation;
    const params=new URLSearchParams({min:String(profile.minHz||20),max:String(profile.maxHz||5000),window:String(profile.windowSize||4096),record:String(record)});
    // Queue only control requests. A stop must follow an in-flight start even
    // when that start's acknowledgement arrives after the user cancels it.
    const request=this.pending.catch(()=>{}).then(async()=>{
      if(generation!==this.generation)return null;
      const response=await fetch(`audio/start?${params}`,{method:'POST'}),data=await response.json();
      if(!response.ok)throw new Error(data.error||'无法启动本地麦克风。');
      return{after:performance.now()};
    });
    this.pending=request.then(()=>{},()=>{});
    const control=await request;
    if(!control||generation!==this.generation)return false;
    // The server acknowledges only after device-ready. Process/device startup
    // precedes capture and must not be mistaken for symmetric network latency.
    // Loopback acknowledgement is an approximate capture origin; subsequent
    // attack timing comes from sample positions, with device buffering limits.
    this.origin=control.after;
    return new Promise((resolve,reject)=>{
      let started=false;
      const events=this.events=new EventSource('audio/events');
      const timer=setTimeout(()=>{events.close();reject(new Error('本地听音连接超时。'));},8000);
      this.cancelStart=()=>{clearTimeout(timer);events.close();resolve(false);};
      events.onmessage=event=>{
        if(generation!==this.generation)return;
        let frame;try{frame=JSON.parse(event.data);}catch{return;}
        if(frame.type==='ready'){started=true;clearTimeout(timer);this.cancelStart=null;resolve(true);return;}
        if(frame.type==='stopped'){events.close();return;}
        if(frame.type==='error'){
          const error=new Error('听音中断：'+(frame.message||frame.code||'请检查输入设备。'));
          events.close();clearTimeout(timer);if(!started)reject(error);else this.onError?.(error);return;
        }
        this.onFrame?.(frame,this.origin+frame.timeMs);
      };
      events.onerror=()=>{events.close();clearTimeout(timer);if(generation!==this.generation)return;const error=new Error('本地麦克风连接已断开。');if(!started)reject(error);else this.onError?.(error);};
    });
  }
  stop(){
    ++this.generation;this.cancelStart?.();this.cancelStart=null;this.events?.close();this.events=null;
    this.pending=this.pending.catch(()=>{}).then(async()=>{const response=await fetch('audio/stop',{method:'POST',keepalive:true});if(!response.ok)throw new Error('本地录音未正常结束。');});
    return this.pending;
  }
}
