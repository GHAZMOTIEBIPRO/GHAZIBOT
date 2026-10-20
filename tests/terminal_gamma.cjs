"use strict";
const assert=require("node:assert/strict");
const {gammaView}=require("../public/terminal-hub.js");

const data={generated_at:"2026-10-20T04:00:10Z",independent_numerical_gex_sources:1,metrics:{},
  integrated_engines:{
    ghazi_gex_multi:{available:true,spot:7690.73,gamma_flip:7760.8,call_wall:7800,put_wall:7700,
      gamma_regime:"negative",gci:0.056,expirations_used:4,front_expiry:"2026-10-20",
      provenance:{levels:"MODEL_ESTIMATED"}},
    interpretation:{distance_pct:{gamma_flip:0.91,call_wall:1.42,put_wall:0.12},
      hedging_pressure_bn_per_1pct:28.9,reading_ar:["السعر تحت نقطة الانقلاب التقديرية"]},
    level_validation:{sessions_tested:1,minimum_sessions_for_verdict:20,verdict:"INSUFFICIENT_SAMPLE"}
  }};
const view=gammaView(data,"SPX");
const m=Object.fromEntries(view.metrics);
assert.equal(view.status,"نموذج تقديري · SHADOW");
assert.equal(m["Call Wall (نموذج)"],"7,800 (+1.42%)");
assert.equal(m["نظام الجاما (نموذج)"],"سالب · قد يضخم الحركة");
assert.equal(m["ضغط التحوط لكل 1% (نموذج)"],"28.9 مليار $");
assert.match(m["SPX (مُقاس · Cboe مؤخر)"],/7,690\.73/);
assert.match(view.note,/1 جلسة من 20 مطلوبة؛ لا حكم بعد/);
assert.match(view.note,/مُقاس: السعر وIV/);
// Tested case reports the naive-band comparison.
const tested=gammaView({...data,integrated_engines:{...data.integrated_engines,
  level_validation:{sessions_tested:25,minimum_sessions_for_verdict:20,verdict:"NO_EDGE_OVER_BASELINE",
    walls_contained_range_rate:0.4,same_width_centred_band_rate:0.44}}},"SPX");
assert.match(tested.note,/40% مقابل نطاق بنفس العرض حول السعر 44%/);
assert.match(tested.note,/لا أفضلية على الخط الأساسي/);
// No engine: falls back to external medians, never invents values.
const none=gammaView({generated_at:"2026-10-20T04:00:10Z",metrics:{}},"SPY");
assert.equal(Object.fromEntries(none.metrics)["Gamma Flip"],"غير متاح");
assert.match(none.note,/مستويات SPX وليست قيم خيارات SPY/);
console.log("terminal gamma view ok");
