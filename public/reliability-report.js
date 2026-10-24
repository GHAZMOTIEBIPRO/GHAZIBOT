"use strict";
(function(root){
  const URL="https://raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/bot-state/runtime/public/data/reliability_report.json";
  function describe(report,now=Date.now()){
    const raw=report?.generated_at;
    const stamp=typeof raw==="string"&&/(Z|[+-]\d{2}:\d{2})$/.test(raw)?Date.parse(raw):NaN;
    if(report?.schema!=="ghazi.reliability.v1"||report.decision_authority!==false||
       report.raw_market_data_published!==false||!Number.isFinite(stamp)||stamp>now||now-stamp>72*3600000)
      return ["تقرير الجودة غير متاح أو تجاوز ٧٢ ساعة؛ لا تُستنتج الثقة من غيابه."];
    const q=report.quality||{}, i=report.integrity||{};
    const number=n=>Number.isInteger(n)&&n>=0?String(n):"غير متاح";
    const status={VALID:"اجتازت السجلات فحص البنية",INVALID:"رُصدت بيانات تحتاج إصلاحًا",
      EMPTY:"لا توجد سجلات لفحصها",UNAVAILABLE:"تعذر تشغيل مدقق البيانات"}[q.status]||"حالة غير معروفة";
    return [status+" · عدد السجلات: "+number(q.records),
      "أخطاء الفحص: "+number(q.failure_count)+" · بصمات محفوظة: "+number(i.tracked),
      "سجلات تغيرت منذ أول مشاهدة: "+number(i.ever_changed),
      "حالة الإحصاء البحثي: "+({WITHHELD:"محجوب لعدم اكتمال فحص الجودة",INSUFFICIENT_EVIDENCE:"العينة غير كافية",
        RESEARCH_METRICS_ONLY:"إحصاء وصفي متاح داخليًا؛ لا يثبت الربحية",UNAVAILABLE:"غير متاح"}[(report.statistics_input_verified===true?report.statistics_status:"WITHHELD")]||"غير متاحة"),
      "آخر فحص: "+raw,
      "البصمة تبدأ عند أول مشاهدة في المدقق، ولا تثبت إرسال التنبيه. تكاليف الاختبار افتراضية؛ لا تمثل تنفيذًا فعليًا."];
  }
  if(typeof module!=="undefined"&&module.exports)module.exports={describe};
  if(typeof document==="undefined")return;
  async function refresh(){
    const target=document.getElementById("reliability-details");if(!target)return;
    let report=null;
    try{const res=await fetch(URL,{cache:"no-store",signal:AbortSignal.timeout(12000)});if(res.ok)report=await res.json();}catch(_error){}
    target.replaceChildren(...describe(report).map(text=>{const p=document.createElement("p");p.textContent=text;return p;}));
  }
  document.addEventListener("DOMContentLoaded",()=>{
    refresh();document.getElementById("reliability-refresh")?.addEventListener("click",refresh);
  });
})(typeof window!=="undefined"?window:null);
