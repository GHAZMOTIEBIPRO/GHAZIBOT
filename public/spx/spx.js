const $=id=>document.getElementById(id);
const num=(x)=>((typeof x==='number'||(typeof x==='string'&&x.trim()!==''))&&Number.isFinite(Number(x)))?Number(x):null;
function marketAge(d,now=Date.now()){
  const stamp=d?.market_bar_time;
  if(typeof stamp!=='string'||!/(Z|[+-]\d{2}:\d{2})$/.test(stamp))return null;
  const time=Date.parse(stamp);
  return Number.isFinite(time)?(now-time)/60000:null;
}
const fmt=(x,d=2)=>num(x)!=null?num(x).toLocaleString('en-US',{maximumFractionDigits:d}):'—';
async function getJSON(p){const r=await fetch(p,{cache:'no-store'});if(!r.ok)throw Error(r.status);return r.json()}
async function getFirstJSON(paths){let last=null;for(const p of paths){try{return await getJSON(p)}catch(e){last=e}}throw last||Error('DATA_UNAVAILABLE')}
const DURABLE='https://raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/bot-state/runtime/public/data/';
function renderFreeHealth(h){const ok=h?.overall==='healthy';$('freeHealth').textContent=(ok?'HEALTHY':'DEGRADED')+' • '+(h?.generated_at||'—');$('freeHealth').className='status '+(ok?'ok':'warn');const rows=(h?.sources||[]).map(x=>x.name+': '+(x.ok?'OK':'DOWN'));$('freeSources').textContent=rows.length?rows.join(' • '):'لا توجد نتائج فحص.';}
function renderAdvanced(v){
  const e=v?.integrated_engines?.ghazi_gex_multi||{};
  const g=e.greek_exposure_near_spot||{};
  $('dex').textContent=fmt(g.dex,0);
  $('vanna').textContent=fmt(g.vanna,0);
  $('charm').textContent=fmt(g.charm,0);
  $('vomma').textContent=fmt(g.vomma,0);
  $('zomma').textContent=fmt(g.zomma,0);
  $('gciLive').textContent=e.gci!=null?fmt(e.gci*100,1)+'%':'—';
  $('pcOi').textContent=e.put_call_oi_ratio!=null?fmt(e.put_call_oi_ratio,2):'—';
  $('zdteShare').textContent=e.zdte_share_abs_gex!=null?fmt(e.zdte_share_abs_gex*100,1)+'%':'—';
  $('advancedGreekNote').textContent=e.available?'المحرك يعمل؛ النتائج Shadow ولا تمنح الإشارة سلطة.':'المحرك غير متاح حالياً.';
}
function renderValidation(v){const score=num(v?.agreement_score);$('gexValidation').textContent=(v?.decision||'SHADOW_ONLY')+' • توافق '+(score!=null?fmt(score*100,0)+'%':'—');$('gexValidation').className='status '+(score!=null&&score>=.6?'ok':'warn');$('gexValidationReason').textContent=(v?.reasons_ar||[]).join(' • ')||'طبقة تحقق بحثية فقط؛ لا تمنح أي مصدر سلطة منفردة.';
const m=v?.metrics||{};$('gexDisagreement').textContent=['gex','flip','call_wall','put_wall'].map(k=>k+': '+(m[k]?.relative_disagreement!=null?fmt(m[k].relative_disagreement*100,1)+'%':'—')).join(' • ');}
function renderTargets(d){const spot=num(d.spot),flip=num(d.zero_gamma_flip),cw=num(d.call_wall),pw=num(d.put_wall),vix=num(d.vix);$('targetUp').textContent=cw&&spot&&cw>spot?fmt(cw):'—';$('targetDown').textContent=pw&&spot&&pw<spot?fmt(pw):'—';$('targetFlip').textContent=fmt(flip);const em=spot&&vix?spot*(vix/100)/Math.sqrt(252):null;$('expectedUp').textContent=em?fmt(spot+em):'—';$('expectedDown').textContent=em?fmt(spot-em):'—';$('reading').textContent=(d.gamma_regime||'محايد')+' • '+(spot&&flip?(spot>flip?'فوق Gamma Flip':'تحت Gamma Flip'):'قراءة غير مكتملة');}

