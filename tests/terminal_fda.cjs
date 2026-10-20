"use strict";
const assert=require("node:assert/strict");
const {fdaLines}=require("../public/terminal-hub.js");

const report={approvals:[
  {event_type:"APPROVAL_SUPPLEMENT",date:"2026-10-01",sponsor:"Pfizer Inc",ticker:"PFE",importance:"LOW",
   importance_reason:"other supplement approved",products:["X"]},
  {event_type:"APPROVAL_ORIGINAL",date:"2026-10-15",sponsor:"VERTEX PHARMACEUTICALS INC",ticker:"VRTX",
   importance:"HIGH",importance_reason:"original application approved",products:["NEWDRUG"],review_priority:"PRIORITY",
   official_url:"https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo=217123"}],
  recalls:[{event_type:"RECALL",date:"2026-10-14",firm:"Small Firm LLC",ticker:null,importance:"MEDIUM",
   classification:"Class II",reason:"contamination",importance_reason:"Class II recall (FDA classification)"},
   {event_type:"RECALL",date:"2026-10-10",firm:"Evil",importance:"HIGH",official_url:"javascript:alert(1)"}]};
const lines=fdaLines(report);
assert.equal(lines[0].title,"VRTX · VERTEX PHARMACEUTICALS INC");
assert.match(lines[0].status,/موافقة على طلب أصلي · 2026-10-15/);
assert.match(lines[0].url,/^https:\/\/www\.accessdata\.fda\.gov\//);
assert.equal(lines[1].url,null);  // unsafe link dropped
assert.match(lines.find(l=>l.title.includes("Small Firm")).detail,/بلا رمز/);
assert.equal(lines.at(-1).title,"PFE · Pfizer Inc");
assert.deepEqual(fdaLines(null),[]);
console.log("terminal fda ok");
