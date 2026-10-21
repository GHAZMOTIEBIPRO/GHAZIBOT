"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const desk = require("../public/catalyst-desk.js");
const now = Date.parse("2026-10-21T21:00:00Z");
const event = {symbol:"ABBV",kind:"FDA_APPROVAL",date:"2026-10-20",importance:"HIGH",
  label:"New drug",reason:"New molecular entity",source:"openFDA",
  source_url:"https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?ApplNo=1234"};
function report(changes={}){return {schema:"ghazi.catalyst_watchlist.v1",
  generated_at:"2026-10-21T20:00:00Z",decision_authority:false,
  execution_authority:false,research_only:true,
  sources:{openfda:true,sec_edgar:false},watchlist:[{symbol:"ABBV",dilution_risk:false,
    sub10_confirmed:false,price_band:"UNVERIFIED",catalysts:[event]}],...changes};}
const p = desk.validate(report(),now);
assert.equal(p.ok,true);
assert.equal(p.rows.length,1);
assert.equal(p.rows[0].symbol,"ABBV");
assert.equal(p.rows[0].sub10,false);
assert.equal(desk.filter(p.rows,{q:"drug"}).length,1);
assert.equal(desk.filter(p.rows,{importance:"MEDIUM"}).length,0);
assert.equal(desk.filter(p.rows,{kind:"FDA_APPROVAL"}).length,1);
assert.equal(desk.validate(report({generated_at:"2026-10-14T20:00:00Z"}),now).ok,false);
assert.equal(desk.validate(report({decision_authority:true}),now).ok,false);
assert.equal(desk.validate(report({sources:{openfda:false}}),now).rows.length,0);
assert.equal(desk.official("javascript:alert(1)","openFDA"),null);
assert.equal(desk.official("https://evil.com/","openFDA"),null);
assert.match(desk.official(event.source_url,"openFDA"),/^https:/);
const index=fs.readFileSync(path.join(__dirname,"../public/index.html"),"utf8");
assert.ok(index.includes('href="./catalyst-desk.html"'));
const page=fs.readFileSync(path.join(__dirname,"../public/catalyst-desk.html"),"utf8");
assert.ok(page.includes('src="./catalyst-desk.js'));
console.log("official catalyst desk smoke ok");