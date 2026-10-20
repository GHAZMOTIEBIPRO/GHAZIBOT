"use strict";
const assert=require("node:assert/strict");
const {stageQualityLines}=require("../public/terminal-hub.js");

const lines=stageQualityLines({stages:{
  PRESSURE_BUILDING:{decisive:306,precision_direction:0.3595,breakeven_hit_rate:0.3846,
    expectancy_net_pct:-1.252,big_move_any_direction_rate:0.5373,verdict_sample_sufficient:true},
  IGNITION:{decisive:20,precision_direction:0.3,breakeven_hit_rate:0.375,
    expectancy_net_pct:-2.385,big_move_any_direction_rate:0.5862,verdict_sample_sufficient:false},
  EXPLOSION:{decisive:0}
}});
assert.equal(lines.length,3);
assert.match(lines[0],/إصابة الاتجاه 35\.9% مقابل تعادل 38\.5%/);
assert.match(lines[0],/-1\.25%/);
assert.match(lines[0],/أقل من نقطة التعادل/);
assert.match(lines[1],/\(غير كافية\)/);
assert.match(lines[2],/لا توجد نتائج مكتملة/);
assert.deepEqual(stageQualityLines(null),[]);
console.log("terminal stage quality ok");
