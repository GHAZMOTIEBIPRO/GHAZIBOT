from __future__ import annotations

import math

import pandas as pd

from options_radar.classical_stock_direction import analyze_timeframe, build_direction
from scripts.run_classical_direction_radar import DEFAULT_COMPANIES
import scripts.send_classical_direction_alerts as sender


def _frame(*, count: int = 260, bullish: bool = True) -> pd.DataFrame:
    rows = []
    for i in range(count):
        trend = (0.18 * i) if bullish else (-0.18 * i)
        wave = 2.5 * math.sin(i / 5.0)
        close = 100 + trend + wave
        open_price = close - 0.35 if bullish else close + 0.35
        rows.append(
            {
                "Open": open_price,
                "High": max(open_price, close) + 0.8,
                "Low": min(open_price, close) - 0.8,
                "Close": close,
                "Volume": 5_000_000 + i * 5_000,
            }
        )
    return pd.DataFrame(rows)


def test_classical_engine_produces_call_when_three_timeframes_align():
    result = build_direction("AAPL", _frame(), _frame(count=180), _frame(count=180))
    assert result.decision == "CALL"
    assert result.daily.direction == "BULLISH"
    assert result.hourly.direction == "BULLISH"
    assert result.intraday.direction == "BULLISH"


def test_classical_engine_produces_put_when_three_timeframes_align():
    result = build_direction(
        "MSFT",
        _frame(bullish=False),
        _frame(count=180, bullish=False),
        _frame(count=180, bullish=False),
    )
    assert result.decision == "PUT"
    assert result.daily.direction == "BEARISH"
    assert result.hourly.direction == "BEARISH"
    assert result.intraday.direction == "BEARISH"


def test_classical_engine_waits_when_hourly_conflicts_with_daily():
    result = build_direction(
        "NVDA",
        _frame(),
        _frame(count=180, bullish=False),
        _frame(count=180),
    )
    assert result.decision == "WAIT"


def test_timeframe_exposes_only_classical_structure_features():
    view = analyze_timeframe(_frame(), "1D")
    assert view.trendline_bias in {"BULLISH", "BEARISH", "NEUTRAL"}
    assert view.pattern in {"DOUBLE_TOP", "DOUBLE_BOTTOM", "NONE"}
    assert isinstance(view.breakout_retest, bool)
    assert isinstance(view.breakdown_retest, bool)


def test_company_universe_is_large_company_only_and_excludes_funds_indexes():
    forbidden = {"SPY", "QQQ", "IWM", "SPX", "VIX", "RUT", "NDX"}
    assert not forbidden.intersection(DEFAULT_COMPANIES)
    assert len(DEFAULT_COMPANIES) >= 48
    assert {"AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "XOM"}.issubset(DEFAULT_COMPANIES)


def test_arabic_message_states_direction_and_underlying_only_method():
    row = build_direction("AAPL", _frame(), _frame(count=180), _frame(count=180)).as_dict()
    row["rank_score"] = 80
    message = sender._message(row)
    assert "CALL — صعود" in message
    assert "اتفاق الاتجاه" in message
    assert "تحليل السهم نفسه فقط" in message
    assert "لا يستخدم سعر العقد" in message
    assert "سترايك" in message
    assert "متى أتأكد ومتى ألغي الفكرة؟" in message


def test_sender_deduplicates_same_direction(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(sender, "_send", sent.append)
    row = build_direction("AAPL", _frame(), _frame(count=180), _frame(count=180)).as_dict()
    row["rank_score"] = 80
    payload = {"path": "classical_direction", "signals": [row]}
    state = {"sent": {}}
    assert sender.send(payload, state) == 1
    assert sender.send(payload, state) == 0
    assert len(sent) == 1


def test_sender_never_sends_wait(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(sender, "_send", sent.append)
    payload = {"path": "classical_direction", "signals": [{"symbol": "AAPL", "decision": "WAIT"}]}
    assert sender.send(payload, {"sent": {}}) == 0
    assert sent == []
