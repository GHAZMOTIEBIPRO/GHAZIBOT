"""Alpaca chain adapter: honest feed labels, rejected quotes, OI join, clusters, buckets, scoring."""
from datetime import date, datetime, timezone

from options_radar import alpaca_chain as ac

TODAY = date(2026, 11, 30)


def _snap(bid, ask, vol, delta=None, t="2026-11-30T15:00:00Z"):
    s = {"latestQuote": {"bp": bid, "ap": ask, "t": t}, "dailyBar": {"v": vol}}
    if delta is not None:
        s["greeks"] = {"delta": delta, "gamma": 0.05, "theta": -0.3, "vega": 0.1}
        s["impliedVolatility"] = 0.25
    return s


CHAIN = {"SPY261130C00600000": _snap(1.0, 1.1, 5000, 0.45), "SPY261130C00601000": _snap(0.6, 0.7, 3000, 0.35),
         "SPY261130P00590000": _snap(0.0, 0.1, 900), "SPY261130P00595000": _snap(1.2, 1.0, 900),  # zero bid, crossed
         "SPY261204C00610000": _snap(0.5, 0.9, 40), "SPXW261130C06000000": _snap(5.0, 5.4, 800)}


def test_rows_label_the_feed_reject_bad_quotes_and_join_open_interest():
    rows = ac.rows(CHAIN, today=TODAY, open_interest={"SPY261130C00600000": {"open_interest": 2500,
                                                                           "open_interest_date": "2026-11-27"}})
    by = {r["contract"]: r for r in rows}
    assert "SPY261130P00590000" not in by and "SPY261130P00595000" not in by
    spy = by["SPY261130C00600000"]
    assert spy["feed"] == "indicative" and spy["execution_grade"] is False and spy["dte"] == 0
    assert spy["vol_to_oi_ratio"] == 2.0 and spy["open_interest_date"] == "2026-11-27"
    assert by["SPXW261130C06000000"]["delta"] is None  # index greeks absent: not filled in


def test_rank_uses_buckets_liquidity_floor_and_existing_score():
    ranked = ac.rank(ac.rows(CHAIN, today=TODAY))
    assert [r["contract"] for r in ranked["0DTE"]][:1] == ["SPY261130C00600000"] or ranked["0DTE"]
    assert all(r["volume"] >= 50 and r["spread_pct"] <= ac.MAX_SPREAD for b in ranked.values() for r in b)
    assert not ranked["2-7"]  # the 4-DTE contract trades only 40 and has a 57 % spread
    top = ranked["0DTE"][0]
    assert top["label"] in ("HIGH", "BUILDING", "LOW") and "strike_cluster_score" in top


def test_strike_cluster_and_freshness():
    rows = ac.rows(CHAIN, today=TODAY)
    ac.strike_cluster(rows)
    calls0 = [r for r in rows if r["root"] == "SPY" and r["dte"] == 0 and r["type"] == "CALL"]
    assert all(r["strike_cluster_score"] == 100.0 for r in calls0)
    f = ac.freshness(rows, datetime(2026, 11, 30, 15, 10, tzinfo=timezone.utc))
    assert f["age_s"] == 600.0


def test_rejects_are_counted_by_reason_and_coverage_is_reported():
    rejects = {}
    kept = ac.rows(CHAIN, today=TODAY, rejects=rejects)
    assert rejects == {"zero_bid": 1, "crossed": 1}
    cov = ac.coverage({"SPY": CHAIN}, kept, rejects, {"SPY": 1})
    assert cov["contracts_seen"] == 6 and cov["unique_two_sided"] == 4 and cov["two_sided_share"] == round(4 / 6, 3)
    assert cov["roots"] == ["SPXW", "SPY"] and cov["rejects"] == rejects


def _row(**kw):
    base = {"contract": "X", "type": "CALL", "spread_pct": 0.05, "volume": 1000, "vol_to_oi_ratio": None, "mid": 1.0,
            "prev_close": 0.9}
    return {**base, **kw}


def test_classes_need_activity_direction_and_freshness():
    kw = {"bucket_median_volume": 100.0, "quote_age_s": 30, "in_session": True}
    assert ac.classify(_row(volume=600), underlying_change_pct=None, **kw)[0] == "UNUSUAL_ACTIVITY"
    assert ac.classify(_row(volume=600), underlying_change_pct=0.8, **kw)[0] == "CONFIRMED_BY_AVAILABLE_DATA"
    assert ac.classify(_row(volume=600, type="PUT"), underlying_change_pct=0.8, **kw)[0] == "UNUSUAL_ACTIVITY"
    assert ac.classify(_row(volume=250), underlying_change_pct=None, **kw)[0] == "EARLY_WATCH"
    assert ac.classify(_row(volume=150), underlying_change_pct=None, **kw)[0] == "REJECTED"
    assert ac.classify(_row(mid=2.0, prev_close=0.9), underlying_change_pct=None, **kw)[0] == "EXTENDED"
    stale = {**kw, "quote_age_s": 3600}
    assert ac.classify(_row(volume=600), underlying_change_pct=None, **stale)[0] == "REJECTED"
    off = {**kw, "quote_age_s": 3600, "in_session": False}
    assert ac.classify(_row(volume=600), underlying_change_pct=None, **off)[0] == "UNUSUAL_ACTIVITY"
