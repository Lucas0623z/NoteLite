/** Windows UI transport. Audio detection, following and judging belong to the local service. */
export class WindowsPracticeClient {
  constructor(){this.pending=Promise.resolve();this.polling=false;this.stopped=true;}
  async request(route,body){const response=await fetch(route,body===undefined?undefined:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw new Error(data.error||'本地陪练服务暂不可用。');return data;}
  event(event){const next=this.pending.catch(()=>{}).then(()=>this.request('practice/event',event));this.pending=next.then(()=>{},()=>{});return next;}
  poll(callback,onError){this.stopped=false;const run=async()=>{if(this.stopped||this.polling)return;this.polling=true;try{callback(await this.request('practice/state'));}catch(error){onError?.(error);}finally{this.polling=false;if(!this.stopped)this.timer=setTimeout(run,100);}};run();}
  stop(){this.stopped=true;clearTimeout(this.timer);}
  async finish(){this.stop();await this.pending;return this.request('practice/finish',{});}
}

/** Presentation-only mapping from repeat occurrence IDs back to written score positions. */
export function displaySession(snapshot,score){
  const originals=new Map(score.parts.flatMap(p=>p.notes).map(n=>[n.id,n]));
  const groups=(snapshot.groups||[]).map(g=>{const notes=g.notes.map(n=>({...originals.get(n.sourceNoteId||n.id),...n}));return{...g,notes,onset:originals.get(notes[0]?.sourceNoteId||notes[0]?.id)?.onset??0};});
  return{...snapshot,index:snapshot.currentIndex||0,groups,matched:new Set(snapshot.matched||[]),current:groups[snapshot.currentIndex]||null,metadata:{...snapshot.metadata,engine:snapshot.engine,scope:snapshot.scope},report:()=>snapshot};
}
