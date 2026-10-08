import OSMD from 'opensheetmusicdisplay';
import {PitchDetector} from 'pitchy';
import {unzipSync,strFromU8} from 'fflate';
import {parseScore,selectGroups,inferInstrument,isPolyphonic,noteName} from './score.js';
import {PracticeSession,PitchGate} from './session.js';
import {collectScoreNotes,colorScoreGroup,colorScoreNotes,resetScoreColors} from './score-colors.js';
import {NativeInputBridge} from './native-bridge.js';
import {INSTRUMENT_PROFILES,resolveInstrument} from './instruments.js';
import {WindowsAudioBridge,NativePitchGate} from './windows-audio.js';
import {analyzeRecording} from './recorded-analysis.js';
import {WindowsPracticeClient,displaySession} from './windows-practice.js';

const $=id=>document.getElementById(id);
const bridge=new NativeInputBridge(window.webkit?.messageHandlers?.noteLite);
document.body.classList.toggle('native',bridge.available);
const cursorOptions={type:1,color:'#345da8',alpha:.85,follow:true};
const osmd=new OSMD.OpenSheetMusicDisplay('score',{autoResize:false,backend:'svg',drawTitle:false,drawComposer:false,drawPartNames:true,followCursor:true,cursorsOptions:[cursorOptions]});
let score,session,groups=[],graphics=[],phase='idle',scoreID=null;
let micStream,audioContext,micAnalyser,animation,midiAccess,selectedMidi,inputGeneration=0;
let playback=[],playbackTimer,tickTimer,beatTimer,beatStartTimer,createdAt,activeStartedAt=null,elapsedMilliseconds=0,lastReport=null;
let renderedRange='',resizeTimer;
let engines={windows:false,nativeAudio:false,basicPitch:false},nativeListening=false,recordingMode=false,analysisBusy=false;
let scoreMetadata=null,finishingWindows=false,nativePlayback=false,pendingPracticePackage=null,windowsTransition=null,pendingRecheck=false;
const windowsPractice=new WindowsPracticeClient();
const local=()=>engines.windows&&engines.localPractice;
const instrumentPreferences=new Map(),nativeGate=new NativePitchGate();
const windowsAudio=new WindowsAudioBridge({onFrame(frame,time){
  if(local()||!nativeListening||recordingMode||phase!=='active')return;
  const result=nativeGate.push(frame,Number($('a4').value));
  if(result)receive(result.midi,time-frame.timeMs+result.timeMs,result.cents);
},onError(error){if(['active','connecting'].includes(phase)){if(recordingMode){recordingMode=false;finish(false);}else pause();message(error.message,'error');}}});
const gate=new PitchGate(),buffer=new Float32Array(4096),detector=PitchDetector.forFloat32Array(4096);
const labels={short:'时值偏短',long:'时值偏长',wrong:'错音',extra:'多弹 / 过早',missing:'漏音',early:'抢拍',late:'慢拍',intonation:'音准偏差',uncertain:'需确认'};

