/** Execute the production UI note-on gate on the native recorded benchmark traces. */
import {readFileSync,writeFileSync} from 'node:fs';
import {resolve,dirname,join} from 'node:path';
import {NativePitchGate} from '../../practice-web/src/windows-audio.js';

const source=resolve(process.argv[2]);
const raw=JSON.parse(readFileSync(source,'utf8'));
const results=raw.results.map(sample=>{
  const frames=JSON.parse(readFileSync(sample.trace,'utf8')),gate=new NativePitchGate(),events=[];
  for(const frame of frames){
    if(frame.type)continue;
    const event=gate.push(frame);
    if(event)events.push({...event,correct:event.midi===sample.expectedMidi});
  }
  return {...sample,firstNoteMatches:events[0]?.midi===sample.expectedMidi,
    acceptedEvents:events.length,wrongPitchEvents:events.filter(event=>!event.correct).length,
    extraEvents:Math.max(0,events.length-1),events};
});
const summary=cases=>({samples:cases.length,firstNoteMatches:cases.filter(c=>c.firstNoteMatches).length,
  noDetection:cases.filter(c=>c.acceptedEvents===0).length,
  cleanSingleAttack:cases.filter(c=>c.acceptedEvents===1&&c.firstNoteMatches).length,
  wrongPitchEvents:cases.reduce((sum,c)=>sum+c.wrongPitchEvents,0),
  extraEvents:cases.reduce((sum,c)=>sum+c.extraEvents,0)});
const report={method:'Production NativePitchGate on complete native MPM/YIN frame traces',
  rawReport:source,attribution:raw.attribution,limitation:raw.limitation,
  onsetLimit:'Multiple physical bow/breath articulations can occur in source files. There is no independent onset ground truth; extras are counts, not asserted false positives.',
  summary:summary(results),
  perInstrument:Object.fromEntries([...new Set(results.map(c=>c.instrument))].map(instrument=>[instrument,summary(results.filter(c=>c.instrument===instrument))])),
  results};
const target=join(dirname(source),'gate-results.json');
writeFileSync(target,JSON.stringify(report,null,2));
console.log(JSON.stringify({summary:report.summary,perInstrument:report.perInstrument,report:target},null,2));
