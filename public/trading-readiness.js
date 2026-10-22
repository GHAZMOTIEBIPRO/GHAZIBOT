"use strict";
/* External, dated, evidence-only trading readiness. Never treats a 100-pt
   dashboard score or historical hit rate as a probability or trading signal. */
(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;
  if(root)root.GhaziTradingReadiness=api;
})(typeof window!=="undefined"?window:null,function(){
  const FEED="https://raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/bot-state/runtime/public/data/trading_readiness.json";
  const CHECKS={
    website_and_bot:"الموقع والبوت",
    independent_licensed_prices:"أسعار مستقلة مرخصة",
    market_operations:"صحة محركات السوق",
    options_execution_sources:"سعر وتنفيذ عقود الأوبشن",
    walk_forward_passed:"اختبار زمني خارج العينة",
    stock_edge_proven:"أفضلية قابلة للإثبات للأسهم",
    option_premium_outcomes_validated:"أداء عقود مؤهل ومتكرر"
  };
  const BLOCKERS={
    NO_LICENSED_INDEPENDENT_EXECUTION_PRICE:"لا توجد أسعار مستقلة مؤهلة وقابلة للتحقق.",
    NO_EXECUTION_GRADE_OPTION_CHAIN_AND_FLOW:"عروض العقود وتدفقها لم يتأهلا.",
    OUT_OF_SAMPLE_WALK_FORWARD_NOT_PASSED:"اختبار المشي الزمني لم يجتز شروطه.",
    NO_VERIFIED_STOCK_TRADABLE_EDGE:"لا توجد أفضلية تداول مثبتة للأسهم.",
    NO_QUALIFIED_OPTION_PREMIUM_OUTCOMES:"لا توجد عينة كافية من نتائج العقود المؤهلة.",
    MARKET_OPERATIONS_NOT_HEALTHY:"صحة مصادر السوق دون مستوى الجاهزية.",
    SITE_OR_BOT_ACCESS_NOT_FRESHLY_VERIFIED:"فحص وصول الموقع أو البوت مفقود أو قديم."
  };
  const fin=value=>typeof value==="number"&&Number.isFinite(value);
  function validate(value,now=Date.now()){
    if(!value||value.schema!=="ghazi.trading_readiness.v1"||
       !["NOT_TRADE_READY","RESEARCH_GATES_REPORTED_READY"].includes(value.status)||
       value.trade_recommendations_authorized!==false||
       value.automated_execution_allowed!==false||
       value.option_v11_execution_override!==false||
       !value.checks||typeof value.checks!=="object"||
       !Array.isArray(value.blockers)||value.blockers.length>16||
       !value.historical_evidence||typeof value.historical_evidence!=="object")
      return null;
    const t=Date.parse(value.generated_at);
    if(!Number.isFinite(t)||t>now+300000||now-t>36*3600000||t<now-36*3600000)return null;
    if(Object.keys(CHECKS).some(k=>typeof value.checks[k]!=="boolean"))return null;
    if(value.status==="RESEARCH_GATES_REPORTED_READY"&&
       (value.blockers.length>0||Object.keys(CHECKS).some(k=>value.checks[k]!==true)))return null;
    if(value.status==="NOT_TRADE_READY"&&value.blockers.length===0)return null;
    return value;
  }
  function assess(value,now=Date.now()){
    const report=validate(value,now);
    if(!report)return {
      ready:false,verified:false,title:"لا تتداول اعتمادًا على الرادار",
      reason:"تقرير الاعتمادية مفقود أو متأخر أو غير مطابق، لذلك لا توجد أهلية للتداول.",
      rows:Object.entries(CHECKS).map(([key,name])=>({key,name,pass:false})),
      blockers:["لا يوجد إثبات صالح للاعتماد حاليًا."],historical:null,generated:null
    };
    return {
      ready:false,verified:true,title:"غير مؤهل لاتخاذ قرارات تداول منفردة",
      reason:"هذه بوابة أدلة بحثية فقط. حتى إن تحققت بعض الشروط، يجب التحقق من كل عقد/سعر على حدة.",
      rows:Object.entries(CHECKS).map(([key,name])=>({
        key,name,pass:report.checks[key]===true
      })),
      blockers:report.blockers.map(x=>BLOCKERS[x]||"مانع أهليّة غير معروف"),
      historical:report.historical_evidence,
      generated:report.generated_at
    };
  }
  function render(view){
    const heading=document.getElementById("trust-heading");
    if(!heading)return;
    heading.textContent=view.title;
    document.getElementById("trust-reason").textContent=view.reason;
    document.getElementById("trust-stamp").textContent=view.generated?
      "وقت إنتاج التقرير: "+view.generated+" UTC":"لا يوجد تقرير تحقق حديث";
    const rows=document.getElementById("trust-checks");
    rows.replaceChildren();
    for(const item of view.rows){
      const li=document.createElement("li");
      const status=document.createElement("strong");
      status.textContent=item.pass?"متحقق بحثيًا":"غير متحقق";
      status.className=item.pass?"ok":"bad";
      li.append(document.createTextNode(item.name+" — "),status);
      rows.append(li);
    }
    const blockers=document.getElementById("trust-blockers");
    blockers.replaceChildren();
    for(const reason of view.blockers){
      const li=document.createElement("li");li.textContent=reason;blockers.append(li);
    }
    const h=view.historical||{};
    const pct=fin(h.target_t1_historical_hit_rate_pct)?
      h.target_t1_historical_hit_rate_pct.toFixed(2)+"%":"غير متوفر";
    const sample=Number.isInteger(h.target_t1_intraday_matured)?
      h.target_t1_intraday_matured:"—";
    const hits=Number.isInteger(h.target_t1_intraday_hits)?
      h.target_t1_intraday_hits:"—";
    document.getElementById("trust-t1").textContent=hits+" / "+sample+" · "+pct;
    document.getElementById("trust-t1-note").textContent=
      "تحقق هدف T1 وفق قياس تاريخي لشموع السهم نفسه؛ لا يعني ربح صفقة أو احتمال نجاح مستقبلي.";
    const win=document.getElementById("trust-stock");
    const tracked=Number.isInteger(h.stock_audit_records)?h.stock_audit_records:"—";
    const proof=Number.isInteger(h.individually_close_time_verified_records)?
      h.individually_close_time_verified_records:"—";
    win.textContent=proof+" حالات تحقق إغلاق فردي من "+tracked+" حالة مدونة";
    const options=document.getElementById("trust-options");
    options.textContent=Number.isInteger(h.qualified_option_closed_samples)?
      String(h.qualified_option_closed_samples)+" حالة مؤهلة مغلقة":"غير متوفر";
    const score=document.getElementById("trust-score");
    score.textContent=fin(h.research_data_strength_score)?
      h.research_data_strength_score.toFixed(0)+" / 100 · قوة أدلة فقط":"غير متاح";
    const stages=document.getElementById("trust-stages");
    stages.replaceChildren();
    for(const row of Array.isArray(h.stage_cost_model_expectancy)?
          h.stage_cost_model_expectancy:[]){
      if(!["PRESSURE_BUILDING","IGNITION","EXPLOSION"].includes(row.name))continue;
      const li=document.createElement("li");
      li.textContent=row.name+" · "+(fin(row.modelled_net_expectancy_pct)?
        row.modelled_net_expectancy_pct.toFixed(2)+"% صافي متوقع بنموذج تكاليف":
        "لا يوجد تقدير صالح")+" · ليست أرباحًا منفذة";
      stages.append(li);
    }
  }
  if(typeof document!=="undefined"){
    document.addEventListener("DOMContentLoaded",async()=>{
      let data=null;
      try{
        const response=await fetch(FEED,{cache:"no-store"});
        if(response.ok)data=await response.json();
      }catch(_error){ /* Fail closed and show the unavailable report. */ }
      render(assess(data));
    });
  }
  return {validate,assess,CHECKS,BLOCKERS,FEED};
});