function message(content,type=''){$('message').textContent=content;$('message').className=`practice-message ${type}`;if($('settings').open)$('settings-message').textContent=type==='error'||type==='warning'?content:'';}
function guard(fn){return(...args)=>Promise.resolve().then(()=>fn(...args)).catch(e=>{if(e.name!=='AbortError')message(e.message||String(e),'error');});}
function openSettings(focus){$('settings-message').textContent='';if(!$('settings').open)$('settings').showModal();if(focus)$(focus)?.focus();}
function view(name){document.body.dataset.view=name;$('review-view').hidden=name!=='review';$('practice-nav').classList.toggle('selected',name==='practice');$('review-nav').classList.toggle('selected',name==='review');if(name==='practice'&&score&&phase!=='loading')requestAnimationFrame(()=>{renderScore(true);if(session?.active)cursorAt(session.current);});}
function setPhase(next){
  phase=next;document.body.dataset.phase=phase;
  const locked=['connecting','active','paused','loading'].includes(phase)||analysisBusy;
  for(const id of ['part','instrument-choice','input','mode','bpm','a4','from','to','verified','import','demo','listen','settings-listen'])$(id).disabled=locked;
  for(const id of ['instrument-variant','recorded-import','recorded-engine','alignment-baseline','capture-device','playback-device','save-recording'])$(id).disabled=locked;
  $('start').disabled=phase==='connecting'||phase==='loading'||!score||analysisBusy;
  $('stop').disabled=!['connecting','active','paused'].includes(phase)||analysisBusy;$('skip').disabled=phase!=='active'||recordingMode;
  $('start-label').textContent=analysisBusy?'正在分析…':phase==='active'?(recordingMode?'结束录音':'暂停'):phase==='paused'?'继续练习':phase==='connecting'?'正在连接…':'开始练习';
  $('start-icon').src=`icons/${phase==='active'?'pause':'play'}.svg`;
  document.body.classList.toggle('is-connected',phase==='active');
  const input=$('input').value,connected=input==='midi'?'MIDI 已连接':input==='recording'?'正在本地录音':input==='microphone'?'麦克风监听中':'电脑键盘演示';
  const status=phase==='active'?connected:phase==='paused'?'输入已暂停':phase==='connecting'?'正在连接':'尚未连接';
  for(const node of document.querySelectorAll('.connection-text'))node.textContent=status;
}
function currentOptions(){return{part:$('part').value,from:Number($('from').value),to:Number($('to').value)};}
function instrumentOptions(){return{instrument:$('instrument-choice').value,variant:$('instrument-variant').value};}
function selectedInstrument(){return resolveInstrument(score?.parts.find(p=>p.id===$('part').value)||score?.parts[0],$('instrument-choice').value,{variant:$('instrument-variant').value});}
function instrumentForPart(part){const options=$('part').value==='all'&&$('instrument-choice').value==='auto'?(instrumentPreferences.get(part.id)||{instrument:'auto'}):instrumentOptions();return resolveInstrument(part,options);}
function resolvedSelected(){return score.parts.filter(p=>$('part').value==='all'||p.id===$('part').value).map(instrumentForPart);}
function selection(){const o=currentOptions();if(!Number.isInteger(o.from)||!Number.isInteger(o.to)||o.from<1||o.to<o.from||o.to>score.lengths.length)throw new Error('请设置有效的小节范围。');const options=o.part==='all'&&$('instrument-choice').value==='auto'?{byPart:Object.fromEntries(instrumentPreferences)}:instrumentOptions();return selectGroups(score,o.part,o.from,o.to,engines.windows?options:undefined);}
function inputHint(){
  const input=$('input').value,poly=isPolyphonic(groups);$('midi-device').hidden=bridge.available||input!=='midi'||!midiAccess;
  $('input-hint').textContent=input==='keyboard'?'电脑键盘演示：A S D F G H J 为 C4 至 B4，K 为 C5。':input==='midi'?(bridge.available?'连接 USB MIDI 乐器后开始。支持同时演奏和弦；使用所有已连接的 MIDI 输入。':'连接 USB MIDI 乐器，开始后可在这里选择设备。支持同时演奏和弦。'):poly?'此声部含和弦或重叠音，请使用 MIDI，或选择单音声部。':'适合独奏单音。远离伴奏音源，并用耳机试听。';
  if(input==='recording')$('input-hint').textContent=local()?'演奏结束后在本机比对。严格节拍模式检查起音与时值，自由跟谱允许速度变化；疑似问题可回听复核。':'演奏结束后在本机比对音符与和弦。使用 A4=440，按所选 BPM 演奏；第一起音作为录音起点，不评整体抢拍。';
  else if(engines.windows&&input==='microphone')$('input-hint').textContent=poly?'此声部含和弦或重叠音，请使用 MIDI 或录后音频比对。':engines.nativeAudio?'本机麦克风识别单音；低音乐器使用较长观察窗。请用耳机试听。':$('input-hint').textContent;
}
function refreshVariant(saved=null){
  const profile=selectedInstrument(),manual=$('instrument-choice').value!=='auto';
  $('instrument-variant').replaceChildren(...profile.variants.map(v=>new Option(v.name,v.id)));
  $('instrument-variant').value=saved||profile.defaultVariant;
  $('variant-row').hidden=!engines.windows||!manual||profile.variants.length<2;
}
function rememberInstrument(){instrumentPreferences.set($('part').value,instrumentOptions());}
function configure(autoInput=false){
  if(!score)return;groups=selection();const parts=score.parts.filter(p=>$('part').value==='all'||p.id===$('part').value),info=parts.map(inferInstrument),poly=isPolyphonic(groups),manual=$('instrument-choice').value!=='auto';
  const resolved=engines.windows?resolvedSelected():null;
  const instrument=resolved?resolved.map(i=>i.name).join(' + '):manual?$('instrument-choice').selectedOptions[0].textContent:info.map(i=>i.name).join(' + ');
  $('instrument').textContent=instrument;$('instrument-summary').textContent=`${instrument} · ${$('part').selectedOptions[0]?.textContent||''}`;
  $('instrument-source').textContent=manual?'已手动选择乐器。':info.map(i=>i.source).join('；')+'，可手动调整。';
  if(resolved)$('instrument-source').textContent=resolved.map(i=>i.source).join('；')+'。'+(parts.some(p=>p.notes.some(n=>n.transposeExplicit))?'实声音高采用谱面移调信息。':manual?`谱面未注明移调，按所选谱制 ${selectedInstrument().transpose} 半音比对。`:'谱面未注明移调；移调乐器请手动确认乐器与谱制。');
  if(autoInput)$('input').value=poly||(!manual&&info.some(i=>i.input==='midi'))||$('instrument-choice').value==='piano'?'midi':'microphone';
  if(autoInput&&engines.windows){const midi=resolved.some(i=>i.input==='midi');$('input').value=midi?'midi':poly?(engines.basicPitch&&engines.nativeAudio?'recording':'midi'):'microphone';}
  const {from,to}=currentOptions();$('range-label').textContent=`第 ${from}–${to} 小节`;$('transport-range').textContent=`范围 ${from}–${to}`;
  $('tempo-label').textContent=`${$('bpm').value} BPM`;$('mode-label').textContent=$('mode').value==='wait'?'等我弹对':$('mode').value==='free'?'自由跟谱':'跟随节拍';
  inputHint();if(!session)$('next').textContent=groups.length?`${groups.length} 个起音位置 · ${poly?'请用 MIDI 演奏多音声部':'可用麦克风练习单音'}`:'这个声部没有可练习的音符。';
  if(phase!=='loading')renderScore();
}
function renderScore(force=false){
  if(!score||document.body.dataset.view==='review')return;
  const compact=matchMedia('(max-width:599px)').matches,scope=currentOptions();let from=scope.from,to=scope.to;
  if(compact){const current=session?.current?.mi+1||from;from+=Math.floor(Math.max(0,current-from)/2)*2;to=Math.min(to,from+1);}
  $('range-label').textContent=`第 ${from}${from!==to?`–${to}`:''} 小节`;
  const key=`${compact}/${from}/${to}/${$('score').clientWidth}`;if(!force&&key===renderedRange)return;renderedRange=key;
  osmd.setOptions({drawPartNames:!compact,drawFromMeasureNumber:from,drawUpToMeasureNumber:to,cursorsOptions:[cursorOptions]});osmd.Zoom=compact ? .85 : 1;osmd.render();osmd.cursor.CursorOptions=cursorOptions;
}
async function load(xml,title=null,id=null,metadata=null){
  const savedPackage=pendingPracticePackage;pendingPracticePackage=null;if(savedPackage?.omrMetadata)metadata=savedPackage.omrMetadata;
  await finish(false);stopPlayback();setPhase('loading');message('正在排版乐谱…');
  try{
    const parsed=parseScore(xml);
    if(engines.windows&&metadata?.origin==='local-omr')for(const p of parsed.parts){const real=metadata.parts?.find(m=>m.id===p.id);if(real){p.instrumentNames=[];p.instrumentAbbreviations=[];p.name=real.name||real.abbreviation||`声部 ${p.id}`;p.abbreviation=real.abbreviation||'';p.program=real.program||0;p.programExplicit=!!real.program;p.instrumentConfirmed=real.confirmed;}}
    if(local())await windowsPractice.request('score/prepare',{xml,title:title||parsed.title,metadata:metadata||{}});
    view('practice');await osmd.load(parsed.doc);if(local()&&parsed.parts.some(p=>p.notes.length)&&!collectScoreNotes(osmd,parsed).length){score=null;session=null;throw new Error('乐谱未能正确显示音符，请先校对后重新导入。');}score=parsed;scoreID=id;renderedRange='';
    if(title&&(!score.title||score.title==='未命名乐谱'))score.title=title.replace(/\.(musicxml|mxl|xml)$/i,'');
    for(const target of ['title','window-title','sidebar-title'])$(target).textContent=score.title;
    const composer=Array.from(score.doc.getElementsByTagName('creator')).find(n=>n.getAttribute('type')==='composer')?.textContent||'';
    $('composer').textContent=$('window-composer').textContent=composer;$('sheet-length').textContent=`共 ${score.lengths.length} 小节`;
    $('bpm').value=Math.min(240,Math.max(30,Math.round(score.tempo)));$('from').value=1;$('to').value=score.lengths.length;
    $('from').max=$('to').max=score.lengths.length;$('verified').checked=false;$('instrument-choice').value='auto';
    instrumentPreferences.clear();refreshVariant();
    $('part').replaceChildren(...score.parts.map(p=>new Option(p.name,p.id)));if(score.parts.length>1)$('part').add(new Option('全部声部','all'));$('part').value=score.parts[0]?.id||'';
    if(local()&&savedPackage?.selection){const saved=savedPackage.selection;for(const key of ['part','from','to','bpm','a4','mode','input'])if(saved[key]!=null)$(key).value=saved[key];$('instrument-choice').value=saved.instrument||'auto';if(saved.engine)$('recorded-engine').value=saved.engine;if(saved.baseline)$('alignment-baseline').value=saved.baseline;for(const [part,options]of Object.entries(saved.byPart||{}))instrumentPreferences.set(part,options);refreshVariant(saved.variant);}
    session=null;lastReport=null;configure(!savedPackage);renderScore(true);graphics=collectScoreNotes(osmd,score);osmd.cursor.reset();osmd.cursor.hide();renderReport();
    $('position').textContent='尚未开始';$('correct').textContent='—';$('errors').textContent='0';$('heard').textContent='—';$('progress').value=0;
    const warnings=local()?score.warnings.filter(w=>!w.startsWith('含反复或跳转')):score.warnings;message(warnings.length?warnings.join(' '):'先试听并校对乐谱，再开始练习。',warnings.length?'warning':'');
    setPhase('idle');
    if(engines.windows&&score.parts.some(p=>!resolveInstrument(p).reliable))openSettings('instrument-choice');
  }catch(error){setPhase('idle');throw error;}
}
function cursorAt(group){if(!group)return;osmd.cursor.reset();let i=0;while(!osmd.cursor.Iterator.EndReached&&osmd.cursor.Iterator.CurrentSourceTimestamp.RealValue*4<group.onset-.00001&&i++<50000)osmd.cursor.next();osmd.cursor.show();}
function colorGroup(group,color){colorScoreGroup(osmd,graphics,group,color);}
function update(){
  if(!session)return;const g=session.current;
  $('correct').textContent=`${session.results.filter(r=>r.status==='correct').length} / ${session.groups.length}`;$('errors').textContent=String(session.errors.filter(e=>!e.resolved).length);
  $('position').textContent=g?`第 ${g.measure} 小节 / 共 ${score.lengths.length} 小节`:'本段已完成';$('progress').max=session.groups.length;$('progress').value=session.index;
  $('next').textContent=g?`第 ${g.measure} 小节 · 第 ${formatBeat(g.beat)} 拍 · 应弹 ${[...new Set(g.notes.map(n=>noteName(n.midi)))].join(' + ')}`:'本段已完成，可在回顾中重练难点。';
  renderScore();if(g&&phase==='active')cursorAt(g);
  for(const r of session.results){
    if(local()&&r.notes){for(const note of r.notes){const relevant=session.errors.filter(e=>e.index===r.index&&(e.expected?.includes(note.midi)||e.played===note.midi));const uncertain=relevant.some(e=>e.kind==='uncertain'&&!e.resolved),bad=relevant.some(e=>!['uncertain'].includes(e.kind));colorScoreNotes(osmd,graphics,[note.sourceNoteId||note.id],uncertain?'#a77b36':bad||!note.matched?'#b84f45':'#417f62');}}
    else colorGroup(session.groups[r.index],r.status==='correct'?'#417f62':r.status==='missing'?'#b84f45':'#a77b36');
  }
  if(local())for(const error of [...session.errors,...(session.pendingReview||[])]){if(error.resolved)continue;const affected=session.groups[error.index]?.notes.filter(n=>!error.expected?.length||error.expected.includes(n.midi)).map(n=>n.sourceNoteId||n.id)||[];colorScoreNotes(osmd,graphics,affected,error.kind==='uncertain'?'#a77b36':'#b84f45');}
  renderReport();if(!session.active&&phase==='active'&&!recordingMode)guard(()=>finish(true))();
}
function receive(midi,time=performance.now(),cents=0){
  if(local()){if(phase==='active')guard(()=>windowsNote('note-on',midi,`${$('input').value}:${midi}`,time))();return;}
  if(phase!=='active'||!session?.active||!Number.isInteger(midi)||midi<0||midi>127)return;
  $('heard').textContent=noteName(midi)+(Math.abs(cents)>3?` ${cents>0?'+':''}${Math.round(cents)}¢`:'');
  const result=session.noteOn(midi,time,cents);if(!result)return;
  if(result.kind==='wrong'||result.kind==='extra'){colorGroup(result.group,'#b84f45');message(`第 ${result.group.measure} 小节 · 第 ${formatBeat(result.group.beat)} 拍：应弹 ${result.group.notes.map(n=>noteName(n.midi)).join(' + ')}，听到 ${noteName(midi)}。`,'warning');}
  else if(result.kind==='correct'){colorGroup(result.group,'#417f62');message(result.complete?'这个位置已弹对，继续下一音。':'音高正确，请继续弹齐和弦。');}
  update();
}
function processAudio(samples,sampleRate){
  if(phase!=='active'||$('input').value!=='microphone'||samples.length!==4096||!(sampleRate>=8000&&sampleRate<=192000))return;
  buffer.set(samples);const rms=Math.sqrt(buffer.reduce((sum,x)=>sum+x*x,0)/buffer.length),[hz,clarity]=detector.findPitch(buffer,sampleRate);
  const result=gate.push(hz*440/Number($('a4').value),clarity,rms);if(result)receive(result.midi,performance.now(),result.cents);
}
async function context(){audioContext??=new AudioContext();if(audioContext.state==='suspended')await audioContext.resume();return audioContext;}
async function connectMic(){
  const generation=inputGeneration;if(!navigator.mediaDevices?.getUserMedia)throw new Error('此浏览器不能录音，请使用音伴原生应用，或在支持录音的浏览器打开。');
  const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:false,noiseSuppression:false,autoGainControl:false},video:false});
  if(generation!==inputGeneration){stream.getTracks().forEach(t=>t.stop());return false;}
  let ctx;try{ctx=await context();}catch(error){stream.getTracks().forEach(t=>t.stop());throw error;}
  if(generation!==inputGeneration){stream.getTracks().forEach(t=>t.stop());return false;}
  micStream=stream;micAnalyser=ctx.createAnalyser();micAnalyser.fftSize=4096;ctx.createMediaStreamSource(stream).connect(micAnalyser);gate.reset();
  const poll=()=>{if(!micStream)return;micAnalyser.getFloatTimeDomainData(buffer);processAudio(buffer,ctx.sampleRate);animation=requestAnimationFrame(poll);};poll();return true;
}
function refreshMidi(){
  const devices=Array.from(midiAccess.inputs.values()).filter(d=>d.state==='connected'),previous=$('midi-device').value;
  $('midi-device').replaceChildren(...devices.map(d=>new Option(d.name||d.id,d.id)));if(devices.some(d=>d.id===previous))$('midi-device').value=previous;
  if(!devices.length){if(phase==='active')pause();message('MIDI 乐器已断开，请重新连接后继续。','warning');return false;}selectMidi();inputHint();return true;
}
function selectMidi(){if(selectedMidi)selectedMidi.onmidimessage=null;selectedMidi=midiAccess?.inputs.get($('midi-device').value);if(selectedMidi)selectedMidi.onmidimessage=({data,timeStamp})=>{const type=data[0]&0xf0;if(local()&&(type===0x80||type===0x90)){guard(()=>windowsNote(type===0x90&&data[2]>0?'note-on':'note-off',data[1],`midi:${data[0]&15}:${data[1]}`,timeStamp))();}else if(type===0x90&&data[2]>0)receive(data[1],timeStamp);};}
async function connectMidi(){
  const generation=inputGeneration;if(!navigator.requestMIDIAccess)throw new Error('此浏览器不支持 MIDI，请使用音伴原生应用，或在 Chrome / Edge 打开。');
  const access=midiAccess||await navigator.requestMIDIAccess({sysex:false});if(generation!==inputGeneration)return false;
  midiAccess=access;midiAccess.onstatechange=()=>{if(phase==='active')refreshMidi();};if(!refreshMidi())throw new Error('未找到 MIDI 乐器。连接后重试，或在设置中选择电脑键盘演示。');return true;
}
async function connectInput(){gate.reset();const input=$('input').value;if(input==='keyboard')return true;if(bridge.available)return bridge.requestInput(input);
  if(engines.windows&&engines.nativeAudio&&['microphone','recording'].includes(input)){
    const profiles=resolvedSelected(),profile={...profiles[0],minHz:Math.min(...profiles.map(p=>p.minHz)),maxHz:Math.max(...profiles.map(p=>p.maxHz)),windowSize:Math.max(...profiles.map(p=>p.windowSize))};nativeGate.reset();recordingMode=input==='recording';
    nativeListening=true;try{return await windowsAudio.start({...profile,minHz:Math.max(15,profile.minHz/1.08),maxHz:Math.min(10000,profile.maxHz*1.08)},{record:recordingMode||local()&&$('save-recording').checked,a4:Number($('a4').value),device:Number($('capture-device').value)});}catch(error){nativeListening=false;recordingMode=false;await windowsAudio.stop().catch(()=>{});throw error;}
  }
  return input==='microphone'?connectMic():connectMidi();}
