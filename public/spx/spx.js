const $=id=>document.getElementById(id);
const num=(x)=>Number.isFinite(Number(x))?Number(x):null;
const fmt=(x,d=2)=>num(x)!=null?num(x).toLocaleString('en-US',{maximumFractionDigits:d}):'—';
async function getJSON(p){const r=await fetch(p,{cache:'no-store'});if(!r.ok)throw Error(r.status);return r.json()}
function renderFreeHealth(h){const ok=h?.overall==='healthy';$('freeHealth').textContent=(ok?'HEALTHY':'DEGRADED')+' • '+(h?.generated_at||'—');$('freeHealth').className='status '+(ok?'ok':'warn');const rows=(h?.sources||[]).map(x=>x.name+': '+(x.ok?'OK':'DOWN'));$('freeSources').textContent=rows.length?rows.join(' • '):'لا توجد نتائج فحص.';}
function renderValidation(v){const score=num(v?.agreement_score);$('gexValidation').textContent=(v?.decision||'SHADOW_ONLY')+' • توافق '+(score!=null?fmt(score*100,0)+'%':'—');$('gexValidation').className='status '+(score!=null&&score>=.6?'ok':'warn');$('gexValidationReason').textContent=(v?.reasons_ar||[]).join(' • ')||'طبقة تحقق بحثية فقط؛ لا تمنح أي مصدر سلطة منفردة.';
const m=v?.metrics||{};$('gexDisagreement').textContent=['gex','flip','call_wall','put_wall'].map(k=>k+': '+(m[k]?.relative_disagreement!=null?fmt(m[k].relative_disagreement*100,1)+'%':'—')).join(' • ');}
function renderTargets(d){const spot=num(d.spot),flip=num(d.zero_gamma_flip),cw=num(d.call_wall),pw=num(d.put_wall),vix=num(d.vix);$('targetUp').textContent=cw&&spot&&cw>spot?fmt(cw):'—';$('targetDown').textContent=pw&&spot&&pw<spot?fmt(pw):'—';$('targetFlip').textContent=fmt(flip);const em=spot&&vix?spot*(vix/100)/Math.sqrt(252):null;$('expectedUp').textContent=em?fmt(spot+em):'—';$('expectedDown').textContent=em?fmt(spot-em):'—';$('reading').textContent=(d.gamma_regime||'محايد')+' • '+(spot&&flip?(spot>flip?'فوق Gamma Flip':'تحت Gamma Flip'):'قراءة غير مكتملة');}

