"use strict";
/* GHAZI Source Truth: metadata-only monitoring. No proprietary quotes or
 * research signal authority; Date.now never stands in for quote/event time. */
(function(root){
  const BASE="https://raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/bot-state/runtime/public/data/";
  const URLS={market:BASE+"data-status.json",engines:BASE+"live_dashboard_status.json"};
  const VALID_STATES=new Set(["healthy","degraded","critical","unavailable"]);
  const ENGINES=["fast_discovery","stocks","options"];
  function time(raw,now){
    if(typeof raw!=="string"||!/(?:Z|[+-]\d{2}:\d{2})$/.test(raw))return null;
    const value=Date.parse(raw);
    return Number.isFinite(value)&&value<=now+300000?value:null;
  }
  function assessment(market,engines,now=Date.now()){
    const mt=time(market?.generated_at,now);
    const validMarket=market&&VALID_STATES.has(String(market.status||"").toLowerCase())&&
      mt!==null&&now-mt>=0&&now-mt<=120*60000&&market.coverage_diagnostics&&typeof market.coverage_diagnostics==="object";
    const marketStatus=validMarket?market.status.toLowerCase():"unavailable";
    const coverage=validMarket?market.coverage_diagnostics:{};
    const eAt=time(engines?.generated_at,now);
    const validEngines=!!(engines&&engines.decision_authority===false&&
      engines.contains_secrets===false&&eAt!==null&&now-eAt>=0&&now-eAt<=120*60000&&
      engines.paths&&typeof engines.paths==="object");
    const quoteReady=validMarket&&coverage.options_execution_quote_ready===true&&
      coverage.options_trade_flow_ready===true;
    const sec=validMarket?market.source_status?.sec_fulltext:null;
    const secObserved=time(sec?.checked_at,now);
    const secVerified=sec&&sec.available===true&&secObserved!==null&&now-secObserved>=0&&now-secObserved<=120*60000;
    const failureCodes=Array.isArray(coverage.blocking_codes)?coverage.blocking_codes
      .filter(s=>typeof s==="string").slice(0,5):[];
    const healthStatus={
      healthy:"مصادر التقرير: سليمة بحسب آخر فحص",
      degraded:"مصادر التقرير: متدهورة",
      critical:"مصادر التقرير: حرجة",
      unavailable:"لا يوجد تقرير مصدر حديث قابل للتحقق"
    }[marketStatus];
    const summary=[
      {key:"market",name:"جودة المصادر",value:healthStatus,
       note:validMarket?"تقرير نظام البيانات: "+market.generated_at:"غياب التقرير أو قدمه يمنع اعتبار السوق متاحًا.",
       status:marketStatus},
      {key:"options",name:"عقود الأوبشن",value:quoteReady?"وردت أهلية أسعار وتدفق، تحقق من كل عقد في V11":"لا يوجد إثبات متكامل لأهلية التنفيذ",
       note:validMarket?(failureCodes.join(" · ")||"لا توجد أسباب رفض إضافية في التقرير"):"بيانات جاهزية الخيارات غير متاحة.",
       status:quoteReady?"healthy":"unavailable"},
      {key:"sec",name:"بحث SEC الرسمي",value:secVerified?"آخر فحص SEC Full-Text متاح":"SEC Full-Text غير متحقق حاليًا",
       note:validMarket?(sec?.circuit_state==="open"?
         "دائرة الاستعلام مغلقة مؤقتًا بعد رفض المصدر؛ لا إعادة جلب قسريّة.":"وجود بدائل لا يعني تأكيد ملفات SEC الجديدة.") :
         "لا تقرير حديث عن SEC.",status:secVerified?"healthy":"unavailable"},
    ];
    for(const [key,label] of [["fast_discovery","الأسهم الصغيرة"],["stocks","تحليل الأسهم"],["options","محرك العقود"]]){
      const path=validEngines?engines.paths[key]:null;
      const ts=time(path?.generated_at,now);
      const age=ts===null?null:Math.max(0,Math.round((now-ts)/60000));
      const healthy=path?.status==="HEALTHY"&&age!==null&&ts<=now&&
        age<=Math.min(120,Number.isFinite(path.maximum_age_minutes)?path.maximum_age_minutes:90);
      summary.push({key,name:label,value:healthy?"تقرير تشغيل حديث":"لا يوجد دليل تشغيل حديث",
        note:validEngines?(age!==null?"وقت بيانات المحرك: "+path.generated_at+
          " · عمر البيانات "+age+" دقيقة":"وقت بيانات المحرك غير محدد"):
          "تقرير المحركات غائب أو قديم؛ لا تعتمد على الحالة القديمة.",
        status:healthy?"healthy":"unavailable"});
    }
    return {marketReportAvailable:!!validMarket,engineReportAvailable:validEngines,
      marketStatus,quoteReady:!!quoteReady,secVerified:!!secVerified,
      generatedAt:validMarket?market.generated_at:null,
      items:summary,decisionAuthority:false};
  }
  if(typeof module!=="undefined"&&module.exports)module.exports={assessment,time,URLS};
  if(typeof document==="undefined"||!root)return;
  const $=id=>document.getElementById(id);
  function item(tag,text,cls){const el=document.createElement(tag);el.textContent=text;if(cls)el.className=cls;return el;}
  function render(result){
    const box=$("desk-truth-grid");if(!box)return;
    box.replaceChildren();
    for(const data of result.items){
      const card=item("article","","truth-card");
      card.dataset.status=data.status;
      card.append(item("small",data.name),item("strong",data.value),item("p",data.note));
      box.append(card);
    }
    const status=$("desk-truth-status");
    if(status)status.textContent=result.marketReportAvailable?
      "تقرير المراقبة: "+new Date(result.generatedAt).toLocaleString("ar-SA",{timeZone:"Asia/Riyadh"})+
      " · ليس وقت عرض سعر":"حالة المصادر غير موثقة ببيانات حديثة";
  }
  async function read(url){
    const response=await fetch(url+"?v="+Date.now(),{cache:"no-store"});
    if(!response.ok)throw Error("health report unavailable");
    const content=await response.json();
    if(!content||typeof content!=="object"||Array.isArray(content))throw Error("invalid health report");
    return content;
  }
  async function refresh(){
    const [market,engines]=await Promise.allSettled([read(URLS.market),read(URLS.engines)]);
    render(assessment(market.status==="fulfilled"?market.value:null,
      engines.status==="fulfilled"?engines.value:null));
  }
  root.GhaziSourceTruth={refresh};
  document.addEventListener("DOMContentLoaded",()=>{
    const refreshButton=$("desk-truth-refresh");
    if(refreshButton)refreshButton.addEventListener("click",refresh);
    refresh();
  });
})(typeof window!=="undefined"?window:null);
