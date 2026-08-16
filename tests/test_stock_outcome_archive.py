from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import options_radar.durable_stock_state as durable_stock
from options_radar.adaptive_learning import build_learning_model
from options_radar.stock_outcome_archive import update_stock_outcome_archive


def _event(
    signal_id: str,
    *,
    outcome: str = "success",
    with_60m: bool = True,
    entry_stage: str = "IGNITION",
    stage: str = "EXPLOSION",
    entry_score: float = 85.0,
    score: float = 95.0,
    signal_time: str = "2026-08-10T15:00:00+00:00",
) -> dict:
    checkpoints = {}
    if with_60m:
        checkpoints["60m"] = {
            "observed_at": "2026-08-10T16:00:00+00:00",
            "directional_return_pct": 12.0 if outcome == "success" else -7.0,
        }
    return {
        "signal_id": signal_id,
        "signal_time": signal_time,
        "symbol": f"T{signal_id[-3:]}",
        "direction": "up",
        "entry_price": 10.0,
        "entry_stage": entry_stage,
        "entry_score": entry_score,
        "entry_score_band": "80-89",
        "stage": stage,
        "score": score,
        "score_band": "90-100",
        "market_regime": "risk_on",
        "cause_category": "EARNINGS",
        "cause_tier": "official_primary",
        "official_cause": True,
        "follow_through_target_pct": 10.0,
        "failure_threshold_pct": 6.0,
        "terminal_outcome": outcome,
        "terminal_reason": "follow_through_target_observed" if outcome == "success" else "failure_threshold_observed",
        "terminal_at": "2026-08-10T16:00:00+00:00",
        "mfe_pct": 12.0,
        "mae_pct": -2.0,
        "checkpoints": checkpoints,
        "measurement_basis": "repeated_radar_snapshots",
    }


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_archive_accepts_only_matured_decisive_events(tmp_path):
    stock = tmp_path / "stock.json"
    archive = tmp_path / "archive.json"
    _write(
        stock,
        {
            "signals": {
                "good": _event("good"),
                "open": {**_event("open"), "terminal_outcome": "open"},
                "young": _event("young", with_60m=False),
            }
        },
    )
    payload = update_stock_outcome_archive(stock, archive)
    assert payload["summary"]["records"] == 1
    assert payload["summary"]["successes"] == 1
    assert set(payload["records"]) == {"good"}
    assert payload["decision_authority"] is False


def test_same_event_updates_without_inflating_sample(tmp_path):
    stock = tmp_path / "stock.json"
    archive = tmp_path / "archive.json"
    row = _event("same")
    _write(stock, {"signals": {"same": row}})
    first = update_stock_outcome_archive(stock, archive)
    assert first["summary"]["added_this_pass"] == 1

    row["checkpoints"]["1d"] = {
        "observed_at": "2026-08-11T15:00:00+00:00",
        "directional_return_pct": 18.0,
    }
    row["mfe_pct"] = 18.0
    _write(stock, {"signals": {"same": row}})
    second = update_stock_outcome_archive(stock, archive)
    assert second["summary"]["records"] == 1
    assert second["summary"]["added_this_pass"] == 0
    assert second["summary"]["updated_this_pass"] == 1
    assert "1d" in second["records"]["same"]["checkpoints"]


def test_archive_survives_live_tracker_window_and_drives_shadow_model(tmp_path):
    stock = tmp_path / "stock.json"
    archive = tmp_path / "archive.json"
    signals = {}
    base = datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc)
    for index in range(60):
        outcome = "success" if index < 42 else "failed"
        signals[f"s{index}"] = _event(
            f"s{index}",
            outcome=outcome,
            signal_time=(base + timedelta(days=index)).isoformat(),
        )
    _write(stock, {"signals": signals})
    archived = update_stock_outcome_archive(stock, archive)
    assert archived["summary"]["records"] == 60

    # Simulate the operational rolling window having already discarded old rows.
    _write(stock, {"signals": {}})
    options_signals = tmp_path / "options.jsonl"
    options_signals.write_text("", encoding="utf-8")
    options_outcomes = tmp_path / "options_outcomes.json"
    _write(options_outcomes, {"signals": {}})

    model = build_learning_model(
        stock_outcomes_path=stock,
        stock_archive_path=archive,
        options_signals_path=options_signals,
        options_outcomes_path=options_outcomes,
    )
    assert model["stock"]["matured_decisive"] == 60
    assert model["stock"]["ready"] is True
    assert model["policy"]["stock_learning_uses_durable_event_archive"] is True
    assert model["policy"]["stock_event_identity_deduped"] is True


