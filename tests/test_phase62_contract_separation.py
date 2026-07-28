from __future__ import annotations

from options_radar.phase62_contract_separation import (
    normalize_option_type,
    separated_near_miss_contracts,
)


def _contract(
    symbol: str,
    contract_symbol: str,
    option_type: str,
    *,
    expiration: str = "2026-08-21T00:00:00+00:00",
    flow: float = 70.0,
) -> dict:
    return {
        "kind": "option",
        "symbol": symbol,
        "contract_symbol": contract_symbol,
        "expiration": expiration,
        "strike": 100.0,
        "option_type": option_type,
        "bid": 2.0,
        "ask": 2.1,
        "last": 2.05,
        "volume": 500,
        "open_interest": 800,
        "spread_pct": 0.0476,
        "last_trade_age_minutes": 2,
        "flow_momentum_score": flow,
        "source": "Yahoo",
        "rejection_reason": "direction_delta_dte_or_score_filter",
    }


def test_occ_symbol_is_authoritative_for_call_put_type() -> None:
    row = _contract("AAPL", "AAPL260821P00100000", "call")
    assert normalize_option_type(row) == "put"

    row = _contract("AAPL", "AAPL260821C00100000", "put")
    assert normalize_option_type(row) == "call"


def test_opposite_direction_contracts_are_removed() -> None:
    payload = {
        "stocks": [
            {"symbol": "AAPL", "setup_side": "CALL"},
            {"symbol": "TSLA", "setup_side": "PUT"},
        ],
        "rejected": [
            _contract("AAPL", "AAPL260821C00100000", "call", flow=80),
            _contract("AAPL", "AAPL260821P00100000", "put", flow=99),
            _contract("TSLA", "TSLA260821P00400000", "put", flow=78),
            _contract("TSLA", "TSLA260821C00400000", "call", flow=98),
        ],
    }

    rows = separated_near_miss_contracts(payload, set(), limit=8)
    symbols = {row["contract_symbol"] for row in rows}

    assert "AAPL260821C00100000" in symbols
    assert "TSLA260821P00400000" in symbols
    assert "AAPL260821P00100000" not in symbols
    assert "TSLA260821C00400000" not in symbols


def test_watchlist_is_split_and_diversified_by_symbol_and_expiry() -> None:
    payload = {
        "stocks": [],
        "rejected": [
            _contract("AAA", "AAA260821C00100000", "call", flow=95),
            _contract("AAA", "AAA260821C00105000", "call", flow=94),
            _contract("AAA", "AAA260828C00110000", "call", expiration="2026-08-28T00:00:00+00:00", flow=93),
            _contract("AAA", "AAA260904C00115000", "call", expiration="2026-09-04T00:00:00+00:00", flow=92),
            _contract("BBB", "BBB260821C00100000", "call", flow=91),
            _contract("CCC", "CCC260821C00100000", "call", flow=90),
            _contract("DDD", "DDD260821P00100000", "put", flow=89),
            _contract("EEE", "EEE260821P00100000", "put", flow=88),
            _contract("FFF", "FFF260821P00100000", "put", flow=87),
            _contract("GGG", "GGG260821P00100000", "put", flow=86),
        ],
    }

    rows = separated_near_miss_contracts(payload, set(), limit=8)
    calls = [row for row in rows if row["option_type"] == "call"]
    puts = [row for row in rows if row["option_type"] == "put"]

    assert len(calls) == 4
    assert len(puts) == 4
    assert sum(row["symbol"] == "AAA" for row in calls) <= 2
    assert len({row["contract_symbol"] for row in rows}) == len(rows)
    assert not ({row["contract_symbol"] for row in calls} & {row["contract_symbol"] for row in puts})
