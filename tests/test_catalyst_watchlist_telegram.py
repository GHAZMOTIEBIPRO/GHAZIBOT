"""Realistic source-policy regression for the official catalyst Telegram bridge."""
from datetime import datetime, timedelta, timezone

from scripts.send_catalyst_watchlist_alerts import candidates, message, run

NOW = datetime(2026, 10, 21, 20, 0, tzinfo=timezone.utc)


def row(symbol="ABBV", **overrides):
    event = {
        "symbol": symbol, "kind": "FDA_SUPPLEMENT", "date": "2026-10-20",
        "importance": "MEDIUM", "label": "Medicine efficacy supplement",
        "source": "openFDA",
        "source_url": "https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?ApplNo=212345",
    }
    event.update(overrides)
    return {"symbol": symbol, "dilution_risk": False, "catalysts": [event]}


def report(*entries, **options):
    result = {
        "schema": "ghazi.catalyst_watchlist.v1",
        "research_only": True, "decision_authority": False, "execution_authority": False,
        "generated_at": NOW.isoformat(), "sources": {"openfda": True, "sec_edgar": False},
        "watchlist": list(entries),
    }
    result.update(options)
    return result


def test_initial_seed_is_silent_then_send_once():
    msgs = []
    first, s = run(report(row()), None, now=NOW, send=msgs.append)
    assert s["mode"] == "seeded" and s["sent"] == 0 and not msgs
    next_row = row("MRK")
    second, result = run(report(row(), next_row), first, now=NOW, send=msgs.append)
    assert result["sent"] == 1 and "MRK" in msgs[0]
    _, result2 = run(report(row(), next_row), second, now=NOW, send=msgs.append)
    assert result2["sent"] == 0 and len(msgs) == 1


def test_fda_high_owned_by_existing_sender_and_no_untrusted_links():
    assert candidates(report(row(importance="HIGH")), now=NOW) == []
    assert candidates(report(row(source_url="http://example.com/fda")), now=NOW) == []
    assert candidates(report(row(source_url="https://evil.example/attack")), now=NOW) == []
    assert candidates(report(row(source_url=None)), now=NOW) == []
    assert candidates(report(row(), sources={"openfda": False}), now=NOW) == []


def test_stale_future_schema_wrong_or_price_claims_not_produced():
    assert candidates(report(row(), generated_at=(NOW-timedelta(days=4)).isoformat()), now=NOW) == []
    assert candidates(report(row(), generated_at=(NOW+timedelta(hours=2)).isoformat()), now=NOW) == []
    assert candidates(report(row(), decision_authority=True), now=NOW) == []
    assert candidates(report(row(date="2026-09-01")), now=NOW) == []
    assert candidates(report(row(date="2026-11-01")), now=NOW) == []


def test_escaped_html_and_send_failure_retry_state():
    event = candidates(report(row(label="<script>alert(1)</script>")), now=NOW)[0]
    text = message(event)
    assert "&lt;script&gt;" in text and "<script>" not in text
    assert "ليست توصية" in text
    old, _ = run(report(), None, now=NOW, send=lambda _: None)

    def fails(_):
        raise RuntimeError("network down")
    state, result = run(report(row()), old, now=NOW, send=fails)
    assert result["failed"] == "RuntimeError" and not state["seen"]
    state, result = run(report(row()), state, now=NOW, send=lambda _: None)
    assert result["sent"] == 1 and len(state["seen"]) == 1


def test_sec_source_requires_official_authorization():
    entry = row("SOME", kind="DILUTION_RISK", importance="HIGH",
                source="SEC EDGAR",
                source_url="https://www.sec.gov/Archives/edgar/data/1234/form8k.htm")
    assert candidates(report(entry), now=NOW) == []
    eligible = candidates(report(entry, sources={"openfda": True, "sec_edgar": True}), now=NOW)
    assert len(eligible) == 1 and eligible[0]["kind"] == "DILUTION_RISK"



def test_one_time_real_telegram_readiness_notice_after_seed():
    messages = []
    base = report(row())
    seeded, initial = run(base, None, now=NOW, send=messages.append, notify_ready=True)
    assert initial["sent"] == 0 and messages == []
    updated, delivery = run(base, seeded, now=NOW, send=messages.append, notify_ready=True)
    assert delivery["ready_notice_sent"] is True
    assert len(messages) == 1
    assert "تم ربط رادار المحفزات الرسمي" in messages[0]
    assert "18" not in messages[0]  # Count comes from the real input, not a hardcoded claim.
    assert "\\n" not in messages[0]  # Render real HTML message lines.
    _, replay = run(base, updated, now=NOW, send=messages.append, notify_ready=True)
    assert replay["ready_notice_sent"] is False and len(messages) == 1


def test_failed_readiness_does_not_mark_delivery_proven():
    seeded, _ = run(report(row()), None, now=NOW, send=lambda _: None)
    def fail(_):
        raise RuntimeError("Telegram unreachable")
    after, result = run(report(row()), seeded, now=NOW, send=fail, notify_ready=True)
    assert result["failed"] == "RuntimeError"
    assert "ready_notice_at" not in after
    assert not any(x.get("status") == "sent" for x in after["seen"].values())


def test_invalid_report_cannot_emit_readiness_notice():
    seeded, _ = run(report(row()), None, now=NOW, send=lambda _: None)
    notices = []
    invalid = report(row(), generated_at=(NOW-timedelta(days=4)).isoformat())
    after, outcome = run(invalid, seeded, now=NOW, send=notices.append, notify_ready=True)
    assert outcome["ready_notice_sent"] is False
    assert not notices and "ready_notice_at" not in after



