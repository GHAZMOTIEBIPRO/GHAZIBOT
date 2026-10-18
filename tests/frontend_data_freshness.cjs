/* Offline regression for GHAZI RADAR snapshot selection. No external network. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const src = fs.readFileSync("public/app.js", "utf8");
const start = src.indexOf("async function fetchDataFreshnessRank()");
const end = src.indexOf("\nasync function fetchLiveStatus()", start);
assert.ok(start >= 0 && end > start, "data-source selection functions exist");
const algorithm = src.slice(start, end);
const now = Date.now();
const iso = minutes => new Date(now - minutes * 60000).toISOString();

function context(records, accesses = []) {
  const sandbox = {
    Date, Promise, String, Number, Error,
    DATA_URLS: ["state-latest", "main-latest", "local-latest"],
    DATA_META_URLS: ["state-status", "main-status", "local-status"],
    fetch: async url => {
      const key = url.split("?")[0];
      accesses.push(key);
      if (!records[key]) return {ok:false, status:404};
      return {ok:true, json:async () => records[key]};
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(algorithm, sandbox);
  return sandbox;
}

(async () => {
  // A newer main mirror must win over the stale-but-present runtime copy.
  const first = context({
    "state-status": {generated_at:iso(70)},
    "main-status": {generated_at:iso(2)},
    "local-status": {generated_at:iso(70)},
    "state-latest": {generated_at:iso(70), source:"stale-runtime"},
    "main-latest": {generated_at:iso(2), source:"fresh-main"},
  });
  assert.equal((await first.fetchRadarData()).source, "fresh-main");

  // If the metadata outruns the actual payload, inspect the other candidate.
  const second = context({
    "state-status": {generated_at:iso(25)},
    "main-status": {generated_at:iso(1)},
    "state-latest": {generated_at:iso(20), source:"valid-runtime"},
    "main-latest": {generated_at:iso(100), source:"old-main-payload"},
  });
  assert.equal((await second.fetchRadarData()).source, "valid-runtime");

  // When metadata is unavailable, preserve the known fallback chain.
  const third = context({
    "main-latest": {generated_at:iso(15), source:"main-fallback"},
  });
  assert.equal((await third.fetchRadarData()).source, "main-fallback");

  // Reject invalid/future clocks rather than incorrectly calling them current.
  const fourth = context({
    "state-status": {generated_at:iso(1)},
    "state-latest": {generated_at:new Date(now + 60*60000).toISOString()},
  });
  await assert.rejects(() => fourth.fetchRadarData());

  // Prefer a single large download when status metadata and payload agree.
  const accesses = [];
  const fifth = context({
    "state-status": {generated_at:iso(3)},
    "main-status": {generated_at:iso(30)},
    "state-latest": {generated_at:iso(3), source:"efficient"},
    "main-latest": {generated_at:iso(30), source:"wasteful"},
  }, accesses);
  assert.equal((await fifth.fetchRadarData()).source, "efficient");
  assert.deepEqual(accesses.filter(s => s.endsWith("-latest")), ["state-latest"]);
  process.stdout.write("GHAZI RADAR dataset selection regressions passed\n");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
