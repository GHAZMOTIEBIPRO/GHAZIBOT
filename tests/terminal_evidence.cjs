"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const {evaluate}=require("../public/terminal-evidence.js");
const NOW=Date.parse("2026-10-19T13:00:00Z");
const bars=Array.from({length:60},(_,i)=>({
  time:Math.floor(Date.parse("2026-10-19T09:00:00Z")/1000)+i*60,
  open:100,high:101,low:99,close:100
}));
const scenario={status:"BULL_WATCH",side:"CALL",hour_bias:"UP"};
const fresh=evaluate({bars,scenario,frame:{current_session_confirmed:true},
  generatedAt:"2026-10-19T12:55:00Z",timeframe:"5m",now:NOW});
assert.equal(fresh.status,"WATCH");
assert.equal(fresh.executable,false);
assert.equal(fresh.probability,null);
assert.equal(fresh.optionContractVerified,false);
assert.equal(fresh.matchedDailyRvol,null);
assert.equal(fresh.checks[3].state,"unknown");
assert.ok(fresh.checks[3].detail.includes("لا يوجد RVOL"));
const stale=evaluate({bars,scenario,frame:{current_session_confirmed:true,
  historical_cache_only:true},generatedAt:"2026-10-19T12:55:00Z",now:NOW});
assert.equal(stale.status,"HISTORICAL");
assert.equal(stale.checks[1].state,"blocked");
const oldReport=evaluate({bars,scenario,frame:{current_session_confirmed:true},
  generatedAt:"2026-10-16T12:00:00Z",now:NOW});
assert.equal(oldReport.status,"HISTORICAL");
assert.equal(evaluate({bars:bars.slice(0,12),scenario,
  frame:{current_session_confirmed:true},generatedAt:"2026-10-19T12:55:00Z",now:NOW}).status,"UNAVAILABLE");
const conflict=evaluate({bars,scenario:{status:"CONFLICT",side:"WAIT",hour_bias:"DOWN"},
  frame:{current_session_confirmed:true},generatedAt:"2026-10-19T12:55:00Z",now:NOW});
assert.equal(conflict.status,"CONFLICT");
const partial=evaluate({bars,scenario:{...scenario,hour_bias:"INSUFFICIENT"},
  frame:{current_session_confirmed:true},generatedAt:"2026-10-19T12:55:00Z",now:NOW});
assert.equal(partial.status,"PARTIAL");
const trueResearch={research_only:true,source_family:"yahoo",
  options_execution_eligible:false,source_last_daily_bar:"2026-10-19",rvol_daily:2.3};
const dailyBars=bars.map((b,i)=>({...b,time:"2026-08-"+String(i+1).padStart(2,"0")}));
dailyBars[dailyBars.length-1].time="2026-10-19";
const research=evaluate({bars:dailyBars,scenario,frame:{current_session_confirmed:true},
  generatedAt:"2026-10-19T12:55:00Z",timeframe:"1d",
  confluence:trueResearch,now:NOW});
assert.equal(research.matchedDailyRvol,2.3);
assert.equal(research.checks[3].state,"ok");
assert.equal(evaluate({bars:dailyBars,scenario,frame:{current_session_confirmed:true},
  generatedAt:"2026-10-19T12:55:00Z",timeframe:"15m",
  confluence:trueResearch,now:NOW}).matchedDailyRvol,null);
const fakeNews={authority:"NEWS_SEARCH_ATTENTION_ONLY",official_catalyst_verified:false,
  research_only:true,latest_published_at:"2026-10-19T12:00:00Z"};
const attention=evaluate({bars,scenario,frame:{current_session_confirmed:true},
  generatedAt:"2026-10-19T12:55:00Z",newsAttention:fakeNews,now:NOW});
assert.equal(attention.newsSearchAttention,true);
assert.equal(attention.checks.at(-1).state,"unknown");
assert.ok(attention.checks.at(-1).detail.includes("غير رسمي"));
const future={...fakeNews,latest_published_at:"2026-10-19T20:00:00Z"};
assert.equal(evaluate({bars,scenario,newsAttention:future,now:NOW}).newsSearchAttention,false);
const html=fs.readFileSync("public/index.html","utf8");
const js=fs.readFileSync("public/terminal-hub.js","utf8");
const css=fs.readFileSync("public/terminal-hub.css","utf8");
assert.ok(html.includes('id="terminal-evidence-grid"'));
assert.ok(html.indexOf("terminal-evidence.js")<html.indexOf("terminal-hub.js"));
assert.ok(html.includes('data-terminal-tf="15m"'));
assert.ok(js.includes("GhaziEvidence.evaluate"));
assert.ok(js.includes("terminal-evidence-grid"));
assert.ok(css.includes(".terminal-evidence"));
console.log("GHAZI Evidence Desk: PASS");
