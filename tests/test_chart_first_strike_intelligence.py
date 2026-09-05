from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from options_radar.chart_first_consensus import (
    build_chart_first_directional_signals,
    score_contract_chart_first,
)
from options_radar.chart_strike_intelligence import (
    build_chart_context,
    enrich_contract_with_chart_and_strike,
)
from options_radar.free_gamma_engine import build_gamma_map
from options_radar.settings import Settings


def _frame(rows: int, *, freq: str, bullish: bool = True) -> pd.DataFrame:
    index = pd.date_range("2026-08-01 13:30", periods=rows, freq=freq, tz="UTC")
    base = 100.0
    step = 0.08 if bullish else -0.08
    closes = [base + step * i for i in range(rows)]
    opens = [value - 0.04 if bullish else value + 0.04 for value in closes]
    highs = [max(o, c) + 0.08 for o, c in zip(opens, closes)]
    lows = [min(o, c) - 0.08 for o, c in zip(opens, closes)]
    volumes = [1000.0 + i * 10 for i in range(rows)]
    volumes[-1] = 7000.0
    return pd.DataFrame(
        {
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": volumes,
        },
        index=index,
    )


class _FakeFetcher:
    def __init__(self, daily: pd.DataFrame, intraday: pd.DataFrame):
        self.daily = daily
        self.intraday = intraday
        self.calls: list[str] = []

    def fetch_stock_bars(self, symbol: str, *, interval: str, **kwargs):
        self.calls.append(interval)
        if interval == "1d":
            return SimpleNamespace(data=self.daily, source="yahoo")
        if interval == "5m":
            return SimpleNamespace(data=self.intraday, source="yahoo")
        raise AssertionError(f"unexpected external interval {interval}")


def _valid_contract(**updates):
    row = {
        "symbol": "XYZ",
        "contract_symbol": "XYZ261002C00105000",
        "option_type": "call",
        "strike": 105.0,
        "underlying_price": 104.0,
        "iv": 0.45,
        "score": 99.0,
        "flow_momentum_score": 99.0,
        "data_quality": 0.95,
        "execution_score": 30.0,
        "reward_risk_1": 2.0,
        "spread_pct": 0.03,
        "vol_to_oi_ratio": 4.0,
        "volume": 5000.0,
        "open_interest": 5000.0,
        "delta": 0.50,
        "dte": 28.0,
        "gamma_concentration_pct": 20.0,
        "gamma_context_alignment": 0.30,
        "gamma_coverage_pct": 95.0,
        "oi_coverage_pct": 95.0,
        "occ_side_context": {"available": False, "bonus": 0.0},
        "fabric_independent_source_count": 1,
        "fabric_consensus_pass": True,
        "learning_active": False,
    }
    row.update(updates)
    return row


def test_chart_context_fetches_only_daily_and_5m_and_builds_15m_locally() -> None:
    fetcher = _FakeFetcher(_frame(260, freq="1D"), _frame(120, freq="5min"))
    chart = build_chart_context("XYZ", fetcher=fetcher)
    assert fetcher.calls == ["1d", "5m"]
    assert chart["available_timeframes"] == 3
    assert chart["timeframes"]["15m"]["available"] is True
    assert chart["institutional_activity_proxy_only"] is True
    assert chart["direction"] == "bullish"


