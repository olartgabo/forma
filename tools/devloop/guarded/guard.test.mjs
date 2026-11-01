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
 const server=createGuard({ledger,externalLedger,token:'test',key:'fake',expires:options.expires||'2099-01-01',cap:options.cap??CAP,maxConcurrent:options.maxConcurrent,request});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));t.after(()=>server.close());
 const call=(body={model:MODEL},auth='test')=>fetch(`http://127.0.0.1:${server.address().port}/v1/responses`,{method:'POST',headers:{authorization:`Bearer ${auth}`},body:JSON.stringify(body)});
 const status=()=>fetch(`http://127.0.0.1:${server.address().port}/status`,{headers:{authorization:'Bearer test'}});
 return {dir,ledger,externalLedger,usageFile:path.join(dir,'usage.jsonl'),call,status,calls:()=>calls};
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

test('maxConcurrent is validated as integer 1 or 2',()=>{
 for(const bad of [0,3,1.5,'2',NaN,null])assert.throws(()=>createGuard({ledger:'x',token:'t',key:'k',expires:'2099-01-01',maxConcurrent:bad}),/maxConcurrent/);
 for(const good of [1,2,undefined])assert.doesNotThrow(()=>createGuard({ledger:'x',token:'t',key:'k',expires:'2099-01-01',maxConcurrent:good}).close());
});
async function waitFor(fn){for(let i=0;i<100;i++){if(fn())return;await new Promise(r=>setTimeout(r,5));}throw Error('waitFor timed out');}
function ledgerEvents(f){return fs.readFileSync(f.ledger,'utf8').trim().split('\n').map(JSON.parse);}
function usageEvents(f){return fs.existsSync(f.usageFile)&&fs.statSync(f.usageFile).isFile()?fs.readFileSync(f.usageFile,'utf8').trim().split('\n').filter(Boolean).map(JSON.parse):[];}

test('default remains single-flight and status reports counters',async t=>{
 let release;const wait=new Promise(r=>release=r);let upstream=0;
 const f=await fixture(t,{request:async()=>{upstream++;await wait;return new Response(JSON.stringify({usage:{input_tokens:100,output_tokens:10}}),{headers:{'content-type':'application/json'}});}});
 const first=f.call();await waitFor(()=>upstream===1);
 const st=await(await f.status()).json();assert.equal(st.activeRequests,1);assert.equal(st.maxConcurrent,1);assert.equal(st.pending,1);
 assert.equal((await f.call()).status,429);assert.equal(upstream,1);assert.equal(ledgerEvents(f).filter(e=>e.kind==='reserve').length,1);
 release();assert.equal((await first).status,200);await waitFor(()=>readLedger(f.ledger).pending.size===0);
 const st2=await(await f.status()).json();assert.equal(st2.activeRequests,0);
});

test('opt-in 2 admits two simultaneous, third 429 before reserve/dispatch, separate settlements and usage',async t=>{
 let release;const wait=new Promise(r=>release=r);let upstream=0;
 const f=await fixture(t,{maxConcurrent:2,request:async(_u,opts)=>{upstream++;await wait;const input=JSON.parse(opts.body).input;const usage=input==='one'?{input_tokens:100,output_tokens:10}:{input_tokens:200,output_tokens:20};return new Response(JSON.stringify({usage}),{headers:{'content-type':'application/json'}});}});
 const p1=f.call({model:MODEL,input:'one'}),p2=f.call({model:MODEL,input:'two'});
 await waitFor(()=>upstream===2);await waitFor(()=>ledgerEvents(f).filter(e=>e.kind==='reserve').length===2);
 const st=await(await f.status()).json();assert.equal(st.activeRequests,2);assert.equal(st.maxConcurrent,2);assert.equal(st.pending,2);
 assert.equal((await f.call({model:MODEL,input:'three'})).status,429);assert.equal(upstream,2);assert.equal(ledgerEvents(f).filter(e=>e.kind==='reserve').length,2);
 release();const [r1,r2]=await Promise.all([p1,p2]);assert.equal(r1.status,200);assert.equal(r2.status,200);await r1.text();await r2.text();
 const events=ledgerEvents(f),reserves=events.filter(e=>e.kind==='reserve'),settles=events.filter(e=>e.kind==='settle');
 assert.equal(new Set(reserves.map(e=>e.id)).size,2);assert.deepEqual(new Set(settles.map(e=>e.id)),new Set(reserves.map(e=>e.id)));assert.deepEqual(settles.map(e=>e.amount).sort((a,b)=>a-b),[600,1200]);
 const usage=usageEvents(f);assert.equal(usage.length,2);assert.deepEqual(new Set(usage.map(e=>e.id)),new Set(reserves.map(e=>e.id)));assert.deepEqual(usage.map(e=>e.input_tokens).sort((a,b)=>a-b),[100,200]);assert.deepEqual(usage.map(e=>e.output_tokens).sort((a,b)=>a-b),[10,20]);
 for(const e of usage){assert.deepEqual(Object.keys(e).sort(),['at','id','input_tokens','model','output_tokens']);assert.equal(e.model,MODEL);assert.ok(Number.isFinite(Date.parse(e.at)));}
 assert.equal(readLedger(f.ledger).pending.size,0);
});

