"use strict";
const assert=require("node:assert/strict");
const {build}=require("../public/terminal-decision.js");

const now=Date.parse("2026-10-20T15:00:00Z");
const fresh="2026-10-20T14:30:00Z";
const classical={generated_at:fresh,source_generated_at:fresh,companies:[
  {symbol:"COST",decision:"CALL",trade_status:"ACTIONABLE",confirmation_level:996.24,
   invalidation_level:989.47,targets:{entry:996.24,t1:1008.37,t2:1014.55,t1_reward_to_risk:2.06},
   timeframes:{daily:"BULLISH",hourly:"BULLISH",intraday:"BULLISH"},
   reasons_ar:["اليومي صاعد","قمم وقيعان صاعدة","ترتيب المتوسطات","سبب رابع"]},
  {symbol:"GS",decision:"PUT",confirmation_level:872.33,invalidation_level:887.05,
   targets:{t1:872.33,t2:859.03,t1_reward_to_risk:0.31},
   timeframes:{daily:"BEARISH",hourly:"BEARISH",intraday:"BEARISH"},reasons_ar:["اليومي هابط"]},
  {symbol:"MU",decision:"WAIT",timeframes:{daily:"BULLISH",hourly:"BEARISH",intraday:"NEUTRAL"},reasons_ar:[]}
]};
const liquidity={generated_at:fresh,symbols:{COST:{status:"OK",volume:{state:"HIGH",rvol:1.8},
  vwap_position:"BELOW",breakout:"FAILED_BREAKOUT",sweep_proxy:null}}};
const news={generated_at:fresh,google_news_attention:[
  {symbol:"COST",impact_level:"MEDIUM",event_topic:"FINANCIAL_REPORT_MENTION"},
  {symbol:"COST",impact_level:"LOW",event_topic:"RISK_OR_ADVERSE_EVENT_MENTION"}]};
const feeds={classical,liquidity,news};

const cost=build("COST",feeds,now);
assert.equal(cost.verdict,"CALL");
assert.equal(cost.why.length,3);
assert.ok(cost.support.includes("الأطر الثلاثة متوافقة"));
assert.ok(cost.support.some(x=>x.includes("RVOL 1.8")));
assert.ok(cost.contra.some(x=>x.includes("تحت VWAP")));
assert.ok(cost.contra.some(x=>x.includes("اختراق فاشل")));
assert.ok(cost.contra.some(x=>x.includes("خبر مخاطر")));
assert.ok(cost.context.some(x=>x.includes("اتجاه أثره غير مؤكد")));
assert.deepEqual(cost.levels,{entry:996.24,t1:1008.37,t2:1014.55,invalidation:989.47,rr:2.06});
assert.equal(cost.probability,null);
assert.equal(cost.executionAuthority,false);

// Low reward/risk becomes NO TRADE even when the published file predates trade_status.
const gs=build("GS",feeds,now);
assert.equal(gs.verdict,"NO_TRADE");
assert.ok(gs.contra.some(x=>x.includes("أقل من 1")));
assert.equal(build("MU",feeds,now).verdict,"WAIT");
assert.ok(build("MU",feeds,now).contra.includes("الأطر الزمنية غير متوافقة"));

// Stale direction data never shows a CALL.
const old=build("COST",{...feeds,classical:{...classical,source_generated_at:"2026-10-18T10:00:00Z"}},now);
assert.equal(old.verdict,"WAIT_STALE");
assert.equal(old.freshness.find(f=>f.label==="الاتجاه").fresh,false);

// Missing secondary feeds do not break the card.
const bare=build("COST",{classical},now);
assert.equal(bare.verdict,"CALL");
assert.equal(build("ZZZ",{},now).verdict,"NO_ANALYSIS");

// Index rules path.
const idx=build("SPX",{index:{generated_at:fresh,symbols:{SPX:{direction:{version:"INDEX_DIRECTION_RULES_V1",
  decision:"PUT",reason_ar:"توافق هبوطي",targets:{t1:7650,t2:7600},invalidation:7720,
  rules:{PUT:{R1_DAILY_NOT_AGAINST:true,R2_INTRADAY_ALIGNED:true,R3_ANCHOR_SIDE:true,
    R4_NOT_EXHAUSTED:true,R5_LEVEL_BREAK:false}}}}}},
  gamma:{integrated_engines:{interpretation:{hedging_direction_model:"AMPLIFYING"}}}},now);
assert.equal(idx.verdict,"PUT");
assert.equal(idx.support.length,4);
assert.ok(idx.contra.includes("غير محقق: كسر قمة/قاع الجلسة السابقة"));
assert.ok(idx.context.some(x=>x.includes("تحوط قد يضخم")));
assert.equal(idx.levels.t1,7650);
console.log("terminal decision card ok");
