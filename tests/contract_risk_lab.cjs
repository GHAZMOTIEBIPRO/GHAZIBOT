const assert = require("node:assert/strict");
const fs = require("node:fs");
const {calculateLongOptionRisk} = require("../public/contract-risk-lab.js");
const approx = (a,b) => assert.ok(Math.abs(a-b)<1e-7, a+" != "+b);
const input = {
  side:"CALL", capital:30000, riskPct:1.5, spot:500, strike:500,
  bid:2.4, ask:2.6, fee:0.65, targetBid:4.2, stopBid:1.6
};
const a=calculateLongOptionRisk(input);
assert.equal(a.count,1);
approx(a.riskBudget,450);
approx(a.debitPerContract,260.65);
approx(a.totalDebit,260.65);
approx(a.maxLoss,260.65);
approx(a.currentSpreadPct,8);
approx(a.breakeven,502.613);
approx(a.targetProfit,158.7);
approx(a.stopProfit,-101.3);
approx(a.ratio,158.7/101.3);
approx(a.payoffAtExpiryPerContract(500),-261.3);
approx(a.payoffAtExpiryPerContract(510),738.7);
assert.equal(a.maxProfit,null);
assert.equal(a.flags.length,0);
const p=calculateLongOptionRisk({...input,side:"PUT"});
approx(p.breakeven,497.387);
approx(p.payoffAtExpiryPerContract(0),49738.7);
approx(p.maxProfit,49738.7);
const z=calculateLongOptionRisk({...input,riskPct:0.1});
assert.equal(z.count,0);
assert.ok(z.flags.some(t=>t.includes("لا يكفي")));
const wide=calculateLongOptionRisk({...input,bid:1.2});
assert.ok(wide.currentSpreadPct>15);
assert.ok(wide.flags.some(t=>t.includes("السبريد")));
const zeroBid=calculateLongOptionRisk({...input,bid:0});
assert.ok(zeroBid.flags.some(t=>t.includes("Bid")));
for(const mutation of [
  {bid:4}, {ask:0}, {capital:-1}, {riskPct:0}, {riskPct:101},
  {side:"STRADDLE"}, {ask:""}, {spot:0}, {strike:0}, {fee:-1},
]) {
  assert.throws(()=>calculateLongOptionRisk({...input,...mutation}));
}
const text=fs.readFileSync("public/index.html","utf8");
for(const id of ["tab-risklab","ghazi-risk-form","risk-payoff-chart","risk-maxloss",
  "risk-count","risk-spread","risk-rr","risk-target","risk-stop"]) {
  assert.ok(text.includes('id="'+id+'"'),"missing "+id);
}
assert.ok(text.includes('data-tab="risklab"'));
assert.ok(text.includes("contract-risk-lab.js"));
assert.ok(text.includes("contract-risk-lab.css"));
assert.ok(text.includes("لا تؤهّل أي إشارة للتنفيذ"));
assert.ok(!fs.readFileSync("public/contract-risk-lab.js","utf8").includes("fetch("));
console.log("GHAZI RISK LAB: all pure math + public wiring tests pass");
