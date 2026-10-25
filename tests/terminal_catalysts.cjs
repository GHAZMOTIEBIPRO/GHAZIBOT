"use strict";
const assert=require("node:assert/strict");
const {catalystLines}=require("../public/terminal-hub.js");

const report={watchlist:[
  {symbol:"RVSP",highest_importance:"HIGH",latest_date:"2026-10-19",charter_or_reverse_split_review:true,
   sub10_confirmed:false,catalysts:[{kind:"CHARTER_OR_REVERSE_SPLIT_REVIEW",date:"2026-10-19",label:"8-K",
   source:"SEC EDGAR",source_url:"https://www.sec.gov/Archives/edgar/data/3/4/b.htm"}]},
  {symbol:"ABCD",highest_importance:"MEDIUM",latest_date:"2026-10-16",sub10_confirmed:true,
   catalysts:[{kind:"FDA_APPROVAL",date:"2026-10-16",source:"openFDA",source_url:"javascript:alert(1)"}]},
  {symbol:"<img>",highest_importance:"HIGH",catalysts:[]}]};
const lines=catalystLines(report);
assert.equal(lines.length,2);  // malformed symbol dropped
assert.equal(lines[0].tone,"DOWN");
assert.match(lines[0].price,/مرشح يحتاج تحققًا سعريًا/);
assert.match(lines[0].items[0].text,/تقسيم عكسي/);
assert.match(lines[0].items[0].url,/^https:\/\/www\.sec\.gov\//);
assert.match(lines[1].price,/تحت 10\$ بسعر حديث مسموح/);
assert.equal(lines[1].items[0].url,null);  // unsafe link dropped
assert.deepEqual(catalystLines(null),[]);
console.log("terminal catalysts ok");
