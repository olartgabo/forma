import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import crypto from 'node:crypto';

export const MODEL='muse-wonder-1.0', CAP=90_000_000, RESERVE=6_000_000;
const ROOT=path.dirname(fileURLToPath(import.meta.url));
const SPARK_LEDGER='C:/Users/axolo/Documents/Meta hackathon/forma/.devloop/ledger.jsonl';
export function readExternalSpend(file) {
  const lines=fs.readFileSync(file,'utf8').trim().split('\n');
  let spent=0;
  for(const line of lines) {
    const entry=JSON.parse(line);
    if(!entry||typeof entry.usd!=='number'||!Number.isFinite(entry.usd)||entry.usd<=0)throw Error('External budget journal invalid; usage blocked');
    const amount=Math.ceil(entry.usd*1e6);
    if(!Number.isSafeInteger(amount)||!Number.isSafeInteger(spent+amount))throw Error('External budget amount invalid; usage blocked');
    spent+=amount;
  }
  return spent;
}
export function readLedger(file) {
  const events=fs.readFileSync(file,'utf8').trim().split('\n').map(JSON.parse);
  if(events[0]?.kind!=='init'||events[0]?.cap!==CAP) throw Error('Budget record invalid');
  let spent=0; const pending=new Map();
  for(const e of events.slice(1)) {
    if(e.kind==='reserve'&&typeof e.id==='string'&&!pending.has(e.id)&&e.amount===RESERVE) {pending.set(e.id,e.amount); spent+=e.amount;}
    else if(e.kind==='settle'&&pending.has(e.id)&&Number.isSafeInteger(e.amount)&&e.amount>=0&&e.amount<=RESERVE) {spent+=e.amount-pending.get(e.id);pending.delete(e.id);}
    else throw Error('Budget journal invalid; usage blocked');
    if(!Number.isSafeInteger(spent)||spent<0) throw Error('Budget amount invalid');
  }
  return {spent,pending};
}
function append(file,event) { const fd=fs.openSync(file,'a');try {fs.writeSync(fd,JSON.stringify(event)+'\n');fs.fsyncSync(fd);}finally{fs.closeSync(fd);} }
export function validate(body) {
  if(body.model!==MODEL) throw Error('Only Muse Wonder is allowed');
  if(body.background||body.conversation||body.previous_response_id||body.service_tier&&body.service_tier!=='default') throw Error('Background, stored conversations and premium tiers blocked');
  if(body.tools?.some(t=>!['function','custom'].includes(t.type))) throw Error('Only local coding tools allowed; hosted paid tools blocked');
  function scan(v) {if(!v||typeof v!=='object')return; if(['input_image','input_audio','input_video','input_file','image_url','file'].includes(v.type))throw Error('Text-only guard: media blocked'); for(const x of Object.values(v))scan(x);}
  scan(body.input);
  body.max_output_tokens=Math.min(16384,Number.isSafeInteger(body.max_output_tokens)&&body.max_output_tokens>0?body.max_output_tokens:16384);
  body.store=false; body.background=false; delete body.service_tier;
  return body;
}
export function usageCost(u) {
  if(!u||!Number.isSafeInteger(u.input_tokens)||!Number.isSafeInteger(u.output_tokens)||u.input_tokens<0||u.output_tokens<0||u.input_tokens>1048576||u.output_tokens>16384) return null;
  // USD micros: input $4/M, output (including reasoning) $20/M. No cache discount assumed.
  return u.input_tokens*4+u.output_tokens*20;
}
export function createGuard({ledger,externalLedger=SPARK_LEDGER,token,key,expires,request=fetch,upstream='https://api.meta.ai/v1/responses',cap=CAP,maxConcurrent=1}) {
  if(!Number.isSafeInteger(cap)||cap<RESERVE)throw Error('Verified funding ceiling invalid');
  if(!Number.isSafeInteger(maxConcurrent)||(maxConcurrent!==1&&maxConcurrent!==2))throw Error('maxConcurrent must be 1 or 2');
  let activeRequests=0, halted=false;
  const usageFile=path.join(path.dirname(ledger),'usage.jsonl');
  const reply=(r,code,message)=>{r.writeHead(code,{'content-type':'application/json'});r.end(JSON.stringify({error:{message,type:'budget_guard'}}));};
  return http.createServer(async(req,res)=>{
    if(req.headers.authorization!==`Bearer ${token}`)return reply(res,401,'Local access token required');
    if(req.method==='GET'&&req.url==='/status') {try{const local=readLedger(ledger),externalSpent=readExternalSpend(externalLedger);res.end(JSON.stringify({...local,pending:local.pending.size,externalSpent,combinedSpent:local.spent+externalSpent,cap,expires,halted,activeRequests,maxConcurrent}));}catch{reply(res,503,'Budget record unavailable');}return;}
    if(req.method!=='POST'||!['/v1/responses','/responses'].includes(req.url))return reply(res,403,'Only guarded Responses requests are allowed');
    if(halted||fs.existsSync(path.join(path.dirname(ledger),'STOP'))||!Number.isFinite(Date.parse(expires))||Date.now()>=Date.parse(expires))return reply(res,403,'Usage paused: stop switch active or account credit/pricing recheck required');
    if(activeRequests>=maxConcurrent)return reply(res,429,'Concurrent request limit reached; concurrent calls blocked');
    // Synchronous admission in the shared event loop: hold the slot before any await.
    activeRequests++; let reserved=false, id=crypto.randomUUID();
    try {
      let raw='';for await(const chunk of req){raw+=chunk.toString('utf8');if(Buffer.byteLength(raw)>8_000_000)throw Error('Request too large');}
      const body=validate(JSON.parse(raw));
      const {spent}=readLedger(ledger);
      const externalSpent=readExternalSpend(externalLedger);
      if(spent+externalSpent+RESERVE>cap)return reply(res,402,'Combined recorded usage reached the lifetime budget; request blocked');
      append(ledger,{kind:'reserve',id,amount:RESERVE,at:new Date().toISOString()}); reserved=true;
      const upstreamResponse=await request(upstream,{method:'POST',headers:{authorization:`Bearer ${key}`,'content-type':'application/json',connection:'close'},body:JSON.stringify(body),redirect:'error',signal:AbortSignal.timeout(600000)});
      const contentType=upstreamResponse.headers.get('content-type')||'application/json';
      res.writeHead(upstreamResponse.status,{'content-type':contentType,'cache-control':'no-store'});
      const chunks=[];let bytes=0;
      for await(const c of upstreamResponse.body){bytes+=c.length;if(bytes>32_000_000)throw Error('Response too large; full reservation retained');chunks.push(Buffer.from(c));if(!res.destroyed)res.write(c);}
      const text=Buffer.concat(chunks).toString('utf8');let usage;
      if(upstreamResponse.ok) {
        if(contentType.includes('text/event-stream')) {
          for(const line of text.split('\n'))if(line.startsWith('data: ')){try{const e=JSON.parse(line.slice(6));if(e.type==='response.completed'||e.type==='response.incomplete')usage=e.response?.usage;}catch{}}
        } else {try{usage=JSON.parse(text).usage;}catch{}}
      }
      const actual=usageCost(usage);
      if(actual!==null) {
        // Audit first, then settle exactly once. If either append fails the
        // catch below halts and the reservation is retained (no retry).
        append(usageFile,{id,at:new Date().toISOString(),model:MODEL,input_tokens:usage.input_tokens,output_tokens:usage.output_tokens});
        append(ledger,{kind:'settle',id,amount:actual,at:new Date().toISOString()});
      } else {
        // Missing/invalid usage: outcome cost unknown, retain full reservation and halt.
        halted=true;
      }
      // Unknown outcomes retain the entire durable reservation; never automatically refund failures.
      if(!res.destroyed)res.end();
    } catch(e) {
      if(reserved){
        halted=true;
        try{
          const safeCode=v=>typeof v==='string'&&/^[A-Z0-9_]{1,64}$/.test(v)?v:null;
          const diagnostic={at:new Date().toISOString(),requestId:id,errorName:['TypeError','TimeoutError','AbortError','RangeError','Error'].includes(e?.name)?e.name:'OtherError',code:safeCode(e?.code)||safeCode(e?.cause?.code),stage:res.headersSent?'stream':'dispatch',message:['Request too large','Response too large; full reservation retained'].includes(e?.message)?e.message:undefined};
          const fd=fs.openSync(path.join(path.dirname(ledger),'guard-diagnostics.jsonl'),'a');try{fs.writeSync(fd,JSON.stringify(diagnostic)+'\n');fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
        }catch{/* ledger reservation is the durable fail-closed record */}
      }
      if(!res.headersSent)reply(res,503,reserved?'Request outcome uncertain; full reservation retained and usage paused':String(e.message));else res.destroy();
    } finally {activeRequests--;}
  });
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  const settings=JSON.parse(fs.readFileSync(path.join(ROOT,'settings.json'),'utf8'));
  readLedger(path.join(ROOT,'ledger.jsonl'));
  readExternalSpend(SPARK_LEDGER);
  const decryptEnv={...process.env}; delete decryptEnv.PSModulePath;
  const decrypted=spawnSync('powershell.exe',['-NoProfile','-Command',"$s=Get-Content -Raw -LiteralPath 'C:/Users/axolo/.meta-budget/key.dpapi' | ConvertTo-SecureString; $p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s); try {[Console]::Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($p))} finally {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p)}"],{encoding:'utf8',windowsHide:true,env:decryptEnv});
  if(decrypted.status!==0||!decrypted.stdout.startsWith('LLM_'))throw Error('Cannot decrypt API credential: '+decrypted.stderr);
  const {freshMetaHTTPS}=await import('./fresh-https.mjs');
  const server=createGuard({ledger:path.join(ROOT,'ledger.jsonl'),token:settings.localToken,key:decrypted.stdout,expires:settings.expires,cap:settings.verifiedFundingCapMicros??CAP,maxConcurrent:settings.maxConcurrent,request:freshMetaHTTPS});
  server.on('error',()=>process.exit(1));
  server.listen(18765,'127.0.0.1',()=>console.log('Muse Wonder budget guard ready on localhost:18765.'));
}

