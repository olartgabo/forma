import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createGuard,readLedger,readExternalSpend,validate,usageCost,CAP,RESERVE,MODEL} from './guard.mjs';
test('blocks model switches, hosted tools, media and hidden conversation state',()=>{
 for(const patch of [{model:'other'},{tools:[{type:'web_search'}]},{input:[{type:'input_image'}]},{previous_response_id:'x'},{background:true},{service_tier:'priority'}])assert.throws(()=>validate({model:MODEL,...patch}));
 assert.equal(validate({model:MODEL,max_output_tokens:999999}).max_output_tokens,16384);
 assert.equal(usageCost({input_tokens:1048576,output_tokens:16384}),4521984);
 assert.equal(usageCost({input_tokens:-1,output_tokens:0}),null);
});
async function fixture(t,options={}){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'meta-guard-test-'));const ledger=path.join(dir,'ledger');
 fs.writeFileSync(ledger,JSON.stringify({kind:'init',cap:CAP})+'\n');
 const externalLedger=path.join(dir,'external.jsonl');
 fs.writeFileSync(externalLedger,JSON.stringify({usd:0.000001})+'\n');
 let calls=0;
 const request=options.request|| (async()=>{calls++;return new Response(JSON.stringify({usage:{input_tokens:100,output_tokens:10}}),{headers:{'content-type':'application/json'}});});
 const server=createGuard({ledger,externalLedger,token:'test',key:'fake',expires:options.expires||'2099-01-01',cap:options.cap??CAP,request});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));t.after(()=>server.close());
 const call=(body={model:MODEL},auth='test')=>fetch(`http://127.0.0.1:${server.address().port}/v1/responses`,{method:'POST',headers:{authorization:`Bearer ${auth}`},body:JSON.stringify(body)});
 const status=()=>fetch(`http://127.0.0.1:${server.address().port}/status`,{headers:{authorization:'Bearer test'}});
 return {ledger,externalLedger,call,status,calls:()=>calls};
}
test('settles usage and persists across reads; rejects unauthorized requests',async t=>{
 const f=await fixture(t);assert.equal((await f.call({},'bad')).status,401);assert.equal(f.calls(),0);
 assert.equal((await f.call()).status,200);assert.equal(readLedger(f.ledger).spent,600);assert.equal(readLedger(f.ledger).pending.size,0);
});
test('reserves before dispatch and refuses a call that could cross budget',async t=>{
 const f=await fixture(t);for(let i=0;i<15;i++)fs.appendFileSync(f.ledger,JSON.stringify({kind:'reserve',id:String(i),amount:RESERVE})+'\n');
 assert.equal((await f.call()).status,402);assert.equal(f.calls(),0);assert.equal(readLedger(f.ledger).spent,CAP);
});
test('uncertain network failure retains full cost and pauses',async t=>{
 const f=await fixture(t,{request:async()=>{throw Error('network lost');}});assert.equal((await f.call()).status,503);assert.equal(readLedger(f.ledger).spent,RESERVE);assert.equal((await f.call()).status,403);
});
test('expired account check and damaged journal fail closed',async t=>{
 const f=await fixture(t,{expires:'2020-01-01'});assert.equal((await f.call()).status,403);assert.equal(f.calls(),0);
 const g=await fixture(t);fs.writeFileSync(g.ledger,'broken');assert.equal((await g.call()).status,503);assert.equal(g.calls(),0);
});
test('stream usage is settled, missing usage keeps full reservation',async t=>{
 const f=await fixture(t,{request:async()=>new Response('data: '+JSON.stringify({type:'response.completed',response:{usage:{input_tokens:10,output_tokens:10}}})+'\n\n',{headers:{'content-type':'text/event-stream'}})});
 await(await f.call()).text();assert.equal(readLedger(f.ledger).spent,240);
 const g=await fixture(t,{request:async()=>new Response('{}')});await(await g.call()).text();assert.equal(readLedger(g.ledger).spent,RESERVE);
});
test('concurrent call is blocked while first reservation is durable',async t=>{
 let release;const wait=new Promise(r=>release=r);
 const f=await fixture(t,{request:async()=>{await wait;return new Response('{}');}});
 const first=f.call();
 for(let i=0;i<50&&readLedger(f.ledger).spent===0;i++)await new Promise(r=>setTimeout(r,5));
 assert.equal(readLedger(f.ledger).spent,RESERVE);
 assert.equal((await f.call()).status,429);release();await(await first).text();
});
test('invalid verification date fails closed',async t=>{
 const f=await fixture(t,{expires:'invalid'});assert.equal((await f.call()).status,403);assert.equal(f.calls(),0);
});

