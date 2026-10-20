"use strict";
const assert=require("node:assert/strict");
const {rightsLines}=require("../public/terminal-hub.js");

const hub={source_rights:{available:true,checked_at:"2026-10-20",evidence_run:"39478127523",providers:{
  yahoo:{name:"Yahoo Finance",rights:{automated_access:"RESTRICTED",persistent_storage:"RESTRICTED",
    public_display_raw:"RESTRICTED",public_display_derived:"RESTRICTED"},summary_ar:"ممنوع الجمع الآلي"},
  openfda:{name:"openFDA",rights:{automated_access:"VERIFIED",persistent_storage:"VERIFIED",
    public_display_raw:"VERIFIED",public_display_derived:"VERIFIED"}},
  tradier:{name:"Tradier",rights:{}}}}};
const lines=rightsLines(hub);
const by=Object.fromEntries(lines.map(l=>[l.key,l]));
assert.equal(by.yahoo.tone,"DOWN");
assert.equal(by.yahoo.status,"لا حق مؤكد لاستخدامنا");
assert.match(by.yahoo.detail,/وصول آلي: مقيد/);
assert.equal(by.openfda.tone,"UP");
assert.match(by.openfda.status,/مسموح: وصول آلي/);
assert.match(by.tradier.detail,/وصول آلي: غير معروف/);
assert.equal(by.tradier.status,"لا حق مؤكد لاستخدامنا");
assert.deepEqual(rightsLines({}),[]);
console.log("terminal rights ok");
