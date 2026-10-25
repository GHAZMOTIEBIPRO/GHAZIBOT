"""Drift-change detection in public macro series (ruptures).

The first version segmented levels and flagged 5 breaks on 100% of random
walks with no change; these tests keep that failure from coming back.
"""
import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
pytest.importorskip("ruptures")
_spec = importlib.util.spec_from_file_location("macro_regimes_under_test", ROOT / "options_radar/macro_regimes.py")
mr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mr)
_mspec = importlib.util.spec_from_file_location("public_macro_under_test", ROOT / "options_radar/public_macro.py")
pm = importlib.util.module_from_spec(_mspec)
_mspec.loader.exec_module(pm)


def _days(n, start=date(2025, 1, 2)):
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


def _spec_for(values, frequency="daily", lag=0):
    return {"frequency": frequency, "unit": "bp", "source": "test", "release_lag_days": lag,
            "dates": _days(len(values)), "values": [round(float(v), 3) for v in values]}


@pytest.mark.parametrize("kind", ["gaussian", "student_t3", "jumps"])
def test_random_walks_without_change_rarely_break(kind):
    rng = np.random.default_rng({"gaussian": 1, "student_t3": 2, "jumps": 3}[kind])
    flagged = 0
    for _ in range(40):
        steps = rng.normal(0, 3, 450) if kind == "gaussian" else rng.standard_t(3, 450) * 2
        if kind == "jumps":
            steps = steps + np.where(np.isin(np.arange(450), [100, 300]), 25, 0)
        report = mr.regime_report("x", _spec_for(np.cumsum(steps)))
        flagged += bool(report["breaks"])
    assert flagged <= 4  # <= 10% of runs; calibration measured 3-5%


def test_known_drift_shift_is_found_and_dated_when_knowable():
    rng = np.random.default_rng(5)
    steps = np.r_[rng.normal(0, 2, 300), rng.normal(2.0, 2, 150)]
    report = mr.regime_report("treasury_10y_2y_bp", _spec_for(100 + np.cumsum(steps)))
    assert report["available"] is True and len(report["breaks"]) >= 1
    first = report["breaks"][0]
    index = _days(451).index(first["date"])
    assert abs(index - 301) <= 20
    assert first["hindsight_only"] is False
    # Knowable only after the break, using data that existed then.
    assert first["detectable_from"] > first["date"]
    current = report["current_regime"]
    assert current["mean_change"] == pytest.approx(2.0, abs=0.5)
    assert current["previous_mean_change"] == pytest.approx(0.0, abs=0.4)
    assert report["method"]["input"] == "period changes"


def test_cftc_publication_lag_shifts_detectable_from():
    rng = np.random.default_rng(8)
    steps = np.r_[rng.normal(0, 1000, 100), rng.normal(3000, 1000, 56)]
    plain = mr.regime_report("w", _spec_for(np.cumsum(steps), "weekly", 0))
    lagged = mr.regime_report("w", _spec_for(np.cumsum(steps), "weekly", 3))
    assert plain["breaks"] and lagged["breaks"]
    a = date.fromisoformat(plain["breaks"][0]["detectable_from"])
    b = date.fromisoformat(lagged["breaks"][0]["detectable_from"])
    assert (b - a).days == 3 and lagged["release_lag_days"] == 3


def test_short_bad_and_flat_series():
    assert mr.regime_report("x", _spec_for([1.0] * 30, "weekly"))["available"] is False
    bad = _spec_for([1.0] * 200)
    bad["values"][-1] = float("nan")
    assert mr.regime_report("x", bad)["available"] is False
    flat = mr.regime_report("x", _spec_for([3.0] * 200))
    assert flat["available"] is True and flat["breaks"] == []
    built = mr.build({"generated_at": "t", "series": {"x": _spec_for(np.arange(200.0))}}, generated_at="t")
    assert built["schema"] == "ghazi.macro_regimes.v2" and built["decision_authority"] is False
    assert mr.build({}, generated_at="t")["status"] == "DATA_UNAVAILABLE"


def test_history_series_from_raw_cftc_and_treasury_rows():
    curve = [{"date": date(2025, 1, 1) + timedelta(days=i), "2Y": 4.0, "10Y": 4.5 + i / 1000, "3M": 4.2}
             for i in range(5)]
    cot = [{"cftc_contract_market_code": "13874A", "report_date_as_yyyy_mm_dd": f"2026-10-{d:02d}T00:00:00.000",
            "market_and_exchange_names": "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
            "asset_mgr_positions_long": "100", "asset_mgr_positions_short": "40",
            "lev_money_positions_long": "10", "lev_money_positions_short": "30"} for d in (6, 13, 20)]
    cot.append({**cot[0], "cftc_contract_market_code": "209742", "market_and_exchange_names": "SOMETHING ELSE"})
    series = pm.history_series(cot, curve)
    assert series["treasury_10y_2y_bp"]["values"][0] == 50.0 and len(series["treasury_10y_pct"]["dates"]) == 5
    assert series["cftc_ES_asset_manager_net"]["values"] == [60, 60, 60]
    assert series["cftc_ES_leveraged_funds_net"]["release_lag_days"] == 3
    assert not any(k.startswith("cftc_NQ") for k in series)
    json.dumps(series)


def test_workflow_single_writer_and_failures_never_block_macro_publish():
    wf = yaml.safe_load((ROOT / ".github/workflows/public-macro.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["update-public-macro"]["steps"]
    regime = next(s for s in steps if s.get("name", "").startswith("Structural breaks"))
    assert regime.get("continue-on-error") is True and "steps.macro.outcome == 'success'" in regime["if"]
    assert "ruptures==1.1.9" in next(s for s in steps if s.get("id") == "regime_deps")["run"]
    writers = [p.name for p in (ROOT / ".github/workflows").glob("*.yml")
               if "macro_regimes.json" in p.read_text(encoding="utf-8")]
    assert writers == ["public-macro.yml"]
