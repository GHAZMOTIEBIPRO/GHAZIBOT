import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from options_radar import source_permissions as sp

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


explosion = _load("publish_explosion_hunter")
classical = _load("publish_classical_direction")
cards = _load("build_platform_scorecards")


@pytest.fixture(autouse=True)
def closed_gates(monkeypatch):
    for gate in sp.GATES.values():
        monkeypatch.delenv(gate["variable"], raising=False)


def _frontend_explosion_ok(d):
    return (d["schema"] == "ghazi.explosion_hunter_public.v1" and d["research_only"] is True
            and d["score_is_probability"] is False and d["execution_authority"] is False
            and isinstance(d["candidates"], list))


def test_explosion_digest_withdrawn_while_nasdaq_gate_closed(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(),
                                 "candidates": [{"symbol": "GPUS"}]}))
    out = tmp_path / "out.json"
    monkeypatch.setattr(sys, "argv", ["x", "--input", str(state), "--output", str(out)])
    assert explosion.main() == 0
    data = json.loads(out.read_text())
    assert data["status"] == "SOURCE_TERMS_BLOCKED" and data["candidates"] == []
    assert _frontend_explosion_ok(data)


def test_explosion_digest_withdrawn_when_scan_is_old(tmp_path, monkeypatch):
    monkeypatch.setenv("NASDAQ_WEB_AUTOMATION_APPROVED", "true")
    state = tmp_path / "state.json"
    old = datetime.now(timezone.utc) - timedelta(hours=7)
    state.write_text(json.dumps({"generated_at": old.isoformat(), "candidates": [{"symbol": "GPUS"}]}))
    out = tmp_path / "out.json"
    monkeypatch.setattr(sys, "argv", ["x", "--input", str(state), "--output", str(out)])
    assert explosion.main() == 0
    data = json.loads(out.read_text())
    assert data["status"] == "STALE" and data["candidates"] == [] and _frontend_explosion_ok(data)


def test_classical_digest_withdrawn_keeps_frontend_contract(tmp_path, monkeypatch):
    out = tmp_path / "classical.json"
    monkeypatch.setattr(sys, "argv", ["x", "--source-blocked", "SOURCE_TERMS_BLOCKED: no source", "--output", str(out)])
    assert classical.main() == 0
    d = json.loads(out.read_text())
    assert d["status"] == "SOURCE_TERMS_BLOCKED" and d["companies"] == []
    assert d["schema"] == "ghazi.classical_direction_public.v1" and d["probability"] is None
    assert d["research_only"] is True and d["execution_authority"] is False
    assert d["option_data_used_for_direction"] is False


def test_classical_publisher_workflow_withdraws_before_download():
    doc = yaml.safe_load((ROOT / ".github/workflows/publish-classical-direction.yml").read_text())
    steps = {s.get("name"): s for s in doc["jobs"]["publish"]["steps"]}
    assert "--source-blocked" in steps["Withdraw the public digest while no permitted source exists"]["run"]
    assert steps["Download the classical direction payload"]["if"] == "steps.gate.outputs.usable == 'true'"


def test_spx_publisher_is_serialised():
    doc = yaml.safe_load((ROOT / ".github/workflows/spx-dashboard.yml").read_text())
    assert doc["concurrency"]["cancel-in-progress"] is False


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def test_scorecards_are_separate_and_honest(tmp_path):
    now = datetime(2026, 10, 20, 19, 0, tzinfo=timezone.utc)
    data, state, runtime = tmp_path / "data", tmp_path / "state", tmp_path / "runtime"
    _write(data / "index_radar.json", {"generated_at": now.isoformat(), "status": "SOURCE_TERMS_BLOCKED"})
    _write(data / "public_macro.json", {"generated_at": now.isoformat()})
    _write(data / "explosion_hunter.json", {"generated_at": now.isoformat(), "status": "STALE"})
    _write(data / "site_strength.json", {"strength_score": 19})
    _write(data / "data_hub.json", {"datasets": [
        {"file": "a", "present": True, "validation": "PASS", "rights_status": "OK_FOR_STATED_USE"},
        {"file": "b", "present": True, "validation": "PASS", "rights_status": "BLOCKED_PENDING_PERMISSION"}]})
    _write(state / "stocks/stock_walk_forward.json", {"status": "FAILED_RESEARCH_GATE", "research_passed": False})
    _write(runtime / "data/live/guardian_delivery_audit.json", {
        "checked_at": now.isoformat(), "bot_api_responded": True, "destination_api_verified": True})
    runs = {"options-radar.yml": [{"status": "completed", "conclusion": "success"},
                                  {"status": "completed", "conclusion": "failure"},
                                  {"status": "completed", "conclusion": "skipped"}]}
    report = cards.build(data, state, runtime, now, runs, None)
    sc = report["scorecards"]
    assert sc["SYSTEM_RELIABILITY"]["value"] == 50.0
    cov = sc["DATA_COVERAGE"]["evidence"]
    assert cov["index_prices"] == "LICENSE_BLOCKED" and cov["macro_positioning"] == "AVAILABLE"
    assert cov["explosion_discovery"] == "STALE" and cov["issuer_filings"] == "SOURCE_UNAVAILABLE"
    assert sc["DATA_TRUST"]["value"] == 50.0
    assert sc["ANALYTICAL_VALIDITY"]["status"] == "UNMEASURED"
    assert sc["SIGNAL_PERFORMANCE"]["status"] == "NO_PROVEN_EDGE"
    assert sc["WEBSITE_FUNCTIONALITY"]["status"] == "UNMEASURED"
    assert sc["TELEGRAM_DELIVERY"]["status"] == "API_VERIFIED"
    assert report["combined_score"] is None and report["decision_grade"] is False
    assert report["original_evidence_score"] == {"value": 19, "weights_changed": False,
                                                 "note": "kept as published by site_strength.json with its original weights"}
