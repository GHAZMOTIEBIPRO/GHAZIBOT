"use strict";
/* Public research watch: primary SEC/FDA links + stock RVOL.
 * No automated trades, no positive market response assumed, no ClinicalTrials
 * generic registry updates promoted to "high-upside news".
 */
(() => {
  const URLS=[
    "https://raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/bot-state/runtime/public/data/decision_brief.json",
    "./data/decision_brief.json",
  ];
  const el = id => document.getElementById(id);
  const set=(id,value)=>{if(el(id))el(id).textContent=value;};
  const n=(v,d=2)=>typeof v==="number"&&Number.isFinite(v)
    ?v.toLocaleString("en-US",{maximumFractionDigits:d}):"—";
  const asDate=t=>{const x=new Date(t);return Number.isFinite(x.getTime())?x:null;};
  const time=t=>{
    const x=asDate(t);return x?new Intl.DateTimeFormat("en-GB",{
      timeZone:"Asia/Riyadh",dateStyle:"medium",timeStyle:"short"
    }).format(x):"غير محدد";
  };
  const node=(tag,label,cls)=>{
    const x=document.createElement(tag);x.textContent=label;if(cls)x.className=cls;return x;
  };
  const safeOfficial=url=>{
    try {
      const x=new URL(url);
      const host=x.hostname.toLowerCase();
      if(x.protocol!=="https:"||x.username||x.password)return null;
      return ["sec.gov","www.sec.gov","fda.gov","www.fda.gov"].includes(host)
        || host.endsWith(".fda.gov") ? url : null;
    }catch(_){return null;}
  };
  const verifiedSchema=d=>d && d.schema==="ghazi.public_decision.v1" &&
    d.authority==="RESEARCH_ONLY_NO_AUTOMATED_CALL_PUT" &&
    d.live_trade_quotes_verified===false &&
    asDate(d.generated_at) && asDate(d.source_generated_at);
  async function fetchOne(url){
    const r=await fetch(url+"?v="+Date.now(),{cache:"no-store"});
    if(!r.ok)throw Error("HTTP "+r.status);
    const data=await r.json();
    if(!verifiedSchema(data)||asDate(data.generated_at).getTime()>Date.now()+300000)
      throw Error("invalid report");
    return data;
  }
  function fallbackWatch(report) {
    return (Array.isArray(report.stocks)?report.stocks:[])
      .filter(s=>["CALL","UP"].includes(s.direction_research))
      .map(s=>({
        symbol:s.symbol,score:s.score,rvol:s.rvol,observed_price:s.observed_price,
        source_bar_generated_at:report.source_generated_at,
        research_label:"PRICE_MOMENTUM_WITHOUT_VERIFIED_NEWS",
        has_primary_publication:false,
      }));
  }
  function render(report) {
    const stamp=asDate(report.source_generated_at);
    const delta=(Date.now()-stamp.getTime())/60000;
    const current=delta>=-5 && delta<=7*24*60;
    set("catalyst-overview-status",
      "وقت الرصد الأصلي: "+time(report.source_generated_at)+
      " (الرياض) · "+(current?"بيانات بحثية":"تقرير قديم، لا يصلح لرصد فرصة حالية")+
      " · الأسعار إن ظهرت هي أسعار وقت الرصد وليست لحظية.");
    const focus=report.catalyst_focus?.schema==="ghazi.catalyst_focus.v1"
      ?report.catalyst_focus:null;
    const events=Array.isArray(focus?.issuer_primary_events)?focus.issuer_primary_events:[];
    const watch=Array.isArray(focus?.upside_watch)?focus.upside_watch:fallbackWatch(report);
    const grid=el("catalyst-upside-grid");
    if(grid){
      grid.replaceChildren();
      for(const row of watch.slice(0,12)){
        const article=node("article","","ghazi-market-pulse");
        article.append(node("strong",String(row.symbol||"—")));
        article.append(node("p","سعر آخر رصد: "+n(row.observed_price)+" دولار"));
        const d=node("dl","");
        const put=(label,value)=>{
          const item=node("div","");
          item.append(node("dt",label),node("dd",value));
          d.append(item);
        };
        put("RVOL رصد",n(row.rvol,2));
        put("درجة التحليل (ليست نسبة)",n(row.score,1));
        put("دليل الخبر",row.has_primary_publication?
          "رابط أولي موجود، أثره غير مثبت":"لا يوجد خبر أولي مؤكد");
        article.append(d);
        const label=row.research_label==="PRIMARY_EVENT_PLUS_RELATIVE_VOLUME_WATCH"?
          "خبر أولي + حجم نسبي مرتفع — يحتاج تدقيق أثر الخبر":
          row.has_primary_publication?"خبر أولي، الزخم يحتاج تأكيد":
          "تحليل زخم فقط، ليس محفز ارتفاع مؤكد";
        article.append(node("small",label+" · "+time(row.source_bar_generated_at||report.source_generated_at)));
        const source=safeOfficial(row.source_url);
        if(source){
          const a=node("a","اقرأ الإفصاح الأصلي ↗");
          a.href=source;a.target="_blank";a.rel="noopener noreferrer";article.append(a);
        }
        grid.append(article);
      }
      if(!watch.length)grid.append(node("p","لا يوجد حاليًا سهم يطابق شروط مراقبة الصعود في بيانات الرادار المنشورة."));
    }
    const list=el("catalyst-official-list");
    if(list){
      list.replaceChildren();
      const allowed=events.filter(e=>safeOfficial(e.source_url)).slice(0,12);
      for(const e of allowed){
        const article=node("article","","ghazi-catalyst-primary");
        article.append(node("h4",String(e.symbol||"—")+" · "+String(e.form||e.source||"حدث رسمي")));
        article.append(node("p",String(e.headline||"بدون عنوان")+" · تاريخ الخبر: "+
          String(e.published_at||"غير مؤكد")+" · تأكيد اتجاه السعر: غير متاح"));
        const a=node("a","المصدر الرسمي ↗");
        a.href=safeOfficial(e.source_url);a.target="_blank";a.rel="noopener noreferrer";
        article.append(a);list.append(article);
      }
      if(!allowed.length)
        list.append(node("p","لم يظهر في التقرير المتاح خبر SEC/FDA مؤهل بروابط أولية. تحديثات ClinicalTrials.gov وحدها لا تعتبر محفز صعود مثبتًا."));
    }
    const counts=focus?.event_counts;
    set("catalyst-overview-note",
      "أحداث أولية مؤهلة في التقرير: "+n(counts?.primary_evidence_in_scanned_sample,0)+
      " · تحديثات السجل الطبي المستبعدة من تأكيد الصعود: "+
      n(counts?.clinical_registry_excluded_from_upside_confirmation,0)+
      " · يجب التحقق من هوية جهة الإصدار وتاريخ الأثر؛ ارتفاع السعر غير مضمون.");
  }
  async function refresh(){
    const btn=el("catalyst-overview-refresh");if(btn)btn.disabled=true;
    const results=await Promise.allSettled(URLS.map(fetchOne));
    const data=results.filter(x=>x.status==="fulfilled").map(x=>x.value);
    data.sort((a,b)=>Date.parse(b.source_generated_at)-Date.parse(a.source_generated_at));
    if(data.length)render(data[0]);
    else set("catalyst-overview-status","تعذر جلب تقرير الأخبار من المصدر والنسخة الاحتياطية. لا توجد قائمة مؤكدة يمكن عرضها.");
    if(btn)btn.disabled=false;
  }
  if(typeof module!=="undefined"&&module.exports)
    module.exports={safeOfficial,verifiedSchema};
  if(typeof document!=="undefined"){
    el("catalyst-overview-refresh")?.addEventListener("click",refresh);
    refresh();
    setInterval(refresh,10*60*1000);
  }
})();
