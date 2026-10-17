"""Regression tests for truthful market-session and Telegram diagnostics."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import send_radar_health as health
from scripts.write_e2e_delivery_evidence import build_evidence


NOW = datetime(2026, 10, 19, 14, 40, tzinfo=timezone.utc)


def option_health(ready=False, status="FALLBACK_ONLY"):
    return {
        "health": {"status": "DEGRADED", "reasons": ["12 chain(s) are Yahoo/YFinance-only fallback"]},
        "provider_readiness": {
            "status": status,
            "production_quote_ready": ready,
            "production_flow_ready": ready,
            "sources": ["yahoo"] if not ready else ["licensed-feed"],
        },
    }


def test_degraded_options_sender_advisory_is_once_per_open_session_day(monkeypatch):
    delivered = []
    monkeypatch.setattr(health, "_send", delivered.append)
    state = {"paths": {}}
    payload = option_health()
    assert health.maybe_send("options", payload, state, now=NOW)
    assert "Yahoo" in delivered[0] or "احتياطي" in delivered[0]
    assert not health.maybe_send("options", payload, state, now=NOW + timedelta(minutes=15))
    assert len(delivered) == 1
    assert health.maybe_send("options", payload, state, now=NOW + timedelta(days=1))
    assert len(delivered) == 2
    assert not health.maybe_send("options", payload, state, now=NOW + timedelta(days=1, minutes=15))


def test_provider_recovers_without_health_status_change_notifies(monkeypatch):
    messages = []
    monkeypatch.setattr(health, "_send", messages.append)
    state = {"paths": {}}
    assert health.maybe_send("options", option_health(), state, now=NOW)
    assert health.maybe_send("options", option_health(True, "LIVE_FLOW_READY"), state, now=NOW + timedelta(minutes=15))
    assert "تحسنت أهلية الأسعار" in messages[-1]
    assert not health.maybe_send("options", option_health(True, "LIVE_FLOW_READY"), state, now=NOW + timedelta(minutes=30))


def test_stock_health_not_given_options_daily_nudge(monkeypatch):
    messages = []
    monkeypatch.setattr(health, "_send", messages.append)
    state = {"paths": {}}
    payload = {"health": {"status": "DEGRADED", "reasons": ["offline"]}}
    assert health.maybe_send("stocks", payload, state, now=NOW)
    assert not health.maybe_send("stocks", payload, state, now=NOW + timedelta(days=1))
    assert len(messages) == 1


def test_closed_market_e2e_records_skip_not_delivery():
    evidence = build_evidence(
        {}, {"last_sent_count": 9, "last_run_at": "2026-10-16T15:00:00Z"},
        run_id="closed-session", now=NOW, market_open=False,
    )
    assert evidence["diagnosis"]["reason_code"] == "MARKET_CLOSED"
    assert evidence["diagnosis"]["new_messages_confirmed_for_scan"] is None
    assert evidence["diagnosis"]["delivery_state_current_scan"] is False
    assert evidence["market_scan"]["candidate_count"] == 0


def test_research_only_options_explains_why_no_execution_signals():
    payload = {
        "generated_at": NOW.isoformat(),
        "provider_readiness": {"status": "FALLBACK_ONLY", "production_quote_ready": False},
        "free_directional_signals": [],
    }
    evidence = build_evidence(payload, {}, run_id="research", now=NOW, market_open=True)
    assert evidence["diagnosis"]["reason_code"] == "NO_EXECUTION_GRADE_QUOTES"
    assert "بحثية" in evidence["diagnosis"]["note_ar"]
    assert evidence["telegram"]["sent_count"] == 0


def test_old_telegram_state_is_never_verified_for_new_scan():
    payload = {"generated_at": NOW.isoformat(),
               "provider_readiness": {"status": "LIVE_FLOW_READY", "production_quote_ready": True}}
    old_state = {"last_sent_count": 7, "last_run_at": "2026-10-16T15:00:00Z"}
    output = build_evidence(payload, old_state, run_id="replay", now=NOW)
    assert output["diagnosis"]["delivery_state_current_scan"] is False
    assert output["diagnosis"]["new_messages_confirmed_for_scan"] is None
    current = dict(old_state, last_run_at=(NOW + timedelta(seconds=25)).isoformat())
    accepted = build_evidence(payload, current, run_id="fresh", now=NOW + timedelta(minutes=1))
    assert accepted["diagnosis"]["delivery_state_current_scan"] is True
    assert accepted["diagnosis"]["new_messages_confirmed_for_scan"] == 7


def test_e2e_artifact_is_written_for_closed_market_runs():
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/options-contract-radar.yml").read_text(encoding="utf-8")
    assert "--market-open" in workflow
    section = workflow.split("name: Record non-sensitive options E2E delivery evidence", 1)[1]
    assert "if: always()" in section.split("name: Upload options E2E delivery evidence")[0]
    assert "name: options-e2e-evidence" in section
