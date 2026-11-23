from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts import bot_acceptance as acc
from scripts import send_catalyst_watchlist_alerts as bot

NOW = datetime(2026, 10, 29, 6, tzinfo=timezone.utc)


def _report(n=8):
    watch = []
    for i in range(n):
        sym = f"AB{chr(65 + i)}"
        watch.append({"symbol": sym, "dilution_risk": False, "catalysts": [{
            "symbol": sym, "kind": "FDA_SUPPLEMENT", "source": "openFDA", "importance": "MEDIUM",
            "date": (NOW - timedelta(days=i % 3)).date().isoformat(), "label": f"supplement {i}",
            "source_url": f"https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=x&ApplNo={100 + i}"}]})
    return {"schema": bot.REPORT, "generated_at": (NOW - timedelta(hours=1)).isoformat(), "research_only": True,
            "decision_authority": False, "execution_authority": False, "sources": {"openfda": True}, "watchlist": watch}


def test_acceptance_passes_on_a_seeded_state_and_covers_recovery():
    report = _report()
    assert bot.candidates(report, now=NOW), "fixture must yield eligible events"
    seeded, _ = bot.run(report, None, now=NOW, send=acc.Recorder())          # the bot's own first run seeds
    result = acc.check(report, seeded, None, NOW)
    assert result["passed"], result["checks"]
    assert result["first_run"]["sent"] == 0 and result["already_delivered"] == result["eligible"]
    assert result["recovery"]["outage_run"]["failed"] == "ConnectionError"


def test_a_sender_that_resends_would_fail_the_dedupe_check(monkeypatch):
    report = _report()
    real_run = bot.run

    def leaky(report, state, **kw):          # forgets what it sent
        new_state, summary = real_run(report, state, **kw)
        return {**new_state, "seen": {}}, summary

    monkeypatch.setattr(bot, "run", leaky)
    fresh = {"schema": bot.SCHEMA, "seen": {}, "updated_at": NOW.isoformat()}
    assert acc.check(report, fresh, None, NOW)["checks"]["repeat_runs_send_each_event_once"] is False


def test_backlog_larger_than_the_per_run_cap_drains_once_and_passes():
    # Regression: 5+ unsent events with the sender's cap of 3 per run. The second run
    # legitimately sends the backlog; the check must accept that and still require
    # every event exactly once and a quiet run after the backlog is gone.
    report = _report()
    fresh = {"schema": bot.SCHEMA, "seen": {}, "updated_at": NOW.isoformat()}
    eligible = len(bot.candidates(report, now=NOW))
    assert eligible > 3, "fixture must exceed the per-run cap"
    result = acc.check(report, fresh, None, NOW)
    assert result["checks"]["repeat_runs_send_each_event_once"] is True, result
    assert result["first_run"]["sent"] == 3 and result["first_run"]["pending"] == eligible - 3
    assert result["drain"]["total_sent"] == eligible and result["drain"]["final_run_sent"] == 0
    assert result["passed"], result["checks"]


def test_a_sender_that_sends_the_same_event_twice_fails(monkeypatch):
    report = _report()
    real_run = bot.run

    def double(report, state, *, send, **kw):        # sends every message twice
        def twice(text):
            send(text)
            return send(text)
        return real_run(report, state, send=twice, **kw)

    monkeypatch.setattr(bot, "run", double)
    fresh = {"schema": bot.SCHEMA, "seen": {}, "updated_at": NOW.isoformat()}
    assert acc.check(report, fresh, None, NOW)["checks"]["repeat_runs_send_each_event_once"] is False
