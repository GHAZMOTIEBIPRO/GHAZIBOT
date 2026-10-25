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


def test_engine_status_keeps_run_source_data_analysis_and_alerts_apart(tmp_path):
    data, state = tmp_path / "data", tmp_path / "state"
    _write(data / "data_hub.json", {
        "source_gates": {"nasdaq_web": {"allowed": False}, "yahoo": {"allowed": False}},
        "datasets": [
            {"file": "explosion_hunter.json", "freshness": "STALE", "data_state": "LICENSE_BLOCKED"},
            {"file": "decision_brief.json", "freshness": "FRESH", "data_state": "RESEARCH_ONLY"},
            {"file": "fda_events.json", "freshness": "FRESH", "data_state": "DELAYED"},
            {"file": "catalyst_watchlist.json", "freshness": "FRESH", "data_state": "DELAYED"},
            {"file": "sec_filing_pulse.json", "freshness": "FRESH", "data_state": "SOURCE_UNAVAILABLE"}]})
    _write(data / "explosion_hunter.json", {"status": "STALE"})
    _write(data / "decision_brief.json", {"stocks": []})
    _write(data / "fda_events.json", {})
    _write(data / "catalyst_watchlist.json", {"watchlist": [{"symbol": "GSK"}]})
    _write(data / "sec_filing_pulse.json", {"status": "SOURCE_UNAVAILABLE"})
    _write(state / "fda/fda_alert_state.json", {"events": {
        "a": {"at": "2026-10-20T19:57:54+00:00", "status": "seeded"},
        "b": {"at": "2026-10-23T17:56:14+00:00", "status": "sent", "message_id": 1292}}})
    # seeded rows and a timestamp without a Telegram message id are not deliveries
    _write(state / "catalyst/catalyst_alert_state.json", {
        "seeded_at": "2026-10-21T20:26:34+00:00", "seen": {"x": {"status": "seeded"}}})
    runs = {"fast-explosion-radar.yml": [{"status": "completed", "conclusion": "success",
                                          "created_at": "2026-10-25T07:20:54Z"}],
            "fda-events.yml": [{"status": "completed", "conclusion": "failure", "created_at": "2026-10-25T06:00:00Z"},
                               {"status": "in_progress", "conclusion": None, "created_at": "2026-10-25T07:00:00Z"}],
            "stock-radar.yml": []}
    eng = cards.engine_status(data, state, runs)
    fast = eng["fast_explosion"]
    # a green run does not restore an engine whose only source is closed
    assert fast["run"] == "OK" and fast["source"] == "BLOCKED_BY_TERMS" and fast["data"] == "STALE"
    assert fast["analysis"] == "NOT_COMPUTED" and fast["verdict_ar"] == "متوقف لغياب مصدر مؤهل"
    stock = eng["stock_radar"]
    assert stock["run"] == "NO_RUN_24H" and stock["data"] == "EMPTY" and stock["rows"] == 0
    fda = eng["fda"]
    assert fda["run"] == "FAILED" and fda["analysis"] == "COMPUTED"
    assert fda["alerts"] == "DELIVERED 2026-10-23T17:56:14+00:00"
    cat = eng["catalysts"]
    assert cat["run"] == "API_UNAVAILABLE" and cat["alerts"] == "NONE_DELIVERED" and cat["rows"] == 1
    assert eng["sec"]["source"] == "REFUSED_OR_DOWN" and eng["sec"]["data"] == "NONE"
    assert eng["daily_plan"]["source"] == "NO_OUTPUT"
    assert set(cards.ENGINE_WORKFLOWS).isdisjoint(cards.CORE_WORKFLOWS)
