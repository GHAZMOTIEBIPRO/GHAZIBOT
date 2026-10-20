"use strict";
const assert=require("node:assert/strict");
const {macroLines}=require("../public/terminal-hub.js");

const report={
  cftc_index_futures:{
    ES:{available:true,label_ar:"عقود E-mini S&P 500",positions_as_of:"2026-10-13",categories:{
      leveraged_funds:{net:-120000,weekly_change:5000,cot_index_3y:8,extreme:"LOW"},
      asset_manager:{net:900000,weekly_change:-2000,cot_index_3y:55,extreme:null},
      dealer:{available:false,reason:"missing"}}},
    VX:{available:false,reason:"no CFTC rows for this contract code"}},
  treasury_curve:{available:true,curve_date:"2026-10-16",yields_pct:{"3M":4,"2Y":3.6,"10Y":4.1,"30Y":4.6},
    spreads_bp:{"10Y_2Y":50,"10Y_3M":10},inverted:{"10Y_2Y":false,"10Y_3M":false},
    change_bp:{"10Y":{"5_sessions":15}}}};
const out=macroLines(report);
assert.equal(out.cot.length,2);
const es=out.cot[0];
assert.match(es.status,/2026-10-13/);
assert.match(es.detail,/-120,000/);
assert.match(es.detail,/أدنى نطاقه/);
assert.match(es.detail,/ليس توقيت انعكاس/);
assert.doesNotMatch(es.detail,/المتعاملون/);
assert.equal(out.cot[1].status,"غير متاح");
assert.match(out.curve.detail,/10Y-2Y 50/);
assert.match(out.curve.detail,/\+15/);
assert.equal(out.curve.tone,"UP");
assert.deepEqual(macroLines(null),{cot:[],curve:null});
console.log("terminal macro ok");
