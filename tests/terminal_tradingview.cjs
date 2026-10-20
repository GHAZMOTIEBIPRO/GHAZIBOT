"use strict";
const assert=require("node:assert/strict");
const {tradingViewConfig,blockedReason}=require("../public/terminal-hub.js");

assert.equal(tradingViewConfig("SPX").symbol,"SP:SPX");
assert.equal(tradingViewConfig("QQQ").symbol,"NASDAQ:QQQ");
assert.equal(tradingViewConfig("NVDA").symbol,"NVDA");
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
