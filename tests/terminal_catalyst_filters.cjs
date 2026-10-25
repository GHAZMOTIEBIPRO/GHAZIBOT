"use strict";
const assert=require("node:assert/strict");
const {catalystLines}=require("../public/terminal-hub.js");

const report={watchlist:[
  {symbol:"ADMN",latest_date:"2026-10-24",catalyst_score:40,catalysts:[{kind:"TRIAL_REGISTRY_UPDATE",impact:"ADMINISTRATIVE",date:"2026-10-24"}]},
  {symbol:"APPR",latest_date:"2026-10-20",catalyst_score:70,catalysts:[{kind:"FDA_APPROVAL",impact:"REGULATORY_DECISION",date:"2026-10-20"}]},
  {symbol:"RISK",latest_date:"2026-10-22",catalyst_score:30,catalysts:[{kind:"DILUTION_RISK",impact:"RISK",date:"2026-10-22"},
    {kind:"TRIAL_RESULTS_POSTED",impact:"RESULTS_POSTED_DIRECTION_UNKNOWN",date:"2026-10-21"}]}]};
const sym=lines=>lines.map(l=>l.symbol);
assert.deepEqual(sym(catalystLines(report)),["ADMN","APPR","RISK"]);
// administrative-only entries drop out; a mixed entry stays
assert.deepEqual(sym(catalystLines(report,20,{filter:"no_admin"})),["APPR","RISK"]);
assert.deepEqual(sym(catalystLines(report,20,{filter:"decisions"})),["APPR"]);
assert.deepEqual(sym(catalystLines(report,20,{filter:"risks"})),["RISK"]);
assert.deepEqual(sym(catalystLines(report,20,{filter:"results"})),["RISK"]);
assert.deepEqual(sym(catalystLines(report,20,{sort:"date"})),["ADMN","RISK","APPR"]);
// the reason shown matches the filter, and never claims a direction
const why=catalystLines(report,20,{filter:"results"})[0].why;
assert.match(why,/سبب الظهور: نتائج منشورة بالسجل \(الاتجاه غير مقيم\) بتاريخ 2026-10-21/);
assert.match(why,/ليس توقعًا لاتجاه السعر/);
console.log("terminal catalyst filters ok");
