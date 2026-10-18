"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const {uniqueValidBars,ema,rsi,atr,safeOfficial,safeResearch}=require("../public/terminal-hub.js");
const make=(n=65)=>Array.from({length:n},(_,i)=>({
  time:"2026-08-"+String(1+i).padStart(2,"0"),
  open:100+i*.75,close:100.5+i*.75,high:101+i*.75,low:99+i*.75
}));
// Valid calendar dates, with no fabricated missing sessions.
const base=make(12).slice(0,12);
const cleaned=uniqueValidBars([...base,{time:"2026-08-10",open:-1,high:5,low:1,close:3}]);
assert.equal(cleaned.length,12); // invalid row with same time must not replace valid one
const candles=Array.from({length:65},(_,i)=>({
  time:Date.UTC(2026,6,1+i)/1000,open:100+i*.75,close:100.5+i*.75,
  high:101+i*.75,low:99+i*.75
}));
assert.equal(uniqueValidBars(candles).length,65);
assert.equal(ema(candles,20).length,46);
assert.equal(ema(candles,50).length,16);
assert.ok(rsi(candles)>50);
assert.ok(atr(candles)>0);
assert.equal(rsi(candles.slice(0,10)),null);
assert.equal(atr(candles.slice(0,10)),null);
assert.equal(safeOfficial("https://www.sec.gov/Archives/edgar/test"),"https://www.sec.gov/Archives/edgar/test");
assert.equal(safeOfficial("https://sec.gov.evil.test"),null);
assert.equal(safeResearch("https://news.google.com/rss/articles/test"),"https://news.google.com/rss/articles/test");
assert.equal(safeResearch("https://unrelated.example.com"),null);
const html=fs.readFileSync("public/index.html","utf8");
assert.ok(html.includes('id="legacy-dashboard" hidden'));
assert.ok(html.includes('id="terminal-candle-chart"'));
for(const category of ["indices","large","small","news","chart","advanced"]){
  assert.ok(html.includes('data-terminal-tab="'+category+'"'));
  assert.ok(html.includes('id="terminal-panel-'+category+'"'));
}
console.log("GHAZI terminal/chart analysis source and layout acceptance: PASS");

const html2=fs.readFileSync("public/index.html","utf8");
const hub=fs.readFileSync("public/terminal-hub.js","utf8");
assert.ok(html2.includes('id="terminal-gamma-metrics"'));
assert.ok(html2.includes('id="terminal-chart-scenario"'));
assert.ok(hub.includes("ghazi.stock_charts.v1"));
assert.ok(hub.includes("gamma:d=>d?.policy==="));
assert.ok(hub.includes("No live trade".slice(0,0)) || hub.includes("SHADOW"));
assert.ok(hub.includes("terminal-stock-chart-health"));
