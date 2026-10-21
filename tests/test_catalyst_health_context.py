"""Source-health daily digest: report freshness is not a quote timestamp."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from scripts.catalyst_health_context import health_context
from scripts.send_catalyst_watchlist_alerts import (
    SCHEMA,
    daily_brief_message,
    send_daily_brief,
)

NOW = datetime(2026, 10, 21, 23, 0, tzinfo=timezone.utc)


def sample(**changes):
    content = {
        "generated_at": (NOW - timedelta(minutes=3)).isoformat(),
        "status": "degraded",
        "source_status": {"sec_fulltext": {
            "available": False, "circuit_state": "open",
            "checked_at": (NOW-timedelta(minutes=4)).isoformat(),
        }},
        "coverage_diagnostics": {
            "options_execution_quote_ready": False,
            "options_trade_flow_ready": False,
            "blocking_codes": ["NO_EXECUTION_GRADE_OPTION_QUOTE",
                               "NO_VERIFIED_OPTION_TRADE_FLOW"],
        },
    }
    content.update(changes)
    return content


def official():
    return {
        "schema": "ghazi.catalyst_watchlist.v1",
        "generated_at": (NOW - timedelta(minutes=2)).isoformat(),
        "research_only": True, "decision_authority": False,
        "execution_authority": False, "sources": {"openfda": True, "sec_edgar": False},
        "watchlist": [],
    }


def test_bounded_source_health_never_promotes_quotes_or_sec():
    outcome = health_context(sample(), now=NOW)
    assert outcome["available"] is True
    assert outcome["options_grade"] == "NOT_VERIFIED"
    assert "عرض سعر عقد" in outcome["blockers"][0]
    assert outcome["sec_ar"].startswith("SEC Full-Text غير")
    assert outcome["decision_authority"] is False


def test_missing_undated_future_and_stale_status_fail_closed():
    assert health_context({}, now=NOW)["available"] is False
    assert health_context(None, now=NOW)["available"] is False
    future = sample(generated_at=(NOW+timedelta(minutes=2)).isoformat())
    assert health_context(future, now=NOW)["available"] is False
    stale = sample(generated_at=(NOW-timedelta(hours=4)).isoformat())
    assert health_context(stale, now=NOW)["available"] is False
    undated = sample(generated_at="2026-10-21T23:00:00")
    assert health_context(undated, now=NOW)["available"] is False
    assert health_context(sample(status="fake_success"), now=NOW)["available"] is False
    with pytest.raises(ValueError):
        health_context(sample(), now=datetime(2026, 10, 21, 23))


def test_ready_claim_requires_both_independent_boolean_gates():
    a = sample(coverage_diagnostics={
        "options_execution_quote_ready": True,
        "options_trade_flow_ready": False,
    })
    assert health_context(a, now=NOW)["options_grade"] == "NOT_VERIFIED"
    b = sample(coverage_diagnostics={
        "options_execution_quote_ready": True,
        "options_trade_flow_ready": True,
    })
    assert health_context(b, now=NOW)["options_grade"] == "REPORTED_READY_NEEDS_V11"


def test_daily_brief_can_report_only_verified_health_when_no_recent_catalyst():
    state = {"schema": SCHEMA, "seen": {}}
    sent = []
    result_state, status = send_daily_brief(
        official(), state, now=NOW, market_health=sample(),
        send=lambda msg: sent.append(msg) or SimpleNamespace(message_id=443),
    )
    assert status == {"mode": "sent", "sent": 1, "symbols": 0}
    assert result_state["daily_brief_message_id"] == 443
    assert len(sent) == 1
    assert "تدهور جزئي" in sent[0]
    assert "لا توجد أهلية" in sent[0]
    assert "لا أحداث رسمية حديثة مؤهلة" in sent[0]
    assert "2026-10-21" in sent[0]
    _, repeat = send_daily_brief(official(), result_state, now=NOW,
                                 market_health=sample(), send=sent.append)
    assert repeat["mode"] == "already_sent" and len(sent) == 1


def test_stale_official_report_blocks_digest_even_when_health_is_new():
    source = official()
    source["generated_at"] = (NOW-timedelta(days=4)).isoformat()
    events = []
    new_state, result = send_daily_brief(source, {"schema": SCHEMA, "seen": {}},
                                         now=NOW, market_health=sample(), send=events.append)
    assert result["mode"] == "stale_or_invalid_official_report"
    assert "daily_brief_date" not in new_state and events == []


def test_message_never_claims_live_from_stale_health():
    message = daily_brief_message(official(), [], now=NOW,
        market_health=sample(generated_at=(NOW-timedelta(hours=5)).isoformat()))
    assert "تقرير حديث غير متاح" in message
    assert "سليم بحسب الفحص" not in message
