from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.publish_live_dashboard_status import publish_live_dashboard_status


ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_runtime_metadata_advances_endpoint_source_beyond_stale_main(tmp_path: Path) -> None:
    state_root = tmp_path / "runtime"
    old = "2026-08-17T21:50:02+00:00"
    current = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)
    _write(
        state_root / "public/data/health.json",
        {"generated_at": old, "status": "degraded"},
    )
    _write(
        state_root / "public/data/data-status.json",
        {"generated_at": old, "status": "degraded"},
    )
    _write(
        state_root / "data/live/fast_explosion_scan.json",
        {"generated_at": current.isoformat(), "stocks": []},
    )
    _write(
        state_root / "public/data/stocks_latest.json",
        {
            "generated_at": current.isoformat(),
            "health": {"status": "HEALTHY", "reasons": []},
            "stocks": [],
        },
    )
    _write(
        state_root / "public/data/options_latest.json",
        {
            "generated_at": current.isoformat(),
            "health": {"status": "HEALTHY", "reasons": []},
            "contracts": [],
            "provider_readiness": {
                "status": "FALLBACK_ONLY",
                "production_quote_ready": False,
                "reasons": ["No licensed quote entitlement"],
            },
        },
    )

    publish_live_dashboard_status(
        state_root=state_root,
        source_workflow="BLACK BOX Omega Stock Radar",
        source_run_id="integration-123",
        current=current,
    )

    health = json.loads((state_root / "public/data/health.json").read_text())
    data_status = json.loads((state_root / "public/data/data-status.json").read_text())
    assert health["generated_at"] == current.isoformat()
    assert data_status["generated_at"] == current.isoformat()
    assert health["generated_at"] != old
    assert data_status["runtime_source"] == "bot-state/live_dashboard_status"
    assert data_status["option_provider_readiness"]["production_quote_ready"] is False


def test_public_metadata_contains_no_raw_rows_or_secret_values(tmp_path: Path) -> None:
    state_root = tmp_path / "runtime"
    generated = "2026-10-05T00:00:00+00:00"
    for relative, payload in (
        ("data/live/fast_explosion_scan.json", {"generated_at": generated, "stocks": []}),
        (
            "public/data/stocks_latest.json",
            {"generated_at": generated, "health": {"status": "HEALTHY"}, "stocks": []},
        ),
        (
            "public/data/options_latest.json",
            {
                "generated_at": generated,
                "health": {"status": "DEGRADED"},
                "contracts": [{"symbol": "SECRET_ROW_SHOULD_NOT_ESCAPE"}],
                "provider_readiness": {
                    "status": "FALLBACK_ONLY",
                    "production_quote_ready": False,
                    "reasons": ["research only"],
                },
            },
        ),
    ):
        _write(state_root / relative, payload)

    output = publish_live_dashboard_status(
        state_root=state_root,
        source_workflow="BLACK BOX Omega Options Contract Radar",
        source_run_id="integration-456",
        current=datetime(2026, 10, 5, 0, 1, tzinfo=timezone.utc),
    )
    text = output.read_text(encoding="utf-8")
    assert "SECRET_ROW_SHOULD_NOT_ESCAPE" not in text
    for relative in ("public/data/health.json", "public/data/data-status.json"):
        metadata = (state_root / relative).read_text(encoding="utf-8")
        assert "SECRET_ROW_SHOULD_NOT_ESCAPE" not in metadata
        assert "api_key" not in metadata.lower()
        assert "token" not in metadata.lower()


def test_vercel_and_workflow_keep_metadata_authority_on_main() -> None:
    vercel = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    rewrites = {item["source"]: item["destination"] for item in vercel["rewrites"]}
    assert rewrites["/health"] == "/data/health.json"
    assert rewrites["/data-status"] == "/data/data-status.json"

    ignore_script = (ROOT / "scripts/vercel-ignore-build.sh").read_text(encoding="utf-8")
    assert "public/data/health.json" in ignore_script
    assert "public/data/data-status.json" in ignore_script

    workflow = (ROOT / ".github/workflows/live-dashboard-status.yml").read_text(encoding="utf-8")
    assert "Mirror safe runtime metadata to main for Vercel" in workflow
    assert "git push origin HEAD:main" in workflow
    assert "state/runtime/public/data/health.json" in workflow
    assert "state/runtime/public/data/data-status.json" in workflow
