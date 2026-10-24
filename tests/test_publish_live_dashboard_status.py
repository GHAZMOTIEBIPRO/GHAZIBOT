from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.publish_live_dashboard_status import publish_live_dashboard_status


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_publisher_reports_stock_health_and_research_only_options(tmp_path: Path) -> None:
    state_root = tmp_path / "runtime"
    generated = "2026-09-29T14:30:00+00:00"
    _write(
        state_root / "data/live/fast_explosion_scan.json",
        {"generated_at": generated, "stocks": [{"symbol": "SPY"}]},
    )
    _write(
        state_root / "public/data/stocks_latest.json",
        {
            "generated_at": generated,
            "health": {"status": "HEALTHY", "reasons": []},
            "stocks": [{"symbol": "NVDA"}],
        },
    )
    _write(
        state_root / "public/data/options_latest.json",
        {
            "generated_at": generated,
            "health": {"status": "HEALTHY", "reasons": []},
            "contracts": [],
            "provider_readiness": {
                "status": "FALLBACK_ONLY",
                "production_quote_ready": False,
                "reasons": ["Delayed research data only"],
            },
        },
    )

    output = publish_live_dashboard_status(
        state_root=state_root,
        source_workflow="BLACK BOX Omega Stock Radar",
        source_run_id="123",
        current=datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc),
    )

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["overall_status"] == "DEGRADED"
    assert result["paths"]["stocks"]["status"] == "HEALTHY"
    assert result["paths"]["stocks"]["candidate_count"] == 1
    assert result["paths"]["options"]["status"] == "RESEARCH_ONLY"
    assert result["paths"]["options"]["provider_readiness"] == "FALLBACK_ONLY"
    assert result["decision_authority"] is False


def test_publisher_keeps_source_rows_out_of_public_state(tmp_path: Path) -> None:
    state_root = tmp_path / "runtime"
    source_payload = tmp_path / "incoming" / "stocks_latest.json"
    _write(
        source_payload,
        {
            "generated_at": "2026-09-29T14:30:00+00:00",
            "health": {"status": "HEALTHY", "reasons": []},
            "stocks": [{"symbol": "NVDA", "price": 999.99}],
        },
    )

    output = publish_live_dashboard_status(
        state_root=state_root,
        source_workflow="BLACK BOX Omega Stock Radar",
        source_run_id="789",
        current=datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc),
        source_path="stocks",
        source_payload=source_payload,
    )

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["paths"]["stocks"]["candidate_count"] == 1
    assert not (state_root / "public/data/stocks_latest.json").exists()
    assert "NVDA" not in output.read_text(encoding="utf-8")


def test_publisher_fails_closed_when_stock_payload_is_missing(tmp_path: Path) -> None:
    output = publish_live_dashboard_status(
        state_root=tmp_path / "runtime",
        source_workflow="BLACK BOX Omega Stock Radar",
        source_run_id="456",
        current=datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc),
    )

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["overall_status"] == "CRITICAL"
    assert result["paths"]["stocks"]["status"] == "UNAVAILABLE"


def test_carried_over_paths_are_re_aged_and_marked_stale(tmp_path: Path) -> None:
    from scripts.publish_live_dashboard_status import build_live_dashboard_status

    status_path = tmp_path / "public/data/live_dashboard_status.json"
    status_path.parent.mkdir(parents=True)
    status_path.write_text(json.dumps({"paths": {
        "fast_discovery": {"status": "HEALTHY", "file": "data/live/fast_explosion_scan.json",
                           "generated_at": "2026-10-02T22:25:13+00:00",
                           "age_minutes": 0.29, "maximum_age_minutes": 45.0, "reasons": []},
        "options": {"status": "RESEARCH_ONLY", "file": "public/data/options_latest.json",
                    "generated_at": "2026-10-19T16:50:00+00:00",
                    "age_minutes": 1.0, "maximum_age_minutes": 45.0, "reasons": ["x"]},
    }}), encoding="utf-8")
    report = build_live_dashboard_status(
        state_root=tmp_path, source_workflow="manual", source_run_id="0",
        current=datetime(2026, 10, 19, 17, 0, tzinfo=timezone.utc),
    )
    fast = report["paths"]["fast_discovery"]
    assert fast["status"] == "STALE"
    assert fast["age_minutes"] > 20000
    assert "exceeds the 45m safety limit" in fast["reasons"][0]
    options = report["paths"]["options"]
    assert options["status"] == "RESEARCH_ONLY" and options["age_minutes"] == 10.0
    assert report["overall_status"] == "CRITICAL"


