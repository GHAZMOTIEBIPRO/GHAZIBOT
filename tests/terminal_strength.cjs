"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const page=fs.readFileSync("public/index.html","utf8");
const hub=fs.readFileSync("public/terminal-hub.js","utf8");
const wf=fs.readFileSync(".github/workflows/site-evidence-strength.yml","utf8");
for(const id of ["terminal-strength-score","terminal-strength-breakdown",
                 "terminal-strength-summary"]){
  assert.ok(page.includes('id="'+id+'"'),"missing visual element "+id);
}
assert.ok(page.includes("ليست نسبة")||page.includes("ليس نسبة"));
assert.ok(hub.includes("ghazi.evidence_strength.v1"));
assert.ok(hub.includes("score_is_prediction_win_rate===false"));
assert.ok(hub.includes("score_includes_visual_ui_audit===false"));
assert.ok(hub.includes("score_includes_unverified_live_quotes===false"));
assert.ok(hub.includes("state.strength"));
assert.ok(hub.includes("renderStrength()"));
assert.ok(hub.includes("site_strength.json"));
assert.ok(wf.includes("--walk-forward state/state/stocks/stock_walk_forward.json"));
assert.ok(wf.includes("git add runtime/public/data/site_strength.json"));
console.log("Transparent 100-point research-score UI and scheduled publisher: PASS");
