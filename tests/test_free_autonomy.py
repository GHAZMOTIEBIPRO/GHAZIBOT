from __future__ import annotations

from pathlib import Path

from options_radar.free_autonomy import enforce_free_autonomy_environment


def test_free_autonomy_forces_zero_cost_alpaca_feeds():
    env = {
        "FREE_AUTONOMY_MODE": "true",
        "PAID_MARKET_DATA_ALLOWED": "true",
        "ALPACA_STOCK_FEED": "sip",
        "ALPACA_OPTIONS_FEED": "opra",
    }
    status = enforce_free_autonomy_environment(env)
    assert status.enabled is True
    assert status.paid_market_data_allowed is False
    assert status.user_intervention_required is False
    assert status.persistent_host_required is False
    assert env["ALPACA_STOCK_FEED"] == "iex"
    assert env["ALPACA_OPTIONS_FEED"] == "indicative"
    assert env["PAID_MARKET_DATA_ALLOWED"] == "false"
    assert status.option_stream_grade == "context_only"


def test_free_autonomy_is_default_when_flag_missing():
    env: dict[str, str] = {}
    status = enforce_free_autonomy_environment(env)
    assert status.enabled is True
    assert env["FREE_AUTONOMY_MODE"] == "true"
    assert env["ALPACA_STOCK_FEED"] == "iex"
    assert env["ALPACA_OPTIONS_FEED"] == "indicative"


def test_explicit_non_autonomous_mode_does_not_mutate_entitlements():
    env = {
        "FREE_AUTONOMY_MODE": "false",
        "PAID_MARKET_DATA_ALLOWED": "true",
        "ALPACA_STOCK_FEED": "sip",
        "ALPACA_OPTIONS_FEED": "opra",
    }
    status = enforce_free_autonomy_environment(env)
    assert status.enabled is False
    assert status.paid_market_data_allowed is True
    assert env["ALPACA_STOCK_FEED"] == "sip"
    assert env["ALPACA_OPTIONS_FEED"] == "opra"


def test_live_options_entrypoint_enforces_guard_before_hardened_import():
    root = Path(__file__).resolve().parents[1]
    text = (root / "scripts" / "run_options_radar_fabric.py").read_text(encoding="utf-8")
    enforce_pos = text.index("enforce_free_autonomy_environment()")
    hardened_pos = text.index("from scripts.run_options_radar_hardened import")
    assert enforce_pos < hardened_pos


def test_stream_gateway_enforces_free_autonomy():
    root = Path(__file__).resolve().parents[1]
    text = (root / "scripts" / "run_stream_gateway.py").read_text(encoding="utf-8")
    assert "enforce_free_autonomy_environment()" in text