def test_live_status_merges_into_export_data_status_instead_of_erasing_it(tmp_path: Path) -> None:
    state_root = tmp_path / "runtime"
    generated = "2026-09-29T14:30:00+00:00"
    _write(state_root / "public/data/stocks_latest.json",
           {"generated_at": generated, "health": {"status": "HEALTHY", "reasons": []},
            "stocks": [{"symbol": "NVDA"}]})
    # Fields only the radar export writes (the terminal's runtime schema needs them).
    _write(state_root / "public/data/data-status.json",
           {"status": "healthy", "generated_at": "2026-09-29T14:00:00+00:00",
            "row_counts": {"stocks": 5}, "quality_counts": {"ok": 4},
            "option_provider_readiness": {"production_quote_ready": False}})
    publish_live_dashboard_status(
        state_root=state_root, source_workflow="stock-radar.yml", source_run_id="9",
        current=datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc))
    merged = json.loads((state_root / "public/data/data-status.json").read_text(encoding="utf-8"))
    assert merged["row_counts"] == {"stocks": 5}
    assert merged["quality_counts"] == {"ok": 4}
    assert merged["runtime_source"] == "bot-state/live_dashboard_status"
    assert "workflow_health" in merged
    assert merged["generated_at"] != "2026-09-29T14:00:00+00:00"


def test_missing_artifact_preserves_data_time_and_does_not_refresh_market_metadata(tmp_path):
    generated = "2026-10-21T12:00:00+00:00"
    _write(tmp_path / "public/data/live_dashboard_status.json", {"paths": {"stocks": {
        "status": "HEALTHY", "generated_at": generated, "maximum_age_minutes": 90}}})
    _write(tmp_path / "public/data/data-status.json", {"generated_at": generated})
    output = publish_live_dashboard_status(state_root=tmp_path, source_workflow="stock-radar.yml",
        source_run_id="123", source_path="stocks", missing_artifact=True,
        current=datetime(2026, 10, 24, tzinfo=timezone.utc))
    data = json.loads(output.read_text())
    assert data["paths"]["stocks"]["status"] == "UNAVAILABLE"
    assert data["paths"]["stocks"]["generated_at"] == generated
    assert data["publisher"]["mode"] == "missing_artifact_status_only"
    assert json.loads((tmp_path / "public/data/data-status.json").read_text())["generated_at"] == generated


def test_quote_readiness_never_implies_flow_or_survives_staleness(tmp_path):
    generated = "2026-10-24T12:00:00+00:00"
    _write(tmp_path / "public/data/options_latest.json", {"generated_at": generated,
        "provider_readiness": {"production_quote_ready": True, "production_flow_ready": False}})
    publish_live_dashboard_status(state_root=tmp_path, source_workflow="options", source_run_id="1",
        current=datetime(2026, 10, 24, 12, 5, tzinfo=timezone.utc))
    status_file = tmp_path / "public/data/data-status.json"
    readiness = json.loads(status_file.read_text())["option_provider_readiness"]
    assert readiness["production_quote_ready"] is True
    assert readiness["production_flow_ready"] is False
    publish_live_dashboard_status(state_root=tmp_path, source_workflow="options", source_run_id="2",
        current=datetime(2026, 10, 24, 14, tzinfo=timezone.utc))
    assert json.loads(status_file.read_text())["option_provider_readiness"]["production_quote_ready"] is False


def test_future_payload_is_never_healthy(tmp_path):
    _write(tmp_path / "public/data/stocks_latest.json", {"generated_at": "2030-01-01T00:00:00Z"})
    result = publish_live_dashboard_status(state_root=tmp_path, source_workflow="stocks", source_run_id="1",
        current=datetime(2026, 10, 24, tzinfo=timezone.utc))
    assert json.loads(result.read_text())["paths"]["stocks"]["status"] == "CRITICAL"
