from __future__ import annotations

from datetime import datetime, timezone

from options_radar.omega_observability import build_health


def _payload(errors: dict[str, str] | None = None) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": 6,
        "model_version": "test",
        "errors": errors or {},
        "omega": {"validation": {"edge_status": "EDGE NOT YET PROVEN"}},
    }


def test_health_contract_exposes_explicit_zero_error_semantics() -> None:
    health = build_health(_payload())

    assert health["health_schema_version"] == 2
    assert health["checks"]["critical_pipeline_ok"] is True
    assert health["checks"]["critical_pipeline_error_count"] == 0
    # Backward compatibility: legacy alias stays available until a future schema removal.
    assert health["checks"]["critical_pipeline_errors"] is True


def test_health_contract_counts_real_critical_pipeline_errors() -> None:
    health = build_health(_payload({"options_fetch": "boom"}))

    assert health["status"] == "degraded"
    assert health["checks"]["critical_pipeline_ok"] is False
    assert health["checks"]["critical_pipeline_error_count"] == 1
    assert health["checks"]["critical_pipeline_errors"] is False