def test_gamma_map_adds_flip_oi_volume_and_liquidity_levels() -> None:
    settings = Settings(min_dte=7, max_dte=60)
    expiry = pd.Timestamp.now().normalize() + pd.Timedelta(days=30)
    rows = [
        {"option_type": "put", "strike": 95, "expiration": expiry, "open_interest": 6000, "volume": 900, "gamma": 0.035, "delta": -0.40, "iv": 0.35, "underlying_price": 100, "source": "yahoo"},
        {"option_type": "call", "strike": 100, "expiration": expiry, "open_interest": 1000, "volume": 1000, "gamma": 0.030, "delta": 0.52, "iv": 0.32, "underlying_price": 100, "source": "yahoo"},
        {"option_type": "call", "strike": 105, "expiration": expiry, "open_interest": 7000, "volume": 5000, "gamma": 0.040, "delta": 0.42, "iv": 0.34, "underlying_price": 100, "source": "yahoo"},
        {"option_type": "put", "strike": 110, "expiration": expiry, "open_interest": 500, "volume": 300, "gamma": 0.020, "delta": -0.65, "iv": 0.38, "underlying_price": 100, "source": "yahoo"},
    ]
    gamma_map = build_gamma_map("XYZ", pd.DataFrame(rows), settings)
    assert gamma_map.call_wall == 105
    assert gamma_map.put_wall == 95
    assert gamma_map.gamma_flip in {100, 105}
    assert gamma_map.top_oi_strikes[0] == 105
    assert gamma_map.top_volume_strikes[0] == 105
    assert gamma_map.liquidity_strike == 105
    assert "not verified dealer or institutional inventory" in gamma_map.source_note


def test_chart_aligned_contract_can_pass_strict_consensus() -> None:
    row = _valid_contract(
        chart_available_timeframes=3,
        chart_side_alignment=0.72,
        strike_intelligence_score=82.0,
        institutional_activity_proxy_score=72.0,
        strike_distance_expected_move_ratio=0.55,
    )
    signals = build_chart_first_directional_signals([row], minimum_score=80)
    assert len(signals) == 1
    assert signals[0]["direction"] == "CALL"
    assert signals[0]["chart_first_required"] is True


def test_strongly_opposing_chart_blocks_even_high_base_score() -> None:
    row = _valid_contract(
        chart_available_timeframes=3,
        chart_side_alignment=-0.75,
        strike_intelligence_score=80.0,
        institutional_activity_proxy_score=75.0,
        strike_distance_expected_move_ratio=0.50,
    )
    score, _, blockers = score_contract_chart_first(row)
    assert score > 0
    assert "chart_strongly_opposes_side" in blockers
    assert build_chart_first_directional_signals([row], minimum_score=70) == []


def test_missing_multiframe_or_far_strike_is_hard_blocked() -> None:
    missing = _valid_contract(
        chart_available_timeframes=1,
        chart_side_alignment=0.8,
        strike_intelligence_score=90,
        institutional_activity_proxy_score=80,
        strike_distance_expected_move_ratio=0.5,
    )
    far = _valid_contract(
        chart_available_timeframes=3,
        chart_side_alignment=0.8,
        strike_intelligence_score=65,
        institutional_activity_proxy_score=80,
        strike_distance_expected_move_ratio=1.8,
    )
    assert "chart_multiframe_unavailable" in score_contract_chart_first(missing)[2]
    assert "strike_outside_expected_move" in score_contract_chart_first(far)[2]
    assert build_chart_first_directional_signals([missing, far], minimum_score=70) == []


def test_contract_enrichment_explains_strike_choice() -> None:
    chart = {
        "direction": "bullish",
        "score": 60.0,
        "available_timeframes": 3,
        "reasons_ar": ["15m: فوق VWAP"],
        "institutional_activity_proxy_score": 70.0,
    }
    gamma_map = {
        "spot": 100.0,
        "call_wall": 105.0,
        "put_wall": 95.0,
        "gamma_flip": 99.0,
        "liquidity_strike": 105.0,
        "top_oi_strikes": [105.0, 100.0],
        "top_volume_strikes": [105.0, 110.0],
    }
    row = _valid_contract(strike=105.0, underlying_price=100.0, strike_liquidity_score=90)
    enriched = enrich_contract_with_chart_and_strike(row, chart=chart, gamma_map=gamma_map)
    assert enriched["chart_first"] is True
    assert enriched["strike_intelligence_score"] > 60
    assert enriched["expected_move_1sigma"] is not None
    assert any("OI" in reason for reason in enriched["strike_reasons_ar"])
    assert enriched["institutional_activity_proxy_only"] is True
