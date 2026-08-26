from types import SimpleNamespace

from options_radar.intrinio_realtime import trade_to_event, unusual_activity_to_event


def test_intrinio_trade_adapter_preserves_execution_evidence():
    trade = SimpleNamespace(
        contract="NVDA__260828C00200000",
        timestamp=1787756400.0,
        price=3.0,
        size=50,
        total_volume=1200,
        qualifiers=(19, 0, 0, 0),
        bid_price_at_execution=2.95,
        ask_price_at_execution=3.0,
        underlying_price_at_execution=200.0,
        exchange=SimpleNamespace(name="CBOE"),
    )
    event = trade_to_event(trade, delayed=False)
    assert event is not None
    assert event.underlying == "NVDA"
    assert event.option_type == "CALL"
    assert event.side == "BUYER"
    assert event.iso_evidence is True
    assert event.is_realtime is True


def test_intrinio_unusual_activity_adapter_marks_provider_sweep():
    activity = SimpleNamespace(
        contract="NVDA__260828P00195000",
        timestamp=1787756400.0,
        average_price=2.5,
        total_size=800,
        total_value=200_000,
        bid_price_at_execution=2.45,
        ask_price_at_execution=2.5,
        underlying_price_at_execution=200.0,
        activity_type=SimpleNamespace(name="SWEEP"),
        sentiment=SimpleNamespace(name="BEARISH"),
    )
    event = unusual_activity_to_event(activity, delayed=False)
    assert event is not None
    assert event.option_type == "PUT"
    assert event.sweep_confirmed is True
    assert event.bias == "BEARISH"
    assert event.premium == 200_000
