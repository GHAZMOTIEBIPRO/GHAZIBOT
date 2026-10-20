"use strict";
const assert=require("node:assert/strict");
const {liquidityView}=require("../public/terminal-hub.js");

const now=Date.parse("2026-10-20T12:00:00Z");
const row={status:"OK",session_date:"2026-10-19",last_bar_start:"2026-10-19T15:45:00-04:00",
  volume:{rvol:1.62,state:"HIGH"},session_vwap:10.2,vwap_position:"BELOW",
  profile_session:{poc:10.13,vah:10.4,val:9.9},opening_range:{high:10.5,low:9.95,status:"INSIDE"},
  prior_day:{high:10.6,low:9.8,close:10.1},breakout:"FAILED_BREAKOUT",
  sweep_proxy:"ABOVE_PRIOR_HIGH_REJECTED",gap_pct:-1.25,
  reading_ar:["الحجم مرتفع (RVOL 1.62) مقارنة بنفس الوقت في الجلسات السابقة."]};
const map={schema:"ghazi.liquidity_map.v1",order_book_available:false,
  generated_at:"2026-10-20T03:52:47Z",symbols:{RGC:row}};

const view=liquidityView(map,"RGC",now);
assert.equal(view.status,"جلسة 2026-10-19");
const byLabel=Object.fromEntries(view.metrics);
assert.equal(byLabel["الحجم النسبي (نفس الوقت)"],"مرتفع · RVOL 1.62");
assert.match(byLabel["VWAP الجلسة (تقريبي)"],/تحت/);
assert.equal(byLabel["POC / VAH / VAL (تقدير)"],"10.13 / 10.4 / 9.9");
assert.equal(byLabel["الاختراق"],"اختراق فاشل لقمة الأمس");
assert.equal(byLabel["سحب سيولة (استنتاج سعري)"],"تجاوز قمة الأمس ثم ارتداد");
assert.equal(byLabel["فجوة الافتتاح"],"-1.25%");
assert.match(view.note,/RVOL 1.62/);

// Missing RVOL sample stays missing; never shown as a number.
const thin=liquidityView({...map,symbols:{RGC:{...row,volume:null}}},"RGC",now);
assert.equal(Object.fromEntries(thin.metrics)["الحجم النسبي (نفس الوقت)"],"عينة غير كافية");

// Stale file is labelled, not presented as current.
const old=liquidityView(map,"RGC",now+48*3600000);
assert.match(old.status,/^قديمة/);
assert.match(old.note,/أقدم من 36 ساعة/);

// Uncovered symbol and insufficient bars fail closed with no metrics.
assert.equal(liquidityView(map,"AAPL",now).metrics.length,0);
assert.equal(liquidityView(null,"RGC",now).metrics.length,0);
assert.equal(liquidityView({...map,symbols:{RGC:{status:"INSUFFICIENT_BARS"}}},"RGC",now).metrics.length,0);
console.log("terminal liquidity view ok");
