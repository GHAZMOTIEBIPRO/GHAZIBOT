"""Black-76 model Greeks on the parity forward: arbitrage-consistent, refused on bad inputs."""
from datetime import datetime, timezone

from options_radar import alpaca_chain as ac
from options_radar import black76 as b

F, K, T = 6000.0, 6000.0, 3 / 365


def test_put_call_parity_and_iv_round_trip():
    c, p = b.price(F, K, T, 0.15, 0.0, True), b.price(F, K, T, 0.15, 0.0, False)
    assert abs((c - p) - (F - K)) < 1e-9
    g = b.greeks(premium=c, forward=F, strike=K, years=T, rate=0.0, call=True)
    assert g["status"] == "OK" and abs(g["iv"] - 0.15) < 1e-3 and 0.45 < g["delta"] < 0.55
    put = b.greeks(premium=p, forward=F, strike=K, years=T, rate=0.0, call=False)
    assert abs(g["delta"] - put["delta"] - 1) < 1e-3 and g["gamma"] == put["gamma"] and g["theta"] < 0


def test_refuses_without_valid_inputs():
    assert b.greeks(premium=None, forward=F, strike=K, years=T, rate=0, call=True)["status"] == "INPUT_MISSING"
    assert b.greeks(premium=5, forward=None, strike=K, years=T, rate=0, call=True)["status"] == "INPUT_MISSING"
    below_intrinsic = b.greeks(premium=50, forward=6100, strike=6000, years=T, rate=0, call=True)
    assert below_intrinsic["status"] == "NO_IMPLIED_VOL"


def test_model_greeks_fill_only_missing_index_rows_on_an_ok_forward(monkeypatch):
    from scripts import run_options_hunter as h

    now = datetime(2026, 11, 30, 15, 0, tzinfo=timezone.utc)
    rows = [{"root": "SPXW", "expiry": "2026-12-02", "type": "CALL", "strike": 6000.0, "mid": 30.0, "delta": None},
            {"root": "SPXW", "expiry": "2026-12-02", "type": "PUT", "strike": 6000.0, "mid": 28.0, "delta": -0.4,
             "greeks_source": "provider_indicative"},
            {"root": "NDXP", "expiry": "2026-12-02", "type": "CALL", "strike": 21000.0, "mid": 90.0, "delta": None}]
    monkeypatch.setattr(h.pr, "implied_forward", lambda snaps, root, **kw: (
        {"status": "OK", "forward": 6002.0} if root == "SPXW" else {"status": "LOW_QUALITY"}))
    status = h.model_greeks(rows, {"SPXW": {}, "NDXP": {}}, now)
    assert status == {"SPXW:2026-12-02": "OK", "NDXP:2026-12-02": "LOW_QUALITY"}
    assert rows[0]["greeks_source"] == b.SOURCE and rows[0]["forward_basis"] == "IMPLIED_FORWARD_NOT_CASH_INDEX"
    assert rows[1]["delta"] == -0.4 and rows[1]["greeks_source"] == "provider_indicative"  # provider kept
    assert rows[2]["delta"] is None  # a low-quality forward gives no Greeks


def test_coverage_counts_eligible_and_dte_buckets_and_confirmed_wording():
    rows = [{"contract": "A", "root": "SPY", "expiry": "2026-12-01", "dte": 0, "spread_pct": 0.05, "volume": 1,
             "iv": 0.2, "greeks_source": "provider_indicative"},
            {"contract": "B", "root": "SPY", "expiry": "2026-12-01", "dte": 20, "spread_pct": 0.6, "volume": 0,
             "iv": None, "greeks_source": None}]
    cov = ac.coverage({"SPY": {"A": {}, "B": {}, "C": {}}}, rows, {"zero_bid": 1}, {"SPY": 1})
    assert cov["eligible"] == 1 and cov["with_iv"] == 1 and cov["greeks_by_source"] == {"none": 1, "provider_indicative": 1}
    assert sum(cov["by_dte_bucket"].values()) == 2
    assert "ليس تأكيد دخول" in ac.CLASS_AR["CONFIRMED_BY_AVAILABLE_DATA"]
