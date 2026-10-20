"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const {evaluate}=require("../public/terminal-oos.js");
const pending={
  mode:"EXPANDING_SESSION_WALK_FORWARD",decision_authority:false,
  live_promotion_allowed:false,
  data_policy:{random_split_allowed:false,future_session_training_allowed:false},
  status:"NOT_READY",research_passed:false,
  gate:{coverage_60m_pct:64.15,independent_60m_sessions:26,ready:false},
  metrics:{oos_sessions:0,oos_records:0}
};
const one=evaluate(pending);
assert.equal(one.ready,false);
assert.equal(one.coverage,64.15);
assert.equal(one.outRecords,0);
assert.equal(one.claimedWinRate,null);
assert.equal(one.livePromotionAllowed,false);
assert.equal(one.sourceTimestampVerified,false);
assert.match(one.summary,/لم تكتمل/);
for(const value of [
  {...pending,live_promotion_allowed:true},
  {...pending,decision_authority:true},
  {...pending,data_policy:{...pending.data_policy,random_split_allowed:true}},
  {...pending,gate:{...pending.gate,coverage_60m_pct:130}},
  {...pending,metrics:{...pending.metrics,oos_records:-1}},
  {},
  null
])assert.equal(evaluate(value),null);
const enough={...pending,status:"SHADOW_RESEARCH",research_passed:true,
  gate:{coverage_60m_pct:94,independent_60m_sessions:11,ready:true},
  metrics:{oos_sessions:6,oos_records:57}};
const ready=evaluate(enough);
assert.equal(ready.ready,true);
assert.equal(ready.claimedWinRate,null);
assert.equal(ready.livePromotionAllowed,false);
assert.equal(evaluate({...enough,gate:{...enough.gate,coverage_60m_pct:89.99}}).ready,false);
assert.equal(evaluate({...enough,metrics:{...enough.metrics,oos_records:39}}).ready,false);
const html=fs.readFileSync("public/index.html","utf8");
const js=fs.readFileSync("public/terminal-hub.js","utf8");
assert.ok(html.includes('id="terminal-oos-status"'));
assert.ok(html.indexOf("terminal-oos.js")<html.indexOf("terminal-hub.js"));
assert.ok(js.includes("GhaziOOS.evaluate"));
assert.ok(js.includes("sourceTimestampVerified"));
console.log("OOS readiness disclosure: PASS");

const reasons=evaluate({...pending,coverage_gap_diagnostics:{
  coverage_deficit_known:true,
  missing_60m_records:247,
  additional_records_needed_at_fixed_denominator:179,
  missing_reason_counts_observed:{
    NO_POST_SIGNAL_BARS:55,
    PENDING_OR_UNFINISHED:130,
    OTHER_MISSING_60M:62
  },
  missing_reason_count_is_exhaustive:true
}});
assert.equal(reasons.additionalCoverageNeeded,179);
assert.equal(reasons.reasonCounts.NO_POST_SIGNAL_BARS,55);
assert.equal(reasons.ready,false);
// Gate ran the OOS test and it failed: show the measured figures, never "ready".
const failed=evaluate({...pending,status:"FAILED_RESEARCH_GATE",research_passed:false,
  gate:{coverage_60m_pct:98.44,independent_60m_sessions:26,ready:true},
  metrics:{oos_sessions:18,oos_records:123,baseline_auc:0.6038,
    overall_oos:{n:123,positive_rate:0.3252},
    adjusted_top_quartile:{n:39,positive_rate:0.3333,mean_60m_return_pct:-0.5169},
    session_robustness_rate:0.7222}});
assert.equal(failed.ready,false);
assert.equal(failed.tested,true);
assert.match(failed.summary,/ولم تثبت أفضلية/);
assert.equal(failed.findings.auc,0.6038);
assert.equal(failed.findings.topQuartileMeanReturn,-0.5169);
assert.equal(failed.claimedWinRate,null);
assert.equal(one.findings,null);
