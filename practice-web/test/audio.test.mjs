import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdirSync,writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {PitchDetector} from 'pitchy';
import {PitchGate,PracticeSession} from '../src/session.js';

// Reproducible artificial waveforms, not recordings or evidence of real-instrument accuracy.
const profiles = {
  sine:[1], flute_like:[1,.2,.04,.02], clarinet_like:[1,0,.65,0,.4,0,.2],
  bowed_string_like:[1,.75,.5,.4,.3,.2], plucked_string_like:[1,.8,.45,.3,.2,.12],
  voice_like:[1,.45,.3,.4,.25,.12]
};
const notes=[36,40,43,48,52,55,60,64,67,72,76,79,84];
const rates=[44100,48000];
const noises=[{name:'clean',snrDb:null},{name:'30dB_noise',snrDb:30},{name:'20dB_noise',snrDb:20}];
const bufferSize=4096;
const frequency=midi=>440*2**((midi-69)/12);
const rms=a=>Math.sqrt(a.reduce((s,x)=>s+x*x,0)/a.length);
function random(seed=1){let state=seed>>>0;return()=>{state=(Math.imul(1664525,state)+1013904223)>>>0;return state/2**32;};}
function wave(hz,harmonics,sampleRate,frame,{snrDb=null,detuneCents=0,seed=1234}={}) {
  const data=new Float32Array(bufferSize),hzActual=hz*2**(detuneCents/1200);
  const total=harmonics.reduce((s,a)=>s+Math.abs(a),0),amplitude=.25/total;
  for(let i=0;i<data.length;i++)for(let h=0;h<harmonics.length;h++) {
    if((h+1)*hzActual<sampleRate/2)data[i]+=amplitude*harmonics[h]*Math.sin(2*Math.PI*(h+1)*hzActual*(i+frame*Math.round(sampleRate/60))/sampleRate+.31*(h+1));
  }
  if(snrDb!==null){const scale=rms(data)*10**(-snrDb/20)*Math.sqrt(3),rand=random(seed+frame);for(let i=0;i<data.length;i++)data[i]+=(rand()*2-1)*scale;}
  return data;
}

const detector=PitchDetector.forFloat32Array(bufferSize);
function evaluateCase({name,harmonics,midi,sampleRate,snrDb=null,detuneCents=0}) {
  const gate=new PitchGate(),events=[],frames=[];
  for(let frame=0;frame<6;frame++) {
    const data=wave(frequency(midi),harmonics,sampleRate,frame,{snrDb,detuneCents,seed:midi*197+sampleRate});
    const [hz,clarity]=detector.findPitch(data,sampleRate),volume=rms(data),event=gate.push(hz,clarity,volume);
    frames.push({hz,clarity,rms:volume});
    if(event)events.push(event);
  }
  const event=events[0],correct=events.length===1&&event.midi===midi;
  return {profile:name,midi,sampleRate,snrDb,detuneCents,detectedMidi:event?.midi??null,
    cents:event?.cents??null,eventCount:events.length,correct,
    minimumClarity:Math.min(...frames.map(f=>f.clarity))};
}

const measured=[];
for(const noise of noises)for(const [name,harmonics] of Object.entries(profiles)) {
  test(`actual Pitchy FFT + gate: ${name}, ${noise.name}, two sample rates and 13 pitches`,()=>{
    const cases=rates.flatMap(sampleRate=>notes.map(midi=>evaluateCase({name,harmonics,midi,sampleRate,snrDb:noise.snrDb})));
    measured.push(...cases);
    const incorrect=cases.filter(c=>!c.correct||Math.abs(c.cents)>10);
    assert.deepEqual(incorrect,[],`Sustained artificial ${name} tones must yield one accurate note-on`);
  });
}

test('actual detuned synthetic A4 reaches pitch-accuracy feedback with the right sign',()=>{
  for(const cents of [-42,42]) {
    const result=evaluateCase({name:'detuned_sine',harmonics:[1],midi:69,sampleRate:48000,detuneCents:cents});
    measured.push(result);
    assert.equal(result.correct,true);
    assert.ok(Math.abs(result.cents-cents)<1);
    const s=new PracticeSession([{onset:0,measure:'3',mi:2,beat:2,notes:[{midi:69,onset:0,duration:1,part:'P1'}]}]);
    s.noteOn(result.detectedMidi,1000,result.cents);
    assert.equal(s.errors[0].kind,'intonation');
    assert.equal(Math.sign(s.errors[0].cents),Math.sign(cents));
    assert.equal(s.errors[0].measure,'3');
  }
});

test('actual digital silence and white noise yield no false note attacks',()=>{
  let falseAttacks=0;
  const rand=random(98765);
  for(const amplitude of [0,.002,.025,.2]) {
    const gate=new PitchGate();
    for(let frame=0;frame<30;frame++) {
      const data=Float32Array.from({length:bufferSize},()=>amplitude*(rand()*2-1));
      const [hz,clarity]=detector.findPitch(data,48000);
      if(gate.push(hz,clarity,rms(data)))falseAttacks++;
    }
  }
  assert.equal(falseAttacks,0);
  measured.push({profile:'silence_and_white_noise',frames:120,falseAttacks});
});

test('record realistic limits: loud noise and no-silence repeated same-pitch attacks',()=>{
  const stress=[];
  for(const [name,harmonics] of Object.entries(profiles))for(const midi of [40,60,79]) {
    stress.push(evaluateCase({name,harmonics,midi,sampleRate:48000,snrDb:5}));
  }
  const gate=new PitchGate(),events=[];
  for(const level of [.1,.1,.1,.1,.02,.02,.1,.1,.1]) {
    const event=gate.push(440,1,level);if(event)events.push(event);
  }
  // The gate explicitly suppresses held pitches. This documents its repeated-note limitation;
  // it is not an assertion that two real plucks/strikes would always be detected.
  assert.equal(events.length,1);
  measured.push({profile:'stress_5dB',cases:stress,detectedCorrect:stress.filter(c=>c.correct).length,total:stress.length},
    {profile:'same_pitch_without_silence',intendedAttacks:2,detectedAttacks:events.length,
      limitation:'No amplitude-onset detector; repeated pitch needs at least three unvoiced frames.'});
});

test.after(()=>{
  const main=measured.filter(c=>c.profile in profiles),summary={};
  for(const noise of noises){const cases=main.filter(c=>c.snrDb===noise.snrDb);summary[noise.name]={cases:cases.length,
    correctAttacks:cases.filter(c=>c.correct).length,
    wrongAttacks:cases.filter(c=>c.detectedMidi!==null&&!c.correct).length,
    missedAttacks:cases.filter(c=>c.detectedMidi===null).length,
    maximumAbsoluteCents:Math.max(0,...cases.filter(c=>c.correct).map(c=>Math.abs(c.cents)))};}
  const result={generatedAt:new Date().toISOString(),method:'Executed pitchy 4.1.0 PitchDetector and production PitchGate on deterministic Float32 PCM',
    limitation:'Synthetic waveform regression only. Not live microphone, room-noise, true instrument, polyphonic, or end-to-end performance accuracy.',
    windowSamples:bufferSize,sampleRates:rates,frequencyRangeHz:[frequency(notes[0]),frequency(notes.at(-1))],
    profiles,summary,cases:measured};
  const folder=new URL('../../work/',import.meta.url);mkdirSync(folder,{recursive:true});
  const target=new URL('practice-audio-metrics.json',folder);writeFileSync(target,JSON.stringify(result,null,2));
  console.log(`Synthetic audio metrics: ${fileURLToPath(target)}`);
});
