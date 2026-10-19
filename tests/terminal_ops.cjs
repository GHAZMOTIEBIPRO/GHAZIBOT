/* Offline regression for engine health / feed freshness. No network. */
const assert = require("node:assert/strict");
const ops = require("../public/terminal-ops.js");

const now = Date.parse("2026-10-20T15:00:00Z"); // Tuesday 11:00 New York
const ago = m => new Date(now - m * 60000).toISOString();

const engines = ops.engineRows({workflow_health: {paths: {
  fast_discovery: {status: "HEALTHY", generated_at: ago(4), candidate_count: 2},
  stocks: {status: "HEALTHY", generated_at: ago(9), candidate_count: 3},
  options: {status: "STALE", generated_at: ago(178), candidate_count: 0},
  unknown_path: {status: "HEALTHY"},
}}}, now);
assert.deepEqual(engines.map(r => [r.key, r.kind, r.age]),
  [["fast_discovery", "ok", 4], ["stocks", "ok", 9], ["options", "bad", 178]]);
assert.equal(engines[2].label, "متأخر");
assert.deepEqual(ops.summary(engines), {ok: 2, total: 3, kind: "bad"});

// Unknown status never reads as healthy; missing runtime yields nothing.
assert.equal(ops.engineRows({workflow_health: {paths: {stocks: {status: "WEIRD"}}}}, now)[0].kind, "bad");
assert.deepEqual(ops.engineRows(null, now), []);
assert.equal(ops.summary([]).kind, "bad");
// RESEARCH_ONLY is running but not healthy.
assert.equal(ops.engineRows({workflow_health: {paths: {options: {status: "RESEARCH_ONLY"}}}}, now)[0].kind, "warn");

const feeds = ops.feedRows({gamma: ago(30), index: ago(400), sec: undefined, live: ago(-60)}, now);
const byKey = Object.fromEntries(feeds.map(r => [r.key, r]));
assert.equal(byKey.gamma.kind, "ok");
assert.equal(byKey.index.kind, "warn");      // 150 < 400 <= 450
assert.equal(byKey.sec.kind, "bad");         // not loaded
assert.equal(byKey.live.age, null);       // future timestamp is not "fresh"
assert.equal(byKey.live.kind, "bad");

assert.equal(ops.regularSession(now), true);
assert.equal(ops.regularSession(Date.parse("2026-10-20T22:00:00Z")), false);
assert.equal(ops.regularSession(Date.parse("2026-10-24T15:00:00Z")), false); // Saturday
console.log("terminal_ops: ok");
// live_dashboard_status.json shape (single writer) carries its own maximum age.
const live = ops.engineRows({paths: {options: {status: "STALE", generated_at: ago(60), maximum_age_minutes: 45}}}, now);
assert.deepEqual([live[0].kind, live[0].max, live[0].age], ["bad", 45, 60]);
console.log("terminal_ops live shape: ok");
