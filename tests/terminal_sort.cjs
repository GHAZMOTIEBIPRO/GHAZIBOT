"use strict";
const assert=require("node:assert/strict");
const {sortCandidates}=require("../public/terminal-hub.js");

const rows=[
  {symbol:"AAA",score:60,day_move_pct:5,rvol_same_time:null,float_shares:9e6},
  {symbol:"BBB",score:80,day_move_pct:12,rvol_same_time:2.1,float_shares:null},
  {symbol:"CCC",score:70,day_move_pct:12,rvol_same_time:0.4,float_shares:3e6}];
const order=key=>sortCandidates(rows,key).map(r=>r.symbol).join(",");
assert.equal(order("stage"),"AAA,BBB,CCC");           // published order kept
assert.equal(order("score"),"BBB,CCC,AAA");
assert.equal(order("day_move_pct"),"BBB,CCC,AAA");    // tie keeps published order
assert.equal(order("rvol_same_time"),"BBB,CCC,AAA");  // missing value last, not zero
assert.equal(order("float_shares"),"CCC,AAA,BBB");    // smallest float first, missing last
assert.equal(rows[0].symbol,"AAA");                   // input not mutated
assert.deepEqual(sortCandidates(null,"score"),[]);
console.log("terminal sort ok");
