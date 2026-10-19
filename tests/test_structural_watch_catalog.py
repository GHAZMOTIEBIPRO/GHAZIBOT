"""No made-up prices in the expanded free smallcap watch catalog."""
from datetime import datetime, timedelta, timezone

from scripts.build_structural_watch_catalog import build

NOW = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)


def row(symbol="MICR", **other):
    return dict(symbol=symbol, company_name="Example Smallcap",
                nasdaq_market_cap=50_000_000, nasdaq_price=2.0,
                float_shares=2_000_000, structural_score=78, **other)


def snapshot(rows, when=NOW):
    return {"generated_at": when.isoformat(),
            "market_rows_seen": 7002,
            "candidates": rows}


def test_expands_screener_without_fake_quotes_or_trade_permission():
    data = build(snapshot([row("MICR"), row("ABCD")]), now=NOW)
    assert data["schema"] == "ghazi.structural_watch.v1"
    assert data["status"] == "RESEARCH_SNAPSHOT"
    assert data["universe_rows_screened"] == 7002
    assert len(data["candidates"]) == 2
    first = data["candidates"][0]
    assert first["float_shares_unverified"] == 2_000_000
    assert first["last_nasdaq_price_observed"] is None
    assert first["execution_eligible"] is False
    assert first["chart_available"] is False
    assert first["official_catalyst_verified"] is False
    assert not data["option_execution_ready"]


def test_stale_snapshot_never_rolls_observation_clock_forward():
    data = build(snapshot([row()], NOW-timedelta(days=9)), now=NOW)
    assert data["status"] == "STALE_OR_INVALID"
    assert data["candidates"] == []
    assert data["source_observed_at"] != data["generated_at"]
    future = build(snapshot([row()], NOW+timedelta(minutes=15)), now=NOW)
    assert future["candidates"] == []


def test_excludes_uncertain_market_cap_and_duplicate_or_bad_tickers():
    rows = [row("MICR"), row("MICR"),
            dict(row("BADX"), nasdaq_market_cap=0),
            dict(row("SPY")), row("AA/W"),
            dict(row("HIGH"), nasdaq_market_cap=10_000_000_000)]
    data = build(snapshot(rows), now=NOW)
    assert [x["symbol"] for x in data["candidates"]] == ["MICR"]


def test_bounded_truncated_output_for_full_market_scan():
    rows = [row("M"+str(i)) for i in range(99)]
    data = build(snapshot(rows), now=NOW)
    assert len(data["candidates"]) == 60
    assert all(x["last_nasdaq_price_observed"] is None for x in data["candidates"])
