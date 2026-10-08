import test from 'node:test';
import assert from 'node:assert/strict';
import {WindowsAudioBridge} from '../src/windows-audio.js';

const response = {ok:true,json:async()=>({})};
const tick = () => new Promise(resolve=>setImmediate(resolve));

test('native timing excludes process startup before the device-ready acknowledgement', async () => {
  const originalFetch=globalThis.fetch,originalEvents=globalThis.EventSource,originalPerformance=globalThis.performance;
  let time=0,stream,heard;
  globalThis.performance={now:()=>time};
  globalThis.fetch=async()=>{time=600;return response;};
  globalThis.EventSource=class {constructor(){stream=this;}close(){}};
  let bridge;
  try {
    bridge=new WindowsAudioBridge({onFrame:(frame,at)=>{heard=at;}});
    const starting=bridge.start({});
    await tick();
    stream.onmessage({data:'{"type":"ready"}'});
    assert.equal(await starting,true);
    assert.equal(bridge.origin,600);
    stream.onmessage({data:'{"timeMs":25}'});
    assert.equal(heard,625);
  } finally {
    if(bridge)await bridge.stop();
    globalThis.fetch=originalFetch;globalThis.EventSource=originalEvents;globalThis.performance=originalPerformance;
  }
});

test('cancelled in-flight native start is stopped after its acknowledgement', async () => {
  const original=globalThis.fetch,calls=[];
  let acknowledge;
  globalThis.fetch=async url=>{
    calls.push(url);
    if(url.startsWith('audio/start'))return new Promise(resolve=>{acknowledge=resolve;});
    return response;
  };
  try {
    const bridge=new WindowsAudioBridge(),starting=bridge.start({});
    await tick();
    const stopping=bridge.stop();
    await tick();
    assert.equal(calls.length,1,'stop must wait for the server to finish start');
    acknowledge(response);
    assert.equal(await starting,false);
    await stopping;
    assert.equal(calls.length,2);
    assert.equal(calls[1],'audio/stop');
  } finally {globalThis.fetch=original;}
});

test('a replacement session starts after cancelled capture cleanup without a stale stop', async () => {
  const originalFetch=globalThis.fetch,originalEvents=globalThis.EventSource,calls=[];
  let acknowledge,stream;
  globalThis.fetch=async url=>{
    calls.push(url);
    if(calls.length===1)return new Promise(resolve=>{acknowledge=resolve;});
    return response;
  };
  globalThis.EventSource=class {
    constructor(){stream=this;}
    close(){this.closed=true;}
  };
  let bridge;
  try {
    bridge=new WindowsAudioBridge();
    const first=bridge.start({});
    await tick();
    const stopped=bridge.stop(),replacement=bridge.start({});
    acknowledge(response);
    assert.equal(await first,false);
    await stopped;
    await tick();
    assert.equal(calls.length,3);
    assert.equal(calls[1],'audio/stop');
    assert.ok(calls[2].startsWith('audio/start'));
    stream.onmessage({data:'{"type":"ready"}'});
    assert.equal(await replacement,true);
    assert.equal(calls.filter(url=>url==='audio/stop').length,1);
  } finally {
    if(bridge)await bridge.stop();
    globalThis.fetch=originalFetch;globalThis.EventSource=originalEvents;
  }
});
