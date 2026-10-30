"""Adversarial offline tests for free-data gamma / S-R research."""
from datetime import datetime, timedelta, timezone

from options_radar.core_options_strategy import (
    NY, evaluate, gamma_proxy, ohlcv, rank_contracts, technical_levels,
)
from scripts import run_focus_options_private as private

NOW = datetime(2026, 10, 30, 19, 20, tzinfo=timezone.utc)


def bars():
    session_start = datetime(2026, 10, 30, 13, 30, tzinfo=timezone.utc)
    intra = []
    for i in range(68):
        price = (100.0 + .01 * i) if i < 6 else (101.0 + .11 * (i - 6))
        intra.append({"timestamp": (session_start + timedelta(minutes=5*i)).isoformat(),
                      "open": price, "high": price+.12, "low": price-.12,
                      "close": price+.04, "volume": 700})
    daily = []
    for day in (20, 21, 22, 23, 26, 27, 28, 29):
        daily.append({"timestamp": f"2026-10-{day:02d}T04:00:00+00:00",
                      "open": 98, "high": 103, "low": 96, "close": 100,
                      "volume": 500_000})
    return daily, intra


def contract(code="SPY261102C00105000", *, volume=None, feed="indicative"):
    return {"symbol": code, "type": "call", "expiration": "2026-11-02",
            "strike": 105.0, "delta": .47, "gamma": .019,
            "open_interest": 900, "open_interest_date": "2026-10-29",
            "volume": volume,
            "latest_quote": {"timestamp": (NOW-timedelta(seconds=45)).isoformat(),
                             "bid_price": 2.0, "ask_price": 2.06,
                             "bid_size": 18, "ask_size": 12}}


def test_levels_only_completed_and_separate_iex_market_scope():
    daily, intra = bars()
    plan = technical_levels("SPY", daily, intra, now=NOW)
    assert plan["status"] == "RESEARCH_ONLY_IEX"
    assert plan["decision"] == "CALL"
    assert plan["levels"]["previous_day_high"] == 103
    assert plan["levels"]["opening_range_30m_high"] < plan["levels"]["last_completed_5m_close"]
    assert plan["source_scope"] == "IEX_PARTIAL_EXCHANGE_NOT_SIP"
    assert plan["execution_authority"] is False


def test_partial_bar_and_invalid_prices_rejected():
    _, intra = bars()
    intra += [{"timestamp": (NOW-timedelta(minutes=2)).isoformat(),
               "open": 120, "high": 140, "low": 100, "close": 139, "volume": 500},
              {"timestamp": NOW.isoformat(), "open": -1, "high": 1, "low": -2,
               "close": 1, "volume": -2}]
    clean = ohlcv(intra, now=NOW, minutes=5)
    assert all(x["high"] < 130 for x in clean)


def test_gamma_requires_strike_coverage_and_dated_oi():
    thin = gamma_proxy([contract()], spot=105, asof=NOW)
    assert thin["call_wall"] is None
    assert thin["gamma_flip_verified"] is False
    lots = []
    for i in range(20):
        row = contract()
        row.update({"strike": 95+i, "type": "call" if i%2 else "put"})
        lots.append(row)
    full = gamma_proxy(lots, spot=105, asof=NOW)
    assert full["status"] == "PARTIAL_GEX_RESEARCH"
    assert full["call_wall"] is not None
    assert full["dealer_position_verified"] is False
    for row in lots:
        row["open_interest_date"] = "2026-10-01"
    expired_oi = gamma_proxy(lots, spot=105, asof=NOW)
    assert expired_oi["call_wall"] is None
    assert expired_oi["joint_coverage"] == 0


def test_real_indicative_chain_is_research_only_even_with_tight_bid_ask():
    d, intra = bars()
    p = evaluate("SPY", daily=d, bars5=intra, chain=[contract()],
                 now=NOW, feed="indicative")
    assert p["signal_type"] == "WATCH_RESEARCH_ONLY"
    assert p["option"]["status"] == "RESEARCH_CANDIDATES_ONLY"
    row = p["option"]["candidates"][0]
    assert "INDICATIVE_FEED_NOT_EXECUTION_OPRA" in row["blockers"]
    assert "CONTRACT_TODAY_VOLUME_UNVERIFIED" in row["blockers"]
    assert p["execution_authority"] is False
    assert p["public_display_allowed"] is False


def test_stale_quote_blocks_contract_instead_of_inventing_entry():
    c = contract()
    c["latest_quote"]["timestamp"] = (NOW-timedelta(minutes=20)).isoformat()
    assert rank_contracts("SPY", "CALL", [c], spot=105, now=NOW)["candidates"] == []


def test_no_cash_index_price_proxy_or_fake_direction():
    p = evaluate("SPX", daily=[], bars5=[], chain=[], now=NOW)
    assert p["decision"] == "WAIT"
    assert p["execution_authority"] is False


def test_private_collector_no_permission_makes_zero_requests(monkeypatch):
    for env in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY",
                "ALPACA_INTERNAL_DATA_USE_AUTHORIZED", "DATA_TERMS_CONFIRMED"):
        monkeypatch.delenv(env, raising=False)
    class Never:
        def get(self, *args, **kwargs):
            raise AssertionError("No account API network call without consent")
    report = private.run(now=NOW, session=Never())
    assert report["status"] == "BLOCKED_NO_INTERNAL_ENTITLEMENT"
    assert report["public_redistribution_allowed"] is False
    assert report["eligible_execution_signals"] == 0
    assert report["completed"] == 0


def test_private_collector_rejects_incomplete_pages_and_malformed(monkeypatch):
    class Fake:
        def get(self, *_args, **_kwargs):
            class Response:
                status_code = 200
                content = b'{"next_page_token":"further","bars":[]}'
                def json(self):
                    return {"next_page_token": "further", "bars": []}
            return Response()
    result = private._request(Fake(), "https://data.alpaca.markets", "/v2/stocks/SPY/bars",
                              query={}, key="test", secret="test")
    assert result == {}


def test_source_date_timezone_is_explicit():
    assert NOW.astimezone(NY).strftime("%H:%M") == "15:20"
