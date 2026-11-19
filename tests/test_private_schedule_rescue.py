"""Regression: GitHub delivered the 2026-11-16 opening-Fib crons ~9 h late, so nothing was sent.

The orchestrator now dispatches the private workflows inside their windows. These tests pin when it does
and, above all, when it must not (duplicates, weekends, delivered sessions, attempt cap).
"""
from datetime import datetime, timezone
from pathlib import Path

import yaml

from scripts import private_schedule_rescue as rescue

# 2026-11-16 (Mon) and 2026-11-17 (Tue) are EST: New York = UTC - 5.
NY_1030 = datetime(2026, 11, 17, 15, 30, tzinfo=timezone.utc)


def run(created: str, status: str = "completed", conclusion: str = "success", event: str = "workflow_dispatch"):
    return {"createdAt": created, "status": status, "conclusion": conclusion, "event": event}


def test_the_2026_11_16_failure_mode_is_rescued_inside_the_window():
    # Only late crons exist (23:27/23:45 UTC the previous day): they are outside today's window.
    late = [run("2026-11-16T23:27:49Z", event="schedule"), run("2026-11-16T23:45:45Z", event="schedule")]
    d = rescue.opening_fib_decision(NY_1030, None, late)
    assert d.action == "dispatch" and "attempt 1/2" in d.reason


def test_no_dispatch_when_today_is_already_delivered():
    sent = {"sent_session": "2026-11-17", "sent_at_utc": "2026-11-17T15:28:00+00:00"}
    assert rescue.opening_fib_decision(NY_1030, sent, []).action == "skip"


def test_no_dispatch_outside_window_or_on_weekends():
    before = datetime(2026, 11, 17, 15, 10, tzinfo=timezone.utc)  # 10:10 NY
    assert rescue.opening_fib_decision(before, None, []).action == "skip"
    edge = datetime(2026, 11, 17, 16, 42, tzinfo=timezone.utc)  # 11:42 NY: too late to start
    assert rescue.opening_fib_decision(edge, None, []).action == "skip"
    saturday = datetime(2026, 11, 21, 15, 30, tzinfo=timezone.utc)
    assert rescue.opening_fib_decision(saturday, None, []).reason == "weekend"


def test_missed_session_is_reported_after_the_window():
    after = datetime(2026, 11, 17, 17, 0, tzinfo=timezone.utc)  # 12:00 NY
    d = rescue.opening_fib_decision(after, {"sent_session": "2026-11-16"}, [])
    assert d.action == "missed" and "2026-11-17" in d.reason


def test_running_or_queued_run_blocks_a_second_dispatch():
    active = [run("2026-11-17T15:20:00Z", status="in_progress", conclusion="")]
    assert rescue.opening_fib_decision(NY_1030, None, active).reason == "a run is queued or in progress"
    queued = [run("2026-11-17T15:25:00Z", status="queued", conclusion="")]
    assert rescue.opening_fib_decision(NY_1030, None, queued).action == "skip"


def test_attempt_cap_counts_every_event_inside_the_window():
    one_failed = [run("2026-11-17T15:16:00Z", conclusion="failure")]
    assert rescue.opening_fib_decision(NY_1030, None, one_failed).reason.endswith("attempt 2/2")
    two = one_failed + [run("2026-11-17T15:21:00Z", conclusion="failure", event="schedule")]
    d = rescue.opening_fib_decision(NY_1030, None, two)
    assert d.action == "skip" and "2 runs" in d.reason


def test_dst_window_follows_new_york_time():
    # 2026-07-01 is EDT (UTC-4): 10:30 NY = 14:30 UTC.
    summer = datetime(2026, 7, 1, 14, 30, tzinfo=timezone.utc)
    assert rescue.opening_fib_decision(summer, None, []).action == "dispatch"
    assert rescue.opening_fib_decision(summer.replace(hour=15, minute=50), None, []).action == "missed"


def test_shadow_waits_for_the_close_then_dispatches_once():
    sent = {"sent_session": "2026-11-17", "sent_at_utc": "2026-11-17T15:28:00+00:00"}
    during = datetime(2026, 11, 17, 20, 0, tzinfo=timezone.utc)  # 15:00 NY
    assert rescue.shadow_decision(during, sent, None, []).action == "skip"
    after = datetime(2026, 11, 17, 21, 25, tzinfo=timezone.utc)  # 16:25 NY
    assert rescue.shadow_decision(after, sent, None, []).action == "dispatch"
    done = {"audited_session": "2026-11-17"}
    assert rescue.shadow_decision(after, sent, done, []).action == "skip"
    capped = [run("2026-11-17T21:21:00Z", conclusion="failure"), run("2026-11-17T21:22:00Z", conclusion="failure")]
    assert rescue.shadow_decision(after, sent, None, capped).action == "skip"


