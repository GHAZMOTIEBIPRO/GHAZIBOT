"""Regression coverage for SPX display authority and runtime artifact ordering."""
import ast
import importlib.util
import subprocess
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SpxDataHonestyTests(unittest.TestCase):
    def test_browser_rejects_missing_stale_future_and_legacy_signals(self):
        script = r'''
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
let source = fs.readFileSync('public/spx/spx.js', 'utf8');
source = source.slice(0, source.indexOf('\nsetInterval('));
const context = vm.createContext({});
vm.runInContext(source, context);
vm.runInContext(`
  globalThis.api = {num, fmt, decide};
`, context);
const {num, fmt, decide} = context.api;
for (const missing of [null, undefined, '', '  ', false, true, [], {}, 'NaN', Infinity]) {
  assert.equal(num(missing), null, 'missing value must not become zero');
}
assert.equal(num(0), 0);
assert.equal(num('12.5'), 12.5);
assert.equal(fmt(null), '—');
const now = Date.parse('2026-10-09T15:00:00Z');
const base = {spot: 6700, vwap: 6690, rsi: 60, age_minutes: 1,
 market_bar_time: '2026-10-09T14:55:00Z',
 trade_map: {state: 'CALL', reason_ar: 'research', call_above: 6695}};
assert.equal(decide(base, {}, now).s, 'CALL');
for (const stamp of [undefined, null, '', 'bad', '2026-10-09T14:55:00',
                     '2026-10-08T14:55:00Z', '2026-10-09T15:05:00Z']) {
  const result = decide({...base, market_bar_time: stamp}, {}, now);
  assert.equal(result.s, 'WAIT', 'unverifiable or stale bar must close the gate');
  assert.equal(result.confidence, null);
}
assert.equal(decide({...base, vwap: null}, {}, now).s, 'WAIT');
const legacy = decide({...base, trade_map: undefined},
 {directional_signals: [{symbol: 'SPX', direction: 'CALL', free_alert_eligible: true}]}, now);
assert.equal(legacy.s, 'WAIT');
assert.equal(legacy.confidence, null);
'''
        subprocess.run(["node", "-e", script], cwd=ROOT, check=True)

    def test_python_map_rejects_negative_age_and_missing_vwap(self):
        spec = importlib.util.spec_from_file_location(
            "spx_decision_under_test", ROOT / "options_radar/spx_decision.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for overrides in ({"age_minutes": -1}, {"vwap": None}):
            payload = {"spot": 6700, "vwap": 6690, "age_minutes": 1, **overrides}
            result = module.build_spx_trade_map(payload)
            self.assertEqual(result["state"], "DATA_INSUFFICIENT")
            self.assertIsNone(result["call_above"])

    def test_zero_volume_never_substitutes_spot_for_vwap(self):
        workflow = (ROOT / ".github/workflows/spx-dashboard.yml").read_text()
        code = workflow.split("python - <<'PY'\n", 1)[1].split("\n          PY", 1)[0]
        tree = ast.parse(textwrap.dedent(code))
        assignment = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "vwap" for target in node.targets)
        )

        class EmptyVolume:
            def sum(self):
                return 0

        value = eval(compile(ast.Expression(assignment.value), "workflow", "eval"),
                     {"vol": EmptyVolume()})
        self.assertIsNone(value)

    def test_result_upload_precedes_destructive_main_reset(self):
        workflow = (ROOT / ".github/workflows/options-radar.yml").read_text()
        self.assertLess(
            workflow.index("- name: Upload result files"),
            workflow.index("- name: Mirror fresh safe health metadata to main for Vercel"),
        )


if __name__ == "__main__":
    unittest.main()
