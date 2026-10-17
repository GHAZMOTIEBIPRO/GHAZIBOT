import json
from datetime import datetime, timedelta, timezone

import pytest

from options_radar import spx_external_gamma
from options_radar.gammagrid_research import load_gammagrid_research_snapshot


NOW = datetime(2026, 10, 17, 13, 0, tzinfo=timezone.utc)


def sample():
    return {
        "schema_version": 1,
        "source": "GammaGrid",
        "exported_at": "2026-10-17T12:30:00Z",
        "symbols": [
            {
                "symbol": "SPX",
                "spot": 6500.0,
                "call_wall": 6600.0,
                "put_wall": 6400.0,
                "gamma_flip": 6450.0,
                "net_gex": -12345.0,
            },
            {"symbol": "NVDA", "spot": 185.0},
        ],
    }


def write(tmp_path, payload):
    path = tmp_path / "gamma.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_manual_research_export_is_non_authoritative(tmp_path):
    output = load_gammagrid_research_snapshot(write(tmp_path, sample()), now=NOW)
    assert output["available"] is True
    assert output["symbols"]["SPX"]["call_wall"] == 6600.0
    assert output["symbols"]["NVDA"]["gamma_flip"] is None
    assert output["source_family"] == "yahoo"
    assert output["research_only"] is True
    assert output["affects_signal_score"] is False
    assert output["execution_grade"] is False
    assert output["quote_timestamp_verified"] is False
    assert output["independent_confirmation"] is False


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("source", "some-other-feed", "wrong_source"),
        ("exported_at", "2026-10-15T12:00:00Z", "export_outside_age_window"),
        ("exported_at", "2026-10-18T12:00:00Z", "export_outside_age_window"),
        ("exported_at", "2026-10-17T12:30:00", "missing_export_timestamp"),
        ("symbols", [], "invalid_symbol_count"),
        ("symbols", [{"symbol": "SPX", "spot": -1}], "invalid_spot"),
        ("symbols", [{"symbol": "SPX", "spot": 10, "call_wall": float("inf")}], "invalid_call_wall"),
        (
            "symbols",
            [{"symbol": "SPX", "spot": 10}, {"symbol": "SPX", "spot": 10}],
            "duplicate_symbol",
        ),
    ],
)
def test_invalid_or_stale_export_fails_closed(tmp_path, field, value, reason):
    data = sample()
    data[field] = value
    output = load_gammagrid_research_snapshot(write(tmp_path, data), now=NOW)
    assert output["available"] is False
    assert output["reason"] == reason
    assert output["affects_signal_score"] is False
    assert output["symbols"] == {}


def test_missing_snapshot_is_disabled():
    result = load_gammagrid_research_snapshot(None)
    assert result["reason"] == "not_configured"


def test_spx_context_never_counts_gammagrid_as_independent_source(tmp_path, monkeypatch):
    path = write(tmp_path, sample())
    monkeypatch.setenv("GAMMAGRID_RESEARCH_SNAPSHOT_PATH", str(path))

    def fail_network(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(spx_external_gamma, "_get", fail_network)
    # Snapshot date is old outside the CI run's clock: still fail-closed.
    output = spx_external_gamma.build_spx_external_context()
    assert output["gammagrid_research"]["research_only"] is True
    assert output["gammagrid_research"]["affects_signal_score"] is False
    assert output["sources"] == []
    assert output["available"] is False


def test_current_export_accepted_at_window_boundary(tmp_path):
    data = sample()
    data["exported_at"] = (NOW - timedelta(hours=24)).isoformat()
    output = load_gammagrid_research_snapshot(write(tmp_path, data), now=NOW)
    assert output["available"] is True
