from __future__ import annotations

import json
import subprocess
from pathlib import Path

import options_radar.durable_state as durable


def _write_all_hot_state(root: Path) -> None:
    payloads = {
        "data/live/options_alert_state.json": '{"sent": {}}\n',
        "data/live/options_signals.jsonl": '{"signal_id": "hot"}\n',
        "data/live/options_outcomes.json": '{"signals": {"hot": {}}}\n',
        "data/live/options_calibration.json": '{"sample_size": 0, "shadow_sample_size": 0}\n',
    }
    for name, text in payloads.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def test_durable_restore_never_overwrites_complete_hot_state(tmp_path, monkeypatch):
    _write_all_hot_state(tmp_path)

    def forbidden_git(*args, **kwargs):
        raise AssertionError("git must not run when hot state is complete")

    monkeypatch.setattr(durable, "_git", forbidden_git)
    status = durable.restore_missing_durable_options_state(tmp_path)
    assert status.attempted is False
    assert len(status.preserved_local) == 4
    assert status.restored == ()
    assert json.loads((tmp_path / "data/live/options_outcomes.json").read_text())["signals"] == {"hot": {}}


def test_durable_restore_fills_only_missing_files(tmp_path, monkeypatch):
    hot = tmp_path / "data/live/options_outcomes.json"
    hot.parent.mkdir(parents=True, exist_ok=True)
    hot.write_text('{"signals": {"hot": {}}}\n', encoding="utf-8")

    remote = {
        "state/options/options_alert_state.json": b'{"sent": {}}\n',
        "state/options/options_signals.jsonl": b'{"signal_id": "durable"}\n',
        "state/options/options_outcomes.json": b'{"signals": {"durable": {}}}\n',
        "state/options/options_calibration.json": b'{"sample_size": 0, "shadow_sample_size": 0}\n',
    }

    def fake_git(root: Path, *args: str):
        if args[0] == "fetch":
            return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")
        if args[0] == "show":
            remote_path = args[1].split(":", 1)[1]
            payload = remote.get(remote_path)
            if payload is None:
                return subprocess.CompletedProcess(args, 1, stdout=b"", stderr=b"missing")
            return subprocess.CompletedProcess(args, 0, stdout=payload, stderr=b"")
        raise AssertionError(args)

    monkeypatch.setattr(durable, "_git", fake_git)
    status = durable.restore_missing_durable_options_state(tmp_path)
    assert status.branch_available is True
    assert "data/live/options_outcomes.json" in status.preserved_local
    assert "data/live/options_outcomes.json" not in status.restored
    assert len(status.restored) == 3
    assert json.loads(hot.read_text())["signals"] == {"hot": {}}
    assert json.loads((tmp_path / "data/live/options_alert_state.json").read_text()) == {"sent": {}}
    assert (tmp_path / "data/live/options_signals.jsonl").read_text().strip() == '{"signal_id": "durable"}'


def test_invalid_durable_json_is_not_restored(tmp_path, monkeypatch):
    def fake_git(root: Path, *args: str):
        if args[0] == "fetch":
            return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")
        return subprocess.CompletedProcess(args, 0, stdout=b"not-json", stderr=b"")

    monkeypatch.setattr(durable, "_git", fake_git)
    status = durable.restore_missing_durable_options_state(tmp_path)
    assert status.branch_available is True
    assert status.restored == ()
    assert not (tmp_path / "data/live/options_outcomes.json").exists()


def test_fetch_failure_is_nonfatal_and_does_not_invent_state(tmp_path, monkeypatch):
    def fake_git(root: Path, *args: str):
        return subprocess.CompletedProcess(args, 1, stdout=b"", stderr=b"network unavailable")

    monkeypatch.setattr(durable, "_git", fake_git)
    status = durable.restore_missing_durable_options_state(tmp_path)
    assert status.attempted is True
    assert status.branch_available is False
    assert "network unavailable" in status.error
    assert status.restored == ()


def test_options_runner_restores_durable_state_before_hardened_engine():
    root = Path(__file__).resolve().parents[1]
    text = (root / "scripts" / "run_options_radar_fabric.py").read_text(encoding="utf-8")
    assert "restore_missing_durable_options_state" in text
    assert text.index("restore_missing_durable_options_state()") < text.index("install_data_fabric()")
    assert text.index("restore_missing_durable_options_state()") < text.index("run_options_radar_hardened")


def test_state_vault_is_options_only_secret_guarded_and_skip_ci():
    root = Path(__file__).resolve().parents[1]
    text = (root / ".github" / "workflows" / "options-state-vault.yml").read_text(encoding="utf-8")
    assert "BLACK BOX Omega Options Contract Radar" in text
    assert "BLACK BOX Omega Options Performance Auditor" in text
    assert "contents: write" in text
    assert "ref: bot-state" in text
    assert "state/options/options_outcomes.json" not in text  # copied by basename into fixed state/options directory
    assert "mkdir -p state/options" in text
    assert "options_outcomes.json" in text
    assert "options_calibration.json" in text
    assert "options_performance_report_state.json" in text
    assert "forbidden = ('token', 'secret', 'api_key', 'authorization', 'password', 'credential')" in text
    assert "[skip ci]" in text
    assert "git push origin HEAD:bot-state" in text
    assert "stock-radar.yml" not in text


def test_performance_auditor_uses_durable_state_with_artifact_fallback():
    root = Path(__file__).resolve().parents[1]
    text = (root / ".github" / "workflows" / "options-performance-auditor.yml").read_text(encoding="utf-8")
    assert "bot-state:refs/remotes/origin/bot-state" in text
    assert "state/options/options_outcomes.json" in text
    assert "state/options/options_calibration.json" in text
    assert "state/performance/options_performance_report_state.json" in text
    assert "options-contract-state" in text
    assert "options-performance-audit" in text
    assert "Restored learning state passed integrity checks" in text
    assert "PAID_MARKET_DATA_ALLOWED: \"false\"" in text
