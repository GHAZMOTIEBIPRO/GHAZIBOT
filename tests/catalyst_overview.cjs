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
assert.ok(html.includes('id="sec-filing-source-status"'));
const script=fs.readFileSync("public/catalyst-overview.js","utf8");
assert.ok(script.includes("ghazi.sec_issuer_pulse.v1"));
assert.ok(script.includes("OFFERING_OR_DILUTION_REVIEW"));
assert.ok(script.includes("sec_filing_pulse.json"));
assert.ok(script.includes("positive_news_inferred"));
assert.ok(html.includes('id="gdelt-news-list"'));
assert.ok(html.includes('id="gdelt-source-status"'));
assert.ok(script.includes("gdelt_doc_v2"));
assert.ok(script.includes('x.authority==="ATTENTION_ONLY"'));
assert.ok(script.includes("independent_confirmation===false"));
assert.ok(script.includes("free_public_intelligence.json"));


console.log("GHAZI Radar visible indices and official catalyst source filters: PASS");

assert.ok(html.includes('id="press-wire-news-list"'));
assert.ok(html.includes('id="press-wire-source-status"'));
assert.ok(script.includes("press_wire_attention"));
assert.ok(script.includes("PRESS_RELEASE_DISCOVERY_ONLY"));
assert.ok(script.includes("issuer_release_authenticated===false"));
assert.ok(script.includes("positive_catalyst_verified===false"));
assert.ok(script.includes("market_direction==="));
