import json
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from scripts import guardian_delivery_audit as audit
from scripts import send_contract_guardian_updates as sender


NOW = datetime(2026, 10, 7, 18, 0, tzinfo=timezone.utc)


def _report(*, age_minutes=2, active_count=1):
    return {
        "generated_at": (NOW - timedelta(minutes=age_minutes)).isoformat(),
        "tracked_total": active_count,
        "active_count": active_count,
        "active": [],
    }


def test_guardian_preflight_exposes_blockers_without_secrets():
    blocked = audit.build_delivery_preflight(
        _report(), token_configured=False, destination_ready=False, now=NOW
    )
    assert blocked["status"] == "BLOCKED_MISSING_BOT_TOKEN"

    blocked = audit.build_delivery_preflight(
        _report(), token_configured=True, destination_ready=False, now=NOW
    )
    assert blocked["status"] == "BLOCKED_MISSING_DESTINATION"

    stale = audit.build_delivery_preflight(
        _report(age_minutes=130),
        token_configured=True, destination_ready=True, now=NOW
    )
    assert stale["status"] == "BLOCKED_STALE_GUARDIAN_REPORT"

    idle = audit.build_delivery_preflight(
        _report(active_count=0),
        token_configured=True, destination_ready=True, now=NOW
    )
    assert idle["status"] == "NO_ACTIVE_CONTRACTS"

    ready = audit.build_delivery_preflight(
        _report(), token_configured=True, destination_ready=True, now=NOW
    )
    assert ready["status"] == "READY_TO_DELIVER"
    assert ready["telegram_token_configured"] is True
    assert ready["contains_secrets"] is False


def test_preflight_future_or_missing_generation_time_fails_closed():
    future = audit.build_delivery_preflight(
        _report(age_minutes=-20),
        token_configured=True, destination_ready=True, now=NOW
    )
    missing = audit.build_delivery_preflight(
        {"active_count": 1},
        token_configured=True, destination_ready=True, now=NOW
    )
    assert future["status"] == "BLOCKED_STALE_GUARDIAN_REPORT"
    assert missing["status"] == "BLOCKED_STALE_GUARDIAN_REPORT"


def test_sender_records_real_accepted_delivery_without_credentials(monkeypatch, tmp_path):
    contract = {
        "symbol": "TEST",
        "contract_symbol": "TEST261120C00100000",
        "side": "CALL",
        "stage": "WATCH",
        "strike": 100,
        "expiration": "2026-11-20",
        "entry_premium_reference": 1.2,
        "last_mark": None,
        "last_return_pct": None,
        "data_stale": True,
        "entry_reference_verified": False,
    }
    report_path = tmp_path / "guardian.json"
    report_path.write_text(
        json.dumps({**_report(), "active": [contract]}), encoding="utf-8"
    )
    state_path = tmp_path / "delivery_state.json"
    audit_path = tmp_path / "delivery_audit.json"
    audit_path.write_text(
        json.dumps({"status": "READY_TO_DELIVER"}), encoding="utf-8"
    )

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-fake-secret")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "test-fake-destination")
    monkeypatch.setattr(
        sender, "send_html_message", lambda text: SimpleNamespace(message_id=451)
    )
    monkeypatch.setattr(
        sys, "argv", [
            "sender", "--report", str(report_path),
            "--state", str(state_path), "--audit", str(audit_path),
        ]
    )
    assert sender.main() == 0
    result = json.loads(audit_path.read_text(encoding="utf-8"))
    saved_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert result["status"] == "ACCEPTED_BY_TELEGRAM"
    assert result["sent"] == 1
    assert "test-fake-secret" not in audit_path.read_text(encoding="utf-8")
    assert "message_id" not in audit_path.read_text(encoding="utf-8")
    assert saved_state["contracts"][contract["contract_symbol"]]["message_id"] == 451


def test_sender_respects_blocked_preflight(monkeypatch, tmp_path):
    report_path = tmp_path / "guardian.json"
    report_path.write_text(json.dumps(_report()), encoding="utf-8")
    state_path = tmp_path / "state.json"
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(
        json.dumps({"status": "BLOCKED_MISSING_DESTINATION"}), encoding="utf-8"
    )

    def unexpected(_text):
        raise AssertionError("blocked sender must not call Telegram")

    monkeypatch.setattr(sender, "send_html_message", unexpected)
    monkeypatch.setattr(
        sys, "argv", [
            "sender", "--report", str(report_path),
            "--state", str(state_path), "--audit", str(audit_path),
        ]
    )
    assert sender.main() == 0
    assert not state_path.exists()



def test_probe_verifies_bot_and_chat_without_leaking_destination(monkeypatch):
    class Accepted:
        status_code = 200

        def json(self):
            return {"ok": True, "result": {"id": 1234}}

    calls = []
    def fake_post(url, data, timeout):
        calls.append((url, data, timeout))
        return Accepted()

    monkeypatch.setattr(audit.requests, "post", fake_post)
    result = audit.probe_telegram_access("mock-token", "mock-chat")
    assert result["bot_api_responded"] is True
    assert result["destination_api_verified"] is True
    assert [url.rsplit("/", 1)[-1] for url, _, _ in calls] == ["getMe", "getChat"]
    assert "mock-token" not in str(result)
    assert "mock-chat" not in str(result)


def test_probe_failure_fails_closed_and_does_not_expose_token(monkeypatch):
    class Rejected:
        status_code = 403
        def json(self):
            return {"ok": False, "description": "mock-chat mock-token forbidden"}

    monkeypatch.setattr(audit.requests, "post", lambda *args, **kwargs: Rejected())
    result = audit.probe_telegram_access("mock-token", "mock-chat")
    assert result["destination_api_verified"] is False
    assert result["reason"] == "bot_identity_check_failed"
    assert "mock-token" not in str(result)


def test_telegram_push_probe_never_claims_message_delivery(monkeypatch):
    monkeypatch.setattr(
        audit, "probe_telegram_access",
        lambda token, chat: {
            "bot_api_responded": True,
            "destination_api_verified": True,
            "reason": "api_identity_and_chat_verified",
        },
    )
    preflight = audit.build_delivery_preflight(
        _report(), token_configured=True, destination_ready=True, now=NOW,
    )
    pushed = audit.enhance_with_telegram_probe(
        preflight, token="fake", chat_id="fake-chat", event_name="push",
    )
    assert pushed["status"] == "CONNECTION_VERIFIED_NOT_SENT"
    assert pushed["sent"] == 0
    dispatched = audit.enhance_with_telegram_probe(
        preflight, token="fake", chat_id="fake-chat", event_name="workflow_dispatch",
    )
    assert dispatched["status"] == "READY_TO_DELIVER"


def test_api_failure_prevents_delivery(monkeypatch):
    monkeypatch.setattr(
        audit, "probe_telegram_access",
        lambda token, chat: {
            "bot_api_responded": True,
            "destination_api_verified": False,
            "reason": "chat_access_check_failed",
        },
    )
    preflight = audit.build_delivery_preflight(
        _report(), token_configured=True, destination_ready=True, now=NOW,
    )
    result = audit.enhance_with_telegram_probe(
        preflight, token="fake", chat_id="fake-chat", event_name="workflow_dispatch",
    )
    assert result["status"] == "BLOCKED_TELEGRAM_ACCESS_CHECK"
