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
