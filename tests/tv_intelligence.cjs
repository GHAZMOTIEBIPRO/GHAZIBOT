"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const tv=require("../public/tv-intelligence.js");

// Cash indices do not render in free embeds (probe 2026-10-25): each index is
// shown through its tracking ETF and labelled as such; never a CFD.
const spx=tv.resolve("spx");
assert.equal(spx.tv,"AMEX:SPY");
assert.equal(spx.kind,"ETF_PROXY");
assert.match(spx.note_ar,/ليس المؤشر النقدي SPX/);
assert.equal(spx.cash_url,"https://www.tradingview.com/symbols/SP-SPX/");
assert.equal(tv.tvSymbol("NDX"),"NASDAQ:QQQ");
assert.equal(tv.tvSymbol("DJI"),"AMEX:DIA");
assert.equal(tv.tvSymbol("RUT"),"AMEX:IWM");
// VIX has no equivalent ETF (VIX ETFs track futures): no substitute is shown.
assert.equal(tv.resolve("VIX").kind,"UNAVAILABLE");
assert.equal(tv.tvSymbol("VIX"),null);
// Stocks carry their verified listing exchange; unknown tickers stay bare and say so.
assert.equal(tv.tvSymbol("NVDA"),"NASDAQ:NVDA");
assert.equal(tv.tvSymbol("RGTI"),"NASDAQ:RGTI");
assert.equal(tv.tvSymbol("IONQ"),"NYSE:IONQ");
assert.equal(tv.tvSymbol("BRK.B"),"BRK.B");
assert.match(tv.resolve("ZZZZ").note_ar,/البورصة لم تُحدد/);
for(const sym of Object.values(tv.EXCHANGE))assert.ok(["NASDAQ","NYSE","AMEX"].includes(sym));
assert.ok(!JSON.stringify(tv.EXCHANGE).includes("FOREXCOM"));
// Anything that is not a plain ticker is refused (no injection into the widget config).
for(const bad of ["", "1ABC", "AAPL;alert(1)", "<script>", "TOOLONGTICKER", null])
  assert.equal(tv.tvSymbol(bad),null,String(bad));
assert.equal(tv.config("technical-analysis","<x>"),null);

const ta=tv.config("technical-analysis","QQQ");
assert.equal(ta.symbol,"NASDAQ:QQQ");
assert.equal(ta.showIntervalTabs,true);
assert.equal(ta.locale,"ar_AE");
const chart=tv.config("advanced-chart","AAPL","240");
assert.equal(chart.symbol,"NASDAQ:AAPL");
assert.equal(chart.interval,"240");
assert.equal(chart.timezone,"America/New_York");
assert.equal(chart.allow_symbol_change,false);
assert.equal(tv.config("advanced-chart","AAPL","1").interval,"D");
assert.deepEqual(tv.INTERVALS.map(([v])=>v),["5","15","60","240","D","W"]);
assert.equal(tv.config("events").countryFilter,"us");
assert.equal(tv.config("stock-heatmap").dataSource,"SPX500");
assert.equal(tv.config("screener").market,"america");
assert.equal(tv.config("not-a-widget","AAPL"),null);

// Only TradingView's official embed scripts can be loaded.
assert.equal(tv.widgetSrc("timeline"),"https://s3.tradingview.com/external-embedding/embed-widget-timeline.js");
assert.equal(tv.widgetSrc("../evil"),null);
assert.deepEqual(tv.INDICES,["SPX","NDX","DJI","RUT","VIX"]);

// The module must never read data back from TradingView or fetch anything itself.
const source=fs.readFileSync(path.join(__dirname,"../public/tv-intelligence.js"),"utf8");
for(const forbidden of ["fetch(","XMLHttpRequest","postMessage","contentWindow","WebSocket"])
  assert.ok(!source.includes(forbidden),forbidden);

// The page wires every slot the module fills, a chart view per section, and no CFD.
const html=fs.readFileSync(path.join(__dirname,"../public/classic.html"),"utf8");
for(const id of ["tv-index-buttons","tv-index-ta","tv-index-info","tv-heatmap","tv-screener","tv-calendar",
  "tv-stock-form","tv-stock-input","tv-stock-ta","tv-stock-profile","tv-stock-financials","tv-stock-news"])
  assert.ok(html.includes('id="'+id+'"'),id);
assert.equal((html.match(/data-tv-chart-view/g)||[]).length,3);
assert.ok(!html.includes("FOREXCOM:"),"CFD symbols must not be shown as indices");
assert.match(html,/<details id="terminal-tv-chart" class="terminal-tv-chart" open>/);
assert.match(html,/tv-intelligence\.js\?v=/);
console.log("tv intelligence ok");
