import OSMD from 'opensheetmusicdisplay';
import {PitchDetector} from 'pitchy';
import {unzipSync,strFromU8} from 'fflate';
import {parseScore,selectGroups,inferInstrument,isPolyphonic,noteName} from './score.js';
import {PracticeSession,PitchGate} from './session.js';

const $=id=>document.getElementById(id);
const osmd=new OSMD.OpenSheetMusicDisplay('score',{autoResize:true,backend:'svg',drawTitle:false,drawComposer:false,drawPartNames:true,followCursor:true});
let score,session,groups=[],micStream,audioContext,animation,midiAccess,selectedMidi,micAnalyser,playback=[],inputGeneration=0;
const gate=new PitchGate(),buffer=new Float32Array(4096),detector=PitchDetector.forFloat32Array(4096);
let graphics=[],countdownTimer,tickTimer,beatTimer;
function message(content,type=''){ $('message').textContent=content;$('message').className=type; }
function guard(fn){return (...args)=>Promise.resolve().then(()=>fn(...args)).catch(e=>{message(e.message||String(e),'error');});}
function currentOptions(){return {part:$('part').value,from:Number($('from').value),to:Number($('to').value)};}
function selection(){const o=currentOptions();if(!Number.isInteger(o.from)||!Number.isInteger(o.to)||o.from<1||o.to<o.from||o.to>score.lengths.length)throw new Error('请设置有效的小节范围。');return selectGroups(score,o.part,o.from,o.to);}
function selectedParts(){return score.parts.filter(p=>$('part').value==='all'||p.id===$('part').value);}
function configure(){
  if(!score)return;groups=selection();
  const parts=selectedParts(),info=parts.map(inferInstrument),poly=isPolyphonic(groups);
  $('instrument').textContent=info.map(i=>i.name).join(' + ')+(poly?' · 多音声部':' · 单音旋律');
  $('instrument').title=info.map(i=>i.source).join('；');
  if($('instrument-choice').value!=='auto')$('instrument').textContent=$('instrument-choice').selectedOptions[0].textContent+' · 手动选择'+(poly?' · 多音声部':' · 单音旋律');
  $('input-hint').textContent=poly?'所选声部含和弦或重叠音。请用 MIDI 乐器，或改选单音声部。':'麦克风可检测独奏单音。远离伴奏音源，并用耳机试听。';
  if($('instrument-choice').value==='auto')$('input').value=poly||info.some(i=>i.input==='midi')?'midi':'microphone';
  $('midi-device').hidden=$('input').value!=='midi';
  $('next').textContent=groups.length?`共 ${groups.length} 个起音位置 · ${poly?'支持 MIDI 多音练习':'可用麦克风单音练习'}`:'此声部没有可练习音符。';
}
async function load(xml){
  stop();stopPlayback();message('正在排版乐谱…');
  const parsed=parseScore(xml);await osmd.load(xml);osmd.render();score=parsed;
  $('title').textContent=score.title;$('bpm').value=Math.round(score.tempo);$('from').value=1;$('to').value=score.lengths.length;
  $('from').max=$('to').max=score.lengths.length;$('verified').checked=false;
  $('part').replaceChildren(...score.parts.map(p=>new Option(p.name,p.id)));
  if(score.parts.length>1)$('part').add(new Option('全部声部','all'));
  $('part').value=score.parts[0]?.id||'';
  graphics=[];osmd.cursor.reset();let count=0;
  while(!osmd.cursor.Iterator.EndReached&&count++<50000){
    const onset=osmd.cursor.Iterator.CurrentSourceTimestamp.RealValue*4;
    for(const g of osmd.cursor.GNotesUnderCursor())graphics.push({onset,part:g.sourceNote.ParentStaff.ParentInstrument.IdString,g});
    osmd.cursor.next();
  }
  osmd.cursor.reset();osmd.cursor.hide();session=null;configure();renderReport();
  $('position').textContent='—';$('correct').textContent='—';$('errors').textContent='0 处';$('heard').textContent='—';
  message(score.warnings.length?score.warnings.join(' '):'已载入乐谱。先试听并确认识谱结果，再连接乐器开始。',score.warnings.length?'warning':'');
}
function cursorAt(group){if(!group)return;osmd.cursor.reset();let i=0;while(!osmd.cursor.Iterator.EndReached&&osmd.cursor.Iterator.CurrentSourceTimestamp.RealValue*4<group.onset-0.00001&&i++<50000)osmd.cursor.next();osmd.cursor.show();}
function colorGroup(group,color){
  const parts=new Set(group.notes.map(n=>n.part));
  for(const entry of graphics)if(Math.abs(entry.onset-group.onset)<1e-5&&parts.has(entry.part))entry.g.setColor(color,{applyToNoteheads:true,applyToStem:true,applyToBeams:false,applyToModifiers:false});
}
function resetColors(){for(const {g}of graphics)g.setColor('#202733',{applyToNoteheads:true,applyToStem:true,applyToBeams:false,applyToModifiers:false});}
function update(){
  if(!session)return;
  $('correct').textContent=`${session.results.filter(r=>r.status==='correct').length} / ${session.groups.length}`;
  $('errors').textContent=`${session.errors.length} 处`;
  const g=session.current;
  $('position').textContent=g?`${g.measure} 小节`:'完成';
  $('next').textContent=g?`第 ${g.measure} 小节 · 第 ${g.beat.toFixed(2).replace(/\.00$/,'')} 拍 · 应弹 ${[...new Set(g.notes.map(n=>noteName(n.midi)))].join(' + ')}`:'本段已完成。可以从下面的记录重练难点。';
  if(g)cursorAt(g);
  for(const r of session.results)colorGroup(session.groups[r.index],r.status==='correct'?'#258465':r.status==='missing'?'#c04f50':'#b88027');
  renderReport();
  if(!session.active)stop(true);
}
function receive(midi,time=performance.now(),cents=0){
  $('heard').textContent=noteName(midi)+(Math.abs(cents)>3?` ${cents>0?'+':''}${Math.round(cents)}¢`:'');
  const result=session?.noteOn(midi,time,cents);
  if(!result)return;
  if(result.kind==='wrong'||result.kind==='extra'){colorGroup(result.group,'#c04f50');message(`第 ${result.group.measure} 小节：听到 ${noteName(midi)}，应弹 ${result.group.notes.map(n=>noteName(n.midi)).join(' + ')}。`,'warning');}
  else if(result.kind==='correct'){colorGroup(result.group,'#258465');message(result.complete?'这个位置已弹对，继续下一音。':'音高正确，请继续弹齐和弦。');}
  update();
}
async function context(){audioContext??=new AudioContext();if(audioContext.state==='suspended')await audioContext.resume();return audioContext;}
async function connectMic(){
  const generation=inputGeneration;
    if(!navigator.mediaDevices?.getUserMedia)throw new Error('此浏览器不能录音，请使用 Chrome 或 Edge 打开本地练习页。');
    const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:false,noiseSuppression:false,autoGainControl:false},video:false});
    if(generation!==inputGeneration){stream.getTracks().forEach(t=>t.stop());return false;}
    let ctx;
    try{ctx=await context();}catch(e){stream.getTracks().forEach(t=>t.stop());throw e;}
    if(generation!==inputGeneration){stream.getTracks().forEach(t=>t.stop());return false;}
    micStream=stream;micAnalyser=ctx.createAnalyser();micAnalyser.fftSize=4096;ctx.createMediaStreamSource(stream).connect(micAnalyser);gate.reset();
    const poll=()=>{
      if(!micStream)return;
      micAnalyser.getFloatTimeDomainData(buffer);
      const rms=Math.sqrt(buffer.reduce((sum,x)=>sum+x*x,0)/buffer.length),[hz,clarity]=detector.findPitch(buffer,ctx.sampleRate);
      const reference=Number($('a4').value);const result=gate.push(hz*440/reference,clarity,rms);
      if(result)receive(result.midi,performance.now(),result.cents);
      animation=requestAnimationFrame(poll);
    };poll();return true;
}
function refreshMidi(){
  const devices=Array.from(midiAccess.inputs.values()).filter(d=>d.state==='connected');
  const previous=$('midi-device').value;
  $('midi-device').replaceChildren(...devices.map(d=>new Option(d.name||d.id,d.id)));
  if(devices.some(d=>d.id===previous))$('midi-device').value=previous;
  if(!devices.length){if(session?.active)stop();message('未找到 MIDI 乐器。连接 USB MIDI 乐器后重新开始。','warning');return false;}
  selectMidi();return true;
}
function selectMidi(){
  if(selectedMidi)selectedMidi.onmidimessage=null;
  selectedMidi=midiAccess?.inputs.get($('midi-device').value);
  if(selectedMidi)selectedMidi.onmidimessage=({data,timeStamp})=>{if((data[0]&0xf0)===0x90&&data[2]>0)receive(data[1],timeStamp);};
}
async function connectMidi(){
  const generation=inputGeneration;
  if(!navigator.requestMIDIAccess)throw new Error('此浏览器不支持 MIDI。请在 Chrome 或 Edge 打开。');
  const access=midiAccess||await navigator.requestMIDIAccess({sysex:false});
  if(generation!==inputGeneration)return;
  midiAccess=access;midiAccess.onstatechange=()=>{if(session?.active||$('input').value==='midi')refreshMidi();};
  if(!refreshMidi())throw new Error('请连接 MIDI 乐器；也可选电脑键盘查看演示。');
}
function lock(active){
  for(const id of ['part','instrument-choice','input','mode','bpm','a4','from','to','verified','import','demo','listen'])$(id).disabled=active;
  $('start').disabled=active;$('stop').disabled=!active;$('skip').disabled=!active;
}
async function start(){
  if(!score)throw new Error('请先导入乐谱。');
  if(!$('verified').checked)throw new Error('请先试听或校对乐谱，并勾选确认。');
  groups=selection();const input=$('input').value;
  const range=currentOptions(),invalid=score.issues.filter(i=>(range.part==='all'||i.part===range.part)&&i.mi>=range.from-1&&i.mi<range.to);
  if(invalid.length)throw new Error(`第 ${[...new Set(invalid.map(i=>i.measure))].join('、')} 小节时值超过拍号。请先校对，或选择其他小节练习。`);
  if(input==='microphone'&&isPolyphonic(groups))throw new Error('所选段落含多音或和弦，单音麦克风不能可靠判断。请改选单音声部或使用 MIDI。');
  const bpm=Number($('bpm').value),a4=Number($('a4').value);
  if(!(bpm>=30&&bpm<=240&&a4>=415&&a4<=466))throw new Error('请使用 30–240 BPM，调音 A4 范围 415–466 Hz。');
  stopPlayback();const generation=++inputGeneration;lock(true);resetColors();message('正在连接演奏输入…');
  try{
    session=new PracticeSession(groups,{mode:$('mode').value,bpm});session.active=false;
    session.metadata={input,instrument:$('instrument').textContent,scope:currentOptions(),a4};
    if(input==='microphone'&&!await connectMic())return;
    if(input==='midi')await connectMidi();
    if(generation!==inputGeneration)return;
    session.active=true;
    if($('mode').value==='tempo'){
      const ctx=await context(),beat=60000/bpm;
      if(generation!==inputGeneration)return;
      session.begin(performance.now()+4*beat);
      for(let i=0;i<4;i++)tone(ctx,880,i*beat/1000,.06,.07);
      message('预备 4 拍，再开始演奏。');
      countdownTimer=setTimeout(()=>{if(session?.active){tone(audioContext,880,0,.04,.035);beatTimer=setInterval(()=>{if(session?.active)tone(audioContext,880,0,.04,.035);},beat);}},4*beat);
      tickTimer=setInterval(()=>{if(session?.active){const previous=session.index;session.tick(performance.now());if(previous!==session.index)update();}},40);
    }else message(input==='keyboard'?'电脑键盘演示：A S D F G H J 对应 C4 D4 E4 F4 G4 A4 B4，K 为 C5。':'已连接。弹对当前音后，谱面会自动前进。');
    update();
  }catch(e){if(generation===inputGeneration){stop();throw e;}}
}
function stop(completed=false){
  inputGeneration++;cancelAnimationFrame(animation);clearInterval(tickTimer);clearInterval(beatTimer);clearTimeout(countdownTimer);
  stopPlayback();
  micStream?.getTracks().forEach(t=>t.stop());micStream=null;micAnalyser=null;
  if(selectedMidi){selectedMidi.onmidimessage=null;selectedMidi=null;}
  if(session){session.finish();renderReport();}
  lock(false);if(completed)message('本段练习完成，下面是这次需要复习的位置。');
}
function tone(ctx,midiOrHz,delay,duration,volume=.08,isMidi=false){
  const osc=ctx.createOscillator(),gain=ctx.createGain(),time=ctx.currentTime+delay;
  osc.type='triangle';osc.frequency.value=isMidi?440*2**((midiOrHz-69)/12):midiOrHz;
  gain.gain.setValueAtTime(0,time);gain.gain.linearRampToValueAtTime(volume,time+.012);gain.gain.exponentialRampToValueAtTime(.001,time+Math.max(.04,duration));
  osc.connect(gain);gain.connect(ctx.destination);osc.start(time);osc.stop(time+Math.max(.05,duration)+.02);playback.push(osc);
}
function stopPlayback(){for(const o of playback){try{o.stop();}catch{}}playback=[];$('listen').textContent='试听所选段落';}
async function listen(){
  if(playback.length){stopPlayback();return;}
  const ctx=await context(),notes=selection(),bpm=Number($('bpm').value),start=notes[0]?.onset||0;
  if(notes.length>3000)throw new Error('请先缩小试听小节范围。');
  for(const g of notes)for(const n of g.notes)tone(ctx,n.midi,(n.onset-start)*60/bpm,Math.max(.05,n.duration*60/bpm-.02),.045,true);
  $('listen').textContent='停止试听';
}
const labels={wrong:'错音',extra:'多弹 / 过早',missing:'漏音',early:'抢拍',late:'慢拍',intonation:'音准偏差'};
function describe(e){
  if(e.kind==='wrong')return `应弹 ${(e.expected||[]).map(noteName).join(' + ')}，实际 ${noteName(e.played)}`;
  if(e.kind==='missing')return `未听到 ${e.expected.map(noteName).join(' + ')}`;
  if(e.kind==='intonation')return `${noteName(e.played)} ${e.cents>0?'偏高':'偏低'} ${Math.abs(Math.round(e.cents))} 音分`;
  return `${noteName(e.played)} ${e.delta<0?'提前':'延后'} ${Math.abs(Math.round(e.delta))} ms`;
}
function renderReport(){
  const list=$('error-list');list.replaceChildren();
  if(!session?.errors.length){const p=document.createElement('p');p.className='empty';p.textContent=session?'本次暂未记录错音。未完成的音符不会计为已弹对。':'练习后会列出具体小节、拍位、应弹音与实际音。';list.append(p);return;}
  for(const e of session.errors.slice(-100)){
    const row=document.createElement('div');row.className='error-row';const badge=document.createElement('span');badge.className='badge';badge.textContent=labels[e.kind];
    const details=document.createElement('div'),title=document.createElement('strong'),p=document.createElement('p');title.textContent=`第 ${e.measure} 小节 · 第 ${e.beat.toFixed(2).replace(/\.00$/,'')} 拍`;p.textContent=describe(e);details.append(title,p);
    const button=document.createElement('button');button.textContent='重练此小节';button.disabled=!!session.active;button.onclick=()=>{stop();$('from').value=e.mi+1;$('to').value=e.mi+1;configure();cursorAt(groups[0]);message('已选中这个小节。点击“开始练习”重练。');};row.append(badge,details,button);list.append(row);
  }
}
function downloadReport(){
  if(!session)throw new Error('先完成一次练习再保存记录。');
  const report={title:score.title,createdAt:new Date().toISOString(),...session.metadata,limitations:'Note-on pitch and timing only; microphone monophonic; unperformed notes not graded',...session.report()};
  const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='NoteLite-练习记录.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);
}
async function readFile(file){
  if(file.size>15*1024*1024)throw new Error('乐谱文件过大，请导入不超过 15 MB 的文件。');
  return readBytes(new Uint8Array(await file.arrayBuffer()));
}
function readBytes(bytes){
  if(bytes[0]===80&&bytes[1]===75){
    let total=0;const files=unzipSync(bytes,{filter:f=>{total+=f.originalSize;if(total>30*1024*1024)throw new Error('解压后的乐谱过大。');return /\.(xml|musicxml)$/i.test(f.name);}});
    const container=files['META-INF/container.xml'];
    if(!container)throw new Error('压缩乐谱缺少 MusicXML container.xml。');
    const doc=new DOMParser().parseFromString(strFromU8(container),'application/xml');const root=doc.getElementsByTagName('rootfile')[0]?.getAttribute('full-path');
    if(!root||!files[root])throw new Error('压缩乐谱未找到主文件。');return strFromU8(files[root]);
  }
  return new TextDecoder().decode(bytes);
}
$('import').onclick=()=>$('file').click();$('file').onchange=guard(async()=>{const f=$('file').files[0];if(f)await load(await readFile(f));$('file').value='';});
$('demo').onclick=guard(async()=>load(await (await fetch('demo.musicxml')).text()));
for(const id of ['part','from','to'])$(id).onchange=guard(configure);
$('input').onchange=()=>{$('midi-device').hidden=$('input').value!=='midi';};
$('instrument-choice').onchange=guard(()=>{configure();if($('instrument-choice').value!=='auto')$('input').value=$('instrument-choice').value==='piano'?'midi':'microphone';$('input').onchange();});
$('midi-device').onchange=selectMidi;$('start').onclick=guard(start);$('stop').onclick=()=>stop();$('skip').onclick=()=>{session?.advance(true);update();};$('listen').onclick=guard(listen);$('report').onclick=guard(downloadReport);
const keyMap={a:60,s:62,d:64,f:65,g:67,h:69,j:71,k:72,w:61,e:63,t:66,y:68,u:70};
document.addEventListener('keydown',e=>{if(e.repeat||['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName))return;const n=keyMap[e.key.toLowerCase()];if(n!==undefined&&$('input').value==='keyboard'&&session?.active){e.preventDefault();receive(n);}});
window.addEventListener('pagehide',()=>{stop();stopPlayback();audioContext?.close();});
guard(async()=>{const response=await fetch('score.musicxml');if(!response.ok)throw new Error('无法读取当前乐谱。请从 NoteLite 重新打开，或点击“导入乐谱”。');await load(readBytes(new Uint8Array(await response.arrayBuffer())));})();