test('concurrent cap check: only one of two simultaneous reservations fits the cap',async t=>{
 let release;const wait=new Promise(r=>release=r);let upstream=0;
 const f=await fixture(t,{maxConcurrent:2,request:async()=>{upstream++;await wait;return new Response(JSON.stringify({usage:{input_tokens:100,output_tokens:10}}),{headers:{'content-type':'application/json'}});}});
 for(let i=0;i<13;i++)fs.appendFileSync(f.ledger,JSON.stringify({kind:'reserve',id:'pre'+i,amount:RESERVE})+'\n'+JSON.stringify({kind:'settle',id:'pre'+i,amount:RESERVE})+'\n');
 const p1=f.call(),p2=f.call();
 await waitFor(()=>upstream===1);
 // second must already have been decided (402) without dispatch; give it a moment to arrive
 let statuses=[];const raced=await Promise.race([Promise.all([p1,p2]).then(rs=>{statuses=rs.map(r=>r.status);return 'both';}),new Promise(r=>setTimeout(()=>r('pending'),200))]);
 if(raced==='both'){assert.deepEqual(statuses.sort(),[200,402]);release();}
 else {release();const rs=await Promise.all([p1,p2]);assert.deepEqual(rs.map(r=>r.status).sort(),[200,402]);}
 assert.equal(upstream,1);assert.equal(ledgerEvents(f).filter(e=>e.kind==='reserve').length,14);
});

test('one uncertain failure halts even when the other concurrent call settles',async t=>{
 let release;const wait=new Promise(r=>release=r);
 const f=await fixture(t,{maxConcurrent:2,request:async(_u,opts)=>{const input=JSON.parse(opts.body).input;if(input==='bad')throw Error('network lost');await wait;return new Response(JSON.stringify({usage:{input_tokens:100,output_tokens:10}}),{headers:{'content-type':'application/json'}});}});
 const good=f.call({model:MODEL,input:'good'}),bad=f.call({model:MODEL,input:'bad'});
 assert.equal((await bad).status,503);release();const gr=await good;assert.equal(gr.status,200);await gr.text();
 assert.equal((await f.call()).status,403);
 const st=await(await f.status()).json();assert.equal(st.halted,true);assert.equal(st.pending,1);assert.equal(readLedger(f.ledger).pending.size,1);
 const usage=usageEvents(f);assert.equal(usage.length,1);assert.equal(usage[0].input_tokens,100);
 const settles=ledgerEvents(f).filter(e=>e.kind==='settle');assert.equal(settles.length,1);assert.equal(settles[0].id,usage[0].id);
});

test('safe usage audit is sequential-attributable and contains no prompt, key or token',async t=>{
 const f=await fixture(t,{request:async(_u,opts)=>{const input=JSON.parse(opts.body).input;const usage=input==='alpha-secret'?{input_tokens:100,output_tokens:10}:{input_tokens:200,output_tokens:20};return new Response(JSON.stringify({usage}),{headers:{'content-type':'application/json'}});}});
 await(await f.call({model:MODEL,input:'alpha-secret'})).text();await(await f.call({model:MODEL,input:'beta'})).text();
 const raw=fs.readFileSync(f.usageFile,'utf8');assert.ok(!raw.includes('alpha-secret')&&!raw.includes('fake')&&!raw.includes('test'));
 const usage=usageEvents(f),reserves=ledgerEvents(f).filter(e=>e.kind==='reserve'),settles=ledgerEvents(f).filter(e=>e.kind==='settle');
 assert.deepEqual(usage.map(e=>e.id),reserves.map(e=>e.id));assert.deepEqual(usage.map(e=>[e.input_tokens,e.output_tokens]),[[100,10],[200,20]]);assert.deepEqual(settles.map(e=>e.amount),[600,1200]);
});

test('missing and invalid usage retain full reservation, write no usage audit and halt',async t=>{
 for(const payload of [{},{usage:{input_tokens:-1,output_tokens:0}}]){
  const f=await fixture(t,{request:async()=>new Response(JSON.stringify(payload),{headers:{'content-type':'application/json'}})});
  assert.equal((await f.call()).status,200);assert.equal(readLedger(f.ledger).spent,RESERVE);assert.equal(readLedger(f.ledger).pending.size,1);assert.equal(usageEvents(f).length,0);assert.equal(ledgerEvents(f).filter(e=>e.kind==='settle').length,0);
  assert.equal((await f.call()).status,403);
 }
});

test('usage audit I/O failure fails closed without settlement',async t=>{
 let upstream=0;const f=await fixture(t,{request:async()=>{upstream++;return new Response(JSON.stringify({usage:{input_tokens:100,output_tokens:10}}),{headers:{'content-type':'application/json'}});}});
 fs.mkdirSync(f.usageFile);
 let clientFailed=false;try{const r=await f.call();await r.text();}catch{clientFailed=true;}assert.equal(clientFailed,true);
 assert.equal(upstream,1);assert.equal(readLedger(f.ledger).spent,RESERVE);assert.equal(readLedger(f.ledger).pending.size,1);assert.equal(ledgerEvents(f).filter(e=>e.kind==='settle').length,0);assert.equal(ledgerEvents(f).filter(e=>e.kind==='reserve').length,1);
 assert.equal((await f.call()).status,403);assert.equal(upstream,1);
 const st=await(await f.status()).json();assert.equal(st.halted,true);
});

test('STOP blocks concurrent-mode dispatch without upstream call',async t=>{
 const f=await fixture(t,{maxConcurrent:2});fs.writeFileSync(path.join(f.dir,'STOP'),'');
 assert.equal((await f.call()).status,403);assert.equal(f.calls(),0);assert.equal(ledgerEvents(f).filter(e=>e.kind==='reserve').length,0);
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
