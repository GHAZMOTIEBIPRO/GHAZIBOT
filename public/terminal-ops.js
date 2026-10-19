"use strict";
/* Engine health and per-feed freshness. Reports publication age only; never
   certifies prices, quotes or signal quality. */
(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;
  if(root)root.GhaziOps=api;
})(typeof window!=="undefined"?window:null,function(){
  const ENGINES={
    fast_discovery:"اكتشاف الانفجار السريع",
    stocks:"رادار الأسهم",
    options:"رادار عقود الأوبشن",
  };
  const STATUS={
    HEALTHY:["سليم","ok"],
    RESEARCH_ONLY:["يعمل · بحثي فقط","warn"],
    DEGRADED:["متدهور","warn"],
    STALE:["متأخر","bad"],
    CRITICAL:["معطل","bad"],
    FAILED:["فشل","bad"],
  };
  // Maximum expected publication age (minutes) during the regular session.
  const FEEDS={
    index:["المؤشرات الأمريكية",150],
    charts:["شارتات المؤشرات",150],
    watch:["شارتات الأسهم",180],
    brief:["ملخص قرار الأسهم",90],
    news:["الأخبار العامة",120],
    sec:["إفصاحات SEC",360],
    freeOptions:["بيانات OCC المجانية",1440],
    gamma:["تحقق Gamma",60],
    trust:["فحص المصادر",60],
    live:["حالة التشغيل",30],
    audit:["تدقيق النتائج",1440],
    structural:["رصد الأسهم الصغيرة",1440],
    explosion:["رادار الانفجار المبكر",45],
    classical:["الاتجاه الكلاسيكي",45],
    strength:["مؤشر قوة الأدلة",1440],
  };
  const parse=value=>{const t=Date.parse(value||"");return Number.isFinite(t)?t:null;};
  const ageMinutes=(value,now)=>{
    const t=parse(value);
    return t===null||t>now+5*60000?null:Math.max(0,Math.round((now-t)/60000));
  };
  function regularSession(now){
    const parts=Object.fromEntries(new Intl.DateTimeFormat("en-US",{
      timeZone:"America/New_York",weekday:"short",hour:"2-digit",minute:"2-digit",hourCycle:"h23"
    }).formatToParts(new Date(now)).map(p=>[p.type,p.value]));
    const minutes=Number(parts.hour)*60+Number(parts.minute);
    return !["Sat","Sun"].includes(parts.weekday)&&minutes>=570&&minutes<960;
  }
  // Accepts live_dashboard_status.json (single writer) or the legacy
  // data-status.json workflow_health block.
  function engineRows(runtime,now){
    const paths=runtime?.paths||runtime?.workflow_health?.paths;
    if(!paths||typeof paths!=="object")return [];
    return Object.keys(ENGINES).filter(key=>paths[key]).map(key=>{
      const path=paths[key];
      const [label,kind]=STATUS[String(path.status)]||["غير معروف","bad"];
      const count=Number.isInteger(path.candidate_count)?path.candidate_count:null;
      const max=Number.isFinite(path.maximum_age_minutes)?path.maximum_age_minutes:null;
      return {key,name:ENGINES[key],status:String(path.status||"UNKNOWN"),label,kind,
        generated_at:path.generated_at||null,age:ageMinutes(path.generated_at,now),
        max,candidates:count};
    });
  }
  function feedRows(stamps,now){
    return Object.keys(FEEDS).filter(key=>key in stamps).map(key=>{
      const [name,max]=FEEDS[key];
      const age=ageMinutes(stamps[key],now);
      const kind=age===null?"bad":age<=max?"ok":age<=max*3?"warn":"bad";
      const label=age===null?"غير متاح":age<=max?"حديث":age<=max*3?"متأخر":"قديم";
      return {key,name,age,max,kind,label,generated_at:stamps[key]||null};
    });
  }
  function summary(engines){
    const ok=engines.filter(row=>row.kind==="ok").length;
    return {ok,total:engines.length,
      kind:engines.length===0?"bad":ok===engines.length?"ok":engines.some(r=>r.kind==="bad")?"bad":"warn"};
  }
  return {engineRows,feedRows,summary,regularSession,ENGINES,FEEDS};
});
