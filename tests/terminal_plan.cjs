"use strict";
const assert=require("node:assert/strict");
const {planLines}=require("../public/terminal-hub.js");

const sheet={generated_at:"2026-10-25T12:00:00Z",session:{today:null,last_closed_session:"2026-10-23",
  next_session:{date:"2026-10-26",open_new_york:"09:30",close_new_york:"16:00",open_riyadh:"16:30",close_riyadh:"23:00",early_close:false}},
  frames:{weekly:{public:"UNAVAILABLE",private_owner:"UNAVAILABLE",reason:"no permitted public price source"},
    daily:{public:"UNAVAILABLE",private_owner:"AVAILABLE",reason:"Alpaca internal use only"}},
  catalysts:[{symbol:"GSK",kind:"FDA_APPROVAL",date:"2026-10-20",score:60.8,risk_flags:[]}],
  macro:{curve_date:"2026-10-23",spreads_bp:{"10Y_2Y":31},yields_pct:{"10Y":5},regime_series_with_breaks:2,regime_series:12},
  private_mode:{enabled:true}};
const l=planLines(sheet);
assert.match(l.session,/لا جلسة اليوم · الجلسة القادمة 2026-10-26 09:30 نيويورك \(16:30 الرياض\)/);
assert.deepEqual(l.frames,["أسبوعي: غير متاح","يومي: خاص بالمالك فقط"]);
assert.match(l.cats[0],/GSK · موافقة FDA · 2026-10-20 · أولوية 60.8/);
assert.match(l.macro,/فرق 10Y−2Y 31 ن\.أ/);
assert.match(l.private,/لا يُنشر/);
const early=planLines({...sheet,session:{...sheet.session,today:{date:"2026-11-27",open_new_york:"09:30",close_new_york:"13:00",
  open_riyadh:"17:30",close_riyadh:"21:00",early_close:true}}});
assert.match(early.session,/إغلاق مبكر/);
assert.equal(planLines(null),null);
console.log("terminal plan ok");
