from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd

from options_radar.data_fabric import reconcile_option_chains
from options_radar.execution_confidence import assess_execution_quote
from options_radar.intrinio_flow import enrich_with_intrinio_flow
from options_radar.providers import TradierProvider, _to_utc
from options_radar.settings import Settings


NOW = datetime(2026, 10, 3, 14, 0, tzinfo=timezone.utc)
CONTRACT = "XYZ261120C00100000"


class _Response:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _TradierSession:
    def __init__(self, payload: dict):
        self.payload = payload

    def get(self, *args, **kwargs):
        return _Response(self.payload)


def _frame(source: str, *, updated_at: str = "2026-10-03T13:59:30Z") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "contract_symbol": CONTRACT,
                "symbol": "XYZ",
                "expiration": "2026-11-20",
                "strike": 100.0,
                "option_type": "call",
                "bid": 1.0,
                "ask": 1.1,
                "last": 1.05,
                "volume": 1000,
                "open_interest": 800,
                "iv": 0.4,
                "delta": 0.5,
                "gamma": 0.03,
                "theta": -0.02,
                "vega": 0.08,
                "underlying_price": 101.0,
                "updated_at": updated_at,
                "source": source,
                "data_quality": 0.7,
                "freshness_label": "unofficial / may be delayed",
            }
        ]
    )


def test_missing_provider_time_never_becomes_now() -> None:
    assert pd.isna(_to_utc(None))
    assert pd.isna(_to_utc(""))


def test_tradier_chain_preserves_trade_time_without_manufacturing_quote_time() -> None:
    expiry = (date.today() + timedelta(days=30)).isoformat()
    trade_time = "2026-10-01T14:30:00Z"
    provider = TradierProvider(
        Settings(tradier_token="test-token", tradier_base_url="https://api.tradier.com")
    )
    provider._expirations = lambda symbol: [expiry]  # type: ignore[method-assign]
    provider._underlying = lambda symbol: 101.0  # type: ignore[method-assign]
    provider.session = _TradierSession(
        {
            "options": {
                "option": [
                    {
                        "symbol": CONTRACT,
                        "expiration_date": expiry,
                        "strike": 100.0,
                        "option_type": "call",
                        "bid": 1.0,
                        "ask": 1.1,
                        "last": 1.05,
                        "volume": 100,
                        "open_interest": 200,
                        "trade_date": trade_time,
                        "greeks": {
                            "mid_iv": 0.4,
                            "delta": 0.5,
                            "gamma": 0.03,
                            "theta": -0.02,
                            "vega": 0.08,
                        },
                    }
                ]
            }
        }
    )

    row = provider.get_chain("XYZ", 1, 60).iloc[0]
    assert row["timestamp_kind"] == "last_trade"
    assert pd.isna(row["quote_timestamp"])
    assert pd.Timestamp(row["last_trade_timestamp"]) == pd.Timestamp(trade_time)
    assert pd.Timestamp(row["updated_at"]) == pd.Timestamp(trade_time)


def test_last_trade_timestamp_cannot_satisfy_execution_quote_freshness() -> None:
    gate = assess_execution_quote(
        {
            "source": "licensed OPRA realtime",
            "freshness_label": "realtime",
            "bid": 2.0,
            "ask": 2.1,
            "updated_at": (NOW - timedelta(seconds=5)).isoformat(),
            "last_trade_timestamp": (NOW - timedelta(seconds=5)).isoformat(),
            "timestamp_kind": "last_trade",
        },
        now=NOW,
    )
    assert gate.execution_ready is False
    assert gate.confidence == "RESEARCH"
    assert any("توقيت Quote" in blocker for blocker in gate.blockers)


def test_yahoo_transports_count_once_as_independent_source() -> None:
    out, audit = reconcile_option_chains(
        {
            "yahoo/yfinance": _frame("yahoo/yfinance"),
            "yahooquery": _frame("yahooquery"),
        },
        freshness={
            "yahoo/yfinance": "unofficial / may be delayed",
            "yahooquery": "unofficial / may be delayed",
        },
    )
    assert len(out) == 1
    row = out.iloc[0]
    assert row["fabric_source_count"] == 2
    assert row["fabric_independent_source_count"] == 1
    assert audit["transport_source_count"] == 2
    assert audit["independent_source_count"] == 1
    assert audit["source_families"] == ["yahoo"]


def test_delayed_data_remains_research_not_execution() -> None:
    gate = assess_execution_quote(
        {
            "source": "yahoo/yfinance",
            "freshness_label": "unofficial / may be delayed",
            "bid": 2.0,
            "ask": 2.1,
            "updated_at": (NOW - timedelta(seconds=5)).isoformat(),
        },
        now=NOW,
    )
    assert gate.confidence == "RESEARCH"
    assert gate.execution_ready is False


def test_opra_overlay_label_is_not_enough_without_execution_grade_flag() -> None:
    gate = assess_execution_quote(
        {
            "source": "alpaca_opra_stream",
            "freshness_label": "Alpaca OPRA stream; execution-grade quote overlay",
            "fabric_quote_provider": "alpaca_opra_stream",
            "stream_feed": "opra",
            "stream_execution_grade": False,
            "quote_timestamp": (NOW - timedelta(seconds=5)).isoformat(),
            "bid": 2.0,
            "ask": 2.1,
        },
        now=NOW,
    )
    assert gate.execution_ready is False
    assert gate.confidence == "RESEARCH"
    assert any("stream_execution_grade" in blocker for blocker in gate.blockers)


class _PartialIntrinio:
    enabled = True

    def recent_by_contract(self, symbol: str):
        if symbol == "BAD":
            raise RuntimeError("provider symbol failure")
        return {
            CONTRACT: [
                {
                    "contract": CONTRACT,
                    "timestamp": "2026-10-03T13:59:00+00:00",
                    "type": "block",
                    "total_value": 250000,
                    "total_size": 100,
                    "average_price": 1.05,
                    "ask_at_execution": 1.10,
                    "bid_at_execution": 1.00,
                    "sentiment": "bullish",
                }
            ]
        }


def test_intrinio_symbol_failure_is_isolated_and_audited() -> None:
    rows, errors = enrich_with_intrinio_flow(
        [
            {"symbol": "BAD", "contract_symbol": "BAD261120C00100000"},
            {"symbol": "GOOD", "contract_symbol": CONTRACT},
        ],
        client=_PartialIntrinio(),
        max_symbols=4,
    )
    assert errors["BAD"].startswith("RuntimeError:")
    assert len(rows) == 2
    assert rows[0].get("verified_trade_flow") is not True
    assert rows[1]["verified_trade_flow"] is True
    assert rows[1]["block_confirmed"] is True
