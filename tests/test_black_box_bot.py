from __future__ import annotations

from pathlib import Path

from options_radar.black_box_bot import BlackBoxBot, BotConfig, EventLedger


def _bot(tmp_path: Path) -> BlackBoxBot:
    config = BotConfig(
        enabled=False,
        scan_minutes=15,
        top_stocks=10,
        top_options=10,
        universe_path="data/universe.txt",
        telegram_token=None,
        telegram_chat_id=None,
        state_path=tmp_path / "state.json",
    )
    return BlackBoxBot(config=config)


def test_black_box_has_no_indicator_bridge(tmp_path: Path) -> None:
    bot = _bot(tmp_path)
    assert not hasattr(bot, "handle_sniper")
    assert not hasattr(bot.config, "webhook_secret")
    assert not hasattr(bot.config, "notify_sniper_score")


def test_event_ledger_deduplicates_scanner_events(tmp_path: Path) -> None:
    ledger = EventLedger(tmp_path / "state.json")
    payload = {"symbol": "NVDA", "stage": "CONFIRMED"}
    assert ledger.first_time("thesis", payload) is True
    assert ledger.first_time("thesis", payload) is False


def test_black_box_runtime_identity_is_standalone(tmp_path: Path) -> None:
    bot = _bot(tmp_path)
    assert bot.config.enabled is False
    assert "Standalone" in (BlackBoxBot.__doc__ or "")
    assert callable(bot.scan_once)
