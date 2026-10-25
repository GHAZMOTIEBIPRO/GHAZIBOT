"use strict";
const assert=require("node:assert/strict");
const {engineStateLines}=require("../public/terminal-hub.js");

const report={generated_at:"2026-10-25T08:00:00Z",engines:{
  fast_explosion:{label_ar:"رادار الانفجار السريع",verdict_ar:"متوقف لغياب مصدر مؤهل",run:"OK",source:"BLOCKED_BY_TERMS",
    data:"STALE",analysis:"NOT_COMPUTED",alerts:"NO_ALERT_PATH",closed_gates:["nasdaq_web"],rows:null},
  fda:{label_ar:"أحداث FDA",verdict_ar:"يعمل",run:"OK",source:"AVAILABLE",data:"FRESH",analysis:"COMPUTED",
    alerts:"DELIVERED 2026-10-23T17:56:14+00:00",closed_gates:[],rows:7}}};
const [fast,fda]=engineStateLines(report);
// A green run must not hide a closed source.
assert.equal(fast.status,"متوقف لغياب مصدر مؤهل");
assert.equal(fast.tone,"DOWN");
assert.match(fast.detail,/التشغيل: سليم · المصدر: محجوب حسب الشروط \(nasdaq_web\) · البيانات: قديمة/);
assert.match(fast.detail,/التحليل: غير محسوب · التنبيه: لا مسار تنبيه/);
assert.equal(fda.tone,"UP");
assert.match(fda.detail,/البيانات: حديثة \(7 صف\)/);
assert.match(fda.detail,/التنبيه: آخر تسليم/);
assert.deepEqual(engineStateLines(null),[]);
console.log("terminal engine states ok");
