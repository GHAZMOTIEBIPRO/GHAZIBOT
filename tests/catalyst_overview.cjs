"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const {safeOfficial,verifiedSchema}=require("../public/catalyst-overview.js");
assert.equal(safeOfficial("https://www.sec.gov/Archives/edgar/8-k"),"https://www.sec.gov/Archives/edgar/8-k");
assert.equal(safeOfficial("https://www.fda.gov/news/press"),"https://www.fda.gov/news/press");
assert.equal(safeOfficial("https://sec.gov.evil.invalid/path"),null);
assert.equal(safeOfficial("http://www.sec.gov/path"),null);
assert.equal(safeOfficial("javascript:alert(1)"),null);
assert.equal(safeOfficial(undefined),null);
assert.ok(verifiedSchema({schema:"ghazi.public_decision.v1",
    authority:"RESEARCH_ONLY_NO_AUTOMATED_CALL_PUT",
    live_trade_quotes_verified:false,
    generated_at:"2026-10-18T11:13:00+00:00",
    source_generated_at:"2026-10-18T11:11:00+00:00"}));
assert.ok(!verifiedSchema({schema:"ghazi.public_decision.v1",
    live_trade_quotes_verified:true,
    generated_at:"2026-10-18T11:13:00+00:00",
    source_generated_at:"2026-10-18T11:11:00+00:00"}));
const html=fs.readFileSync("public/index.html","utf8");
assert.ok(html.indexOf('id="indices-overview"')<html.indexOf('<nav class="tabs"'));
assert.ok(html.indexOf('id="catalyst-overview"')<html.indexOf('<nav class="tabs"'));
assert.ok(html.includes("catalyst-overview.js"));
assert.ok(html.includes("index-radar.js"));
console.log("GHAZI Radar visible indices and official catalyst source filters: PASS");
