"use strict";
const assert=require("node:assert/strict");
const {brief}=require("../public/terminal-decision.js");

const now=Date.parse("2026-10-21T15:00:00Z");
const fresh="2026-10-21T14:30:00Z";
const dataHub={datasets:[
  {file:"index_radar.json",data_state:"LICENSE_BLOCKED",source:"Yahoo",generated_at:fresh},
  {file:"classical_direction.json",data_state:"LICENSE_BLOCKED",source:"Yahoo",generated_at:fresh},
  {file:"sec_filing_pulse.json",data_state:"SOURCE_UNAVAILABLE",source:"SEC EDGAR",generated_at:fresh},
  {file:"catalyst_watchlist.json",data_state:"DELAYED",source:"openFDA (CC0) + SEC EDGAR",generated_at:fresh}]};
const catalysts={watchlist:[{symbol:"ABCD",highest_importance:"HIGH",dilution_risk:true,sub10_confirmed:false,
  catalysts:[{kind:"FDA_APPROVAL",date:"2026-10-16",label:"NEWDRUG",source:"openFDA"},
             {kind:"DILUTION_RISK",date:"2026-10-18",label:"424B5",source:"SEC EDGAR"}]}]};
const feeds={dataHub,catalysts,sec:{filings:[]},brief:{catalysts:[
  {symbol:"ABCD",headline:"Registry update",source:"ClinicalTrials.gov",published_at:"2026-10-20"}]}};

// Catalysts only: no direction, explicit gaps, data states listed.
const b=brief("ABCD",feeds,now);
assert.equal(b.verdict,"NO_ANALYSIS");
assert.equal(b.probability,null);
assert.equal(b.executionAuthority,false);
const sec=Object.fromEntries(b.sections.map(s=>[s.key,s]));
assert.deepEqual(Object.keys(sec),["catalysts","filings","technical","liquidity","options","scenarios","risks","can","cannot",
  "wait","data","history"]);
assert.match(b.headline,/لا قراءة اتجاه؛ توجد 2 أحداث رسمية/);
assert.match(sec.catalysts.lines[0],/موافقة FDA · 2026-10-16/);
assert.ok(sec.catalysts.lines.some(l=>l.startsWith("سياق غير مؤكد")));
assert.match(sec.filings.lines[0],/SEC_USER_AGENT/);
assert.match(sec.technical.lines[0],/محجوبة بشروطها/);
assert.ok(sec.scenarios.empty);
assert.ok(sec.risks.lines.some(l=>l.includes("خطر تخفيف")));
assert.ok(sec.cannot.lines.some(l=>l.includes("لا يصدر من الأخبار أو المحفزات وحدها")));
assert.ok(sec.cannot.lines.some(l=>l.includes("مرشح يحتاج تحققًا سعريًا")));
assert.ok(sec.data.lines.some(l=>l.startsWith("قائمة المحفزات: رسمي مؤجل")));
assert.ok(sec.data.lines.some(l=>l.startsWith("الأخبار العامة: غير منشور")));
assert.ok(!JSON.stringify(b).includes("CALL بحثي"));

// With a price-based direction feed, scenarios follow the side.
const classical={generated_at:fresh,source_generated_at:fresh,companies:[{symbol:"GS",decision:"PUT",
  trade_status:"ACTIONABLE",confirmation_level:872.33,invalidation_level:887.05,
  targets:{entry:872.33,t1:860,t2:850,t1_reward_to_risk:1.4},timeframes:{daily:"BEARISH",hourly:"BEARISH",intraday:"BEARISH"},
  reasons_ar:["اليومي هابط"]}]};
const hub2={datasets:[{file:"classical_direction.json",data_state:"RESEARCH_ONLY",generated_at:fresh}]};
const g=brief("GS",{classical,dataHub:hub2},now);
assert.equal(g.verdict,"PUT");
const gs=Object.fromEntries(g.sections.map(s=>[s.key,s]));
assert.match(gs.scenarios.lines[0],/^هابط \(القراءة الحالية\).*T1 860/);
assert.match(gs.scenarios.lines[1],/^صاعد \(إلغاء\): العودة فوق 887.05/);
assert.ok(gs.technical.lines[0].includes("PUT بحثي"));
console.log("terminal brief ok");
