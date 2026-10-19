"use strict";
/* Source-labelled research readout. No win rate or live-trade promotion. */
(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;
  if(root)root.GhaziOOS=api;
})(typeof window!=="undefined"?window:null,function(){
  function evaluate(value){
    if(!value||value.mode!=="EXPANDING_SESSION_WALK_FORWARD"||
        value.decision_authority!==false||
        value.live_promotion_allowed!==false||
        value.data_policy?.random_split_allowed!==false||
        value.data_policy?.future_session_training_allowed!==false||
        typeof value.gate!=="object"||value.gate===null||
        typeof value.metrics!=="object"||value.metrics===null)
      return null;
    const coverage=value.gate.coverage_60m_pct;
    const sessions=value.gate.independent_60m_sessions;
    const outSessions=value.metrics.oos_sessions;
    const outRecords=value.metrics.oos_records;
    if(![coverage,sessions,outSessions,outRecords].every(
      n=>typeof n==="number"&&Number.isFinite(n)&&n>=0
    )||coverage>100||![sessions,outSessions,outRecords].every(Number.isInteger))
      return null;
    const ready=value.status!=="NOT_READY"&&
      value.gate.ready===true&&value.research_passed===true&&
      coverage>=90&&sessions>=10&&outSessions>=4&&outRecords>=40;
    const summary=ready?
      "اكتملت شروط الحد الأدنى للبحث خارج العينة؛ النتائج لا تثبت ربح تداول فعليًا.":
      "لم تكتمل شروط الاعتماد البحثي خارج العينة؛ لا توجد نسبة نجاح تنفيذية مثبتة.";
    return {ready,coverage,sessions,outSessions,outRecords,summary,
      claimedWinRate:null,livePromotionAllowed:false,
      sourceTimestampVerified:false};
  }
  return {evaluate};
});
