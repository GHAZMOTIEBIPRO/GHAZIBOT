import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("public_macro_under_test", ROOT / "options_radar" / "public_macro.py")
macro = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(macro)


def cftc_rows(code="13874A", name="E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE", weeks=60, last_lev_net=None):
    start = date(2025, 8, 26)
    rows = []
    for i in range(weeks):
        lev_long = 100_000 + i * 1_000
        lev_short = 150_000
        if last_lev_net is not None and i == weeks - 1:
            lev_long = lev_short + last_lev_net
        rows.append({
            "cftc_contract_market_code": code,
            "market_and_exchange_names": name,
            "report_date_as_yyyy_mm_dd": (start + timedelta(weeks=i)).isoformat() + "T00:00:00.000",
            "open_interest_all": "2000000",
            "dealer_positions_long_all": "300000", "dealer_positions_short_all": "250000",
            "asset_mgr_positions_long": "900000", "asset_mgr_positions_short": "200000",
            "lev_money_positions_long": str(lev_long), "lev_money_positions_short": str(lev_short),
        })
    return rows


def test_cot_positioning_nets_changes_and_three_year_index():
    out = macro.cot_positioning(cftc_rows())["ES"]
    assert out["available"] is True and out["weeks"] == 60
    assert out["positions_as_of"] == (date(2025, 8, 26) + timedelta(weeks=59)).isoformat()
    lev = out["categories"]["leveraged_funds"]
    assert lev["net"] == 100_000 + 59_000 - 150_000
    assert lev["weekly_change"] == 1_000
    assert lev["cot_index_3y"] == 100.0 and lev["extreme"] == "HIGH"
    # Constant net has no range, so no index rather than a fake 0/100.
    assert out["categories"]["dealer"]["cot_index_3y"] is None


def test_cot_index_needs_a_year_of_history():
    out = macro.cot_positioning(cftc_rows(weeks=20))["ES"]
    assert out["categories"]["leveraged_funds"]["cot_index_3y"] is None


def test_code_pointing_at_another_market_is_refused():
    out = macro.cot_positioning(cftc_rows(name="SOMETHING ELSE - CME"))["ES"]
    assert out["available"] is False and "names" in out["reason"]
    assert macro.cot_positioning([])["NQ"]["available"] is False


def test_duplicate_report_dates_count_once():
    rows = cftc_rows(weeks=55)
    out = macro.cot_positioning(rows + rows[-3:])["ES"]
    assert out["weeks"] == 55


TREASURY = """Date,"1 Mo","3 Mo","2 Yr","5 Yr","10 Yr","30 Yr"
10/16/2026,4.10,4.00,3.60,3.70,4.10,4.60
10/15/2026,4.10,4.00,3.70,3.70,4.05,4.60
10/14/2026,4.10,4.00,3.70,3.70,4.00,4.60
10/13/2026,4.10,4.00,3.70,3.70,4.00,4.60
10/10/2026,4.10,4.00,3.70,3.70,4.00,4.60
10/09/2026,4.10,4.00,3.80,3.70,3.95,4.60
bad,row
"""


def test_treasury_curve_spreads_changes_and_inversion():
    curve = macro.treasury_curve(macro.parse_treasury_csv(TREASURY))
    assert curve["available"] is True and curve["curve_date"] == "2026-10-16"
    assert curve["spreads_bp"] == {"10Y_2Y": 50.0, "10Y_3M": 10.0}
    assert curve["inverted"] == {"10Y_2Y": False, "10Y_3M": False}
    assert curve["change_bp"]["10Y"]["5_sessions"] == 15.0
    assert curve["change_bp"]["2Y"]["5_sessions"] == -20.0
    assert curve["change_bp"]["10Y"]["20_sessions"] is None
    assert macro.treasury_curve([])["available"] is False


def test_report_policy_and_no_authority():
    report = macro.build(cftc_rows(), macro.parse_treasury_csv(TREASURY), generated_at="2026-10-20T12:00:00+00:00")
    assert report["schema"] == "ghazi.public_macro.v1"
    assert report["decision_authority"] is False and report["execution_authority"] is False
    json.dumps(report, allow_nan=False)


def test_script_keeps_previous_file_when_nothing_validates(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("build_public_macro_under_test", ROOT / "scripts" / "build_public_macro.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    out = tmp_path / "public_macro.json"
    out.write_text('{"keep": true}')
    monkeypatch.setattr(script, "_get", lambda url, attempts=3: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(sys, "argv", ["x", "--output", str(out)])
    assert script.main() == 1
    assert json.loads(out.read_text()) == {"keep": True}
    monkeypatch.setattr(script, "cftc_rows", lambda: cftc_rows())
    assert script.main() == 0
    assert json.loads(out.read_text())["cftc_index_futures"]["ES"]["available"] is True
