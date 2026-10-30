'use strict';
const el=id=>document.getElementById(id);
const fmt=v=>typeof v==='number'&&Number.isFinite(v)?v.toFixed(2):'—';
let records=[];
function text(id,value){el(id).textContent=value;}
function draw(){
 const row=records.find(r=>r.contract_symbol===el('contracts').value);
 for(const id of ['facts','rows','chart'])el(id).replaceChildren();
 if(!row){text('empty','لا توجد عقود محفوظة حاليًا.');return;}
 const url=new URL(location.href);url.searchParams.set('contract',row.contract_symbol);history.replaceState(null,'',url);
 text('name',`${row.symbol||''} ${row.side||''} — ${row.contract_symbol}`);
 text('meta',`الاسترايك ${fmt(row.strike)} | الانتهاء ${row.expiration||'—'} | متابعة بحثية دون تنفيذ أوامر`);
 const facts=[`سعر الاختيار المرجعي: ${row.entry_reference_verified?fmt(row.entry_premium_reference):'غير موثق'}`,`آخر سعر موثق: ${row.data_stale?'قديم / غير صالح كسعر حالي':fmt(row.last_mark)}`,`عمر السعر بالدقائق: ${fmt(row.quote_age_minutes)}`];
 for(const f of facts){const p=document.createElement('p');p.textContent=f;el('facts').append(p);}
 text('targets',['t1','t2','t3','invalidation'].map(k=>`${k==='invalidation'?'إبطال السيناريو':k.toUpperCase()}: ${fmt(row.target_map?.[k]?.price)}`).join(' | '));
 const points=(Array.isArray(row.quote_snapshots)?row.quote_snapshots:[]).filter(p=>Number.isFinite(Date.parse(p.quote_timestamp))&&typeof p.mark_for_exit==='number'&&p.mark_for_exit>0).sort((a,b)=>Date.parse(a.quote_timestamp)-Date.parse(b.quote_timestamp));
 text('empty',points.length?`${points.length} لقطة بحثية؛ المحور الأفقي وقت المصدر، والرأسي دولار للعقد. لا تتوفر شموع أو حجم تداول موثق في هذا السجل.`:'لا توجد لقطات أسعار موثقة لهذا العقد. لن يُرسم شارت تقديري.');
 if(points.length){
 const times=points.map(p=>Date.parse(p.quote_timestamp)), prices=points.map(p=>p.mark_for_exit),lo=Math.min(...prices),hi=Math.max(...prices),start=times[0],end=times[times.length-1];
 const svg=(tag,attrs,label)=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);if(label)n.textContent=label;el('chart').append(n);};
 for(let i=0;i<5;i++){let v=lo+(hi-lo)*i/4,y=270-i*55;svg('line',{x1:70,x2:870,y1:y,y2:y,stroke:'#30435b'});svg('text',{x:60,y:y+5,fill:'#b8c6d8','text-anchor':'end'},v.toFixed(2));}
 points.forEach((p,i)=>svg('circle',{cx:80+780*(times[i]-start)/(end-start||1),cy:270-220*(p.mark_for_exit-lo)/(hi-lo||1),r:4,fill:'#61dbca'}));
 svg('text',{x:80,y:305,fill:'#b8c6d8'},new Date(start).toISOString().slice(11,19)+' UTC');svg('text',{x:870,y:305,fill:'#b8c6d8','text-anchor':'end'},new Date(end).toISOString().slice(11,19)+' UTC');
 }
 for(const p of points.slice(-100).reverse()){const tr=document.createElement('tr');for(const v of [p.quote_timestamp,p.source||'غير معروف',fmt(p.bid),fmt(p.ask)]){const td=document.createElement('td');td.textContent=v;tr.append(td);}el('rows').append(tr);}
}
async function refresh(){try{
 const response=await fetch('https://raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/bot-state/runtime/public/data/contract_guardian.json',{cache:'no-store',signal:AbortSignal.timeout(15000)});if(!response.ok)throw Error('feed');const data=await response.json();
 if(!Array.isArray(data.active)||!Array.isArray(data.terminal_recent))throw Error('schema');
 const selected=el('contracts').value||new URLSearchParams(location.search).get('contract');records=[...data.active,...data.terminal_recent];el('contracts').replaceChildren();
 records.forEach(r=>{const option=document.createElement('option');option.value=r.contract_symbol;option.textContent=r.contract_symbol;el('contracts').append(option);});
 if(selected){el('contracts').value=selected;}
 text('status',`آخر إنشاء للتقرير: ${data.generated_at||'غير معروف'} — ليس وقت سعر العقد`);draw();
 }catch{ text('status','تعذر تحديث السجل. أي عرض سابق محفوظ وليس سعرًا حيًا.');}}
el('contracts').addEventListener('change',draw);refresh();setInterval(refresh,60000);