def test_riyadh_daily_brief_source_authentication_and_research_only():
    from scripts.send_catalyst_watchlist_alerts import daily_brief_candidates, daily_brief_message
    base = report(row())
    result = daily_brief_candidates(base, now=NOW)
    assert len(result) == 1 and result[0]["symbol"] == "ABBV"
    txt = daily_brief_message(base, result, now=NOW)
    assert "الملخص الرسمي اليومي" in txt and "ليست" in txt
    assert "2026-10-20" in txt and "www.accessdata.fda.gov" in txt
    assert "CALL/PUT" in txt
    assert daily_brief_candidates(report(row(), generated_at=(NOW-timedelta(days=3)).isoformat()),
                                  now=NOW) == []
    assert daily_brief_candidates(report(row(), sources={"openfda": False}), now=NOW) == []
    assert daily_brief_candidates(report(row(source_url="https://evil.example/")),
                                  now=NOW) == []


def test_riyadh_daily_brief_dedupe_and_failed_send_retry():
    from types import SimpleNamespace

    from scripts.send_catalyst_watchlist_alerts import send_daily_brief
    event_report = report(row())
    initial, _ = run(event_report, None, now=NOW, send=lambda _: None)
    msgs = []
    state, result = send_daily_brief(event_report, initial, now=NOW,
                                     send=lambda message: msgs.append(message) or SimpleNamespace(message_id=987))
    assert result["mode"] == "sent" and result["sent"] == 1
    assert state["daily_brief_message_id"] == 987
    _, second = send_daily_brief(event_report, state, now=NOW,
                                send=lambda message: msgs.append(message))
    assert second["mode"] == "already_sent" and len(msgs) == 1

    def offline(_):
        raise RuntimeError("Telegram timeout")
    failed_state, failure = send_daily_brief(event_report, initial, now=NOW, send=offline)
    assert failure["failed"] == "RuntimeError" and "daily_brief_date" not in failed_state
    recovered, delivery = send_daily_brief(event_report, failed_state, now=NOW,
                                           send=lambda _: SimpleNamespace(message_id=988))
    assert delivery["sent"] == 1 and recovered["daily_brief_message_id"] == 988


def test_daily_digest_groups_issuer_and_excludes_future_and_unsafe_domains():
    from scripts.send_catalyst_watchlist_alerts import daily_brief_candidates
    same = row()
    same["catalysts"].extend([
        {**same["catalysts"][0], "date": "2026-10-19", "importance": "HIGH"},
        {**same["catalysts"][0], "date": "2026-10-21", "source_url": "https://evil.com/report"},
        {**same["catalysts"][0], "date": "2026-11-30"},
    ])
    events = daily_brief_candidates(report(same), now=NOW)
    assert len(events) == 1 and events[0]["date"] == "2026-10-19"



def test_daily_catchup_only_after_0815_riyadh_weekdays():
    from pathlib import Path

    import yaml

    from scripts.send_catalyst_watchlist_alerts import daily_brief_due

    assert daily_brief_due(datetime(2026, 10, 22, 5, 14, tzinfo=timezone.utc)) is False
    assert daily_brief_due(datetime(2026, 10, 22, 5, 15, tzinfo=timezone.utc)) is True
    assert daily_brief_due(datetime(2026, 10, 22, 7, 15, tzinfo=timezone.utc)) is True
    assert daily_brief_due(datetime(2026, 10, 24, 8, 0, tzinfo=timezone.utc)) is False
    try:
        daily_brief_due(datetime(2026, 10, 22, 8, 15))
    except ValueError:
        pass
    else:
        raise AssertionError("naive local time must not be accepted")

    wf = Path(".github/workflows/catalyst-watchlist.yml").read_text(encoding="utf-8")
    parsed = yaml.safe_load(wf)
    assert parsed[True]["schedule"] == [
        {"cron": "15 5 * * 1-5"}, {"cron": "15 8 * * 1-5"}
    ]
    assert "--daily-brief-if-due" in wf
    assert "--market-health state/runtime/public/data/data-status.json" in wf
    assert "git push origin HEAD:bot-state" in wf


def test_daily_digest_requires_telegram_ack_before_deduplication():
    from types import SimpleNamespace

    from scripts.send_catalyst_watchlist_alerts import send_daily_brief

    event_report = report(row())
    initial, _ = run(event_report, None, now=NOW, send=lambda _: None)
    for incomplete in (None, SimpleNamespace(message_id=None),
                       SimpleNamespace(message_id="123"), SimpleNamespace(message_id=0),
                       SimpleNamespace(message_id=True)):
        after, status = send_daily_brief(
            event_report, initial, now=NOW, send=lambda _: incomplete
        )
        assert status["mode"] == "delivery_unconfirmed"
        assert status["failed"] == "NO_TELEGRAM_MESSAGE_ID"
        assert status["sent"] == 0 and after == initial
        assert "daily_brief_date" not in after
    verified, status = send_daily_brief(
        event_report, initial, now=NOW,
        send=lambda _: SimpleNamespace(message_id=773)
    )
    assert status["mode"] == "sent"
    assert verified["daily_brief_message_id"] == 773
    assert verified["daily_brief_date"] == "2026-10-21"