function optionSignal(o){
  const sigs=o?.research_directional_signals||o?.directional_signals||[];
  return sigs.find(x=>String(x.symbol||'').toUpperCase()==='SPX')||null;
}
function decide(d,o,now=Date.now()){
  const wait=(reason,gate)=>({s:'WAIT',confidence:null,confidenceText:'غير معاير',reason,gate});
  const age=marketAge(d,now);
  if(age==null||age<0||age>20)return wait('وقت شمعة SPX مفقود أو غير صالح أو متأخر؛ الانتظار.', 'STALE_DATA');
  if(!(num(d.spot)>0)||!(num(d.vwap)>0))return wait('السعر أو VWAP غير متاح؛ لا تُنشأ إشارة.', 'DATA');
  const map=d?.trade_map||{};
  if(!['CALL','PUT','NO_TRADE','DATA_INSUFFICIENT'].includes(map.state)){
    return wait('خريطة SPX البحثية غير متاحة؛ لا تُستنتج إشارة بديلة من الخيارات.', 'DATA');
  }
  const s=map.state==='DATA_INSUFFICIENT'?'WAIT':map.state;
  return{
    s,
    confidence:null,
    confidenceText:'غير معاير',
    reason:map.reason_ar||'خريطة SPX الهيكلية غير مكتملة.',
    gate:s==='CALL'||s==='PUT'?'STRUCTURAL_RESEARCH':s==='NO_TRADE'?'NO_TRADE_ZONE':'DATA',
    tradeMap:map
  };
}
function renderOptions(o){
  const sigs=o?.research_directional_signals||o?.directional_signals||[];
  const spx=optionSignal(o);
  $('calls').textContent=sigs.filter(x=>x.direction==='CALL').length;
  $('puts').textContent=sigs.filter(x=>x.direction==='PUT').length;
  $('flow').textContent=spx?.direction||'WAIT';
  $('quality').textContent=spx?.score!=null?fmt(spx.score,0):((o?.provider_readiness?.status)||'—');
  $('optionsReason').textContent=spx?('SPX '+spx.direction+' • '+(spx.omega_decision?.state||spx.selection_policy||'research')):'لا توجد إشارة خيارات مؤكدة من الرادار.';
  const gm=o?.gamma_maps?.SPX||o?.gamma_maps?.spx||{};
  $('topoi').textContent=(gm.top_oi_strikes||[]).slice(0,3).map(x=>fmt(x,0)).join(' / ')||'—';
  $('topvol').textContent=(gm.top_volume_strikes||[]).slice(0,3).map(x=>fmt(x,0)).join(' / ')||'—';
  $('liq').textContent=fmt(gm.liquidity_strike,0);
  $('coverage').textContent=gm.gamma_coverage_pct!=null?fmt(gm.gamma_coverage_pct,0)+'%':'—';
}
function render(d,o){
  $('spot').textContent=fmt(d.spot);$('change').textContent=num(d.change_pct)!=null?fmt(d.change_pct,2)+'%':'—';
  $('vwap').textContent=fmt(d.vwap);$('rsi').textContent=fmt(d.rsi);$('vix').textContent=fmt(d.vix);$('regime').textContent=d.gamma_regime||'—';
  $('flip').textContent=fmt(d.zero_gamma_flip);$('callwall').textContent=fmt(d.call_wall);$('putwall').textContent=fmt(d.put_wall);$('gex').textContent=fmt(d.net_gex_dollars,0);
  renderOptions(o);
  const q=decide(d,o),s=$('signal');s.textContent=q.s;s.className='signal '+q.s.toLowerCase();
  $('confidence').textContent=q.confidenceText||(q.confidence!=null?q.confidence+'%':'غير معاير');
  $('confluence').textContent=(q.s==='CALL'||q.s==='PUT')?'PASS':'WAIT';$('gate').textContent=q.gate;$('reason').textContent=q.reason;
  $('entry').textContent='—';$('tp1').textContent='—';$('tp2').textContent='—';$('sl').textContent='—';
  const map=q.tradeMap||d?.trade_map||{};
  if(q.s==='CALL'||q.s==='PUT'){
    const expectedMove=num(map.expected_move_1d_proxy);
    const entry=q.s==='CALL'?num(map.call_above):num(map.put_below);
    const tp1=q.s==='CALL'?num(map.call_target):num(map.put_target);
    const tp2=tp1&&expectedMove?(q.s==='CALL'?tp1+expectedMove*0.5:tp1-expectedMove*0.5):null;
    const invalidation=num(d.vwap);
    $('entry').textContent=fmt(entry);
    $('tp1').textContent=fmt(tp1);
    $('tp2').textContent=fmt(tp2);
    $('sl').textContent=fmt(invalidation);
  }else if(q.s==='NO_TRADE'&&map.no_trade_zone){
    $('entry').textContent='CALL>'+fmt(map.call_above)+' / PUT<'+fmt(map.put_below);
  }
}
let lastSnapshot=null, lastOptions={};
async function boot(){
  if(lastSnapshot)render(lastSnapshot,lastOptions);
  try{
    const [d,s,o,h,v]=await Promise.all([
      getFirstJSON([DURABLE+'spx_dashboard.json','../data/spx_dashboard.json']),
      getJSON('../data/data-status.json'),
      getJSON('../data/options_latest.json').catch(()=>({})),
      getFirstJSON([DURABLE+'free_data_health.json','../data/free_data_health.json']).catch(()=>({overall:'degraded',sources:[]})),
      getFirstJSON([DURABLE+'free_gex_validation.json','../data/free_gex_validation.json']).catch(()=>({decision:'SHADOW_ONLY',agreement_score:0,reasons_ar:['لا توجد نتيجة تحقق منشورة حالياً.']}))
    ]);
    lastSnapshot=d;lastOptions=o;
    render(d,o);renderFreeHealth(h);renderValidation(v);renderAdvanced(v);renderTargets(d);
    const age=marketAge(d), optionTime=o?.generated_at||o?.updated_at||'';
    $('status').textContent=age!=null&&age>=0&&age<=10?'RECENT / RESEARCH • '+fmt(age,1)+' min old':'STALE • '+fmt(age,1)+' min old';
    $('status').className='status '+(age!=null&&age>=0&&age<=10?'ok':'warn');
    $('sources').textContent='Price: '+(d.price_source||'—')+' • Gamma: '+(d.gamma_source||'—')+' • Options: '+(optionTime||'—')+' • Updated: '+(d.generated_at||'—');
    if(s.option_provider_readiness)$('sources').textContent+=' • Provider: '+(s.option_provider_readiness.status||'—');
  }catch(e){
    lastSnapshot=null;lastOptions={};render({},{});renderTargets({});
    $('status').textContent='DATA UNAVAILABLE • '+e.message;$('status').className='status warn';
    $('reason').textContent='لا توجد بيانات منشورة قابلة للتحقق الآن؛ المحرك مغلق.';
  }
}
setInterval(()=>{$('clock').textContent=new Date().toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false})},1000);
boot();setInterval(boot,60000);if('serviceWorker' in navigator)navigator.serviceWorker.register('./sw.js').catch(()=>{});
