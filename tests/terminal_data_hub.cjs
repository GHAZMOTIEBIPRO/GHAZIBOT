"use strict";
const assert=require("node:assert/strict");
const {hubLines}=require("../public/terminal-hub.js");

const lines=hubLines({datasets:[
  {file:"liquidity_map.json",title_ar:"الحجم والسيولة",freshness:"FRESH",validation:"PASS",
   source:"مشتق",license_class:"DERIVED_PUBLIC",age_minutes:90,cadence_min:60,limitations:"استنتاج"},
  {file:"index_radar.json",title_ar:"رادار المؤشرات",freshness:"STALE",validation:"FAIL",
   source:"Yahoo (yfinance)",license_class:"FALLBACK_LABELLED",age_minutes:600,cadence_min:30,limitations:"غير رسمي"},
  {file:"options_analytics.json",title_ar:"تحليلات العقود",freshness:"MISSING",validation:"MISSING",
   source:"Cboe delayed",license_class:"DERIVED_PUBLIC",age_minutes:null,cadence_min:30}]});
assert.equal(lines.length,3);
assert.equal(lines[0].tone,"UP");
assert.equal(lines[0].status,"حديث");
assert.match(lines[0].detail,/العمر: 1\.5 ساعة/);
assert.equal(lines[1].tone,"DOWN");
assert.equal(lines[1].status,"قديم · فشل التحقق");
assert.match(lines[1].detail,/مصدر احتياطي غير مرخص للأتمتة/);
assert.equal(lines[2].status,"غير منشور");
assert.equal(lines[2].tone,null);
assert.deepEqual(hubLines(null),[]);
// The directive state wins over the freshness label when the hub provides it.
const [blocked,delayed]=hubLines({datasets:[
  {file:"liquidity_map.json",freshness:"FRESH",validation:"PASS",data_state:"LICENSE_BLOCKED",data_state_ar:"محجوب حتى الترخيص"},
  {file:"fda_events.json",freshness:"FRESH",validation:"PASS",data_state:"DELAYED",data_state_ar:"رسمي منشور بتأخر معروف"}]});
assert.equal(blocked.status,"محجوب حتى الترخيص (LICENSE_BLOCKED)");
assert.equal(blocked.tone,"DOWN");
assert.equal(delayed.tone,"UP");
console.log("terminal data hub ok");
