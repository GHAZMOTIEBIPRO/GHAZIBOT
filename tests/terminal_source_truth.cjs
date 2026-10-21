"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const s=require("../public/catalyst-source-truth.js");
const now=Date.parse("2026-10-21T23:00:00Z");
const market={
  status:"degraded",generated_at:"2026-10-21T22:50:00Z",
  coverage_diagnostics:{options_execution_quote_ready:false,
    options_trade_flow_ready:false,
    blocking_codes:["NO_EXECUTION_GRADE_OPTION_QUOTE","NO_VERIFIED_OPTION_TRADE_FLOW"]},
  source_status:{sec_fulltext:{available:false,checked_at:"2026-10-21T22:49:00Z",circuit_state:"open"}}
};
const engines={
  generated_at:"2026-10-21T22:50:00Z",
  decision_authority:false,contains_secrets:false,
  paths:{
    fast_discovery:{status:"HEALTHY",generated_at:"2026-10-21T22:48:00Z",maximum_age_minutes:45},
    stocks:{status:"STALE",generated_at:"2026-10-21T17:40:00Z",maximum_age_minutes:90},
    options:{status:"HEALTHY",generated_at:"2026-10-21T18:00:00Z",maximum_age_minutes:45}
  }
};
let r=s.assessment(market,engines,now);
assert.equal(r.marketReportAvailable,true);
assert.equal(r.marketStatus,"degraded");
assert.equal(r.quoteReady,false);
assert.equal(r.secVerified,false);
assert.equal(r.items.length,6);
assert.match(r.items[1].value,/لا يوجد إثبات/);
assert.match(r.items[2].note,/مغلقة مؤقتًا/);
assert.equal(r.items[3].status,"healthy");
assert.equal(r.items[4].status,"unavailable");
assert.equal(r.items[5].status,"unavailable");
assert.equal(r.decisionAuthority,false);
let good=s.assessment({...market,coverage_diagnostics:{
    options_execution_quote_ready:true,options_trade_flow_ready:true}},engines,now);
assert.equal(good.quoteReady,true);
assert.match(good.items[1].value,/V11/);
let future=s.assessment({...market,generated_at:"2026-10-21T23:03:00Z"},engines,now);
assert.equal(future.marketReportAvailable,false);
let old=s.assessment({...market,generated_at:"2026-10-21T18:03:00Z"},
  {...engines,generated_at:"2026-10-21T19:00:00Z"},now);
assert.equal(old.marketReportAvailable,false);
assert.equal(old.engineReportAvailable,false);
assert.equal(old.items[3].status,"unavailable");
assert.equal(s.time("2026-10-21T22:30:00",now),null);
assert.equal(s.time("bogus",now),null);
const html=fs.readFileSync(path.join(__dirname,"../public/catalyst-desk.html"),"utf8");
assert.ok(html.includes('id="desk-truth-grid"'));
assert.ok(html.includes('src="./catalyst-source-truth.js'));
console.log("source trust dashboard rejects stale/future/missing rights evidence");
