"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(require("node:path").join(__dirname, "../public/market-chart.js"), "utf8");
const context = {
  document: { addEventListener() {} }, Date, Number, Math, console,
};
vm.createContext(context);
vm.runInContext(source, context, { filename: "market-chart.js" });

const bars = Array.from({ length: 60 }, (_, i) => {
  const date = new Date(Date.UTC(2026, 0, 1 + i)).toISOString().slice(0, 10);
  return { time: date, open: 100, high: 101, low: 99, close: 100 };
});
let metrics = context.ghaziChartResearchLevels(bars);
assert.equal(metrics.ema20, 100);
assert.equal(metrics.ema50, 100);
assert.equal(metrics.resistance20, 101);
assert.equal(metrics.support20, 99);
assert.equal(metrics.breakout, "NONE");
assert.equal(metrics.execution_grade, false);
assert.equal(metrics.probability, null);

const breakout = bars.map(x => ({ ...x }));
breakout[59] = { ...breakout[59], open: 100, high: 111, close: 110 };
metrics = context.ghaziChartResearchLevels(breakout);
assert.equal(metrics.breakout, "ABOVE_PRIOR_20_HIGH");
assert.equal(metrics.resistance20, 101); // No look-ahead to the current close.
assert.ok(metrics.ema20 > 100);

const breakdown = bars.map(x => ({ ...x }));
breakdown[59] = { ...breakdown[59], open: 100, low: 89, close: 90 };
metrics = context.ghaziChartResearchLevels(breakdown);
assert.equal(metrics.breakout, "BELOW_PRIOR_20_LOW");

assert.equal(context.ghaziChartResearchLevels(bars.slice(0, 10)).ema20, null);
assert.equal(context.ghaziChartResearchLevels(bars.slice(0, 10)).resistance20, null);
assert.equal(context.ghaziChartResearchLevels([{ ...bars[0], close: 120 }]), null);
assert.equal(context.ghaziChartResearchLevels([bars[1], bars[0]]), null);
assert.equal(context.ghaziChartResearchLevels([bars[0], bars[0]]), null);
assert.equal(context.ghaziChartResearchLevels([{ ...bars[0], open: null }]), null);
assert.equal(context.ghaziChartResearchLevels([{ ...bars[0], high: "NaN" }]), null);
assert.equal(context.ghaziFinitePositive(null), null);
assert.equal(context.ghaziFinitePositive(""), null);
assert.equal(context.ghaziFinitePositive(-3), null);

const lines = [];
const series = { createPriceLine(x) { lines.push(x); } };
context.ghaziAddPriceLine(series, null, "missing");
context.ghaziAddPriceLine(series, "NaN", "missing");
context.ghaziAddPriceLine(series, 450, "valid");
assert.equal(lines.length, 1);
assert.equal(lines[0].price, 450);
console.log("market chart overlays: 17 assertions passed");
