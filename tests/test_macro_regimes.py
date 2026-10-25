"""Change points in public macro series (ruptures): known breaks found, noise left alone."""
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


def test_known_level_shifts_are_found_near_their_dates():
    rng = np.random.default_rng(7)
    values = np.concatenate([rng.normal(-40, 3, 150), rng.normal(10, 3, 120), rng.normal(45, 3, 130)])
    report = mr.regime_report("treasury_10y_2y_bp", {"frequency": "daily", "unit": "bp", "source": "test",
                                                   "dates": _days(400), "values": [round(v, 1) for v in values]})
    assert report["available"] is True
    idx = [_days(400).index(d) for d in report["change_points"]]
    assert len(idx) == 2 and abs(idx[0] - 150) <= 3 and abs(idx[1] - 270) <= 3
    current = report["current_regime"]
    assert current["since"] == report["change_points"][-1]
    assert current["mean"] == pytest.approx(45, abs=1.5) and current["previous_mean"] == pytest.approx(10, abs=1.5)
    assert current["shift"] == pytest.approx(35, abs=2)
    assert report["method"]["library"] == "ruptures" and report["method"]["cost"] == "l2"


def test_pure_noise_has_no_breaks_and_short_or_bad_series_are_refused():
    rng = np.random.default_rng(11)
    noise = mr.regime_report("x", {"frequency": "daily", "dates": _days(300),
                                   "values": list(rng.normal(0, 5, 300))})
    assert noise["available"] is True and noise["change_points"] == []
    assert noise["current_regime"]["previous_mean"] is None and noise["current_regime"]["shift"] is None
    short = mr.regime_report("x", {"frequency": "weekly", "dates": _days(30), "values": [1.0] * 30})
    assert short["available"] is False and "52" in short["reason"]
    bad = mr.regime_report("x", {"frequency": "daily", "dates": _days(200), "values": [1.0] * 199 + [float("nan")]})
    assert bad["available"] is False
    flat = mr.regime_report("x", {"frequency": "daily", "dates": _days(200), "values": [3.0] * 200})
    assert flat["available"] is True and flat["change_points"] == []


def test_breaks_are_capped_and_the_report_is_research_only():
    values = []
    for k in range(10):
        values += [k * 50.0 + (i % 2) for i in range(25)]
    report = mr.regime_report("x", {"frequency": "daily", "dates": _days(len(values)), "values": values})
    assert len(report["change_points"]) <= mr.MAX_BREAKS
    built = mr.build({"generated_at": "2026-10-24T01:00:00+00:00", "series": {
        "x": {"frequency": "daily", "dates": _days(len(values)), "values": values}}}, generated_at="t")
    assert built["status"] == "AVAILABLE" and built["research_only"] is True and built["decision_authority"] is False
    assert mr.build({}, generated_at="t")["status"] == "DATA_UNAVAILABLE"


def test_history_series_from_raw_cftc_and_treasury_rows():
    curve = [{"date": date(2025, 1, 1) + timedelta(days=i), "2Y": 4.0, "10Y": 4.5 + i / 1000, "3M": 4.2}
             for i in range(5)]
    cot = [{"cftc_contract_market_code": "13874A", "report_date_as_yyyy_mm_dd": f"2026-10-{d:02d}T00:00:00.000",
            "market_and_exchange_names": "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
            "asset_mgr_positions_long": "100", "asset_mgr_positions_short": "40",
            "lev_money_positions_long": "10", "lev_money_positions_short": "30"} for d in (6, 13, 20)]
    cot.append({**cot[0], "cftc_contract_market_code": "209742",
                "market_and_exchange_names": "SOMETHING ELSE"})
    series = pm.history_series(cot, curve)
    assert series["treasury_10y_2y_bp"]["values"][0] == 50.0 and len(series["treasury_10y_pct"]["dates"]) == 5
    assert series["cftc_ES_asset_manager_net"]["values"] == [60, 60, 60]
    assert series["cftc_ES_leveraged_funds_net"]["frequency"] == "weekly"
    assert not any(k.startswith("cftc_NQ") for k in series)  # name no longer matches the code
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
