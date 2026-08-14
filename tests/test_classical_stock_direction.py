from __future__ import annotations

import math

import pandas as pd

import scripts.run_classical_direction_radar as runner
import scripts.send_classical_direction_alerts as sender
from options_radar.classical_stock_direction import analyze_timeframe, build_direction
from scripts.run_classical_direction_radar import DEFAULT_COMPANIES


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


def _flat_frame(count: int = 180) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [100.0] * count,
            "High": [101.0] * count,
            "Low": [99.0] * count,
            "Close": [100.0] * count,
            "Volume": [5_000_000] * count,
        }
    )


def test_classical_engine_produces_call_when_three_timeframes_align():
    result = build_direction("AAPL", _frame(), _frame(count=180), _frame(count=180))
    assert result.decision == "CALL"
    assert result.agreement_pct == 100
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
    assert result.agreement_pct == 100
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


def test_classical_engine_requires_all_three_timeframes_to_align():
    result = build_direction(
        "NVDA",
        _frame(),
        _flat_frame(),
        _frame(count=180),
    )
    assert result.hourly.direction == "NEUTRAL"
    assert result.agreement_pct == 67
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
    assert {"AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "XOM"}.issubset(
        DEFAULT_COMPANIES
    )


def test_intraday_resampling_uses_completed_regular_session_bars():
    index = pd.date_range("2025-06-02 13:30:00+00:00", periods=78, freq="5min")
    source = pd.DataFrame(
        {
            "Open": range(78),
            "High": [value + 1 for value in range(78)],
            "Low": [value - 1 for value in range(78)],
            "Close": [value + 0.5 for value in range(78)],
            "Volume": [1_000_000] * 78,
        },
        index=index,
    )
    bars_15m = runner._resample_regular_session(source, 15)
    bars_60m = runner._resample_regular_session(source, 60)
    assert len(bars_15m) == 26
    assert len(bars_60m) == 6
    assert bars_15m.index.tz is not None


def test_fetch_failures_are_errors_not_waits(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(runner, "_fetch_symbol_frames", fail)
    frames, errors = runner._fetch_all_frames(["AAPL"], runner.Settings())
    assert frames == {}
    assert "provider unavailable" in errors["AAPL"]


def test_arabic_message_states_direction_and_underlying_only_method():
    row = build_direction("AAPL", _frame(), _frame(count=180), _frame(count=180)).as_dict()
    row["rank_score"] = 80
    message = sender._message(row)
    assert "CALL — صعود" in message
    assert "اتفاق الاتجاه" in message
    assert "درجة توافق الأطر" in message
    assert "100/100" in message
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
