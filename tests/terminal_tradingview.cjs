"use strict";
const assert=require("node:assert/strict");
const {tradingViewConfig,blockedReason}=require("../public/terminal-hub.js");

// The chart panel resolves symbols like the section charts: SPX shows SPY (labelled).
assert.equal(tradingViewConfig("SPX").symbol,"AMEX:SPY");
assert.equal(tradingViewConfig("QQQ").symbol,"NASDAQ:QQQ");
assert.equal(tradingViewConfig("NVDA").symbol,"NASDAQ:NVDA");
assert.equal(tradingViewConfig("VIX"),null);
// The panel's timeframe drives the external chart's interval.
assert.equal(tradingViewConfig("NVDA","15m").interval,"15");
assert.equal(tradingViewConfig("NVDA","4h").interval,"240");
assert.equal(tradingViewConfig("NVDA").interval,"D");
const cfg=tradingViewConfig("RGC");
assert.equal(cfg.allow_symbol_change,false);
assert.equal(cfg.timezone,"America/New_York");
assert.doesNotThrow(()=>JSON.parse(JSON.stringify(cfg)));
for(const bad of ['"><script>',"","1ABC",null])assert.equal(tradingViewConfig(bad),null);
assert.equal(blockedReason({status:"OK"}),null);
assert.equal(blockedReason(null),null);
assert.match(blockedReason({status:"SOURCE_TERMS_BLOCKED",reason_ar:"شروط Yahoo تمنع"}),/Yahoo/);
assert.match(blockedReason({status:"SOURCE_TERMS_BLOCKED"}),/إذن/);
console.log("terminal tradingview ok");
