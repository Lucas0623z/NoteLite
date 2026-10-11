/* NoteLite OMR module. SPDX-License-Identifier: AGPL-3.0-or-later */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const state={file:null,job:null,notes:[],parts:[],xml:'',revision:0,movement:0,selected:null,dirty:false,xmlDirty:false,busy:false,poll:0,render:0,changed:new Set()};
  let osmd,downloadURL,renderChain=Promise.resolve();
  const phase={queued:'等待识谱',running:'正在识谱',succeeded:'识谱已完成',failed:'识谱未完成'};
  const isImport=file=>file?.recognitionMode==='import'||/\.(musicxml|xml|mxl)$/i.test(file?.name||file?.filename||'');
  const importPhase={queued:'等待导入',running:'正在导入乐谱',succeeded:'乐谱已导入',failed:'乐谱导入未完成'};
  const durationByType={maxima:32,long:16,breve:8,whole:4,half:2,quarter:1,eighth:.5,'16th':.25,'32nd':.125,'64th':.0625,'128th':.03125};
  const store={get(key){try{return sessionStorage.getItem(`notelite-omr-${key}`)||'';}catch{return ''; }},set(key,value){try{sessionStorage.setItem(`notelite-omr-${key}`,value);}catch{}}};
  $('token').value=store.get('token');$('job-id').value=store.get('job');
  function message(text,error=false){$('message').textContent=text;$('message').classList.toggle('error',error);}
  function guard(action){return async event=>{try{await action(event);}catch(error){message(error.message||'操作失败，请重试。',true);}};}
  function token(){const value=$('token').value.trim();if(!value)throw new Error('请先在右上角“连接设置”输入访问口令。');return value;}
  function url(resource='',withScore=true){if(!state.job?.id)throw new Error('请先识谱或打开已有任务。');const path=['musicxml','midi'].includes(resource)?'score/'+resource:resource;return `/api/jobs/${encodeURIComponent(state.job.id)}${path?'/'+path:''}${withScore&&['notes','score','musicxml','midi'].includes(resource)?'?score='+state.movement:''}`;}
  async function request(target,options={}){
    const headers=new Headers(options.headers||{});headers.set('Authorization',`Bearer ${token()}`);
    const response=await fetch(target,{...options,headers,cache:'no-store'});
    if(!response.ok){let text;try{const error=await response.json();text=error.error||error.message;}catch{text=`请求未完成（${response.status}）。`;}
      if(response.status===401)text='访问口令无效，请在“连接设置”中重新填写。';
      if(response.status===409)text=text||'谱面已有更新。请取消当前修改并重新载入后再编辑。';throw new Error(text||'请求未完成。');}
    return response;
  }
  async function json(target,options){return (await request(target,options)).json();}
  function unsaved(){if(state.dirty||state.xmlDirty)throw new Error('当前修改尚未保存。请先保存或取消，再执行此操作。');}
  function busy(value){state.busy=value;$('recognize').disabled=value||!state.file;$('choose-file').disabled=value;$('reopen').disabled=value;
    $('reload').disabled=value||!state.job;$('movement').disabled=value;$('xml-save').disabled=value;$('note-save').disabled=value||!state.dirty;$('note-cancel').disabled=value||!state.dirty;
    $('note-fields').disabled=value||$('delete-note').checked;$('delete-note').disabled=value;}
  function selectFile(file){if(state.busy)return;unsaved();if(!file)return;if(!/\.(pdf|png|jpe?g|musicxml|xml|mxl)$/i.test(file.name))throw new Error('请选择 PDF、PNG、JPEG 或 MusicXML 乐谱。');
    if(!file.size||file.size>25*1024*1024)throw new Error('文件需大于 0 字节，且不超过 25 MB。');state.file=file;$('filename').textContent=file.name;$('recognize').textContent=isImport(file)?'导入乐谱':'开始识谱';busy(false);}
  function clearScore(){state.notes=[];state.parts=[];state.xml='';state.selected=null;state.dirty=false;state.xmlDirty=false;$('note-list').replaceChildren();$('note-form').hidden=true;$('note-filters').hidden=true;$('xml-editor').hidden=true;$('note-count').textContent='处理完成后可编辑音符。';$('score-title').textContent='乐谱预览';$('score-info').textContent='正在等待处理结果。';$('score').replaceChildren();const placeholder=document.createElement('p');placeholder.className='empty';placeholder.textContent='正在等待处理结果…';$('score').append(placeholder);}
  function jobView(job){state.job=job;$('job-title').textContent=job.filename||job.id;$('job-state').textContent=(isImport(job)?importPhase:phase)[job.state||job.status]||'正在获取结果';$('job-id').value=job.id;store.set('job',job.id);
    $('progress').hidden=!['queued','running'].includes(job.state||job.status);$('downloads').hidden=false;
    for(const button of document.querySelectorAll('[data-download]')){const resource=button.dataset.download;button.disabled=['musicxml','midi'].includes(resource)?(job.state||job.status)!=='succeeded':!job.artifacts?.[resource];}
    const scores=job.scores||[];$('movement-label').hidden=scores.length<2;$('movement').replaceChildren(...scores.map((score,index)=>new Option(score.name||`乐章 ${index+1}`,String(score.index??index))));$('movement').value=String(state.movement);
    busy(state.busy);}
  async function openJob(id){unsaved();state.poll++;state.movement=0;busy(true);try{const job=await json(`/api/jobs/${encodeURIComponent(id)}`);clearScore();jobView(job);
      if((job.state||job.status)==='succeeded')await loadScore();else if((job.state||job.status)==='failed')message(job.error||'识谱失败，可下载处理日志查看原因。',true);else startPoll();
    }finally{busy(false);}}
  async function start(){unsaved();token();if(!state.file)throw new Error('请先选择乐谱文件。');busy(true);message('正在上传乐谱…');
    try{const job=await json(`/api/jobs?filename=${encodeURIComponent(state.file.name)}`,{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:state.file});state.poll++;state.movement=0;clearScore();jobView(job);message(isImport(job)?'乐谱已上传，正在导入并生成 MIDI。':'原稿已上传，等待识谱结果。');startPoll();}finally{busy(false);}}
  function startPoll(){const generation=++state.poll;const id=state.job.id;
    async function poll(){if(generation!==state.poll)return;try{const job=await json(`/api/jobs/${encodeURIComponent(id)}`);if(generation!==state.poll)return;jobView(job);
        if((job.state||job.status)==='succeeded'){await loadScore();return;}if((job.state||job.status)==='failed'){message(job.error||'处理未完成，请下载处理日志查看原因。',true);return;}message(isImport(job)?'正在导入乐谱并生成 MIDI，请稍候。':'正在识谱，请稍候。');setTimeout(poll,1500);
      }catch(error){if(generation===state.poll){$('progress').hidden=true;message(`${error.message} 任务编号已保留，可点击“重新载入”继续。`,true);}}}
    setTimeout(poll,500);
  }
  async function loadScore(){const id=state.job.id,movement=state.movement;
    const [scoreResponse,notesData]=await Promise.all([request(url('musicxml')),json(url('notes'))]);const xml=await scoreResponse.text();
    if(state.job.id!==id||state.movement!==movement)return;state.xml=xml;state.notes=notesData.notes||[];state.parts=notesData.parts||[];state.revision=notesData.revision??state.job.revision??0;state.selected=null;state.dirty=false;state.xmlDirty=false;
    $('note-form').hidden=true;$('note-filters').hidden=false;$('xml-editor').hidden=false;$('xml-source').value=xml;
    $('part-filter').replaceChildren(new Option('全部声部',''),...state.parts.map(part=>new Option(part.name||part.id,part.id)));$('measure-filter').value='';
    const doc=parseXML(xml);$('score-title').textContent=doc.getElementsByTagName('work-title')[0]?.textContent||doc.getElementsByTagName('movement-title')[0]?.textContent||state.job.filename||'乐谱预览';
    $('score-info').textContent=`${state.parts.length} 个声部 · ${state.notes.length} 个音符与休止符 · 已保存版本 ${state.revision}`;renderNotes();
    const warnings=state.job.warnings||[];$('warnings').hidden=!warnings.length;$('warnings').replaceChildren(...warnings.map(value=>{const p=document.createElement('p');p.textContent=typeof value==='string'?value:JSON.stringify(value);return p;}));
    const rendered=await renderScore();message(rendered?(isImport(state.job)?'MusicXML 乐谱已导入。请选择音符校对，或下载乐谱。':'识谱结果已载入。请选择音符校对，或下载乐谱。'):'乐谱文件已载入；当前谱面无法预览，可下载文件或使用高级编辑。',!rendered);busy(state.busy);
  }
  function parseXML(xml){const doc=new DOMParser().parseFromString(xml,'application/xml');if(doc.getElementsByTagName('parsererror').length)throw new Error('MusicXML 内容无法读取，请核对文件后重试。');return doc;}
  function children(node,name){return Array.from(node?.children||[]).filter(child=>child.localName===name);}
  function previewXML(){if(!state.selected)return state.xml;const doc=parseXML(state.xml),part=children(doc.documentElement,'part').find(p=>p.getAttribute('id')===state.selected.partId);
    const measure=children(part,'measure')[state.selected.measureIndex],note=children(measure,'note')[state.selected.noteIndex];if(note){note.setAttribute('color','#345da8');for(const element of ['notehead','stem'])for(const child of children(note,element))child.setAttribute('color','#345da8');}
    return new XMLSerializer().serializeToString(doc);}
  function renderScore(){const generation=++state.render;const xml=previewXML();const work=renderChain.catch(()=>{}).then(async()=>{
      if(generation!==state.render)return true;try{const OSMD=window.opensheetmusicdisplay?.OpenSheetMusicDisplay;if(!OSMD)throw new Error('本地谱面显示组件未能载入。');
        osmd??=new OSMD('score',{autoResize:true,backend:'svg',drawTitle:true,drawComposer:true,drawPartNames:true});await osmd.load(xml);if(generation!==state.render)return true;osmd.render();
        if(state.selected)$('score').querySelector('[fill="#345da8" i]')?.scrollIntoView({block:'nearest',behavior:'auto'});return true;
      }catch(error){if(generation===state.render){$('score').replaceChildren();const p=document.createElement('p');p.className='empty';p.textContent='当前乐谱无法预览。文件下载与音符列表仍可使用。';$('score').append(p);}return false;}});renderChain=work;return work;}
  function key(note){return `${note.partId}/${note.measureIndex}/${note.noteIndex}`;}
  function pitchName(note){if(note.rest)return '休止符';if(!note.pitch)return '无固定音高';const {step,alter=0,octave}=note.pitch;return `${step}${alter===1?'♯':alter===-1?'♭':alter===2?'𝄪':alter===-2?'𝄫':alter?' ('+alter+')':''}${octave}`;}
  function beats(note){return Number(note.duration)/Number(note.divisions||1);}
  function location(note){const part=state.parts.find(p=>p.id===note.partId);return `${part?.name||note.partId} · 第 ${note.measure??note.measureIndex+1} 小节 · 音符 ${note.noteIndex+1}`;}
  function renderNotes(){const part=$('part-filter').value,measure=$('measure-filter').value.trim();const filtered=state.notes.filter(note=>(!part||note.partId===part)&&(!measure||String(note.measure??note.measureIndex+1)===measure));
    $('note-count').textContent=`${filtered.length} / ${state.notes.length} 个音符与休止符`;$('note-list').replaceChildren(...filtered.map(note=>{const button=document.createElement('button');button.type='button';button.className='note-row';button.classList.toggle('selected',key(note)===key(state.selected||{}));button.setAttribute('aria-pressed',String(key(note)===key(state.selected||{})));const name=document.createElement('span'),detail=document.createElement('span');name.textContent=`${note.measure??note.measureIndex+1} · ${pitchName(note)}`;detail.textContent=`${Number.isFinite(beats(note))?Number(beats(note).toFixed(4)):'—'} 时值${note.chord?' · 和弦':''}`;button.append(name,detail);button.onclick=guard(()=>selectNote(note));return button;}));
    if(!filtered.length){const p=document.createElement('p');p.className='empty-list';p.textContent='没有符合筛选条件的音符。';$('note-list').append(p);}}
  async function selectNote(note){if(state.busy)return;unsaved();state.selected=note;state.dirty=false;$('note-form').hidden=false;$('note-location').textContent=location(note);$('note-detail').textContent=`声部 ${note.partId}${note.voice?' · 声部线 '+note.voice:''}${note.staff?' · 谱表 '+note.staff:''}${note.chord?' · 和弦中的音符':''}`;
    state.changed.clear();$('rest').checked=Boolean(note.rest);$('step').value=note.pitch?.step||'C';const alter=String(note.pitch?.alter||0);if(!Array.from($('alter').options).some(o=>o.value===alter))$('alter').add(new Option(`升降 ${alter}`,alter));$('alter').value=alter;$('octave').value=note.pitch?.octave??4;$('duration').value=Number.isFinite(beats(note))&&beats(note)>0?beats(note):1;
    $('note-type').value=note.type||'';if(note.type&&!Array.from($('note-type').options).some(o=>o.value===note.type))$('note-type').add(new Option(note.type,note.type));$('note-type').value=note.type||'';
    $('dots').value=note.dot??note.dots??0;$('delete-note').checked=false;$('note-fields').disabled=false;pitchEnabled();dirty(false);renderNotes();await renderScore();}
  function pitchEnabled(){for(const control of $('pitch-fields').querySelectorAll('input,select'))control.disabled=$('rest').checked||state.busy;$('pitch-fields').classList.toggle('muted',$('rest').checked);}
  function dirty(value=true){state.dirty=value;$('edit-state').textContent=value?($('delete-note').checked?'保存后将删除这个音符。':'修改尚未保存。'):'尚未修改';busy(state.busy);}
  function typeDuration(){const base=durationByType[$('note-type').value],dots=Number($('dots').value);if(base&&Number.isInteger(dots)&&dots>=0&&dots<=4){$('duration').value=base*(2-2**(-dots));state.changed.add('duration');}dirty();}
  async function saveNote(event){event.preventDefault();if(state.xmlDirty)throw new Error('请先保存或取消高级编辑中的修改。');if(!state.selected||!state.dirty)return;const selected=state.selected,edit={partId:selected.partId,measureIndex:selected.measureIndex,noteIndex:selected.noteIndex};
    if($('delete-note').checked)edit.delete=true;else{const duration=Number($('duration').value),octave=Number($('octave').value),dot=Number($('dots').value);if(!Number.isFinite(duration)||duration<=0)throw new Error('请填写大于 0 的时值。');if(!Number.isInteger(dot)||dot<0||dot>4)throw new Error('附点需为 0–4 的整数。');
      const rest=$('rest').checked;if(rest!==Boolean(selected.rest))edit.rest=rest;
      if(state.changed.has('duration')&&duration!==beats(selected))edit.duration=duration*Number(selected.divisions||1);
      if($('note-type').value!==(selected.type||''))edit.type=$('note-type').value;if(dot!==(selected.dot??selected.dots??0))edit.dot=dot;
      if(!rest){if(!Number.isInteger(octave)||octave<0||octave>9)throw new Error('八度需为 0–9 的整数。');const pitch={step:$('step').value,alter:Number($('alter').value),octave};if(selected.rest||!selected.pitch||pitch.step!==selected.pitch.step||pitch.alter!==(selected.pitch.alter||0)||pitch.octave!==selected.pitch.octave)edit.pitch=pitch;}}
    if(Object.keys(edit).length===3){dirty(false);message('当前内容没有需要保存的修改。');return;}
    busy(true);message('正在保存修改并更新 MIDI…');try{await json(url('notes'),{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:state.revision,score:state.movement,edits:[edit]})});state.dirty=false;state.job=await json(url('',false));jobView(state.job);await loadScore();message(edit.delete?'音符已删除，乐谱和 MIDI 已更新。':'修改已保存，乐谱和 MIDI 已更新。');}finally{busy(false);}}
  async function saveXML(){if(state.dirty)throw new Error('请先保存或取消音符表单中的修改。');const source=$('xml-source').value;parseXML(source);busy(true);message('正在保存完整乐谱并更新 MIDI…');
    try{await request(url('score'),{method:'PUT',headers:{'Content-Type':'application/xml; charset=utf-8','If-Match':String(state.revision)},body:source});state.xmlDirty=false;state.job=await json(url('',false));jobView(state.job);await loadScore();message('完整乐谱已保存，MIDI 已更新。');}finally{busy(false);}}
  async function download(resource){if(!state.job)throw new Error('请先完成识谱。');const target=['musicxml','midi'].includes(resource)?url(resource):state.job.artifacts?.[resource]||url(resource,false);const response=await request(target);const blob=await response.blob(),object=URL.createObjectURL(blob),link=document.createElement('a');
    const disposition=response.headers.get('Content-Disposition')||'',match=disposition.match(/filename\*=UTF-8''([^;]+)|filename="([^"]+)"/i);let filename=match?(match[1]?decodeURIComponent(match[1]):match[2]):`${(state.job.filename||'score').replace(/\.[^.]+$/,'')}.${resource==='musicxml'?'musicxml':resource==='midi'?'mid':resource==='log'?'log':resource==='omr'?'omr':'bin'}`;
    if(downloadURL)URL.revokeObjectURL(downloadURL);downloadURL=object;link.href=object;link.download=filename.split(/[\\/]/).pop();link.textContent=`下载 ${link.download}`;message('文件已准备；若浏览器没有自动下载，可点击：');$('message').append(' ',link);link.click();}
  $('choose-file').onclick=()=>$('file').click();$('file').onchange=guard(()=>selectFile($('file').files[0]));$('recognize').onclick=guard(start);
  for(const event of ['dragenter','dragover'])$('drop-zone').addEventListener(event,e=>{e.preventDefault();$('drop-zone').classList.add('dragging');});
  for(const event of ['dragleave','drop'])$('drop-zone').addEventListener(event,e=>{e.preventDefault();$('drop-zone').classList.remove('dragging');});$('drop-zone').addEventListener('drop',guard(e=>selectFile(e.dataTransfer.files[0])));
  $('token-save').onclick=guard(async()=>{const value=token();store.set('token',value);message('口令已保留在本次会话中。');if($('job-id').value.trim())await openJob($('job-id').value.trim());});
  $('reopen').onclick=guard(()=>openJob($('job-id').value.trim()));$('reload').onclick=guard(async()=>{unsaved();busy(true);try{state.job=await json(url('',false));jobView(state.job);if((state.job.state||state.job.status)==='succeeded')await loadScore();else if((state.job.state||state.job.status)==='failed')message(state.job.error||'识谱未完成。',true);else startPoll();}finally{busy(false);}});
  $('movement').onchange=guard(async()=>{try{unsaved();state.movement=Number($('movement').value);busy(true);await loadScore();}catch(error){$('movement').value=String(state.movement);throw error;}finally{busy(false);}});
  $('part-filter').onchange=renderNotes;$('measure-filter').oninput=renderNotes;$('note-form').onsubmit=guard(saveNote);
  $('note-fields').oninput=event=>{state.changed.add(event.target.id);pitchEnabled();dirty();};$('note-type').onchange=typeDuration;$('dots').onchange=typeDuration;$('delete-note').onchange=()=>dirty();
  $('note-cancel').onclick=guard(async()=>{const note=state.selected;state.dirty=false;await selectNote(note);});$('xml-source').oninput=()=>{state.xmlDirty=$('xml-source').value!==state.xml;};
  $('xml-save').onclick=guard(saveXML);$('xml-reset').onclick=()=>{$('xml-source').value=state.xml;state.xmlDirty=false;};
  for(const button of document.querySelectorAll('[data-download]'))button.onclick=guard(()=>download(button.dataset.download));
  if($('token').value&&$('job-id').value)guard(()=>openJob($('job-id').value))();
})();
