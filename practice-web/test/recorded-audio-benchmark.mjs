/** Run production Pitchy + PitchGate on an existing, attributed real-instrument sample manifest.
 * node test/recorded-audio-benchmark.mjs /absolute/path/manifest.json
 * No access to browser microphone, MIDI devices, or account data.
 */
import {readFileSync,writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {PitchDetector} from 'pitchy';
import {PitchGate} from '../src/session.js';

const manifestPath=path.resolve(process.argv[2]);
const manifest=JSON.parse(readFileSync(manifestPath,'utf8'));
const fftSize=4096,detector=PitchDetector.forFloat32Array(fftSize);
const hash=data=>createHash('sha256').update(data).digest('hex');
const rms=data=>Math.sqrt(data.reduce((s,x)=>s+x*x,0)/data.length);
const results=[];
for(const sample of manifest.samples) {
  const original=readFileSync(sample.original),bytes=readFileSync(sample.pcm);
  if(hash(original)!==sample.sourceSha256||hash(bytes)!==sample.pcmSha256)throw new Error(`Sample checksum changed: ${sample.original}`);
  const pcm=new Float32Array(bytes.buffer,bytes.byteOffset,bytes.byteLength/4),gate=new PitchGate(),window=new Float32Array(fftSize);
  const hop=Math.round(sample.sampleRate/60),events=[],trace=[];
  let audibleFrames=0,acceptedFrames=0,correctPitchFrames=0,firstAudibleMs=null;
  // Causal 4096-sample analysis: left-pad initial windows and finish with a full silence window.
  // A 60Hz hop approximates requestAnimationFrame; real display rates/timing can differ.
  for(let end=0;end<pcm.length+fftSize;end+=hop) {
    window.fill(0);
    const sourceStart=Math.max(0,end-fftSize),sourceEnd=Math.min(end,pcm.length);
    if(sourceEnd>sourceStart)window.set(pcm.subarray(sourceStart,sourceEnd),Math.max(0,fftSize-end));
    const [hz,clarity]=detector.findPitch(window,sample.sampleRate),volume=rms(window);
    const timeMs=end/sample.sampleRate*1000;
    if(volume>=.008){audibleFrames++;if(firstAudibleMs===null)firstAudibleMs=timeMs;}
    const valid=hz>=27.5&&hz<=4200&&clarity>=.9&&volume>=.008;
    const rawMidi=hz>0?69+12*Math.log2(hz/440):null;
    if(valid){acceptedFrames++;if(Math.round(rawMidi)===sample.expectedMidi)correctPitchFrames++;}
    const event=gate.push(hz,clarity,volume);
    if(event)events.push({...event,timeMs,correct:event.midi===sample.expectedMidi,
      centsFromLabel:(rawMidi-sample.expectedMidi)*100});
    trace.push({timeMs,hz,clarity,rms:volume,accepted:valid,midi:rawMidi===null?null:Math.round(rawMidi)});
  }
  const first=events[0],matched=first?.midi===sample.expectedMidi;
  results.push({...sample,firstDetectedMidi:first?.midi??null,firstNoteMatches:matched,
    firstDetectionMs:first?.timeMs??null,firstAudibleMs,
    attackDetectionDelayFromAudibleMs:first?first.timeMs-firstAudibleMs:null,
    noDetection:events.length===0,eventCount:events.length,
    wrongPitchEvents:events.filter(e=>!e.correct).length,extraEvents:Math.max(0,events.length-1),
    cleanSingleAttack:events.length===1&&matched,events,
    audibleFrames,acceptedFrames,correctPitchFrames,
    rejectedAudibleFrames:audibleFrames-acceptedFrames,trace});
}
const summarize=cases=>({samples:cases.length,firstNoteMatches:cases.filter(c=>c.firstNoteMatches).length,
  firstNoteMatchRate:cases.filter(c=>c.firstNoteMatches).length/cases.length,
  noDetection:cases.filter(c=>c.noDetection).length,
  cleanSingleAttack:cases.filter(c=>c.cleanSingleAttack).length,
  wrongPitchEvents:cases.reduce((s,c)=>s+c.wrongPitchEvents,0),extraEvents:cases.reduce((s,c)=>s+c.extraEvents,0),
  medianFirstDetectionMs:cases.filter(c=>c.firstDetectionMs!==null).map(c=>c.firstDetectionMs).sort((a,b)=>a-b)[Math.floor(cases.filter(c=>c.firstDetectionMs!==null).length/2)]??null});
const perInstrument=Object.fromEntries([...new Set(results.map(c=>c.instrument))].map(name=>[name,summarize(results.filter(c=>c.instrument===name))]));
const source=fileURLToPath(new URL('../src/session.js',import.meta.url));
const result={generatedAt:new Date().toISOString(),benchmark:'Actual recorded-instrument samples through production Pitchy and PitchGate',
  source:{...manifest,samples:undefined},method:{fftSize,frameHop:'native sample rate / 60, rounded',
    timing:'Causal left-padded windows from the beginning through full release; no attack/sustain trimming',
    pitchy:'4.1.0',sessionSourceSha256:hash(readFileSync(source)),
    input:'Original sample bytes verified with SHA256; decoded mono PCM verified with SHA256',
    scoring:'First accepted note pitch versus upstream named sample. Extra/wrong events over the entire file also counted.',
    extraEventsCaveat:'Events beyond the first are reported, not assumed to be all false positives: original samples may contain repeated bow articulations. No independent onset ground truth is available.'},
  summary:summarize(results),perInstrument,results};
const target=path.join(path.dirname(manifestPath),'recorded-audio-metrics.json');
writeFileSync(target,JSON.stringify(result,null,2));
console.log(JSON.stringify({summary:result.summary,perInstrument,output:target},null,2));
