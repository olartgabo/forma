import {test} from 'node:test';
import assert from 'node:assert/strict';
import {checkStatus} from './run.mjs';

const NOW=Date.parse('2026-01-01T00:00:00Z');
const base=()=>({halted:false,pending:0,cap:90_000_000,combinedSpent:0,expires:'2099-01-01'});

test('idle legacy status without counters is accepted',()=>{
 assert.doesNotThrow(()=>checkStatus(base(),false,NOW));
});

test('legacy uncertain pending is rejected',()=>{
 assert.throws(()=>checkStatus({...base(),pending:1},false,NOW),/Guard paused/);
});

test('healthy active reservation with a free slot is accepted',()=>{
 assert.doesNotThrow(()=>checkStatus({...base(),pending:1,activeRequests:1,maxConcurrent:2},false,NOW));
 assert.doesNotThrow(()=>checkStatus({...base(),pending:0,activeRequests:0,maxConcurrent:2},false,NOW));
});

test('full capacity is rejected',()=>{
 assert.throws(()=>checkStatus({...base(),pending:2,activeRequests:2,maxConcurrent:2},false,NOW),/capacity|Guard paused/);
 assert.throws(()=>checkStatus({...base(),pending:1,activeRequests:1,maxConcurrent:1},false,NOW));
});

test('unknown pending greater than activeRequests is rejected',()=>{
 assert.throws(()=>checkStatus({...base(),pending:2,activeRequests:1,maxConcurrent:2},false,NOW),/Guard paused/);
 assert.throws(()=>checkStatus({...base(),pending:1,activeRequests:0,maxConcurrent:2},false,NOW),/Guard paused/);
});

test('invalid counters are rejected',()=>{
 const bad=[
  {activeRequests:-1,maxConcurrent:2},{activeRequests:1.5,maxConcurrent:2},{activeRequests:'1',maxConcurrent:2},
  {activeRequests:NaN,maxConcurrent:2},{activeRequests:1,maxConcurrent:0},{activeRequests:1,maxConcurrent:3},
  {activeRequests:1,maxConcurrent:1.5},{activeRequests:1,maxConcurrent:'2'},{activeRequests:3,maxConcurrent:2},
  {activeRequests:1},{maxConcurrent:2},{activeRequests:1,maxConcurrent:undefined},
 ];
 for(const patch of bad)assert.throws(()=>checkStatus({...base(),pending:0,...patch},false,NOW),undefined,JSON.stringify(patch));
});

test('halted, STOP, expired and invalid dates are rejected',()=>{
 assert.throws(()=>checkStatus({...base(),halted:true,activeRequests:0,maxConcurrent:2},false,NOW),/Guard paused/);
 assert.throws(()=>checkStatus({...base(),activeRequests:0,maxConcurrent:2},true,NOW),/Guard paused/);
 assert.throws(()=>checkStatus({...base(),expires:'2020-01-01',activeRequests:0,maxConcurrent:2},false,NOW),/Guard paused/);
 assert.throws(()=>checkStatus({...base(),expires:'invalid',activeRequests:0,maxConcurrent:2},false,NOW),/Guard paused/);
 assert.throws(()=>checkStatus({...base(),pending:-1,activeRequests:0,maxConcurrent:2},false,NOW),/Guard paused/);
 assert.throws(()=>checkStatus({...base(),pending:'0'},false,NOW),/Guard paused/);
});

test('budget cap still gates even with a free slot',()=>{
 assert.throws(()=>checkStatus({...base(),combinedSpent:85_000_000,activeRequests:1,maxConcurrent:2,pending:1},false,NOW),/budget/);
 assert.doesNotThrow(()=>checkStatus({...base(),combinedSpent:84_000_000,activeRequests:1,maxConcurrent:2,pending:1},false,NOW));
});