def test_learning_cohorts_use_entry_evidence_not_later_stage(tmp_path):
    stock = tmp_path / "stock.json"
    archive = tmp_path / "archive.json"
    signals = {f"s{i}": _event(f"s{i}") for i in range(60)}
    _write(stock, {"signals": signals})
    update_stock_outcome_archive(stock, archive)
    options_signals = tmp_path / "options.jsonl"
    options_signals.write_text("", encoding="utf-8")
    options_outcomes = tmp_path / "options_outcomes.json"
    _write(options_outcomes, {"signals": {}})
    _write(stock, {"signals": {}})

    model = build_learning_model(
        stock_outcomes_path=stock,
        stock_archive_path=archive,
        options_signals_path=options_signals,
        options_outcomes_path=options_outcomes,
    )
    assert model["stock"]["stages"]["IGNITION"]["sample"] == 60
    assert "EXPLOSION" not in model["stock"]["stages"]
    assert model["stock"]["score_bands"]["80-89"]["sample"] == 60
    assert "90-100" not in model["stock"]["score_bands"]


def test_archive_cap_is_bounded(tmp_path):
    stock = tmp_path / "stock.json"
    archive = tmp_path / "archive.json"
    base = datetime(2026, 1, 1, 15, 0, tzinfo=timezone.utc)
    signals = {
        f"s{i}": _event(f"s{i}", signal_time=(base + timedelta(hours=i)).isoformat())
        for i in range(120)
    }
    _write(stock, {"signals": signals})
    payload = update_stock_outcome_archive(stock, archive, maximum_records=100)
    assert payload["summary"]["records"] == 100
    assert payload["maximum_records"] == 100
    assert "s0" not in payload["records"]
    assert "s119" in payload["records"]


def test_durable_stock_restore_preserves_hot_files(tmp_path, monkeypatch):
    hot = tmp_path / "data/live/stock_outcomes.json"
    _write(hot, {"signals": {"hot": {}}})
    remote = {
        "state/stocks/stock_outcomes.json": b'{"signals":{"old":{}}}',
        "state/stocks/stock_outcome_archive.json": b'{"records":{"a":{}}}',
        "state/stocks/stock_outcome_audit.json": b'{"records":{"audit":{}}}',
        "state/stocks/adaptive_learning.json": b'{"stock":{"ready":false}}',
    }

    def fake_git(root: Path, *args: str):
        if args[0] == "fetch":
            return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")
        path = args[1].split(":", 1)[1]
        return subprocess.CompletedProcess(args, 0, stdout=remote[path], stderr=b"")

    monkeypatch.setattr(durable_stock, "_git", fake_git)
    status = durable_stock.restore_missing_durable_stock_state(tmp_path)
    assert "data/live/stock_outcomes.json" in status.preserved_local
    assert "data/live/stock_outcomes.json" not in status.restored
    assert json.loads(hot.read_text())["signals"] == {"hot": {}}
    assert len(status.restored) == 3
    assert "data/live/stock_outcome_audit.json" in status.restored


def test_stock_vault_and_adaptive_workflow_preserve_shadow_only_policy():
    root = Path(__file__).resolve().parents[1]
    vault = (root / ".github/workflows/stock-state-vault.yml").read_text(encoding="utf-8")
    adaptive = (root / ".github/workflows/adaptive-review.yml").read_text(encoding="utf-8")
    options_vault = (root / ".github/workflows/options-state-vault.yml").read_text(encoding="utf-8")

    assert "BLACK BOX Omega Stock Radar" in vault
    assert "BLACK BOX Omega Adaptive Evidence Review" in vault
    assert "BLACK BOX Omega Stock Outcome Auditor" in vault
    assert "ref: bot-state" in vault
    assert "contents: write" in vault
    assert "stock_outcome_archive.json" in vault
    assert "stock_outcome_audit.json" in vault
    assert "adaptive_learning.json" in vault
    assert "[skip ci]" in vault
    assert "git pull --rebase origin bot-state" in vault
    assert "git push origin HEAD:bot-state" in vault
    assert "options-contract-state" not in vault

    assert "STOCK_OUTCOME_ARCHIVE_PATH" in adaptive
    assert "stock_outcome_archive.json" in adaptive
    assert 'PAID_MARKET_DATA_ALLOWED: "false"' in adaptive
    assert "live_alert_weights_changed'] is False" in adaptive
    assert "stock_learning_uses_durable_event_archive" in adaptive

    assert "git pull --rebase origin bot-state" in options_vault
    assert "for attempt in 1 2 3" in options_vault
