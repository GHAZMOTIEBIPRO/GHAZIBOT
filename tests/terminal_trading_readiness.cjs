"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const {assess,validate,CHECKS}=require("../public/trading-readiness.js");
const now=Date.parse("2026-10-22T08:00:00Z");
function base(){
  return {
    schema:"ghazi.trading_readiness.v1",generated_at:new Date(now).toISOString(),
    status:"NOT_TRADE_READY",trade_recommendations_authorized:false,
    automated_execution_allowed:false,option_v11_execution_override:false,
    checks:Object.fromEntries(Object.keys(CHECKS).map(k=>[k,false])),
    blockers:["NO_QUALIFIED_OPTION_PREMIUM_OUTCOMES"],
    historical_evidence:{target_t1_intraday_matured:412,
      target_t1_intraday_hits:8,target_t1_historical_hit_rate_pct:1.94,
      qualified_option_closed_samples:0,stock_audit_records:714}
  };
}
assert.equal(validate(base(),now)?.status,"NOT_TRADE_READY");
const v=assess(base(),now);
assert.equal(v.ready,false);
assert.equal(v.verified,true);
assert.equal(v.historical.target_t1_intraday_hits,8);
assert.equal(v.rows.length,7);
assert.match(v.blockers[0],/عينة/);
assert.equal(assess(null,now).verified,false);
assert.equal(assess(base(),now+37*3600000).verified,false);
let invalid=base();invalid.trade_recommendations_authorized=true;
assert.equal(validate(invalid,now),null);
invalid=base();invalid.option_v11_execution_override=true;
assert.equal(validate(invalid,now),null);
invalid=base();invalid.generated_at=new Date(now+10*60000).toISOString();
assert.equal(validate(invalid,now),null);
invalid=base();invalid.status="RESEARCH_GATES_REPORTED_READY";
assert.equal(validate(invalid,now),null);
invalid=base();invalid.checks.website_and_bot="yes";
assert.equal(validate(invalid,now),null);
invalid=base();invalid.blockers=[];
assert.equal(validate(invalid,now),null);
const page=fs.readFileSync(require("node:path").join(__dirname,"../public/trading-readiness.html"),"utf8");
assert.match(page,/id="trust-heading"/);
assert.match(page,/id="trust-stages"/);
assert.match(page,/id="trust-t1"/);
assert.match(page,/trading-readiness\.js/);
assert.ok(!page.includes("100% success"));
console.log("Trading-readiness UI: fail-closed, dated and no execution/probability upgrade.");
