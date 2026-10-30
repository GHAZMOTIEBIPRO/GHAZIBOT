'use strict';
// Guardian contract page: quotes are observations, not trades or synthetic OHLCV.
const el = id => document.getElementById(id);
const money = v => typeof v === 'number' && Number.isFinite(v) && v > 0 ? v.toFixed(2) : 'غير متاح';
const stageName = {
 WATCH:'مراقبة', CONFIRMED:'إشارة مؤكدة بحثيًا', ACTIVE:'متابعة',
 T1_HIT:'وصول السهم للهدف الأول', T2_HIT:'وصول السهم للهدف الثاني',
 T3_HIT:'وصول السهم للهدف الثالث', INVALIDATED:'إبطال سيناريو السهم',
 EXPIRED:'انتهى العقد', LICENSE_BLOCKED:'محجوب بسبب ترخيص البيانات'
};
let records = [];
let reportGeneratedAt = null;
const statusText = (id, value) => { el(id).textContent = value; };
const create = (tag, value, parent) => {
 const node = document.createElement(tag);
 node.textContent = value;
 parent.append(node);
 return node;
};
function svgElement(tag, attributes, value) {
 const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
 for (const [key, attr] of Object.entries(attributes)) node.setAttribute(key, String(attr));
 if (value !== undefined) node.textContent = String(value);
 el('chart').append(node);
}
function pointsFor(row) {
 if (!Array.isArray(row.quote_snapshots)) return [];
 return row.quote_snapshots.filter(p => p && Number.isFinite(Date.parse(p.quote_timestamp))
  && typeof p.mark_for_exit === 'number' && Number.isFinite(p.mark_for_exit)
  && p.mark_for_exit > 0 && typeof p.source === 'string' && p.source.trim())
  .sort((a,b) => Date.parse(a.quote_timestamp) - Date.parse(b.quote_timestamp));
}
function plot(points) {
 const chart = el('chart');
 chart.replaceChildren();
 if (!points.length) { chart.hidden = true; return; }
 chart.hidden = false;
 const stamps=points.map(p=>Date.parse(p.quote_timestamp));
 const prices=points.map(p=>p.mark_for_exit);
 const minimum=Math.min(...prices),maximum=Math.max(...prices);
 const start=stamps[0],end=stamps[stamps.length-1];
 const chartY=v=>270-220*(v-minimum)/(maximum-minimum || 1);
 for(let i=0;i<5;i++){
   const price=minimum+(maximum-minimum)*i/4, y=270-i*55;
   svgElement('line',{x1:70,y1:y,x2:870,y2:y,stroke:'#30435b'});
   svgElement('text',{x:60,y:y+4,fill:'#c1d2e5','text-anchor':'end'},price.toFixed(2));
 }
 points.forEach((p,i)=>svgElement('circle',{
   cx:stamps.length===1?475:80+780*(stamps[i]-start)/(end-start || 1),
   cy:chartY(p.mark_for_exit),r:4,fill:'#61dbca'
 }));
 const time=v=>new Date(v).toISOString().slice(0,16).replace('T',' ')+' UTC';
 svgElement('text',{x:80,y:305,fill:'#c1d2e5'},time(start));
 svgElement('text',{x:870,y:305,fill:'#c1d2e5','text-anchor':'end'},time(end));
}
function draw() {
 const selected=el('contracts').value;
 const row=records.find(r=>r.contract_symbol===selected);
 for(const id of ['facts','rows','chart']) el(id).replaceChildren();
 statusText('warning','');
 statusText('name','');
 statusText('meta','');
 statusText('targets','');
 statusText('empty','');
 el('chart').hidden=true;
 if(!row) {
   statusText('warning',selected
     ? 'العقد المطلوب غير موجود في الملف العام الحالي. قد يكون خارج سجل العقود المنشور.'
     : 'لا توجد عقود متاحة في التقرير المنشور.');
   return;
 }
 const url=new URL(location.href);
 url.searchParams.set('contract',selected);
 history.replaceState(null,'',url);
 const blocked=row.stage==='LICENSE_BLOCKED'||row.data_state==='LICENSE_BLOCKED';
 statusText('name',row.symbol+' '+row.side+' — '+row.contract_symbol);
 statusText('meta','الاسترايك: '+money(row.strike)+' | الاستحقاق: '+(row.expiration||'غير معروف')
  +' | الحالة: '+(stageName[row.stage]||row.stage||'غير معروفة'));
 if(blocked){
   statusText('warning',row.reason_ar||'لا تتوفر صلاحية لعرض بيانات الأسعار لهذا العقد.');
   statusText('empty','لا يمكن عرض شارت أو سعر دخول أو أهداف عقد من بيانات غير مصرح بنشرها.');
   return;
 }
 const quoteValid=row.current_quote_research_valid===true && row.data_stale===false;
 const facts=[
   'مرجع الدخول البحثي: '+(row.entry_reference_verified===true?money(row.entry_premium_reference):'غير موثق'),
   'آخر Bid مؤرّخ: '+(quoteValid?money(row.last_mark):'غير متاح أو قديم'),
   'عمر السعر: '+(quoteValid && typeof row.quote_age_minutes==='number'?
     row.quote_age_minutes.toFixed(1)+' دقيقة':'غير مؤكد')
 ];
 facts.forEach(f=>create('p',f,el('facts')));
 if(row.stage_provisional) statusText('warning','حالة الهدف أو الوقف مبدئية؛ لم تثبت بمصدر مؤرّخ لسعر السهم.');
 const targets=row.target_map && typeof row.target_map==='object'?row.target_map:{};
 statusText('targets',['t1','t2','t3','invalidation'].map(key=>{
   const label=key==='invalidation'?'إبطال السهم':key.toUpperCase();
   return label+': '+money(targets[key]?.price);
 }).join(' | '));
 const points=pointsFor(row);
 statusText('empty',points.length
   ? points.length+' لقطة عرض Bid موثقة بوقت المصدر. هذه نقاط منفصلة، وليست شموع تداول أو إثبات تنفيذ.'
   : 'لم تصل لقطات Bid مؤرخة ومسموح عرضها. لا يُنشأ شارت تقديري.');
 plot(points);
 for(const p of points.slice(-100).reverse()){
   const tr=document.createElement('tr');
   [p.quote_timestamp,p.source,money(p.bid),money(p.ask)].forEach(v=>create('td',String(v),tr));
   el('rows').append(tr);
 }
}
async function refresh() {
 try {
   const response=await fetch(
    'https://raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/bot-state/runtime/public/data/contract_guardian.json',
    {cache:'no-store',signal:AbortSignal.timeout(15000)}
   );
   if(!response.ok) throw new Error('fetch');
   const data=await response.json();
   if(!Array.isArray(data.active)||!Array.isArray(data.terminal_recent)) throw new Error('schema');
   const previouslySelected=el('contracts').value;
   const requested=new URLSearchParams(location.search).get('contract');
   const unique=new Map();
   [...data.active,...data.terminal_recent].filter(r=>r && typeof r.contract_symbol==='string')
    .forEach(r=>unique.set(r.contract_symbol,r));
   records=[...unique.values()];
   const selector=el('contracts');
   selector.replaceChildren();
   records.forEach(r=>{
     const option=document.createElement('option');
     option.value=r.contract_symbol;
     option.textContent=r.contract_symbol+(r.data_state==='LICENSE_BLOCKED'?' — محجوب':'');
     selector.append(option);
   });
   selector.disabled=records.length===0;
   const wanted=previouslySelected||requested;
   if(wanted && unique.has(wanted)) selector.value=wanted;
   else if(wanted) {
     // Never silently show a different contract when a Telegram deep link is missing.
     const option=document.createElement('option');
     option.value=wanted;
     option.textContent=wanted+' — غير مدرج';
     selector.append(option);
     selector.value=wanted;
   }
   reportGeneratedAt=data.generated_at||null;
   const generated=reportGeneratedAt?Date.parse(reportGeneratedAt):NaN;
   const age=Number.isFinite(generated)?(Date.now()-generated)/60000:Infinity;
   const freshness=age>=0&&age<=10?'تقرير حديث':'تقرير قديم أو غير مؤرخ';
   statusText('status','تاريخ إنشاء التقرير: '+(reportGeneratedAt||'غير معروف')
     +' | '+freshness+' | عقود مسموح متابعتها: '+(data.active_count||0)
     +' | عقود محجوبة: '+(data.license_blocked_count||0));
   draw();
 }catch{
   statusText('status','تعذر جلب تقرير العقود. لا تتوفر بيانات آنية موثوقة.');
   statusText('warning','فشل الاتصال بمصدر التقرير؛ يُمنع اعتبار البيانات السابقة محدثة.');
 }
}
el('contracts').addEventListener('change',draw);
refresh();
setInterval(refresh,60000);
