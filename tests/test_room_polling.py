"""Exercise the Room scheduler with deterministic timers and network replies."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_room_polling_backs_off_wakes_and_never_overlaps_requests():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed to exercise browser timers")
    script = r"""
const assert = require('node:assert/strict'), vm = require('node:vm'), fs = require('node:fs');
const timers = new Map(), events = {}, hint = {textContent:'', title:''};
const session = {id:'room', scene:'one.md', managed:true, runtime:{revision:1}, outbox:[], busy:false};
let timerId = 0, calls = 0, resolveRequest;
const c = {
  _roomSessionsByScene:{'one.md':session}, _roomCurrentScenePath:()=> 'one.md', roomTabIsOpen:()=>true,
  setTimeout:(fn, delay)=> { timers.set(++timerId,{fn,delay}); return timerId; },
  clearTimeout:id=>timers.delete(id),
  document:{hidden:false, getElementById:()=>hint, addEventListener:(name,fn)=>events[name]=fn},
  window:{addEventListener:(name,fn)=>events[name]=fn},
  discussApi:()=>{calls++; return new Promise(resolve=>resolveRequest=resolve);}
};
vm.createContext(c); vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),c);
c.roomRuntimeApply=(_,state)=>{session.runtime=state; session.busy=state.status==='running';};
c.drainRoomOutbox=()=>{};
function onlyTimer() { assert.equal(timers.size,1); return [...timers.values()][0]; }
function start() { const [id,timer]=[...timers][0];timers.delete(id);timer.fn(); }
async function reply(status='idle', revision=1) {
  resolveRequest({ok:true,room:{status,revision}}); await new Promise(r=>setImmediate(r));
}
(async()=>{
  c.roomRuntimePoll(session); assert.equal(onlyTimer().delay,0);
  start(); await reply(); const firstIdle=onlyTimer().delay; assert.ok(firstIdle>=5000);
  start(); await reply(); assert.ok(onlyTimer().delay>firstIdle);
  for(let i=0;i<4;i++){start();await reply();} assert.equal(onlyTimer().delay,30000);
  c.roomRuntimePoll(session,true); assert.equal(onlyTimer().delay,0);
  start(); const before=calls; c.roomRuntimePoll(session,true); c.roomRuntimePoll(session,true);
  assert.equal(calls,before); assert.equal(timers.size,0,'a pending request cannot overlap');
  await reply('running',2); assert.equal(onlyTimer().delay,0);
  start(); await reply('running',2); assert.equal(onlyTimer().delay,800);
  start(); await reply('idle',3); assert.equal(onlyTimer().delay,5000);
  c.document.hidden=true; events.visibilitychange(); assert.equal(timers.size,0);
  c.document.hidden=false; events.visibilitychange(); assert.equal(onlyTimer().delay,0);
  start(); await reply('idle',3);
  events.focus(); assert.equal(onlyTimer().delay,0);
  start(); resolveRequest({ok:false,error:'Server unavailable'});await new Promise(r=>setImmediate(r));
  assert.ok(hint.textContent.includes('Connection interrupted'));
  start();await reply('idle',3);assert.equal(hint.textContent,'');
  start();const oldReply=resolveRequest;
  session.id='another-room';c.roomRuntimePoll(session,true);
  oldReply({ok:true,room:{status:'running',revision:999}});await new Promise(r=>setImmediate(r));
  assert.equal(session.runtime.revision,3,'a late old-room response must not overwrite the selected room');
  assert.equal(onlyTimer().delay,0);start();await reply('idle',4);
  const replacement={...session,runtime:{revision:4}};c._roomSessionsByScene['one.md']=replacement;
  c.roomRuntimePoll(replacement,true);assert.equal(onlyTimer().delay,0);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    runtime = Path(__file__).resolve().parents[1] / "proseview/templates/assets/js/70-room-runtime.js"
    subprocess.run([node, "-e", script, str(runtime)], check=True, capture_output=True, text=True)
