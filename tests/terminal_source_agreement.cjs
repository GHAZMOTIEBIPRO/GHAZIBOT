"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const {evaluate}=require("../public/terminal-source-agreement.js");
const report={
  schema:"ghazi.source_consensus_status.v1",
  research_only:true,
  quote_execution_eligible:false,
  independent_price_comparison:"NOT_VERIFIED",
  concordance_ratio:null,
  independent_confirmations:0,
  source_price_families:["yahoo"],
  source_charts_count:20,
  massive_market_data_published:false
};
const result=evaluate(report);
assert.equal(result.status,"غير مثبت");
assert.equal(result.families,1);
assert.equal(result.decisionAuthority,false);
assert.equal(evaluate({...report,source_price_families:["yahoo","yahooquery"]}),null);
assert.equal(evaluate({...report,independent_confirmations:2}),null);
assert.equal(evaluate({...report,concordance_ratio:1}),null);
assert.equal(evaluate({...report,massive_market_data_published:true}),null);
const html=fs.readFileSync("public/index.html","utf8");
const js=fs.readFileSync("public/terminal-hub.js","utf8");
assert.ok(html.includes('id="terminal-source-agreement-status"'));
assert.ok(html.indexOf("terminal-source-agreement.js")<html.indexOf("terminal-hub.js"));
assert.ok(js.includes("GhaziSourceAgreement.evaluate"));
assert.ok(js.includes("source_agreement.json"));
console.log("One-source agreement safeguards: PASS");
