"""Audit regressions: no false source availability, no tradable proxy outcomes."""
import json
from datetime import datetime, timezone
from pathlib import Path

from options_radar import phase6_publisher as publisher
from options_radar.trust_verdict import assess
from scripts.runtime_state_vault import publish_runtime_state

NOW = datetime(2026, 10, 30, 22, 50, tzinfo=timezone.utc)


def sample():
    latest = {"generated_at": NOW.isoformat(), "stocks": [], "options": [],
              "summary": {"option_candidates": 0},
              "source_network": {"summary": {"active_option_sources": 1}},
              "performance": {"path_evaluated": 128, "successful": 28,
                              "stopped_out": 84, "ambiguous": 0,
                              "option_contract_basis": 0,
                              "underlying_proxy_basis": 128},
              "calibration": {"calibration_ready": True, "matured_sample": 230}}
    status = {"generated_at": NOW.isoformat(), "status": "degraded",
              "row_counts": {"stocks": 0, "options": 0},
              "quality_counts": {"critical_errors": 2},
              "coverage_diagnostics": {
                  "stock_primary_non_yahoo_families_reported": [],
                  "option_chain_source_families": [],
                  "option_live_primary_chains_reported": 0,
                  "options_execution_quote_ready": False,
                  "options_trade_flow_ready": False}}
    health = {"generated_at": NOW.isoformat(),
              "checks": {"critical_pipeline_ok": False}}
    return latest, status, health


def test_critical_production_state_cannot_be_mistaken_for_verified_edge():
    latest, status, health = sample()
    v = assess(latest, status, health, now=NOW)
    assert v["status"] == "NOT_TRADE_READY"
    assert v["historical_research"]["target_first"] == 28
    assert v["historical_research"]["stop_first"] == 84
    assert v["historical_research"]["unclassified_within_evaluated"] == 16
    assert v["historical_research"]["target_first_pct_of_path_evaluated"] == 21.88
    assert v["historical_research"]["option_contract_basis"] == 0
    assert v["historical_research"]["underlying_proxy_basis"] == 128
    assert v["historical_research"]["sample_gate"] == "SAMPLE_SIZE_ONLY_NOT_EDGE"
    assert v["prediction_accuracy_pct"] is None
    assert v["historical_research"]["win_probability_calibrated"] is False
    assert "SOURCE_COUNT_NOT_PROOF_OF_APPROVED_OPTION_CHAIN" in v["source_reporting_disagreements"]
    assert v["trade_recommendations_authorized"] is False


def test_source_network_does_not_claim_yahoo_as_live_from_empty_rows(monkeypatch):
    for k in ("YAHOO_AUTOMATED_ACCESS_APPROVED",):
        monkeypatch.delenv(k, raising=False)
    report = publisher.build_source_network({
        "stocks": [], "options": [], "errors": {}, "provider_audit": {}})
    assert report["summary"]["active_option_sources"] == 0
    assert not next(x for x in report["options"] if "Yahoo" in x["name"])["active"]
    assert not next(x for x in report["stocks"] if "Yahoo" in x["name"])["active"]


def test_context_plus_yahoo_is_not_two_tradable_price_confirmations():
    stock = publisher._stock_recommendation({
        "symbol": "AAPL", "score": 100,
        "new_stock_setup": True, "catalyst_source": "Official IR",
        "fundamental_source": "SEC Company Facts"})
    assert stock["decision"] != "دخول مشروط"
    assert stock["execution_authority"] is False
    assert stock["confidence_basis"] == "heuristic_priority_score_not_win_probability"
    contract = publisher._contract_recommendation({
        "contract_symbol": "SPY261030C00750000", "score": 100,
        "flow_score": 100, "unusual_activity_flag": True,
        "source": "indicative", "volume_history_source": "historical bars",
        "catalyst_source": "Official IR"})
    assert contract["decision"] != "دخول مشروط"
    assert contract["execution_authority"] is False


def test_bad_counters_and_stale_reports_fail_closed():
    latest, status, health = sample()
    latest["performance"]["successful"] = 140
    latest["performance"]["underlying_proxy_basis"] = 140
    v = assess(latest, status, health, now=NOW)
    assert not v["historical_research"]["outcome_counters_valid"]
    assert v["historical_research"]["target_first_pct_of_path_evaluated"] is None
    assert "OUTCOME_COUNTERS_INVALID" in v["blockers"]
    latest, status, health = sample()
    v2 = assess(latest, status, health, now=NOW.replace(day=31))
    assert "REPORT_STALE_OR_INCONSISTENT_TIMESTAMPS" in v2["blockers"]


def test_public_vault_updates_already_redacted_latest_and_status_without_prices(tmp_path):
    source = tmp_path / "code"
    target = tmp_path / "bot-state"
    (source / "public/data").mkdir(parents=True)
    latest, status, health = sample()
    latest["stock_recommendations"] = [
        {"symbol": "AMD", "decision": "دخول مشروط بعد تحقق منطقة الدخول",
         "confidence": 92}]
    latest["contract_recommendations"] = [
        {"symbol": "SPY", "decision": "عقد مرشح لدخول مشروط بعد تحقق السعر",
         "confidence": 94}]
    latest["summary"]["stock_recommendations"] = 1
    latest["summary"]["contract_recommendations"] = 1
    (source / "public/data/latest.json").write_text(json.dumps(latest))
    (source / "public/data/data-status.json").write_text(json.dumps(status))
    (source / "public/data/health.json").write_text(json.dumps(health))
    publish_runtime_state(repo_root=source, vault_root=target)
    a = json.loads((target / "public/data/latest.json").read_text())
    b = json.loads((target / "public/data/data-status.json").read_text())
    assert a["trust_verdict"] == b["trust_verdict"]
    assert a["trust_verdict"]["status"] == "NOT_TRADE_READY"
    assert a["trust_verdict"]["trade_recommendations_authorized"] is False
    assert "option_prices" not in json.dumps(a["trust_verdict"])
    for row in a["stock_recommendations"] + a["contract_recommendations"]:
        assert "دخول مشروط" not in row["decision"]
        assert row["execution_authority"] is False
        assert row["confidence_basis"] == "research_ranking_not_win_probability"
    assert a["summary"]["stock_recommendations"] == 0
    assert a["summary"]["contract_recommendations"] == 0


def test_quality_panel_accepts_valid_data_status_with_null_options_readiness():
    source = Path("public/ghazi-radar-quality.js").read_text(encoding="utf-8")
    assert "!payload.coverage_diagnostics" in source
    assert "!payload.option_provider_readiness" not in source
    assert "const truth = data.trust_verdict" in source
    assert "option_chain_source_families" in source
    classic = Path("public/app.js").read_text(encoding="utf-8")
    assert "حد عدد عينات المراجعة البحثية" in classic
    assert "ليست نسبة نجاح عقود منفذة" in classic
