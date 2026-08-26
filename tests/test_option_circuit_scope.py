from __future__ import annotations

from options_radar.data_fabric import FabricAttempt, ProviderHealthRegistry
from options_radar.data_fabric_runtime import _option_health_operation


def test_option_health_operation_is_symbol_scoped() -> None:
    assert _option_health_operation("VIX") == "option_chain:VIX"
    assert _option_health_operation("spy") == "option_chain:SPY"
    assert _option_health_operation("") == "option_chain:UNKNOWN"


def test_unsupported_symbol_failures_do_not_block_other_underlyings(tmp_path) -> None:
    registry = ProviderHealthRegistry(
        tmp_path / "health.json",
        failure_threshold=3,
        cool_down_minutes=20,
    )
    vix_operation = _option_health_operation("VIX")
    spy_operation = _option_health_operation("SPY")

    for _ in range(3):
        registry.record(
            FabricAttempt(
                provider="yahoo",
                operation=vix_operation,
                success=False,
                elapsed_ms=25,
                error="empty response",
            )
        )

    assert registry.allowed("yahoo", vix_operation) is False
    assert registry.allowed("yahoo", spy_operation) is True