function releaseInput(){
  inputGeneration++;cancelAnimationFrame(animation);clearInterval(tickTimer);clearInterval(beatTimer);clearTimeout(beatStartTimer);stopPlayback();
  if(nativeListening){nativeListening=false;windowsAudio.stop().catch(error=>message(error.message,'error'));}nativeGate.reset();
  micStream?.getTracks().forEach(t=>t.stop());micStream=null;micAnalyser=null;if(selectedMidi){selectedMidi.onmidimessage=null;selectedMidi=null;}bridge.stop();gate.reset();
}
function stopDuration(){if(activeStartedAt!==null){elapsedMilliseconds+=performance.now()-activeStartedAt;activeStartedAt=null;}}
function startClock(ctx,fresh){
  if(session.mode!=='tempo')return;const beat=60000/session.bpm,now=performance.now();
  if(fresh){session.begin(now+4*beat);for(let i=0;i<4;i++)tone(ctx,880,i*beat/1000,.06,.07);message('预备 4 拍，再开始演奏。');}
  const nextBeat=session.startedAt+Math.max(0,Math.ceil((now-session.startedAt)/beat))*beat;
  beatStartTimer=setTimeout(()=>{if(phase==='active'){tone(ctx,880,0,.04,.035);beatTimer=setInterval(()=>{if(phase==='active')tone(ctx,880,0,.04,.035);},beat);}},Math.max(0,nextBeat-now));
  tickTimer=setInterval(()=>{if(phase==='active'){const previous=session.index;session.tick(performance.now());if(previous!==session.index)update();}},40);
}
async function start(){
  if(local())return startWindows();
  if(phase==='active'){if(recordingMode)await finishRecording();else pause();return;}if(phase==='paused'){await resume();return;}
  if(!score)throw new Error('请先导入乐谱。');
  if(!$('verified').checked){openSettings('verified');throw new Error('请先试听或校对乐谱，并勾选确认。');}
  groups=selection();const input=$('input').value,range=currentOptions(),invalid=score.issues.filter(i=>(range.part==='all'||i.part===range.part)&&i.mi>=range.from-1&&i.mi<range.to);
  if(invalid.length)throw new Error(`第 ${[...new Set(invalid.map(i=>i.measure))].join('、')} 小节时值超过拍号。请先校对，或选择其他小节。`);
  if(input==='microphone'&&isPolyphonic(groups)){openSettings('input');throw new Error('所选段落含多音或和弦，请改选单音声部或使用 MIDI。');}
  if(engines.windows&&['microphone','recording'].includes(input)&&resolvedSelected().some(p=>!p.reliable)){openSettings('instrument-choice');throw new Error('谱面没有可靠的乐器信息，请先逐声部选择演奏乐器。');}
  if(input==='recording'&&(!engines.basicPitch||!engines.nativeAudio))throw new Error('此安装包没有本地录后音频组件。');
  const bpm=Number($('bpm').value),a4=Number($('a4').value);if(!(bpm>=30&&bpm<=240&&a4>=415&&a4<=466))throw new Error('请使用 30–240 BPM，调音 A4 范围 415–466 Hz。');
  if(input==='recording'&&a4!==440){openSettings('a4');throw new Error('录音分析目前使用标准 A4=440 Hz，请先将调音设为 440。其他调音可使用实时麦克风。');}
  const candidate=new PracticeSession(groups,{mode:$('mode').value,bpm});candidate.active=false;
  candidate.metadata={input,instrument:$('instrument').textContent,scope:currentOptions(),a4};
  stopPlayback();const generation=++inputGeneration;setPhase('connecting');message('正在连接演奏输入…');
  try{
    const ctx=candidate.mode==='tempo'?await context():null;if(generation!==inputGeneration)return;
    if(!await connectInput()||generation!==inputGeneration)return;
    if(ctx?.state==='suspended')await ctx.resume();if(generation!==inputGeneration)return;
    session=candidate;session.active=true;createdAt=new Date();elapsedMilliseconds=0;activeStartedAt=performance.now();lastReport=null;
    resetScoreColors(osmd,graphics);view('practice');setPhase('active');$('settings').close();
    message(recordingMode?'正在本地录音。按所选速度演奏，结束后点击“结束录音”。':input==='keyboard'?'键盘演示：A S D F G H J 对应 C4–B4，K 为 C5。':'弹对当前音后，谱面会自动前进。');if(!recordingMode)startClock(ctx,true);update();
  }catch(error){if(generation===inputGeneration){releaseInput();setPhase('idle');throw error;}}
}
function pause(){
  if(local()){guard(pauseWindows)();return;}
  if(recordingMode&&phase==='active'){guard(finishRecording)();return;}
  if(phase==='connecting'){releaseInput();setPhase(session?.pausedAt!==null&&session?.current?'paused':'idle');return;}
  if(phase!=='active')return;session.pause(performance.now());stopDuration();releaseInput();setPhase('paused');message('已暂停。继续后从当前音接着练。');renderReport();
}
async function resume(){
  if(local())return resumeWindows();
  if(phase!=='paused'||!session?.current)return;const generation=++inputGeneration;setPhase('connecting');message('正在重新连接…');
  try{
    const ctx=session.mode==='tempo'?await context():null;if(generation!==inputGeneration)return;
    if(!await connectInput()||generation!==inputGeneration)return;
    if(ctx?.state==='suspended')await ctx.resume();if(generation!==inputGeneration)return;
    session.resume(performance.now());activeStartedAt=performance.now();setPhase('active');message('继续演奏当前音。');startClock(ctx,false);update();
  }catch(error){if(generation===inputGeneration){releaseInput();setPhase('paused');throw error;}}
}
function reportData(){
  if(!session)return null;
  if(local())return lastReport||session.report();const data=session.report(),duration=elapsedMilliseconds+(activeStartedAt===null?0:performance.now()-activeStartedAt);
  const practiced=new Set([...session.results.map(r=>session.groups[r.index].mi),...session.errors.map(e=>e.mi)]);if(session.matched.size&&session.current)practiced.add(session.current.mi);
  return{title:score.title,scoreID,createdAt:(createdAt||new Date()).toISOString(),durationSeconds:Math.max(0,duration/1000),...session.metadata,...data,completedPositions:data.completed,completed:session.index>=session.groups.length,measureCount:practiced.size,totalMeasureCount:new Set(session.groups.map(g=>g.mi)).size,limitations:session.metadata?.engine==='basic-pitch'?'Local recorded transcription; constant first-onset alignment; no tone, pedal or expression assessment; model errors may affect results':'Note-on pitch and timing only; microphone monophonic; unperformed notes not graded'};
}
function finish(showReview=true){
  if(local())return finishWindows(showReview);
  stopDuration();releaseInput();
  if(!session){setPhase('idle');return null;}
  if(lastReport){setPhase('finished');if(showReview){renderReport();view('review');}return lastReport;}
  session.finish();lastReport=reportData();bridge.post({type:'report',report:lastReport});setPhase('finished');osmd.cursor.hide();
  $('position').textContent=lastReport.completed?'本段已完成':'练习已结束';message(lastReport.completed?'本段已完成。可以查看记录，重练难点。':'练习记录已保留。未演奏的部分不计为弹对。');renderReport();if(showReview)view('review');return lastReport;
}
function validateRecording(){
  if(local()){validateWindows();return selection();}
  if(!score)throw new Error('请先导入乐谱。');
  if(!$('verified').checked){openSettings('verified');throw new Error('请先试听或校对乐谱，并勾选确认。');}
  const range=currentOptions(),selected=selection();
  if(!selected.length)throw new Error('所选范围没有可练习的音符。');
  if(score.issues.some(i=>(range.part==='all'||i.part===range.part)&&i.mi>=range.from-1&&i.mi<range.to))throw new Error('所选小节时值超过拍号，请先校对乐谱。');
  if(resolvedSelected().some(p=>!p.reliable)){openSettings('instrument-choice');throw new Error('请先逐声部确认演奏乐器。');}
  if(!engines.basicPitch)throw new Error('此安装包没有 Basic Pitch 本地组件。');
  if(Number($('a4').value)!==440){openSettings('a4');throw new Error('录音分析目前使用标准 A4=440 Hz，请先将调音设为 440。');}
  return selected;
}
async function compareRecording(file=null){
  if(local())return compareWindowsRecording(file);
  const selected=validateRecording(),bpm=Number($('bpm').value),meta={input:'recording',instrument:$('instrument').textContent,scope:currentOptions(),a4:Number($('a4').value),instrumentOptions:instrumentOptions()};
  if(!(bpm>=30&&bpm<=240))throw new Error('请使用 30–240 BPM。');
  if(file&&file.size>64*1024*1024)throw new Error('录音不能超过 64 MB。');
  analysisBusy=true;setPhase('loading');message('正在本机分析录音与乐谱，请稍候…');
  try{
    const response=await fetch(file?'analysis':'analysis?recorded=true',{method:'POST',headers:file?{'Content-Type':'application/octet-stream'}:undefined,body:file||undefined});
    const output=await response.json();if(!response.ok)throw new Error(output.error||'本地录音分析失败。');
    if(output.schemaVersion!==1||output.engine!=='basic-pitch'||!Array.isArray(output.notes))throw new Error('本地分析结果格式无效。');
    if(!output.notes.length)throw new Error('没有检测到可靠音符，请检查麦克风或改用更清晰的录音。');
    const report=analyzeRecording(selected,output.notes,{bpm});
    groups=selected;session=new PracticeSession(groups,{mode:'tempo',bpm});session.mode='recorded';session.active=false;session.index=report.completed;session.results=report.results;session.errors=report.errors;session.played=report.played;
    session.metadata={...meta,engine:output.engine,alignment:report.alignment,transcription:output.notes,unjudged:report.unjudged,analysisWarnings:output.warnings||[]};
    createdAt=new Date();elapsedMilliseconds=Number(output.seconds||0)*1000;activeStartedAt=null;lastReport=null;
    resetScoreColors(osmd,graphics);setPhase('finished');update();lastReport=reportData();renderReport();view('review');
    message('录音比对已完成。低置信度与余音仍可能影响结果，可回听核对。');
  }catch(error){setPhase('idle');throw error;}
  finally{analysisBusy=false;recordingMode=false;setPhase(session?.index===session?.groups?.length?'finished':'idle');}
}
async function finishRecording(){
  if(analysisBusy||!recordingMode)return;
  stopDuration();releaseInput();recordingMode=false;setPhase('loading');
  try{await windowsAudio.pending;await compareRecording();}catch(error){analysisBusy=false;setPhase('idle');throw error;}
}
function tone(ctx,midiOrHz,delay,duration,volume=.08,isMidi=false){
  const osc=ctx.createOscillator(),gain=ctx.createGain(),time=ctx.currentTime+delay;osc.type='triangle';osc.frequency.value=isMidi?440*2**((midiOrHz-69)/12):midiOrHz;
  gain.gain.setValueAtTime(0,time);gain.gain.linearRampToValueAtTime(volume,time+.012);gain.gain.exponentialRampToValueAtTime(.001,time+Math.max(.04,duration));
  osc.connect(gain);gain.connect(ctx.destination);osc.start(time);osc.stop(time+Math.max(.05,duration)+.02);playback.push(osc);osc.onended=()=>{playback=playback.filter(item=>item!==osc);osc.disconnect();gain.disconnect();};
}
function stopPlayback(){if(local()&&nativePlayback){nativePlayback=false;windowsPractice.request('playback/stop',{}).catch(()=>{});}clearTimeout(playbackTimer);for(const osc of playback){try{osc.stop();}catch{}}playback=[];$('listen').setAttribute('aria-label','试听所选段落');$('listen').title='试听所选段落';$('listen').querySelector('img').src='icons/volume-2.svg';}
async function listen(){
  if(local())return listenWindows();
  if(playback.length){stopPlayback();return;}if(!score)throw new Error('请先导入乐谱。');
  const ctx=await context(),notes=selection(),bpm=Number($('bpm').value),start=notes[0]?.onset||0;
  if(notes.length>3000)throw new Error('请先缩小试听小节范围。');if(!(bpm>=30&&bpm<=240))throw new Error('试听速度需在 30–240 BPM 之间。');
  let end=0;for(const g of notes)for(const n of g.notes){const delay=(n.onset-start)*60/bpm,duration=Math.max(.05,n.duration*60/bpm-.02);tone(ctx,n.midi,delay,duration,.045,true);end=Math.max(end,delay+duration);}
  $('listen').setAttribute('aria-label','停止试听');$('listen').title='停止试听';$('listen').querySelector('img').src='icons/pause.svg';playbackTimer=setTimeout(stopPlayback,(end+.1)*1000);
}
function formatBeat(beat){return beat.toFixed(2).replace(/\.00$/,'');}
function describe(e){
  if(e.kind==='uncertain')return`未能可靠判断 ${(e.expected||[]).map(noteName).join(' + ')}，请回听确认。`;
  if(e.kind==='short'||e.kind==='long')return `${noteName(e.played)} 持续 ${Math.round(e.durationMs)} ms，应约 ${Math.round(e.expectedDurationMs)} ms`;
  if(e.kind==='extra')return `听到额外的 ${noteName(e.played)}`;
  if(e.kind==='wrong')return`应弹 ${(e.expected||[]).map(noteName).join(' + ')}，听到 ${noteName(e.played)}`;
  if(e.kind==='missing')return`未听到 ${e.expected.map(noteName).join(' + ')}`;
  if(e.kind==='intonation')return`${noteName(e.played)} ${e.cents>0?'偏高':'偏低'} ${Math.abs(Math.round(e.cents))} 音分`;
  return`${noteName(e.played)} ${e.delta<0?'提前':'延后'} ${Math.abs(Math.round(e.delta))} ms`;
}
async function retryMeasures(from,to){
  await finish(false);$('from').value=from;$('to').value=to;session=null;lastReport=null;setPhase('idle');resetScoreColors(osmd,graphics);configure();view('practice');cursorAt(groups[0]);renderReport();message(`已选第 ${from}${to!==from?`–${to}`:''} 小节。点击“开始练习”重练。`);
}
function renderErrorList(id,review=false){
  const list=$(id);list.replaceChildren();const errors=(session?.errors||[]).filter(e=>!e.resolved);
  if(!errors.length){const p=document.createElement('p');p.className='empty';p.textContent=session?'本次暂未记录错音。未完成的音符不会计为弹对。':'演奏后，这里会显示具体小节和需要复习的音符。';list.append(p);return;}
  for(const e of (review?errors:errors.slice(-20))){
    const row=document.createElement('div');row.className='error-row';const badge=document.createElement('span');badge.className='badge';badge.textContent=labels[e.kind];
    const title=document.createElement('strong'),p=document.createElement('p');title.textContent=`第 ${e.measure} 小节 · 第 ${formatBeat(e.beat)} 拍`;p.textContent=describe(e);
    const button=document.createElement('button');button.textContent=['active','connecting','paused'].includes(phase)?'结束后可单独重练':'重练此小节';button.disabled=['active','connecting','paused'].includes(phase);button.onclick=()=>retryMeasures(e.mi+1,e.mi+1);row.append(badge,title,p,button);if(local()&&(lastReport?.hasRecording||session?.hasRecording)){const replay=document.createElement('button');replay.textContent='回听此处';replay.disabled=['active','connecting'].includes(phase);replay.onclick=guard(()=>replayTake(Math.max(0,(e.replayMs||0)-700),(e.replayMs||0)+2500,e.index));row.append(replay);}list.append(row);
  }
}
function renderReport(){
  if(!session){$('correct').textContent='—';$('errors').textContent='0';$('heard').textContent='—';$('position').textContent='尚未开始';$('progress').value=0;}
  renderErrorList('error-list');renderErrorList('review-error-list',true);
  if(local()){$('local-take-actions').hidden=!lastReport?.takeId;$('replay-take').disabled=!lastReport?.hasRecording;$('recheck-take').disabled=!lastReport?.hasRecording;}
  const visibleErrors=(session?.errors||[]).filter(e=>!e.resolved),errorMeasures=[...new Set(visibleErrors.map(e=>e.mi))];$('mobile-error-summary').textContent=session?`已标记 ${visibleErrors.length} 处需要复习`:'练习后查看记录';
  $('review-title').textContent=score?.title||'尚无练习记录';$('review-errors').textContent=String(errorMeasures.length);
  $('review-measures').textContent=String(reportData()?.measureCount||0);$('review-correct').textContent=session?`${session.results.filter(r=>r.status==='correct').length} / ${session.groups.length}`:'—';
  const duration=Math.floor(reportData()?.durationSeconds||0);$('review-date').textContent=session?`${createdAt.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})} · 练习 ${Math.floor(duration/60)} 分 ${duration%60} 秒`:'';
  $('review-heading').textContent=errorMeasures.length?'这些小节再来一次':session?'本次记录':'练习后再来看看';
  $('review-note').textContent=session&&session.index<session.groups.length?'本次尚未弹完所选段落，未演奏的部分没有计为弹对。':'从较慢的速度开始，弹稳后再加速。';
  $('retry').disabled=!session||['active','paused','connecting'].includes(phase);$('retry').querySelector('span').textContent=errorMeasures.length?'重练有错音的段落':'再练一次';$('report').disabled=!session;
}
function showReview(){if(phase==='active')pause();renderReport();view('review');}
function downloadReport(){
  if(!session)throw new Error('先完成一次练习再保存记录。');const report=lastReport||reportData();
  if(bridge.available){message('本次记录会在结束练习后保存到曲谱库。');return;}
  const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='音伴-练习记录.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);
}
async function readFile(file){if(file.size>(/\.zip$/i.test(file.name)?96:15)*1024*1024)throw new Error('文件过大：乐谱限 15 MB，本机练习包限 96 MB。');return readBytes(new Uint8Array(await file.arrayBuffer()));}
function readBytes(bytes){
  if(bytes.byteLength>96*1024*1024||bytes.byteLength>15*1024*1024&&!(bytes[0]===80&&bytes[1]===75))throw new Error('乐谱或练习包过大。');
  if(bytes[0]===80&&bytes[1]===75){
    let total=0;const files=unzipSync(bytes,{filter:f=>{if(/\.(xml|musicxml|json)$/i.test(f.name)){total+=f.originalSize;if(total>30*1024*1024)throw new Error('解压后的乐谱过大。');return true;}return false;}}),container=files['META-INF/container.xml'];
    if(files['source.musicxml']&&files['practice.json']){const pack=JSON.parse(strFromU8(files['practice.json']));if(pack.schemaVersion!==1||pack.format!=='notelite-practice-package')throw new Error('练习包格式无效。');pendingPracticePackage=pack;return strFromU8(files['source.musicxml']);}
    if(!container)throw new Error('压缩乐谱缺少 MusicXML container.xml。');const doc=new DOMParser().parseFromString(strFromU8(container),'application/xml'),root=doc.getElementsByTagName('rootfile')[0]?.getAttribute('full-path');if(!root||!files[root])throw new Error('压缩乐谱未找到主文件。');return strFromU8(files[root]);
  }return new TextDecoder().decode(bytes);
}

