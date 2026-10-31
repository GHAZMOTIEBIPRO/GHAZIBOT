"""Regression tests for the owner-private digest; all numbers are fixtures."""
from __future__ import annotations

import pytest

from options_radar.telegram_market_digest import assess, render


def card(symbol="NVDA", side="UP", rvol=1.8, breakout=None):
    return {
        "symbol": symbol, "available": True, "feed_scope": "IEX only",
        "data_as_of": "2026-10-30", "source": "alpaca_iex",
        "data_quality": {"daily": {"status": "OK", "issues": []},
                         "5m": {"status": "OK", "issues": []}},
        "observed": {"levels": [{"name": "prior_day_high", "value": 142.2},
                                {"name": "prior_day_low", "value": 137.4}]},
        "interpretation": {
            "frames": {k: {"trend": side} for k in ("daily", "1h", "15m", "5m")},
            "liquidity": {"status": "OK", "volume": {"state": "HIGH", "rvol": rvol},
                          "breakout": breakout or
                          ("BREAKOUT_VOLUME_CONFIRMED" if side == "UP" else "BREAKDOWN_VOLUME_CONFIRMED")},
        },
        "missing": [{"item": "options", "reason": "NO_OPTIONS_SOURCE"}],
    }


def test_bullish_and_bearish_watches_require_complete_independent_evidence():
    up = assess(card())
    down = assess(card("TSLA", "DOWN"))
    assert up["state"] == "WATCH_UP" and down["state"] == "WATCH_DOWN"
    for result in (up, down):
        assert result["aligned_frames"] == 4
        assert result["volume_confirmed"] is True
        assert result["win_probability"] is None and result["execution_authority"] is False


def test_no_volume_no_verified_breakout_or_mixed_frames_means_wait():
    weak = card()
    weak["interpretation"]["liquidity"]["volume"]["state"] = "NORMAL"
    assert assess(weak)["state"] == "WAIT"
    missing = card()
    missing["interpretation"]["liquidity"] = {"status": "INSUFFICIENT_BARS"}
    assert assess(missing)["state"] == "WAIT"
    fake = card()
    fake["interpretation"]["liquidity"]["breakout"] = "FAILED_BREAKOUT"
    assert assess(fake)["state"] == "WAIT"
    mixed = card()
    mixed["interpretation"]["frames"]["5m"]["trend"] = "DOWN"
    assert assess(mixed)["state"] == "WAIT"
    broken = card()
    broken["data_quality"]["5m"]["status"] = "DATA_ERROR"
    assert assess(broken)["state"] == "WAIT"
    stale = card()
    stale["available"] = False
    assert assess(stale)["state"] == "WAIT"
    no_levels = card()
    no_levels["observed"]["levels"] = []
    assert assess(no_levels)["state"] == "WAIT"


def test_digest_orders_confirmed_watch_before_wait_and_labels_partial_volume():
    waiting = card("AAPL")
    waiting["interpretation"]["liquidity"] = {"status": "INSUFFICIENT_BARS"}
    good = card("NVDA")
    msg = render({"AAPL": waiting, "NVDA": good}, "2026-10-30")
    assert msg.index("NVDA (") < msg.index("AAPL (")
    assert "مراقبة صعود مشروطة" in msg and "الحجم غير مكتمل" in msg
    assert "IEX فقط، حجم جزئي" in msg and "الأوبشن غير متحقق" in msg
    assert "ليس احتمالًا" in msg and "بلا احتمال نجاح" in msg
    assert "توصية CALL/PUT" in msg and "سجل أوامر" in msg
    assert len(msg) <= 3900


def test_message_escapes_external_content_and_never_splits_a_block():
    cards = {f"S{i:02d}": card(f"S{i:02d}") for i in range(30)}
    cards["INJECT"] = card("<b>EVIL</b>")
    msg = render(cards, "2026-10-30", max_chars=700)
    assert len(msg) <= 700
    assert msg.count("(") == msg.count(")")
    assert "<b>EVIL</b>" not in msg
    assert msg.endswith("قبل أي قرار.") or "لم تُعرض" in msg
    assert "16 دقيقة" in msg


def test_no_candidate_message_does_not_invent_signal():
    msg = render({"T": {"symbol": "T", "available": False}}, "2026-10-30")
    assert "مراقبة صعود مشروطة" not in msg
    assert "بلا احتمال نجاح" in msg
    with pytest.raises(ValueError):
        render({}, "2026-10-30", max_chars=80)
