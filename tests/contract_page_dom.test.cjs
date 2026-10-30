'use strict';
// No browser/network dependency: exercise the contract page with small DOM fixtures.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor(tag='div') {
    this.tag=tag; this.children=[]; this.textContent=''; this.value='';
    this.hidden=false; this.disabled=false; this.attributes={};
  }
  replaceChildren(){this.children=[]; if(this.tag==='select')this.value='';}
  append(...items){
    this.children.push(...items);
    if(this.tag==='select' && !this.value && items[0])this.value=items[0].value;
  }
  setAttribute(k,v){this.attributes[k]=v;}
  addEventListener(){}
}
async function main(){
  const nodes=new Map();
  const get=id=>{
    if(!nodes.has(id))nodes.set(id,new Element(id==='contracts'?'select':'div'));
    return nodes.get(id);
  };
  const blocked='AMD261030P00472500';
  const good='XYZ261120C00100000';
  const location={href:'https://ghazir.vercel.app/contract?contract='+blocked,
                  search:'?contract='+blocked};
  const history={replaceState(){}};
  const document={
    getElementById:get,createElement:tag=>new Element(tag),
    createElementNS:(_ns,tag)=>new Element(tag)
  };
  const context=vm.createContext({
    document, location, history, URL, URLSearchParams, Date, Number,
    AbortSignal:{timeout:()=>({})},setInterval:()=>{},
    fetch:()=>new Promise(()=>{})
  });
  const source=fs.readFileSync(path.join(__dirname,'..','public','contract.js'),'utf8');
  vm.runInContext(source,context,{filename:'contract.js'});
  const fixture=(active,terminal_recent=[])=>({
    active,terminal_recent,generated_at:new Date().toISOString(),
    active_count:active.filter(x=>x.data_state!=='LICENSE_BLOCKED').length,
    license_blocked_count:active.filter(x=>x.data_state==='LICENSE_BLOCKED').length
  });
  const refresh=async data=>{
    context.fetch=async()=>({ok:true,json:async()=>data});
    await vm.runInContext('refresh()',context);
  };
  await refresh(fixture([{
    contract_symbol:blocked,symbol:'AMD',side:'PUT',strike:472.5,
    stage:'LICENSE_BLOCKED',data_state:'LICENSE_BLOCKED',
    reason_ar:'الأسعار محجوبة لعدم ترخيص نشرها'
  }]));
  assert.match(get('warning').textContent,/محجوبة/);
  assert.equal(get('facts').children.length,0);
  assert.equal(get('chart').hidden,true);
  assert.match(get('empty').textContent,/لا يمكن عرض شارت/);
  location.search='?contract='+good;get('contracts').value='';
  await refresh(fixture([{contract_symbol:blocked,stage:'LICENSE_BLOCKED'}]));
  assert.equal(get('contracts').value,good);
  assert.match(get('warning').textContent,/غير موجود/);
  const now=new Date().toISOString();
  const valid={
    contract_symbol:good,symbol:'XYZ',side:'CALL',strike:100,expiration:'2026-11-20',
    stage:'WATCH',current_quote_research_valid:true,data_stale:false,
    entry_reference_verified:true,entry_premium_reference:2.5,last_mark:2.8,
    quote_age_minutes:1,
    target_map:{t1:{price:105},invalidation:{price:95}},
    quote_snapshots:[{quote_timestamp:now,source:'approved_feed',mark_for_exit:2.8,bid:2.8,ask:2.9}]
  };
  get('contracts').value='';
  await refresh(fixture([valid]));
  assert.equal(get('facts').children.length,3);
  assert.equal(get('rows').children.length,1);
  assert.equal(get('chart').hidden,false);
  assert.match(get('empty').textContent,/ليست شموع/);
  assert.match(get('targets').textContent,/105/);
  console.log('Contract page: blocked, missing deep link, and provider-stamped fixtures passed');
}
main().catch(err=>{console.error(err);process.exitCode=1;});