function windowsOptions(){const profiles=score?resolvedSelected():[],byPart=$('part').value==='all'&&$('instrument-choice').value==='auto'?Object.fromEntries(instrumentPreferences):{};return{...currentOptions(),...instrumentOptions(),byPart,minHz:Math.max(15,Math.min(...profiles.map(p=>p.minHz))/1.08),maxHz:Math.min(10000,Math.max(...profiles.map(p=>p.maxHz))*1.08),bpm:Number($('bpm').value),a4:Number($('a4').value),mode:$('mode').value,input:$('input').value,verified:$('verified').checked,engine:$('recorded-engine').value,baseline:$('alignment-baseline').value,feedbackPolicy:'active',gradeDuration:true,autoReposition:true,playbackDevice:Number($('playback-device').value)};}
function validateWindows(){
  if(!score)throw new Error('请先导入乐谱。');
  if(!$('verified').checked){openSettings('verified');throw new Error('请先试听或校对乐谱，并勾选确认。');}
  const selected=selection(),range=currentOptions(),options=windowsOptions();
  if(!selected.length)throw new Error('所选范围没有可练习的音符。');
  if(score.issues.some(i=>(range.part==='all'||i.part===range.part)&&i.mi>=range.from-1&&i.mi<range.to))throw new Error('所选小节时值超过拍号，请先校对乐谱。');
  if(!(options.bpm>=30&&options.bpm<=240&&options.a4>=415&&options.a4<=466))throw new Error('请使用 30–240 BPM，调音 A4 范围 415–466 Hz。');
  if(['microphone','recording'].includes(options.input)&&resolvedSelected().some(p=>!p.reliable)){openSettings('instrument-choice');throw new Error('谱面没有可靠的乐器信息，请先逐声部选择演奏乐器。');}
  if(options.input==='microphone'&&isPolyphonic(selected)){openSettings('input');throw new Error('所选声部含和弦或重叠音，请选单音声部、MIDI 或录后比对。');}
  if(options.input==='recording'&&options.engine!=='basic-pitch'&&isPolyphonic(selected)){openSettings('recorded-engine');throw new Error('所选声部含和弦或重叠音，请先选择“单音与和弦”检测。');}
  return options;
}
let windowsSignature='';
function applyWindows(snapshot){
  if(!snapshot)return;if(!snapshot.groups&&session?.groups)snapshot={...snapshot,groups:session.groups};if(!snapshot.groups)return;
  const signature=JSON.stringify([snapshot.currentIndex,snapshot.errors,snapshot.results,snapshot.active,snapshot.paused,snapshot.awaitingRelease,snapshot.pendingFollowing,snapshot.pendingReview,snapshot.played?.length]);
  session=displaySession(snapshot,score);groups=session.groups;createdAt=new Date(snapshot.createdAt||Date.now());
  const heard=snapshot.played?.at(-1);if(heard)$('heard').textContent=noteName(heard.midi)+(Math.abs(heard.cents||0)>3?` ${Math.round(heard.cents)}¢`:'');
  if(signature===windowsSignature)return;windowsSignature=signature;
  resetScoreColors(osmd,graphics);update();
  const unresolved=(snapshot.pendingReview||[]).filter(e=>!e.resolved),error=snapshot.errors?.filter(e=>!e.resolved).at(-1);
  if(snapshot.pendingFollowing&&phase==='active')message(`正在确认是否${snapshot.pendingFollowing.direction==='backtrack'?'重弹':'跳到'}第 ${snapshot.pendingFollowing.measure} 小节…`,'warning');
  else if(unresolved.length&&phase==='active')message(`待复核：${describe(unresolved.at(-1))}`,'warning');
  else if(error&&phase==='active')message(`第 ${error.measure} 小节 · ${labels[error.kind]||'请复核'}：${describe(error)}`,'warning');
}
function pollWindows(){windowsPractice.poll(applyWindows,error=>{if(phase==='active'){guard(pauseWindows)();message(error.message,'error');}});}
async function windowsNote(type,midi,id,time){
  if(phase!=='active'||!session?.active)return;
  const snapshot=await windowsPractice.event({type,midi,id,cents:0,delayMs:Math.max(0,performance.now()-time)});applyWindows(snapshot);
}
async function startWindows(){
  if(phase==='active'){if(recordingMode)return finishRecording();return pauseWindows();}
  if(phase==='paused')return resumeWindows();
  const options=validateWindows();stopPlayback();const generation=++inputGeneration;setPhase('connecting');message('正在准备本地陪练…');
  const transition={kind:'start'};windowsTransition=transition;
  try{
    transition.promise=(async()=>{
      lastReport=null;windowsSignature='';applyWindows(await windowsPractice.request('practice/start',options));
      if(generation!==inputGeneration)return;
      if(!await connectInput()||generation!==inputGeneration)return;
      resetScoreColors(osmd,graphics);view('practice');setPhase('active');$('settings').close();pollWindows();
      message(recordingMode?'正在本地录音，演奏结束后点击“结束录音”。':options.mode==='tempo'?'预备 4 拍，再跟随节拍演奏。':options.mode==='free'?'跟随你的演奏前进，可停顿、变速或重弹。':'弹对当前音后继续；长音请保持到松开。');update();
    })();await transition.promise;
  }catch(error){if(generation===inputGeneration){releaseInput();await windowsAudio.pending;windowsPractice.stop();await windowsPractice.finish().catch(()=>{});session=null;setPhase('idle');throw error;}}
  finally{if(windowsTransition===transition)windowsTransition=null;}
}
async function pauseWindows(){
  if(recordingMode&&phase==='active')return finishRecording();
  if(!['active','connecting'].includes(phase))return;
  const transition=windowsTransition;releaseInput();windowsPractice.stop();await transition?.promise?.catch(()=>{});await windowsPractice.pending;
  if(transition?.kind==='start'){await windowsAudio.pending;await windowsPractice.finish();session=null;recordingMode=false;setPhase('idle');message('已取消连接，可重新开始。');return;}
  if(session)applyWindows(await windowsPractice.request('practice/pause',{}));releaseInput();await windowsAudio.pending;
  if(session){applyWindows(await windowsPractice.request('practice/state'));if(!session.active||!session.current)return finishWindows();}
  setPhase(session?.current?'paused':'idle');message('已暂停。继续后接着练当前音。');renderReport();
}
async function resumeWindows(){
  if(phase!=='paused'||!session?.current)return;const generation=++inputGeneration;setPhase('connecting');
  const transition={kind:'resume'};windowsTransition=transition;
  try{transition.promise=(async()=>{if(!await connectInput()||generation!==inputGeneration)return;const snapshot=await windowsPractice.request('practice/resume',{});applyWindows(snapshot);if(generation!==inputGeneration)return;setPhase('active');pollWindows();message('继续演奏当前音。');})();await transition.promise;}
  catch(error){if(generation===inputGeneration){releaseInput();await windowsAudio.pending;await windowsPractice.request('practice/pause',{}).catch(()=>{});setPhase('paused');throw error;}}
  finally{if(windowsTransition===transition)windowsTransition=null;}
}
async function finishWindows(showReview=true){
  if(finishingWindows)return lastReport;
  finishingWindows=true;
  try{
    const transition=windowsTransition;if(transition){releaseInput();await transition.promise?.catch(()=>{});await windowsAudio.pending;}
    windowsPractice.stop();if(!session){releaseInput();setPhase('idle');return null;}
    if(lastReport){setPhase('finished');if(showReview)view('review');return lastReport;}
    releaseInput();await windowsAudio.pending;lastReport=await windowsPractice.finish();applyWindows(lastReport);setPhase('finished');osmd.cursor.hide();renderReport();if(showReview)view('review');message(lastReport.warning||(lastReport.hasRecording?'练习和录音已保存在本机。可回听问题位置或单独重练。':'练习记录已保存在本机。可查看反馈并单独重练。'),lastReport.warning?'warning':'');return lastReport;
  }
  finally{finishingWindows=false;}
}
async function compareWindowsRecording(file=null){
  const options=validateWindows();if(file&&file.size>64*1024*1024)throw new Error('录音不能超过 64 MB。');
  if(options.engine!=='basic-pitch'&&isPolyphonic(selection()))throw new Error('此检测用于单音，请选单音声部；和弦请使用“单音与和弦”。');
  analysisBusy=true;windowsPractice.stop();setPhase('loading');message('正在本机转录、跟谱并复核录音…');
  try{const params=new URLSearchParams({options:JSON.stringify({...options,input:'recording'})});if(!file)params.set('recorded','true');
    const response=await fetch(`analysis?${params}`,{method:'POST',headers:file?{'Content-Type':'application/octet-stream'}:undefined,body:file||undefined});const result=await response.json();if(!response.ok)throw new Error(result.error||'本地录后复核失败。');
    lastReport=result;windowsSignature='';applyWindows(result);recordingMode=false;setPhase('finished');renderReport();view('review');message(result.warning||'录后比对已完成，录音与报告保存在本机。疑似问题可回听此处。',result.warning?'warning':'');
  }catch(error){const saved=await windowsPractice.request('practice/state').catch(()=>null);if(saved?.takeId&&((saved.analysisPending&&saved.hasRecording)||saved.recoveryRecordings?.length)){lastReport=saved;applyWindows(saved);renderReport();view('review');error.message+=saved.recoveryRecordings?.length?' 原始录音片段已随练习包保存，可导出保留。':' 录音已保存在本机记录，可重新复核。';}throw error;
  }finally{analysisBusy=false;recordingMode=false;setPhase(lastReport?'finished':'idle');}
}
async function listenWindows(){
  if(nativePlayback){stopPlayback();return;}
  if(!score)throw new Error('请先导入乐谱。');await windowsPractice.request('playback/reference',windowsOptions());nativePlayback=true;
  $('listen').setAttribute('aria-label','停止试听');$('listen').title='停止试听';$('listen').querySelector('img').src='icons/pause.svg';
  const poll=async()=>{if(!nativePlayback)return;const state=await windowsPractice.request('playback/state');if(!state.playing){nativePlayback=false;stopPlayback();}else playbackTimer=setTimeout(()=>guard(poll)(),100);};poll();
}
async function replayTake(startMs=0,endMs=0,index=null){
  if(!lastReport?.takeId)throw new Error('请先完成并保存一次练习。');
  if(nativePlayback){stopPlayback();return;}
  await windowsPractice.request('playback/take',{id:lastReport.takeId,startMs,endMs,device:Number($('playback-device').value)});nativePlayback=true;
  view('practice');if(index!==null){cursorAt(session.groups[index]);colorGroup(session.groups[index],'#a77b36');}
  message('正在回听你的演奏。再次点击回听可停止。');
  const track=async()=>{if(!nativePlayback)return;const state=await windowsPractice.request('playback/state');if(!state.playing){nativePlayback=false;message('回听结束，可在回顾中重练。');return;}
    if(index===null){const played=(lastReport.played||[]).filter(n=>(n.replayMs??n.time??0)<=state.timeMs).at(-1);if(played)cursorAt(session.groups[played.index]);}
    playbackTimer=setTimeout(()=>guard(track)(),100);};track();
}
async function historyWindows(){
  $('more').showModal();const container=$('local-history');container.hidden=false;container.replaceChildren();
  const takes=await windowsPractice.request('takes');if(!takes.length)container.textContent='本机还没有练习记录。';
  for(const take of takes){const row=document.createElement('div'),open=document.createElement('button'),remove=document.createElement('button');
    open.textContent=`${take.title} · ${new Date(take.createdAt||take.savedAt).toLocaleString('zh-CN')} · ${take.errorCount} 处反馈`;
    open.onclick=guard(async()=>{await finish(false);$('more').close();const response=await fetch(`takes/score?id=${encodeURIComponent(take.takeId)}`);pendingPracticePackage=await windowsPractice.request(`takes/plan?id=${encodeURIComponent(take.takeId)}`);await load(await response.text());lastReport=await windowsPractice.request('takes/open',{id:take.takeId});applyWindows(lastReport);setPhase('finished');renderReport();view('review');});
    remove.textContent='移入本机回收区';remove.onclick=guard(async()=>{await windowsPractice.request('takes/remove',{id:take.takeId});await historyWindows();});row.append(open,remove);container.append(row);}
  const trash=await windowsPractice.request('takes/trash');if(trash.length){const label=document.createElement('p');label.textContent='本机回收区';container.append(label);for(const item of trash){const restore=document.createElement('button');restore.textContent=`恢复 · ${item.title}`;restore.onclick=guard(async()=>{await windowsPractice.request('takes/restore',{key:item.key});await historyWindows();});container.append(restore);}}
}
const downloadLocal=(route,id)=>{const anchor=document.createElement('a');anchor.href=`${route}?id=${encodeURIComponent(id)}`;anchor.download='';anchor.click();};
$('replay-take').onclick=guard(()=>replayTake());$('save-take').onclick=guard(()=>downloadLocal('takes/package',lastReport.takeId));
$('history-open').onclick=$('history-menu').onclick=guard(historyWindows);
async function recheckWindows(){analysisBusy=true;setPhase('loading');view('practice');message('正在用所选检测重新复核本机录音…');try{lastReport=await windowsPractice.request('takes/recheck',{id:lastReport.takeId,engine:$('recorded-engine').value,baseline:$('alignment-baseline').value});windowsSignature='';applyWindows(lastReport);view('review');message(lastReport.warning||'复核完成，报告已更新。');}finally{analysisBusy=false;setPhase('finished');renderReport();}}
$('recheck-take').onclick=()=>{pendingRecheck=true;openSettings('recorded-engine');$('settings-close').textContent='开始复核';message('选择录后检测，再点击“开始复核”。');};

