"use strict";
const assert=require("node:assert/strict");
const {optionsSummary}=require("../public/terminal-hub.js");

const view=optionsSummary({status:"OK",
  expected_move:{move_pct:3.0,expiry:"2026-10-23",range_low:194,range_high:206},
  atm_iv_term:[{expiry:"2026-10-23",atm_iv:0.31},{expiry:"2026-10-30",atm_iv:0.28}],
  skew_25d:{put_minus_call:0.08},put_call_volume_ratio:1.25,
  oi_concentration:{call:[{strike:210,oi:2000}],put:[{strike:190,oi:3000}]},
  liquid_contract_screen:{call:[{strike:200,expiry:"2026-10-30",delta:0.51,spread_pct:4.88,oi:500}],put:[]}});
assert.match(view.headline,/حركة متوقعة ±3% حتى 2026-10-23 \(194–206\)/);
assert.match(view.headline,/IV عند السعر 31%/);
assert.ok(view.details.some(x=>x.includes("أعلى OI بوت: 190")));
assert.ok(view.details.some(x=>x.startsWith("CALL 200 · 2026-10-30")));
assert.ok(view.details.every(x=>!/bid|ask|mid/i.test(x)));
assert.equal(optionsSummary({status:"DATA_UNAVAILABLE"}),null);
assert.equal(optionsSummary(null),null);
console.log("terminal options analytics ok");