function optionSignal(o){
  const sigs=o?.research_directional_signals||o?.directional_signals||[];
  return sigs.find(x=>String(x.symbol||'').toUpperCase()==='SPX')||null;
}
function decide(d,o){
  const p=num(d.spot), v=num(d.vwap), r=num(d.rsi), age=num(d.age_minutes);
  if(p==null||v==null||r==null)return{s:'WAIT',confidence:0,reason:'بيانات السعر/VWAP/RSI غير مكتملة.',gate:'DATA'};
  if(age!=null&&age>15)return{s:'WAIT',confidence:0,reason:'بيانات SPX أصبحت قديمة؛ المحرك مغلق لحماية الإشارة.',gate:'STALE_DATA'};
  let bull=0,bear=0,parts=[];
  if(p>v){bull++;parts.push('السعر فوق VWAP')}else{bear++;parts.push('السعر تحت VWAP')}
  if(r>=55){bull++;parts.push('RSI داعم للصعود')}else if(r<=45){bear++;parts.push('RSI داعم للهبوط')}else parts.push('RSI محايد');
  const regime=String(d.gamma_regime||'').toLowerCase();
  if(regime.includes('positive')){p>v?bull++:bear++;parts.push('Gamma موجب')}
  else if(regime.includes('negative')){p<v?bear++:bull++;parts.push('Gamma سالب')}
  const flip=num(d.zero_gamma_flip);
  if(flip!=null){if(p>flip){bull++;parts.push('فوق Gamma Flip')}else if(p<flip){bear++;parts.push('تحت Gamma Flip')}}
  const os=optionSignal(o);
  let optionDir='';
  if(os&&['CALL','PUT'].includes(os.direction)){
    optionDir=os.direction;
    const approved=os.omega_decision?.approved===true || os.free_alert_eligible===true;
    if(approved){os.direction==='CALL'?bull++:bear++;parts.push('رادار الخيارات مؤكد')}
    else parts.push('رادار الخيارات غير مجاز للتنبيه');
  }
  const net=bull-bear;
  const strongest=Math.max(bull,bear), total=bull+bear;
  const conflict=(bull>0&&bear>0&&Math.abs(net)<2);
  if(conflict||strongest<3||Math.abs(net)<2)return{s:'WAIT',confidence:Math.round(Math.max(0,Math.min(100,50+Math.abs(net)*10))),reason:parts.join(' • '),gate:'CONFLUENCE'};
  const s=net>0?'CALL':'PUT';
  if(optionDir&&optionDir!==s)return{s:'WAIT',confidence:45,reason:parts.join(' • ')+' • تعارض مع اتجاه رادار الخيارات.',gate:'CONFLICT'};
  const confidence=Math.round(Math.min(95,55+(Math.abs(net)/Math.max(total,1))*40));
  return{s,confidence,reason:parts.join(' • '),gate:'PASS'};
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
  $('confidence').textContent=q.confidence+'%';$('confluence').textContent=q.gate==='PASS'?'PASS':'WAIT';$('gate').textContent=q.gate;$('reason').textContent=q.reason;
  $('entry').textContent='—';$('tp1').textContent='—';$('tp2').textContent='—';$('sl').textContent='—';
  if(q.s==='CALL'||q.s==='PUT'){
    const spot=num(d.spot),callWall=num(d.call_wall),putWall=num(d.put_wall);
    const tp1=q.s==='CALL'?(callWall&&callWall>spot?callWall:null):(putWall&&putWall<spot?putWall:null);
    const risk=Math.max(spot*0.0015,Math.abs(spot-num(d.vwap))*0.35);
    $('entry').textContent=fmt(spot);
    $('tp1').textContent=fmt(tp1);
    $('tp2').textContent=fmt(q.s==='CALL'?(tp1?tp1+(tp1-spot)*0.5:null):(tp1?tp1-(spot-tp1)*0.5:null));
    $('sl').textContent=fmt(q.s==='CALL'?spot-risk:spot+risk);
  }
}
async function boot(){
  try{
    const [d,s,o,h,v]=await Promise.all([getJSON('../data/spx_dashboard.json'),getJSON('../data/data-status.json'),getJSON('../data/options_latest.json').catch(()=>({})),getJSON('../data/free_data_health.json').catch(()=>({overall:'degraded',sources:[]})),getJSON('../data/free_gex_validation.json').catch(()=>({decision:'SHADOW_ONLY',agreement_score:0,reasons_ar:['لا توجد نتيجة تحقق منشورة حالياً.']}))]);
    render(d,o);renderFreeHealth(h);renderValidation(v);renderTargets(d);
    const age=num(d.age_minutes), optionTime=o?.generated_at||o?.updated_at||'';
    $('status').textContent=age!=null&&age<=10?'LIVE/RECENT • '+fmt(age,1)+' min old':'STALE • '+fmt(age,1)+' min old';
    $('status').className='status '+(age!=null&&age<=10?'ok':'warn');
    $('sources').textContent='Price: '+(d.price_source||'—')+' • Gamma: '+(d.gamma_source||'—')+' • Options: '+(optionTime||'—')+' • Updated: '+(d.generated_at||'—');
    if(s.option_provider_readiness)$('sources').textContent+=' • Provider: '+(s.option_provider_readiness.status||'—');
  }catch(e){
    $('status').textContent='DATA UNAVAILABLE • '+e.message;$('status').className='status warn';
    $('reason').textContent='لا توجد بيانات منشورة قابلة للتحقق الآن؛ المحرك مغلق.';
  }
}
setInterval(()=>{$('clock').textContent=new Date().toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false})},1000);
boot();if('serviceWorker' in navigator)navigator.serviceWorker.register('./sw.js').catch(()=>{});