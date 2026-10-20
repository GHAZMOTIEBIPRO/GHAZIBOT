from datetime import datetime, timezone

from options_radar.chain_analytics import analyze
from scripts.build_options_analytics import build

NOW = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)


def opt(exp, cp, strike, bid, ask, iv, delta, oi=500, vol=50, root="AAPL"):
    return {"option": f"{root}{exp}{cp}{int(strike * 1000):08d}", "bid": bid, "ask": ask,
            "iv": iv, "delta": delta, "open_interest": oi, "volume": vol}


def chain(spot=200.0):
    rows = [
        opt("261023", "C", 200, 3.0, 3.2, 0.30, 0.52),
        opt("261023", "P", 200, 2.8, 3.0, 0.32, -0.48),
        opt("261023", "C", 210, 0.9, 1.0, 0.28, 0.25, oi=2000),
        opt("261023", "P", 190, 1.1, 1.2, 0.36, -0.25, oi=3000),
        opt("261023", "C", 205, 1.8, 2.6, 0.29, 0.40),          # spread 36%: screened out
        opt("261030", "C", 200, 4.0, 4.2, 0.27, 0.51),
        opt("261030", "P", 200, 3.9, 4.1, 0.29, -0.49),
        opt("261016", "C", 200, 9.0, 9.2, 0.30, 0.5),            # expired: ignored
        opt("261023", "C", 195, 0.0, 6.0, 0.31, 0.6),            # one-sided: no mid
    ]
    return {"timestamp": "2026-10-20 10:55:00", "data": {"current_price": spot, "options": rows}}


def test_expected_move_iv_skew_oi_and_screen_from_delayed_chain():
    out = analyze("AAPL", chain(), now=NOW)
    assert out["status"] == "OK" and out["execution_grade"] is False and out["probability"] is None
    em = out["expected_move"]
    assert em["expiry"] == "2026-10-23" and em["atm_strike"] == 200
    assert em["move_abs"] == 6.0 and em["move_pct"] == 3.0  # 3.1 + 2.9
    assert em["range_low"] == 194.0 and em["data_class"] == "DELAYED_QUOTE"
    assert [t["expiry"] for t in out["atm_iv_term"]] == ["2026-10-23", "2026-10-30"]
    assert out["atm_iv_term"][0]["atm_iv"] == 0.31
    assert out["skew_25d"]["put_minus_call"] == 0.08
    assert out["oi_concentration"]["put"][0] == {"strike": 190, "oi": 3000}
    calls = out["liquid_contract_screen"]["call"]
    # 205 too wide, 210 delta too low; tightest spread first (4.88% < 6.45%).
    assert [(c["expiry"], c["strike"]) for c in calls] == [("2026-10-30", 200), ("2026-10-23", 200)]
    assert "mid" not in calls[0] and "bid" not in calls[0]  # no raw quotes republished


def test_missing_spot_or_chain_is_unavailable_not_zero():
    assert analyze("AAPL", {"data": {"current_price": None, "options": []}}, now=NOW)["status"] == "DATA_UNAVAILABLE"
    assert analyze("AAPL", {}, now=NOW)["status"] == "DATA_UNAVAILABLE"


def test_build_records_per_symbol_errors_and_keeps_going():
    def fetch(symbol):
        if symbol == "BAD":
            raise TimeoutError("slow")
        return chain()
    report = build(("AAPL", "BAD"), fetch=fetch, pause=0, now=NOW)
    assert report["symbols"]["AAPL"]["status"] == "OK"
    assert report["errors"] == {"BAD": "TimeoutError"}
    assert report["raw_quotes_published"] is False
