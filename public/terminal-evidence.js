"use strict";
/* Honest, zero-network, evidence-first chart checklist. Not trading advice. */
(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;
  if(root)root.GhaziEvidence=api;
})(typeof window!=="undefined"?window:null,function(){
  const finite=value=>typeof value==="number"&&Number.isFinite(value);
  const date=value=>{
    const ms=typeof value==="number"?value*1000:Date.parse(value||"");
    return Number.isFinite(ms)?ms:null;
  };
  function evaluate(input={}){
    const bars=Array.isArray(input.bars)?input.bars:[];
    const scenario=input.scenario||{};
    const frame=input.frame||{};
    const now=finite(input.now)?input.now:Date.now();
    const generated=date(input.generatedAt);
    const reportAge=generated===null?null:(now-generated)/3600000;
    const feedRecent=reportAge!==null&&reportAge>=-5/60&&reportAge<=24;
    const cached=frame.historical_cache_only===true;
    const current=frame.current_session_confirmed===true&&feedRecent&&!cached;
    const daily=input.timeframe==="1d";
    const sourceBar=bars.length?date(bars[bars.length-1]?.time):null;
    const sourceAge=sourceBar===null?null:Math.max(0,(now-sourceBar)/3600000);
    const enough=bars.length>=50;
    const matchedDaily=input.confluence&&daily&&
      input.confluence.research_only===true&&
      input.confluence.source_family==="yahoo"&&
      input.confluence.options_execution_eligible===false&&
      input.confluence.source_last_daily_bar===bars[bars.length-1]?.time;
    const rvol=matchedDaily&&finite(input.confluence.rvol_daily)&&
      input.confluence.rvol_daily>=0?input.confluence.rvol_daily:null;
    const news=input.newsAttention;
    const published=date(news?.latest_published_at);
    const matchedNews=news?.authority==="NEWS_SEARCH_ATTENTION_ONLY"&&
      news.official_catalyst_verified===false&&
      news.research_only===true&&
      published!==null&&(now-published)>=0&&(now-published)<=72*3600000;
    const hourly=scenario.hour_bias;
    const hourReady=hourly==="UP"||hourly==="DOWN"||hourly==="MIXED";
    const conflict=scenario.status==="CONFLICT";
    const historical=cached||!current||scenario.status==="HISTORICAL";
    const side=scenario.side==="CALL"||scenario.side==="PUT"?scenario.side:"WAIT";
    const watchable=enough&&!historical&&!conflict&&side!=="WAIT";
    const status=!enough?"UNAVAILABLE":historical?"HISTORICAL":
      conflict?"CONFLICT":!hourReady?"PARTIAL":
      watchable?"WATCH":"WAIT";
    const labels={
      UNAVAILABLE:"شموع غير كافية",HISTORICAL:"تاريخي / غير لحظي",
      CONFLICT:"تعارض فريمات",PARTIAL:"تأكيد الساعة غير مكتمل",
      WATCH:"سيناريو مراقبة فقط",WAIT:"انتظار توافق"
    };
    const checks=[
      {label:"الشموع والمصدر",state:enough?"ok":"unknown",
        detail:enough?bars.length+" شمعة مكتملة منشورة · مصدر بحثي":
          "يلزم 50 شمعة سليمة على الأقل"},
      {label:"حداثة الجلسة",state:current?"ok":"blocked",
        detail:cached?"بيانات محفوظة تاريخيًا — ليست سعرًا حاليًا":
          current?"شموع الجلسة متحققة · التقرير ضمن 24 ساعة":
          "لم تثبت جلسة حالية من الشموع ووقت التقرير"},
      {label:"توافق الفريمات",state:conflict?"blocked":hourReady?"ok":"unknown",
        detail:conflict?"تعارض واضح بين الاتجاه والساعة":
          hourReady?"اتجاه الساعة: "+hourly+" · تحقق من فريم الدخول":
          "فريم الساعة غير كافٍ؛ لا نفترض أنه متوافق"},
      {label:"حجم التداول",state:rvol===null?"unknown":rvol>=1.5?"ok":"neutral",
        detail:rvol===null?"لا يوجد RVOL موثق بنفس جلسة هذا الشارت":
          "RVOL يومي "+rvol.toFixed(2)+"× · بيانات Yahoo البحثية فقط"},
      {label:"المحفز الإخباري",state:"unknown",
        detail:matchedNews?"رُصد اسم الشركة في خبر غير رسمي؛ ليس محفزًا مثبتًا":
          "لم يتأكد محفز رسمي من بيانات هذا الشارت"}
    ];
    return {
      status,label:labels[status],checks,
      executable:false,optionContractVerified:false,probability:null,
      sourceAgeHours:sourceAge,reportAgeHours:reportAge,
      matchedDailyRvol:rvol,newsSearchAttention:!!matchedNews,
      summary:status==="WATCH"?
        "توجد قراءة اتجاه بحثية تستحق المراقبة؛ لا يوجد اعتماد لتنفيذ عقد أو ضمان للاستمرار.":
        status==="HISTORICAL"?
        "الشموع أو التقرير غير مثبتين كجلسة حالية؛ المستويات للاطلاع التاريخي فقط.":
        status==="CONFLICT"?
        "تعارض فريمات؛ لا تتعامل مع مستويات الرسم كإشارة دخول.":
        status==="PARTIAL"?
        "لم تكتمل أدلة فريم الساعة؛ أبقِ القراءة تحت المراجعة.":
        "لا توجد أدلة مكتملة تسمح بترقية القراءة إلى سيناريو مراقبة."
    };
  }
  return {evaluate};
});
