"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const research=require("../public/terminal-research.js");

function make(direction="UP", n=75){
  return Array.from({length:n},(_,i)=>{
    const base=direction==="UP"?100+i*.3:140-i*.3;
    const open=direction==="UP"?base-.12:base+.12;
    const close=base;
    return {time:Math.floor(Date.UTC(2026,9,10,14,0)/1000)+i*900,
      open,close,high:Math.max(open,close)+.06,low:Math.min(open,close)-.07};
  });
}

const bullish=make("UP"),bearish=make("DOWN");
const liveBull=research.analyze(bullish,{hourBars:bullish,current_session_confirmed:true});
assert.equal(liveBull.status,"BREAKOUT_OBSERVED");
assert.equal(liveBull.side,"CALL");
assert.equal(liveBull.technical_bias,"UP");
assert.equal(liveBull.hour_bias,"UP");
assert.ok(liveBull.activation>0);
assert.ok(liveBull.target1>liveBull.activation);
assert.ok(liveBull.target2>liveBull.target1);
assert.ok(liveBull.invalidation<liveBull.activation);
assert.equal(liveBull.probability,null);
assert.equal(liveBull.options_quote_verified,false);
assert.equal(liveBull.execution_eligible,false);

const liveBear=research.analyze(bearish,{hourBars:bearish,current_session_confirmed:true});
assert.equal(liveBear.status,"BREAKDOWN_OBSERVED");
assert.equal(liveBear.side,"PUT");
assert.ok(liveBear.target1<liveBear.activation);
assert.ok(liveBear.target2<liveBear.target1);
assert.ok(liveBear.invalidation>liveBear.activation);

// Existing research snapshots are usually historical when markets are closed.
// A model must never turn old Yahoo OHLC into a current contract recommendation.
const stale=research.analyze(bullish,{hourBars:bullish,current_session_confirmed:false});
assert.equal(stale.status,"HISTORICAL");
assert.equal(stale.side,"WAIT");
assert.equal(stale.historical_side,"CALL");
assert.ok(stale.reason_ar.includes("تاريخية"));
assert.equal(stale.execution_eligible,false);

const conflict=research.analyze(bullish,{hourBars:bearish,current_session_confirmed:true});
assert.equal(conflict.status,"CONFLICT");
assert.equal(conflict.side,"WAIT");
assert.equal(conflict.hour_bias,"DOWN");

const undersampled=research.analyze(bullish.slice(-27),{current_session_confirmed:true});
assert.equal(undersampled.side,"WAIT");
assert.equal(undersampled.activation,null);

const lastHighSpike=bullish.map(x=>({...x}));
lastHighSpike.at(-1).high+=40;
const spike=research.analyze(lastHighSpike,{current_session_confirmed:true});
assert.equal(spike.resistance,liveBull.resistance);
assert.equal(spike.support,liveBull.support);

const dirty=bullish.map(x=>({...x}));
dirty.push({...bullish[5],open:-10});
dirty.push({...bullish[3],high:-30});
assert.equal(research.clean(dirty).length,bullish.length);
assert.equal(research.clean([{time:1799999999,open:100,high:90,low:99,close:101}]).length,0);

const html=fs.readFileSync("public/index.html","utf8");
const app=fs.readFileSync("public/terminal-hub.js","utf8");
const css=fs.readFileSync("public/terminal-hub.css","utf8");
for(const tab of ["overview","indices","large","small","news","chart","options","trust","advanced"]){
  assert.ok(html.includes('data-terminal-tab="'+tab+'"'),tab);
  assert.ok(html.includes('id="terminal-panel-'+tab+'"'),tab);
}
for(const tag of ["terminal-overview-pulse","terminal-overview-picks","terminal-overview-events",
  "terminal-options-readiness","terminal-options-breakdown","terminal-decision-levels"]){
  assert.ok(html.includes('id="'+tag+'"'),tag);
}
assert.ok(html.includes("./terminal-research.js?v=20261019-1"));
assert.ok(html.indexOf("terminal-research.js")<html.indexOf("terminal-hub.js"));
assert.ok(app.includes("feedAgeHours"));
assert.ok(app.includes("current_session_confirmed:currentConfirmed"));
assert.ok(app.includes("function renderOverview()"));
assert.ok(app.includes("function renderOptions()"));
assert.ok(app.includes("GhaziResearch"));
assert.ok(app.includes("sourceDate"));
assert.ok(css.includes(".terminal-overview-columns"));
assert.ok(css.includes(".terminal-decision-desk"));
console.log("GHAZI research scenario and mobile desk: PASS");
