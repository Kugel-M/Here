const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const handlers={},writes=[],matches=[];
const context={URL,Response,fetch:async()=>new Response('shell'),caches:{open:async()=>({addAll:async()=>{},put:async(key)=>writes.push(key)}),match:async(key)=>{matches.push(key);return new Response('cached shell');},keys:async()=>[]},self:{location:{origin:'https://example.test'},clients:{claim:async()=>{}},addEventListener:(type,handler)=>handlers[type]=handler}};
vm.runInNewContext(fs.readFileSync('mobile/sw.js','utf8'),context);
async function request(path){let response=null;const waits=[];handlers.fetch({request:{method:'GET',url:'https://example.test'+path},waitUntil:p=>waits.push(p),respondWith:p=>response=p});if(response)await response;await Promise.all(waits);return response;}
(async()=>{
 assert.equal(await request('/api/state?token=TEST_ONLY'),null);
 assert.equal(await request('/api/query?session=TEST_ONLY'),null);
 await request('/?token=TEST_ONLY');assert.equal(writes.length,0);
 await request('/mobile.css');assert.deepEqual(writes,['/mobile.css']);
 context.fetch=async()=>{throw Error('offline')};await request('/?token=TEST_ONLY');assert.deepEqual(matches,['/']);
 console.log('PASS: API and credential URLs never cached; offline navigation uses public shell only.');
})().catch(e=>{console.error(e);process.exitCode=1;});
