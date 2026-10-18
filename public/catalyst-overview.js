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
  const SEC_URLS=[
    "https://raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/bot-state/runtime/public/data/sec_filing_pulse.json",
    "./data/sec_filing_pulse.json",
  ];
  const GDELT_URLS=[
    "https://raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/bot-state/runtime/public/data/free_public_intelligence.json",
    "./data/free_public_intelligence.json",
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
  async function fetchSecOne(url){
    const response=await fetch(url+"?v="+Date.now(),{cache:"no-store"});
    if(!response.ok)throw Error("HTTP "+response.status);
    const data=await response.json();
    if(!data||data.schema!=="ghazi.sec_issuer_pulse.v1"||
       !data.policy||data.policy.positive_news_inferred!==false||
       !asDate(data.generated_at)||asDate(data.generated_at).getTime()>Date.now()+300000)
      throw Error("untrusted SEC evidence");
    return data;
  }
  async function fetchNewsContext(url){
    const response=await fetch(url+"?v="+Date.now(),{cache:"no-store"});
    if(!response.ok)throw Error("HTTP "+response.status);
    const data=await response.json();
    if(!data || data.schema!=="free_public_intelligence_v1" ||
       data.decision_authority!==false ||
       !asDate(data.generated_at) ||
       asDate(data.generated_at).getTime()>Date.now()+300000)
      throw Error("invalid news context");
    return data;
  }
  function safeNewsLink(url){
    try {
      const x=new URL(url);
      return x.protocol==="https:"&&x.hostname&&!x.username&&!x.password?
        url:null;
    }catch(_){return null;}
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
  function render(report,secPulse,newsContext) {
    const stamp=asDate(report.source_generated_at);
    const delta=(Date.now()-stamp.getTime())/60000;
    const current=delta>=-5 && delta<=7*24*60;
    set("catalyst-overview-status",
      "وقت الرصد الأصلي: "+time(report.source_generated_at)+
      " (الرياض) · "+(current?"بيانات بحثية":"تقرير قديم، لا يصلح لرصد فرصة حالية")+
      " · الأسعار إن ظهرت هي أسعار وقت الرصد وليست لحظية.");
    const focus=report.catalyst_focus?.schema==="ghazi.catalyst_focus.v1"
      ?report.catalyst_focus:null;
    const currentSec=secPulse && asDate(secPulse.generated_at) &&
      Date.now()-asDate(secPulse.generated_at).getTime()<=7*24*60*60000;
    const secFilings=currentSec&&Array.isArray(secPulse.filings)?secPulse.filings:[];
    const filingsForDisplay=secFilings.filter(x=>
      x.original_filing_confirmed===true&&safeOfficial(x.source_url)
    ).map(x=>({
      symbol:x.symbol,source_url:x.source_url,source:"SEC EDGAR",
      form:x.form,event_type:x.event_type,
      headline:x.issuer+" — "+x.form+" ("+x.event_type+")",
      published_at:x.filing_date
    }));
    const events=[...filingsForDisplay,...(
      Array.isArray(focus?.issuer_primary_events)?focus.issuer_primary_events:[]
    )];

    const baseWatch=Array.isArray(focus?.upside_watch)?focus.upside_watch:fallbackWatch(report);
    // Joining filings with a ticker never proves a bullish catalyst.
    // Offering/registration filings specifically warn of dilution risks.
    const watch=baseWatch.map(row=>{
      const filing=secFilings.find(x=>x.symbol===row.symbol &&
        x.original_filing_confirmed===true &&
        x.event_type!=="OFFERING_OR_DILUTION_REVIEW" && safeOfficial(x.source_url));
      return filing?{...row,has_primary_publication:true,
        source:"SEC EDGAR",source_url:filing.source_url,
        headline:filing.form+" — event significance not confirmed",
        research_label:row.rvol>=1.5?
          "PRIMARY_EVENT_PLUS_RELATIVE_VOLUME_WATCH":
          "PRIMARY_EVENT_BUT_VOLUME_UNCONFIRMED"}:row;
    });

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
    if(!secPulse){
      set("sec-filing-source-status","تعذر الوصول إلى تغذية SEC المستقلة؛ نعرض سجل الرادار البحثي فقط.");
    }else{
      const coverage=secPulse.coverage||{};
      set("sec-filing-source-status",
        "SEC EDGAR: "+String(secPulse.status||"غير محدد")+
        " · شركات فُحصت "+n(coverage.issuers_inspected,0)+
        " · إفصاحات أصلية "+n(coverage.filings_verified,0)+
        " · آخر فحص "+time(secPulse.generated_at)+
        " · لا يعني صدور 8-K وحده ارتفاع السعر."+
        (String(secPulse.ticker_mapping_source||"").startsWith("UNVERIFIED")?
          " · خريطة CIK احتياطية قديمة؛ لا ينشر مستند إلا إذا أكد SEC الرمز والجهة." : ""));
    }
    const news=el("gdelt-news-list");
    if(news){
      news.replaceChildren();
      const recent=asDate(newsContext?.generated_at) &&
        Date.now()-asDate(newsContext.generated_at).getTime()<=48*60*60000;
      const articles=recent?[
        ...(Array.isArray(newsContext.gdelt_attention)?newsContext.gdelt_attention:[]),
        ...(Array.isArray(newsContext.yahoo_rss_attention)?newsContext.yahoo_rss_attention:[])
      ]:[];
      const included=articles.filter(x=>
        x && ["gdelt_doc_v2","yahoo_finance_rss"].includes(x.source) &&
        x.authority==="ATTENTION_ONLY" &&
        x.official_confirmed===false &&
        x.independent_confirmation===false &&
        x.market_direction==="UNKNOWN" &&
        safeNewsLink(x.url)
      ).slice(0,12);
      for(const a of included){
        const item=node("article","","ghazi-catalyst-primary");
        item.append(node("h4",String(a.symbol||"—")+" · خبر مرصود غير مؤكد"));
        const provider=a.source==="yahoo_finance_rss"?"Yahoo Finance RSS":"GDELT";
        item.append(node("p",String(a.headline||"—")+
          " · المصدر: "+provider+
          " · "+(a.published_at_reported?"تاريخ نشر مبلغ عنه: "+time(a.published_at_reported):
              "وقت رصد المصدر: "+time(a.observed_at))+
          " · خبر تجميعي لا يثبت اتجاه السعر"));
        const link=node("a","اقرأ الخبر الأصلي ↗");
        link.href=safeNewsLink(a.url);link.rel="noopener noreferrer";
        link.target="_blank";item.append(link);news.append(item);
      }
      if(!included.length)news.append(node("p",
        "لا توجد أخبار قابلة للتحقق من عنوانها ورمزها في GDELT أو Yahoo Finance RSS حاليًا؛ هذا لا يعني عدم وجود أخبار أخرى."));
      const errors=newsContext?.source_errors||{};
      set("gdelt-source-status",newsContext?
        "آخر فحص "+time(newsContext.generated_at)+
        " · عناوين مرتبطة بأسهم "+n(included.length,0)+
        (errors.gdelt_attention?" · GDELT: "+String(errors.gdelt_attention):"")+
        (errors.yahoo_rss_attention?" · Yahoo RSS: "+String(errors.yahoo_rss_attention):"")+
        " · المصدران تجميعيان لا يؤكدان أثر الخبر":
        "لم تصل تغذية GDELT المنشورة؛ يظهر قسم SEC منفصلًا.");
    }
    const list=el("catalyst-official-list");
    if(list){
      list.replaceChildren();
      const seenLinks=new Set();
      const allowed=events.filter(e=>{const url=safeOfficial(e.source_url);if(!url||seenLinks.has(url))return false;seenLinks.add(url);return true;}).slice(0,16);
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
    const [results,secResults,newsResults]=await Promise.all([
      Promise.allSettled(URLS.map(fetchOne)),
      Promise.allSettled(SEC_URLS.map(fetchSecOne)),
      Promise.allSettled(GDELT_URLS.map(fetchNewsContext)),
    ]);

    const data=results.filter(x=>x.status==="fulfilled").map(x=>x.value);
    data.sort((a,b)=>Date.parse(b.source_generated_at)-Date.parse(a.source_generated_at));
    const secReports=secResults.filter(x=>x.status==="fulfilled").map(x=>x.value);
    secReports.sort((a,b)=>Date.parse(b.generated_at)-Date.parse(a.generated_at));
    const newsContexts=newsResults.filter(x=>x.status==="fulfilled").map(x=>x.value);
    newsContexts.sort((a,b)=>Date.parse(b.generated_at)-Date.parse(a.generated_at));
    if(data.length)render(data[0],secReports[0]||null,newsContexts[0]||null);
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
