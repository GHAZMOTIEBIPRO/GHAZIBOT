from __future__ import annotations

from options_radar.free_autonomy import enforce_free_autonomy_environment


def test_free_mode_promotes_tradier_production_when_token_exists():
    env = {
        "FREE_AUTONOMY_MODE": "true",
        "PAID_MARKET_DATA_ALLOWED": "true",
        "TRADIER_TOKEN": "broker-production-token",
        "TRADIER_BASE_URL": "https://sandbox.tradier.com",
        "ALPACA_STOCK_FEED": "sip",
        "ALPACA_OPTIONS_FEED": "opra",
    }

    status = enforce_free_autonomy_environment(env)

    assert status.enabled is True
    assert status.paid_market_data_allowed is False
    assert env["TRADIER_BASE_URL"] == "https://api.tradier.com"
    assert env["ALPACA_STOCK_FEED"] == "iex"
    assert env["ALPACA_OPTIONS_FEED"] == "indicative"
    assert status.option_stream_grade == "tradier_realtime_available"
    assert status.execution_model == "tradier_realtime_first_with_free_fallbacks"


def test_free_mode_can_keep_tradier_sandbox_for_explicit_testing():
    env = {
        "FREE_AUTONOMY_MODE": "true",
        "TRADIER_TOKEN": "sandbox-token",
        "TRADIER_BASE_URL": "https://sandbox.tradier.com",
        "TRADIER_LIVE_FREE_ENABLED": "false",
    }

    status = enforce_free_autonomy_environment(env)

    assert env["TRADIER_BASE_URL"] == "https://sandbox.tradier.com"
    assert status.option_stream_grade == "context_only"
    assert status.paid_market_data_allowed is False
