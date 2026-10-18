/* Offline JS acceptance: fail-closed decision room, no future quote authority */
const assert=require("node:assert/strict");
const fs=require("node:fs");
const {decision}=require("../public/decision-room.js");
const NOW=Date.parse("2026-10-18T14:00:00Z");
const iso=(age)=>new Date(NOW-age*60000).toISOString();
const ready={generated_at:iso(1),option_provider_readiness:{
  production_quote_ready:false,production_flow_ready:false
}};
const rows=()=>({generated_at:iso(2),symbols:{
  SPX:{h1:{bias:"UP"},m15:{bias:"UP"},daily:{bias:"UP"},
       current_intraday_bar_confirmed:true,intraday_source_bar_start:iso(26)},
  NDX:{h1:{bias:"UP"},m15:{bias:"UP"},daily:{bias:"UP"},
       current_intraday_bar_confirmed:true,intraday_source_bar_start:iso(28)},
  VIX:{daily:{bias:"MIXED"}}
}});
assert.equal(decision(null,ready,NOW).state,"WAIT");
assert.equal(decision(rows(),null,NOW).state,"WAIT");
assert.equal(decision(rows(),ready,NOW).state,"UP_WATCH");
const stale=rows();
stale.symbols.SPX.intraday_source_bar_start=iso(95);
assert.equal(decision(stale,ready,NOW).state,"WAIT");
const disagreement=rows();
disagreement.symbols.NDX.m15.bias="DOWN";
assert.equal(decision(disagreement,ready,NOW).state,"WAIT");
const risk=rows();
risk.symbols.VIX.daily.bias="UP";
assert.equal(decision(risk,ready,NOW).state,"WAIT");
const down=rows();
for (const symbol of ["SPX","NDX"]) {
  down.symbols[symbol].h1.bias="DOWN";
  down.symbols[symbol].m15.bias="DOWN";
}
assert.equal(decision(down,ready,NOW).state,"DOWN_WATCH");
assert.notEqual(decision(rows(),ready,NOW).state,"CALL");
assert.notEqual(decision(down,ready,NOW).state,"PUT");
const html=fs.readFileSync("public/index.html","utf8");
for(const id of ["tab-decision","decision-main-state","decision-room-refresh",
  "decision-outcome-win-rate","decision-catalysts","decision-stock-list"]) {
  assert.ok(html.includes('id="'+id+'"'),"missing "+id);
}
assert.ok(html.includes("decision-room.js"));
assert.ok(html.includes("decision-room.css"));
console.log("Decision room tests: PASS (stale, divergent, VIX veto, no API signals)");
