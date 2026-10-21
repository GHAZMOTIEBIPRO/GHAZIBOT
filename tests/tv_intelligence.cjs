"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const tv=require("../public/tv-intelligence.js");

// Index symbols map to TradingView's exchange-qualified names; stocks pass through.
assert.equal(tv.tvSymbol("spx"),"SP:SPX");
assert.equal(tv.tvSymbol("VIX"),"TVC:VIX");
assert.equal(tv.tvSymbol("NVDA"),"NVDA");
assert.equal(tv.tvSymbol("BRK.B"),"BRK.B");
// Anything that is not a plain ticker is refused (no injection into the widget config).
for(const bad of ["", "1ABC", "AAPL;alert(1)", "<script>", "TOOLONGTICKER", null])
  assert.equal(tv.tvSymbol(bad),null,String(bad));
assert.equal(tv.config("technical-analysis","<x>"),null);

const ta=tv.config("technical-analysis","QQQ");
assert.equal(ta.symbol,"NASDAQ:QQQ");
assert.equal(ta.showIntervalTabs,true);
assert.equal(ta.locale,"ar_AE");
assert.equal(tv.config("events").countryFilter,"us");
assert.equal(tv.config("stock-heatmap").dataSource,"SPX500");
assert.equal(tv.config("screener").market,"america");
assert.equal(tv.config("not-a-widget","AAPL"),null);

// Only TradingView's official embed scripts can be loaded.
assert.equal(tv.widgetSrc("timeline"),"https://s3.tradingview.com/external-embedding/embed-widget-timeline.js");
assert.equal(tv.widgetSrc("../evil"),null);
assert.equal(tv.INDICES.length,8);

// The module must never read data back from TradingView or fetch anything itself.
const source=fs.readFileSync(path.join(__dirname,"../public/tv-intelligence.js"),"utf8");
for(const forbidden of ["fetch(","XMLHttpRequest","postMessage","contentWindow","WebSocket"])
  assert.ok(!source.includes(forbidden),forbidden);

// The page wires every slot the module fills.
const html=fs.readFileSync(path.join(__dirname,"../public/index.html"),"utf8");
for(const id of ["tv-index-buttons","tv-index-ta","tv-index-info","tv-heatmap","tv-screener","tv-calendar",
  "tv-stock-form","tv-stock-input","tv-stock-ta","tv-stock-profile","tv-stock-financials","tv-stock-news"])
  assert.ok(html.includes('id="'+id+'"'),id);
assert.match(html,/tv-intelligence\.js\?v=/);
console.log("tv intelligence ok");
