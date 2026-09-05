from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from scripts.news_flash_reclaiming import reclaim_metrics


def _minute_frame(*, complete_reclaim: bool, incomplete_spike: bool = False) -> pd.DataFrame:
    index = pd.date_range("2026-09-05T12:00:00Z", periods=17, freq="1min")
    close: list[float] = []
    high: list[float] = []
    low: list[float] = []
    volume: list[float] = []
    for i, stamp in enumerate(index):
        if i <= 5:
            c = 100.0 - (i * 0.10)
            v = 100.0
        elif i <= 10:
            c = 101.0
            v = 100.0
        elif i <= 15:
            c = 103.5 if complete_reclaim else 101.0
            v = 220.0 if complete_reclaim else 100.0
        else:
            c = 120.0 if incomplete_spike else (103.6 if complete_reclaim else 101.0)
            v = 1000.0 if incomplete_spike else 100.0
        close.append(c)
        high.append(c + 0.20)
        low.append(c - 0.20)
        volume.append(v)
    return pd.DataFrame(
        {"Close": close, "High": high, "Low": low, "Volume": volume},
        index=index,
    )


def test_positive_reclaim_requires_vwap_structure_and_volume() -> None:
    metrics = reclaim_metrics(
        _minute_frame(complete_reclaim=True),
        datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc),
        "POSITIVE",
    )
    assert metrics is not None
    assert metrics["vwap_reclaimed"] is True
    assert metrics["structure_5m_reclaimed"] is True
    assert metrics["volume_confirmed"] is True
    assert metrics["reclaiming"] is True
    assert metrics["decision_authority"] is False


def test_incomplete_five_minute_spike_cannot_create_reclaim() -> None:
    metrics = reclaim_metrics(
        _minute_frame(complete_reclaim=False, incomplete_spike=True),
        datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc),
        "POSITIVE",
    )
    assert metrics is not None
    assert metrics["reclaiming"] is False
    assert metrics["structure_5m_reclaimed"] is False


def test_neutral_news_never_gets_reclaim_promotion() -> None:
    assert (
        reclaim_metrics(
            _minute_frame(complete_reclaim=True),
            datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc),
            "NEUTRAL",
        )
        is None
    )


def test_workflow_uses_reclaim_wrapper_without_changing_schedule() -> None:
    workflow = Path(".github/workflows/news-flash-24x7.yml").read_text(encoding="utf-8")
    assert "scripts.send_news_flash_reclaiming" in workflow
    assert '2,7,12,17,22,27,32,37,42,47,52,57 * * * *' in workflow
    assert "market_clock_gate" not in workflow


def test_reclaim_wrapper_persists_fade_memory_and_has_no_trade_authority() -> None:
    source = Path("scripts/send_news_flash_reclaiming.py").read_text(encoding="utf-8")
    assert 'previous.get("ever_faded")' in source
    assert 'previous.get("reaction_state")' in source
    assert 'current["reaction_state"] = "RECLAIMING"' in source
    assert "لا تدخل لمجرد هذا التنبيه" in source
