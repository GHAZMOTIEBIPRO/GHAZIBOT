from __future__ import annotations

from pathlib import Path

import pytest

from options_radar.black_box_bot import BlackBoxBot, BotConfig


class DummyNotifier:
    configured = True

    def __init__(self):
        self.messages: list[str] = []

    def send(self, text: str) -> bool:
        self.messages.append(text)
        return True


def _bot(tmp_path: Path) -> BlackBoxBot:
    config = BotConfig(
        enabled=False,
        scan_minutes=15,
        top_stocks=10,
        top_options=10,
        universe_path="data/universe.txt",
        telegram_token=None,
        telegram_chat_id=None,
        webhook_secret="test-secret",
        state_path=tmp_path / "state.json",
        notify_sniper_score=80,
    )
    bot = BlackBoxBot(config=config)
    bot.notifier = DummyNotifier()
    return bot


def test_sniper_high_score_is_notified_once(tmp_path: Path) -> None:
    bot = _bot(tmp_path)
    payload = {
        "event": "signal",
        "direction": "call",
        "symbol": "NVDA",
        "time": "2026-08-25T14:35:00Z",
        "timeframe": "5",
        "score": 88,
        "entry": 181.25,
        "stop": 179.80,
        "target1": 183.10,
        "target2": 185.00,
        "target3": 187.20,
        "engine": "انعكاس",
        "reason": "سحب سيولة + استعادة + اندفاع",
    }
    first = bot.handle_sniper(payload)
    second = bot.handle_sniper(payload)
    assert first == {"status": "ok", "accepted": True, "notified": True}
    assert second == {"status": "duplicate", "accepted": True}
    assert len(bot.notifier.messages) == 1
    assert "NVDA" in bot.notifier.messages[0]
    assert "88/100" in bot.notifier.messages[0]


def test_sniper_low_score_is_accepted_without_notification(tmp_path: Path) -> None:
    bot = _bot(tmp_path)
    result = bot.handle_sniper(
        {
            "event": "setup",
            "direction": "put",
            "symbol": "QQQ",
            "time": "2026-08-25T14:40:00Z",
            "score": 71,
        }
    )
    assert result == {"status": "ok", "accepted": True, "notified": False}
    assert bot.notifier.messages == []


def test_invalidation_notifies_even_below_score_threshold(tmp_path: Path) -> None:
    bot = _bot(tmp_path)
    result = bot.handle_sniper(
        {
            "event": "invalidation",
            "direction": "call",
            "symbol": "SPX",
            "time": "2026-08-25T15:00:00Z",
            "score": 0,
        }
    )
    assert result["notified"] is True
    assert len(bot.notifier.messages) == 1


def test_rejects_invalid_payload(tmp_path: Path) -> None:
    bot = _bot(tmp_path)
    with pytest.raises(ValueError):
        bot.handle_sniper({"event": "unknown", "direction": "call", "symbol": "SPX"})
    with pytest.raises(ValueError):
        bot.handle_sniper({"event": "signal", "direction": "sideways", "symbol": "SPX"})
    with pytest.raises(ValueError):
        bot.handle_sniper({"event": "signal", "direction": "call", "symbol": ""})
