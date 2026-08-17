from __future__ import annotations

import json

import pytest

from scripts.runtime_state_vault import (
    RUNTIME_PATHS,
    publish_runtime_state,
    restore_runtime_state,
)


def test_runtime_state_round_trip_uses_explicit_allowlist(tmp_path) -> None:
    repo = tmp_path / "repo"
    vault = tmp_path / "vault"
    latest = repo / "public/data/latest.json"
    signals = repo / "data/live/signals.jsonl"
    latest.parent.mkdir(parents=True)
    signals.parent.mkdir(parents=True)
    latest.write_text(json.dumps({"generated_at": "2026-08-17T20:00:00+00:00", "stocks": []}), encoding="utf-8")
    signals.write_text(json.dumps({"signal_id": "abc", "score": 88}) + "\n", encoding="utf-8")

    result = publish_runtime_state(repo_root=repo, vault_root=vault)
    assert result["published"] == 2
    assert (vault / "public/data/latest.json").exists()
    assert (vault / "data/live/signals.jsonl").exists()
    assert (vault / "manifest.json").exists()

    latest.unlink()
    signals.unlink()
    restored = restore_runtime_state(repo_root=repo, vault_root=vault)
    assert restored["restored"] == 2
    assert json.loads(latest.read_text(encoding="utf-8"))["stocks"] == []
    assert json.loads(signals.read_text(encoding="utf-8"))["signal_id"] == "abc"


def test_runtime_state_rejects_secret_like_json_keys(tmp_path) -> None:
    repo = tmp_path / "repo"
    vault = tmp_path / "vault"
    latest = repo / "public/data/latest.json"
    latest.parent.mkdir(parents=True)
    latest.write_text(json.dumps({"api_key": "must-not-persist"}), encoding="utf-8")

    with pytest.raises(ValueError, match="secret-like key"):
        publish_runtime_state(repo_root=repo, vault_root=vault)


def test_runtime_state_does_not_copy_non_allowlisted_files(tmp_path) -> None:
    repo = tmp_path / "repo"
    vault = tmp_path / "vault"
    extra = repo / "private.txt"
    extra.parent.mkdir(parents=True)
    extra.write_text("not runtime state", encoding="utf-8")

    publish_runtime_state(repo_root=repo, vault_root=vault)
    assert not (vault / "private.txt").exists()
    assert "private.txt" not in RUNTIME_PATHS


def test_runtime_allowlist_contains_dashboard_and_continuity_files() -> None:
    assert "public/data/latest.json" in RUNTIME_PATHS
    assert "public/data/health.json" in RUNTIME_PATHS
    assert "public/data/data-status.json" in RUNTIME_PATHS
    assert "data/live/signals.jsonl" in RUNTIME_PATHS
    assert "data/live/outcomes.json" in RUNTIME_PATHS
    assert "data/live/calibration.json" in RUNTIME_PATHS
