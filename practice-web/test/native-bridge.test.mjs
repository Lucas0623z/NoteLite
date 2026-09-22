import test from 'node:test';
import assert from 'node:assert/strict';
import {NativeInputBridge} from '../src/native-bridge.js';

test('native input result resolves only the matching generation',async()=>{
  const sent=[],bridge=new NativeInputBridge({postMessage:m=>sent.push(m)});
  const pending=bridge.requestInput('midi');assert.deepEqual(sent[0],{type:'startInput',input:'midi',requestId:1});
  bridge.inputResult(0,null);assert.equal(bridge.pending.size,1);bridge.inputResult('1',null);assert.equal(await pending,true);
});
test('stop rejects all permission requests and ignores a delayed native reply',async()=>{
  const sent=[],bridge=new NativeInputBridge({postMessage:m=>sent.push(m)});
  const cancelled=bridge.requestInput('microphone');const rejection=assert.rejects(cancelled,{name:'AbortError'});
  bridge.stop();await rejection;bridge.inputResult(1,null);assert.equal(bridge.pending.size,0);assert.equal(sent.at(-1).type,'stopInput');
  const fresh=bridge.requestInput('midi');bridge.inputResult(1,null);assert.equal(bridge.pending.size,1);bridge.inputResult(2,null);assert.equal(await fresh,true);
});
test('native permission or connection failures reach the caller',async()=>{
  const bridge=new NativeInputBridge({postMessage(){}}),pending=bridge.requestInput('microphone');
  bridge.inputResult(1,'麦克风权限未开启');await assert.rejects(pending,/麦克风权限未开启/);
});