for(const [id,focus]of[['settings-open'],['instrument-open','instrument-choice'],['range-open','from'],['mode-open','mode'],['tempo-open','bpm']])$(id).onclick=()=>openSettings(focus);
$('settings-close').onclick=guard(async()=>{const recheck=pendingRecheck;pendingRecheck=false;$('settings-close').textContent='完成';configure();$('settings').close();if(recheck)await recheckWindows();});$('more-open').onclick=()=>$('more').showModal();$('more-close').onclick=()=>$('more').close();
$('settings').addEventListener('close',()=>{pendingRecheck=false;$('settings-close').textContent='完成';});
$('import').onclick=()=>$('file').click();$('file').onchange=guard(async()=>{const file=$('file').files[0];if(file){$('more').close();await load(await readFile(file));}$('file').value='';});
$('demo').onclick=guard(async()=>{$('more').close();const response=await fetch('demo.musicxml');if(!response.ok)throw new Error('演示乐谱无法读取。');await load(await response.text());});
for(const id of ['from','to','bpm','mode'])$(id).onchange=guard(()=>configure());$('part').onchange=guard(()=>{if(engines.windows){const saved=instrumentPreferences.get($('part').value);$('instrument-choice').value=saved?.instrument||'auto';refreshVariant(saved?.variant);}configure(true);});
$('input').onchange=inputHint;$('instrument-choice').onchange=guard(()=>{refreshVariant();rememberInstrument();configure(true);});$('instrument-variant').onchange=guard(()=>{rememberInstrument();configure();});$('midi-device').onchange=selectMidi;
$('recorded-import').onclick=guard(()=>{validateRecording();$('recorded-file').click();});$('recorded-file').onchange=guard(async()=>{const file=$('recorded-file').files[0];$('recorded-file').value='';if(file){await finish(false);$('settings').close();await compareRecording(file);}});
$('start').onclick=guard(start);$('stop').onclick=guard(()=>recordingMode?finishRecording():finish());$('skip').onclick=guard(async()=>{if(local()){applyWindows(await windowsPractice.request('practice/skip',{}));return;}if(phase==='active'&&!recordingMode){session.advance(true);update();}});
$('listen').onclick=$('settings-listen').onclick=guard(listen);$('report').onclick=guard(downloadReport);$('review-nav').onclick=$('mobile-review').onclick=showReview;$('practice-nav').onclick=$('review-back').onclick=()=>view('practice');
$('retry').onclick=guard(()=>{const indices=session.errors.filter(e=>!e.resolved).map(e=>e.mi+1),scope=session.metadata.scope;return retryMeasures(indices.length?Math.min(...indices):scope.from,indices.length?Math.max(...indices):scope.to);});
$('back').onclick=()=>{if(bridge.available){finish(false);bridge.post({type:'close'});}else $('more').showModal();};
for(const id of ['settings','more'])$(id).addEventListener('click',e=>{if(e.target!==$(id))return;const r=$(id).getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$(id).close();});
const keyMap={a:60,s:62,d:64,f:65,g:67,h:69,j:71,k:72,w:61,e:63,t:66,y:68,u:70};
document.addEventListener('keydown',e=>{if(e.repeat||['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName)||$('settings').open||$('more').open)return;const n=keyMap[e.key.toLowerCase()];if(n!==undefined&&$('input').value==='keyboard'&&phase==='active'){e.preventDefault();receive(n);}});
document.addEventListener('keyup',e=>{const n=keyMap[e.key.toLowerCase()];if(local()&&n!==undefined&&$('input').value==='keyboard'&&phase==='active')guard(()=>windowsNote('note-off',n,`keyboard:${n}`,performance.now()))();});
document.addEventListener('visibilitychange',()=>{if(document.hidden)pause();});window.addEventListener('pagehide',()=>{if(local()){windowsPractice.stop();fetch('practice/finish',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',keepalive:true}).catch(()=>{});}else finish(false);audioContext?.close();});
new ResizeObserver(()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(score&&phase!=='loading'){renderScore();if(session?.active)cursorAt(session.current);}},100);}).observe($('score'));
window.NoteLiteNative={
  async loadScore(base64,title,id){if(typeof base64!=='string'||base64.length>21*1024*1024)throw new Error('乐谱文件过大。');const bytes=Uint8Array.from(atob(base64),c=>c.charCodeAt(0));await load(readBytes(bytes),title,id);},
  inputResult:(requestId,error)=>bridge.inputResult(requestId,error),noteOn:midi=>receive(midi,performance.now()),audioFrame:processAudio,
  inputError(error){pause();message(String(error),'warning');},suspend:pause,finish:()=>finish(false)
};
setPhase('idle');
if(bridge.available){$('import').hidden=true;$('demo').hidden=true;$('report').hidden=true;bridge.post({type:'ready'});}
else guard(async()=>{
  try{const capability=await fetch('engines.json');if(capability.ok)engines=await capability.json();}catch{}
  try{const metadata=await fetch('score-info.json');if(metadata.ok)scoreMetadata=await metadata.json();}catch{}
  if(engines.windows){
    const existing=new Set(Array.from($('instrument-choice').options).map(o=>o.value));
    for(const p of INSTRUMENT_PROFILES)if(!existing.has(p.id))$('instrument-choice').add(new Option(p.name,p.id),$('instrument-choice').options.length-1);
    if(engines.nativeAudio&&engines.basicPitch)$('input').add(new Option('麦克风录后比对 · 单音与和弦','recording'));
    $('recorded-import').hidden=!engines.basicPitch;
    $('windows-privacy').hidden=false;
    if(local()){ $('local-engine-settings').hidden=false;$('history-menu').hidden=false;$('mode').add(new Option('自由跟谱 · 允许变速和重弹','free'));$('grading-capabilities').textContent='严格节拍检查音高身份、音分、起音、时值和错漏多音；自由跟谱允许变速、停顿和重弹。疑似问题立即提示，可信度不足时标为待复核。';$('navigation-capabilities').textContent='乐谱与录音均在本机处理。反复、房子和跳转按本地准备的演奏顺序跟随。';windowsPractice.request('audio/devices').then(devices=>{for(const [id,key] of [['capture-device','capture'],['playback-device','playback']])for(const device of devices[key]||[])$(id).add(new Option(device.name,String(device.index)));}).catch(()=>{});}
  }
  const response=await fetch('score.musicxml');if(!response.ok)throw new Error('无法读取当前乐谱。请在“更多”中导入乐谱，或载入演示曲谱。');await load(readBytes(new Uint8Array(await response.arrayBuffer())),null,null,scoreMetadata);
})();
