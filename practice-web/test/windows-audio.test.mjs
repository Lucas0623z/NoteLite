import test from 'node:test';
import assert from 'node:assert/strict';
import {NativePitchGate} from '../src/windows-audio.js';

const frame = (timeMs, changes={}) => ({frequency:440,clarity:.99,rms:.03,timeMs,onset:false,...changes});
const feed = (gate, frames, a4=440) => frames.map(f=>gate.push(f,a4)).filter(Boolean);

test('native sustained tones emit one attack with the first stable sample timestamp', () => {
  const gate=new NativePitchGate();
  const heard=feed(gate,Array.from({length:60},(_,i)=>frame(i*10,{onset:i===0})));
  assert.deepEqual(heard,[{midi:69,cents:0,timeMs:0}]);
});

test('native onset cues allow repeated same-pitch attacks without releasing a held note', () => {
  const gate=new NativePitchGate();
  assert.equal(feed(gate,[frame(0,{onset:true}),frame(10),frame(20)])[0].midi,69);
  assert.deepEqual(feed(gate,[frame(300,{onset:true}),frame(310),frame(320)]),[{midi:69,cents:0,timeMs:300}]);
  assert.equal(feed(gate,[frame(330),frame(340),frame(350)]).length,0);
});

test('native low-frequency estimates retain octave and use the selected concert pitch', () => {
  for(const midi of [21,24,28,34,36]) {
    const gate=new NativePitchGate(),a4=442,frequency=a4*2**((midi-69)/12);
    const heard=feed(gate,[0,11,22].map(t=>frame(t,{frequency})),a4);
    assert.equal(heard[0].midi,midi);
    assert.ok(Math.abs(heard[0].cents)<1e-9);
  }
});

test('native noisy clarity gaps reset a pending pitch before another stable attack', () => {
  const gate=new NativePitchGate();
  assert.equal(gate.push(frame(100)),null);
  assert.equal(gate.push(frame(110)),null);
  for(let t=120;t<200;t+=10)assert.equal(gate.push(frame(t,{clarity:.3})),null);
  assert.equal(gate.push(frame(200)),null);
  assert.equal(gate.push(frame(210)),null);
  assert.deepEqual(gate.push(frame(220)),{midi:69,cents:0,timeMs:200});
});

test('native frequency loss resets pending stability while preserving sustained-note suppression', () => {
  const pending=new NativePitchGate();
  feed(pending,[frame(0),frame(10)]);
  pending.push(frame(20,{frequency:0}));
  assert.equal(pending.push(frame(30)),null);
  assert.equal(pending.push(frame(40)),null);
  assert.equal(pending.push(frame(50)).timeMs,30);
  const sustained=new NativePitchGate();
  feed(sustained,[frame(0),frame(10),frame(20)]);
  feed(sustained,[frame(30,{clarity:.1}),frame(40,{frequency:0}),frame(50,{clarity:.5})]);
  assert.equal(feed(sustained,[frame(60),frame(70),frame(80)]).length,0);
});

test('native brief quiet gaps suppress repeats but three quiet frames release the previous attack', () => {
  const gate=new NativePitchGate();
  feed(gate,[frame(0),frame(10),frame(20)]);
  feed(gate,[frame(30,{rms:0}),frame(40,{rms:0})]);
  assert.equal(feed(gate,[frame(50),frame(60),frame(70)]).length,0);
  feed(gate,[frame(80,{rms:0}),frame(90,{rms:0}),frame(100,{rms:0})]);
  assert.deepEqual(feed(gate,[frame(110),frame(120),frame(130)]),[{midi:69,cents:0,timeMs:110}]);
});

test('native acoustic onset time survives window latency and the stable-pitch wait', () => {
  for(const window of [4096,8192]) {
    const gate=new NativePitchGate(),halfWindow=window/48000*500;
    // The new acoustic attack occurs inside the full FFT window. Its first
    // estimate is uncertain; later stable estimates retain the acoustic time.
    const heard=feed(gate,[
      frame(100,{onset:true,onsetTimeMs:250,pitchTimeMs:100+halfWindow,clarity:.84}),
      frame(110,{onsetTimeMs:250,pitchTimeMs:110+halfWindow}),
      frame(120,{onsetTimeMs:250,pitchTimeMs:120+halfWindow}),
      frame(130,{onsetTimeMs:250,pitchTimeMs:130+halfWindow}),
    ]);
    assert.deepEqual(heard,[{midi:69,cents:0,timeMs:250}],`window ${window} must not shift the attack to its start or center`);
  }
});

test('native same-pitch rearticulation uses the second acoustic attack timestamp', () => {
  const gate=new NativePitchGate();
  assert.deepEqual(feed(gate,[0,10,20].map(t=>frame(t,{onset:t===0,onsetTimeMs:0,pitchTimeMs:t+85}))),[{midi:69,cents:0,timeMs:0}]);
  assert.deepEqual(feed(gate,[280,290,300].map((t,i)=>frame(t,{onset:i===0,onsetTimeMs:450,pitchTimeMs:t+85}))),[{midi:69,cents:0,timeMs:450}]);
  assert.equal(feed(gate,[310,320,330].map(t=>frame(t,{onsetTimeMs:450,pitchTimeMs:t+85}))).length,0);
});

test('native continuous legato pitch changes use sample-derived pitch midpoint when no attack exists', () => {
  const gate=new NativePitchGate(),c5=440*2**(3/12);
  feed(gate,[0,10,20].map(t=>frame(t,{onset:t===0,onsetTimeMs:0,pitchTimeMs:t+85})));
  const heard=feed(gate,[815,825,835].map(t=>frame(t,{frequency:c5,onsetTimeMs:null,pitchTimeMs:t+85})));
  assert.equal(heard.length,1);
  assert.equal(heard[0].midi,72);
  assert.ok(Math.abs(heard[0].cents)<1e-9);
  assert.equal(heard[0].timeMs,900,'Use the first new-pitch midpoint, not the preceding attack, window start, or last confirmation frame');
});

test('native unconfirmed pitch changes discard the previous candidate timestamp', () => {
  const gate=new NativePitchGate(),c5=440*2**(3/12);
  feed(gate,[frame(100,{onsetTimeMs:250,pitchTimeMs:185}),frame(110,{onsetTimeMs:250,pitchTimeMs:195})]);
  const heard=feed(gate,[200,210,220].map(t=>frame(t,{frequency:c5,onsetTimeMs:null,pitchTimeMs:t+85})));
  assert.equal(heard.length,1);
  assert.equal(heard[0].midi,72);
  assert.equal(heard[0].timeMs,285);
});

test('native missing and non-finite optional attack times fall back to midpoint and legacy sample time', () => {
  for(const onsetTimeMs of [undefined,null,NaN,Infinity]) {
    const gate=new NativePitchGate();
    assert.equal(feed(gate,[100,110,120].map(t=>frame(t,{onsetTimeMs,pitchTimeMs:t+85})))[0].timeMs,185);
  }
  for(const pitchTimeMs of [undefined,null,NaN,Infinity]) {
    const gate=new NativePitchGate();
    assert.equal(feed(gate,[100,110,120].map(t=>frame(t,{onsetTimeMs:null,pitchTimeMs})))[0].timeMs,100);
  }
});
