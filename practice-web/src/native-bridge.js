/** The native host owns permission prompts and device lifetime. */
export class NativeInputBridge {
  constructor(handler) { this.handler=handler;this.pending=new Map();this.sequence=0; }
  get available() { return typeof this.handler?.postMessage==='function'; }
  post(message) { if(this.available)this.handler.postMessage(message); }
  requestInput(input) {
    const requestId=++this.sequence;
    return new Promise((resolve,reject)=>{
      this.pending.set(requestId,{resolve,reject});
      try { this.post({type:'startInput',input,requestId}); }
      catch(error) { this.pending.delete(requestId);reject(error); }
    });
  }
  inputResult(requestId,error) {
    const pending=this.pending.get(Number(requestId));if(!pending)return;
    this.pending.delete(Number(requestId));
    if(error)pending.reject(new Error(String(error)));else pending.resolve(true);
  }
  stop() {
    for(const pending of this.pending.values())pending.reject(Object.assign(new Error('输入连接已取消。'),{name:'AbortError'}));
    this.pending.clear();this.post({type:'stopInput'});
  }
}
