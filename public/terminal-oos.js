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
    const tested=value.gate.ready===true&&value.status==="FAILED_RESEARCH_GATE";
    const summary=ready?
      "اكتملت شروط الحد الأدنى للبحث خارج العينة؛ النتائج لا تثبت ربح تداول فعليًا.":
      tested?"أُجري الاختبار خارج العينة ولم تثبت أفضلية كافية للإشارات الأقوى؛ لا توجد نسبة نجاح تنفيذية مثبتة.":
      "لم تكتمل شروط الاعتماد البحثي خارج العينة؛ لا توجد نسبة نجاح تنفيذية مثبتة.";
    // Measured OOS figures, shown only when the gate actually ran the test.
    const m=value.metrics,num=x=>typeof x==="number"&&Number.isFinite(x);
    const findings=(value.gate.ready===true&&num(m.baseline_auc)&&
      num(m.overall_oos?.positive_rate)&&num(m.adjusted_top_quartile?.positive_rate))?{
        auc:m.baseline_auc,
        basePositiveRate:m.overall_oos.positive_rate,
        topQuartilePositiveRate:m.adjusted_top_quartile.positive_rate,
        topQuartileMeanReturn:num(m.adjusted_top_quartile.mean_60m_return_pct)?
          m.adjusted_top_quartile.mean_60m_return_pct:null,
        sessionRobustness:num(m.session_robustness_rate)?m.session_robustness_rate:null
      }:null;
    const audit=value.coverage_gap_diagnostics;
    const missing=(audit?.coverage_deficit_known===true&&
      Number.isInteger(audit?.missing_60m_records)&&
      Number.isInteger(audit?.additional_records_needed_at_fixed_denominator)&&
      audit.missing_60m_records>=0&&
      audit.additional_records_needed_at_fixed_denominator>=0)?
      audit.additional_records_needed_at_fixed_denominator:null;
    const counts=audit?.missing_reason_counts_observed;
    const reasons=(counts&&
      ["NO_POST_SIGNAL_BARS","PENDING_OR_UNFINISHED","OTHER_MISSING_60M"].every(
        k=>Number.isInteger(counts[k])&&counts[k]>=0))?
      counts:null;
    return {ready,tested,findings,coverage,sessions,outSessions,outRecords,summary,
      additionalCoverageNeeded:missing,reasonCounts:reasons,
      reasonCountsExhaustive:audit?.missing_reason_count_is_exhaustive===true,
      claimedWinRate:null,livePromotionAllowed:false,
      sourceTimestampVerified:false};
  }
  return {evaluate};
});
