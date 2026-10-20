"use strict";
const assert=require("node:assert/strict");
const {modelLabLines}=require("../public/terminal-hub.js");

const lines=modelLabLines({models:{
  BASELINE_ALL_DAYS:{all:{target_hit_rate:0.21,breakeven_hit_rate:0.3846,mean_net_pct:-0.9,signals:40000},
    early:{mean_net_pct:-0.8},late:{mean_net_pct:-1.0}},
  GAP_CONTINUATION:{all:{target_hit_rate:0.33,breakeven_hit_rate:0.3846,mean_net_pct:-0.2,signals:900},
    early:{mean_net_pct:0.1},late:{mean_net_pct:-0.5},beats_baseline_both_halves_and_positive_late:false},
  CATALYST_FLOAT:{status:"NOT_TESTABLE",reason:"no point-in-time catalyst history"}}});
assert.equal(lines.length,3);
assert.match(lines[0],/^خط الأساس/);
assert.ok(!lines[0].includes("تفوق"));
assert.match(lines[1],/إصابة الهدف 33% \(تعادل 38\.5%\)/);
assert.match(lines[1],/لا تفوق مثبت/);
assert.match(lines[2],/غير قابل للاختبار/);
assert.deepEqual(modelLabLines(null),[]);
console.log("terminal model lab ok");
