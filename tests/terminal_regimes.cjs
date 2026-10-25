"use strict";
const assert=require("node:assert/strict");
const {regimeLines}=require("../public/terminal-hub.js");

const report={generated_at:"2026-10-25T07:30:00Z",series:{
  treasury_10y_2y_bp:{available:true,label_ar:"فارق 10Y-2Y",unit:"bp",frequency:"daily",latest_value:31,last_date:"2026-10-23",
    observations:453,breaks:[{date:"2026-05-22",detectable_from:"2026-06-26",hindsight_only:false}],
    current_regime:{since:"2026-05-22",mean_change:-0.35,previous_mean_change:0.12}},
  cftc_ES_asset_manager_net:{available:true,unit:"contracts",frequency:"weekly",latest_value:901377,last_date:"2026-10-20",
    observations:156,breaks:[],current_regime:{since:"2023-11-07",mean_change:310,previous_mean_change:null}},
  broken:{available:false,reason:"fewer than 52 observations"}}};
const lines=regimeLines(report);
assert.equal(lines.length,2);
assert.equal(lines[0].status,"نظام منذ 2026-05-22");
assert.match(lines[0].detail,/متوسط التغير لكل جلسة -0\.35 ن\.أ مقابل 0\.12 ن\.أ قبله/);
assert.match(lines[0].detail,/2026-05-22 \(قابل للرصد 2026-06-26\)/);
assert.equal(lines[1].status,"لا تغيّر انجراف مكتشف");
assert.match(lines[1].detail,/لكل أسبوع/);
assert.deepEqual(regimeLines(null),[]);
console.log("terminal regimes ok");
