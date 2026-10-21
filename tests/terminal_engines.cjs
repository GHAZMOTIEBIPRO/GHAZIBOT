"use strict";
const assert=require("node:assert/strict");
const {engineLines}=require("../public/terminal-hub.js");

const hub={source_rights:{engines:{
  PRICE:{status:"INTERNAL_ONLY_WITH_KEY",public_sources:[],internal_only_sources:["twelve_data"],
    providers:{twelve_data:"INTERNAL_ONLY",yahoo:"BLOCKED",tradingview_widgets:"DISPLAY_WIDGET_ONLY"}},
  MACRO:{status:"PUBLIC_SOURCE_AVAILABLE",public_sources:["cftc","treasury_fiscaldata"],internal_only_sources:[],
    providers:{cftc:"PUBLIC",fred:"UNKNOWN"}},
  OPTIONS:{status:"NO_PERMITTED_SOURCE",public_sources:[],internal_only_sources:[],providers:{occ:"BLOCKED"}},
  BOGUS:{status:"PUBLIC_SOURCE_AVAILABLE"}}}};
const lines=engineLines(hub);
assert.equal(lines.length,3);  // unknown engine names are not shown
assert.equal(lines[0].title,"محرك الأسعار");
assert.match(lines[0].status,/داخلي فقط/);
assert.match(lines[0].detail,/داخلي فقط: twelve_data/);
assert.match(lines[0].detail,/محجوب: yahoo/);
assert.equal(lines[1].tone,"UP");
assert.equal(lines[2].tone,"DOWN");
assert.deepEqual(engineLines(null),[]);
console.log("terminal engines ok");
