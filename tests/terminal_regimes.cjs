"use strict";
const assert=require("node:assert/strict");
const {regimeLines}=require("../public/terminal-hub.js");

const report={generated_at:"2026-10-24T23:00:00Z",series:{
  treasury_10y_2y_bp:{available:true,label_ar:"فارق 10Y-2Y",unit:"bp",latest_value:31,last_date:"2026-10-23",observations:450,
    change_points:["2026-03-02","2026-08-14"],current_regime:{since:"2026-08-14",mean:35.2,previous_mean:12.4,shift:22.8}},
  cftc_ES_asset_manager_net:{available:true,unit:"contracts",latest_value:901377,last_date:"2026-10-20",observations:156,
    change_points:[],current_regime:{since:"2023-10-24",mean:850000,previous_mean:null,shift:null}},
  broken:{available:false,reason:"fewer than 52 observations"}}};
const lines=regimeLines(report);
assert.equal(lines.length,2);
assert.equal(lines[0].status,"نظام منذ 2026-08-14");
assert.match(lines[0].detail,/مقابل 12\.4 ن\.أ قبله \(تغير \+22\.8\)/);
assert.match(lines[0].detail,/انكسارات: 2026-03-02، 2026-08-14/);
assert.match(lines[1].detail,/لا انكسار مكتشف/);
assert.deepEqual(regimeLines(null),[]);
console.log("terminal regimes ok");
