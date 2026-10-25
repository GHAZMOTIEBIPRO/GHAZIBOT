"use strict";
const assert=require("node:assert/strict");
const {sizeEvidence}=require("../public/terminal-hub.js");

const line=sizeEvidence({universe:"MARKET_CAP_UNVERIFIED",
  public_float_value:{usd:90e6,as_of:"2026-06-30",stale:false},
  sec_filer_status:{category:"Non-accelerated filer",smaller_reporting_company:true}});
assert.match(line,/^التصنيف السوقي غير متحقق/);
assert.match(line,/Public Float \(SEC، 2026-06-30\): 90\.0 مليون\$ — ليست قيمة سوقية/);
assert.match(line,/تصنيف الإفصاح لدى SEC: Non-accelerated filer/);
assert.doesNotMatch(line,/صغيرة/);
assert.match(sizeEvidence({universe:"KNOWN_LARGE_ISSUER_LIST"}),/قائمة مرجعية يدوية/);
assert.equal(sizeEvidence(null),"التصنيف السوقي غير متحقق");
console.log("terminal size evidence ok");