def test_shadow_needs_a_timestamped_delivery_and_a_recent_session():
    after = datetime(2026, 11, 17, 21, 25, tzinfo=timezone.utc)
    assert rescue.shadow_decision(after, None, None, []).action == "skip"
    assert rescue.shadow_decision(after, {"sent_session": "2026-11-17"}, None, []).action == "skip"
    old = {"sent_session": "2026-11-09", "sent_at_utc": "2026-11-09T15:28:00+00:00"}
    assert "horizon" in rescue.shadow_decision(after, old, None, []).reason


def test_naive_clock_never_dispatches():
    naive = datetime(2026, 11, 17, 15, 30)
    assert rescue.opening_fib_decision(naive, None, []).action == "skip"
    assert rescue.shadow_decision(naive, {"sent_session": "2026-11-17", "sent_at_utc": "x"}, None, []).action == "skip"


def test_main_dispatches_with_explicit_non_dry_run_and_reads_only_markers(monkeypatch, capsys):
    calls = []

    def fake_gh(args):
        calls.append(args)
        if args[0] == "api":
            raise rescue.subprocess.CalledProcessError(1, "gh")  # no marker yet
        if args[:2] == ["run", "list"]:
            return "[]"
        return ""

    monkeypatch.setattr(rescue, "_gh", fake_gh)
    monkeypatch.setattr(rescue, "_now", lambda: NY_1030)
    assert rescue.main(["--repo", "o/r"]) == 0
    dispatched = [c for c in calls if c[:2] == ["workflow", "run"]]
    assert dispatched == [["workflow", "run", "opening-fib-daily.yml", "--repo", "o/r", "--ref", "main", "-f", "dry_run=false"]]
    reads = [c[1] for c in calls if c[0] == "api"]
    assert all("ref=bot-state" in r and r.split("?")[0].endswith((rescue.SENT_MARKER, rescue.SHADOW_MARKER)) for r in reads)
    assert "dispatch" in capsys.readouterr().out


def test_orchestrator_runs_the_rescue_every_pass_and_can_read_it():
    text = Path(".github/workflows/market-orchestrator.yml").read_text(encoding="utf-8")
    spec = yaml.safe_load(text)
    steps = spec["jobs"]["dispatch"]["steps"]
    checkout = next(s for s in steps if s.get("uses", "").startswith("actions/checkout"))
    assert "scripts/private_schedule_rescue.py" in checkout["with"]["sparse-checkout"]
    body = next(s for s in steps if s.get("id") == "cadence")["run"]
    assert 'python3 scripts/private_schedule_rescue.py --repo "$GITHUB_REPOSITORY"' in body
    assert "Private schedule rescue failed" in body
    # The orchestrator never receives market-data keys or Telegram secrets.
    for secret in ("ALPACA_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_OWNER_CHAT_ID"):
        assert secret not in text


def test_shadow_workflow_delivers_only_on_explicit_non_dry_run_dispatch_or_schedule():
    text = Path(".github/workflows/opening-fib-shadow.yml").read_text(encoding="utf-8")
    spec = yaml.safe_load(text)
    on = spec.get(True) or spec.get("on")
    assert on["workflow_dispatch"]["inputs"]["dry_run"]["default"] is True
    steps = spec["jobs"]["private-shadow"]["steps"]
    audit = next(s for s in steps if s.get("name", "").startswith("Audit only"))
    assert '"$INPUT_DRY" == "false"' in audit["run"]
    persist = next(s for s in steps if s.get("name", "").startswith("Persist only"))
    assert "inputs.dry_run == false" in persist["if"] and "github.event_name == 'schedule'" in persist["if"]


def test_private_market_scan_runs_in_the_new_york_session_via_the_orchestrator():
    # 2026-11-18: the scan's own crons arrived at 22:20, 23:08 and 00:44 UTC (OUTSIDE_SESSION).
    central = Path(".github/workflows/market-orchestrator.yml").read_text(encoding="utf-8")
    assert central.count("dispatch_if_stale private-market-scan.yml 150") == 1
    block = central.split("ny_hm=", 1)[1].split("dispatch_if_stale private-market-scan.yml", 1)[0]
    assert "TZ=America/New_York" in block and "ny_hm >= 1000 && ny_hm <= 1530" in block
    assert "date -u +%u) <= 5" in block
    # one dispatcher only: no own schedule that could land next to a dispatch and send twice
    scan = yaml.safe_load(Path(".github/workflows/private-market-scan.yml").read_text(encoding="utf-8"))
    assert "schedule" not in scan[True] and "workflow_dispatch" in scan[True]