test('external historical usage shares the cap and blocked calls modify neither journal',async t=>{
 const f=await fixture(t);
 fs.writeFileSync(f.externalLedger,JSON.stringify({usd:84.0000001})+'\n');
 const local=fs.readFileSync(f.ledger,'utf8'),external=fs.readFileSync(f.externalLedger,'utf8');
 const state=await(await f.status()).json();
 assert.equal(state.externalSpent,84_000_001);assert.equal(state.combinedSpent,84_000_001);
 assert.equal((await f.call()).status,402);assert.equal(f.calls(),0);
 assert.equal(fs.readFileSync(f.ledger,'utf8'),local);assert.equal(fs.readFileSync(f.externalLedger,'utf8'),external);
});

test('external journal is re-read before each request and never written by the guard',async t=>{
 const f=await fixture(t),original=fs.readFileSync(f.externalLedger,'utf8');
 await(await f.call()).text();assert.equal(f.calls(),1);
 assert.equal(fs.readFileSync(f.externalLedger,'utf8'),original);
 fs.appendFileSync(f.externalLedger,JSON.stringify({usd:84})+'\n');
 const local=fs.readFileSync(f.ledger,'utf8'),external=fs.readFileSync(f.externalLedger,'utf8');
 assert.equal((await f.call()).status,402);assert.equal(f.calls(),1);
 assert.equal(fs.readFileSync(f.ledger,'utf8'),local);assert.equal(fs.readFileSync(f.externalLedger,'utf8'),external);
});

test('missing or corrupt external journal fails closed without dispatch or local writes',async t=>{
 const bad=['', 'broken', '{}', '{"usd":null}', '{"usd":-1}', '{"usd":0}', '{"usd":"1"}', '{"usd":1e309}', '{"usd":9007199254740991}'];
 for(const content of [...bad,null]) {
  const f=await fixture(t),local=fs.readFileSync(f.ledger,'utf8');
  if(content===null)fs.unlinkSync(f.externalLedger);else fs.writeFileSync(f.externalLedger,content);
  assert.equal((await f.status()).status,503);assert.equal((await f.call()).status,503);assert.equal(f.calls(),0);
  assert.equal(fs.readFileSync(f.ledger,'utf8'),local);
  if(content!==null)assert.equal(fs.readFileSync(f.externalLedger,'utf8'),content);
 }
});

test('external USD entries round upward individually to micros',async t=>{
 const f=await fixture(t);
 fs.writeFileSync(f.externalLedger,'{"usd":0.0000001}\n{"usd":0.0000011}\n');
 assert.equal(readExternalSpend(f.externalLedger),3);
});

test('verified free-credit funding can supersede the old90cap without rewriting its journal',async t=>{
 const f=await fixture(t,{cap:120_000_000});
 for(let i=0;i<15;i++)fs.appendFileSync(f.ledger,JSON.stringify({kind:'reserve',id:'historic'+i,amount:RESERVE})+'\n'+JSON.stringify({kind:'settle',id:'historic'+i,amount:RESERVE})+'\n');
 assert.equal(readLedger(f.ledger).spent,CAP);
 assert.equal((await f.call()).status,200);
 assert.ok(readLedger(f.ledger).spent>CAP);
 assert.equal(JSON.parse(fs.readFileSync(f.ledger,'utf8').split('\n')[0]).cap,CAP);
 assert.equal((await(await f.status()).json()).cap,120_000_000);
});
