"""Storage rights and delivery semantics (owner, independent audit RELEASE GATE).

Nothing derived from restricted data - prices, levels, stages, detections, tags or counts of them - is
stored on the public branch or in a cache; dedupe is recomputed from the source data and the run history.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from options_radar import run_window as rw
from scripts import build_oracle_status as bos
from scripts import run_smallcap_scan as run

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 30, 17, 0, tzinfo=timezone.utc)
OPEN = datetime(2026, 11, 30, 14, 30, tzinfo=timezone.utc)

# Every path a workflow holding the Alpaca secret may commit to bot-state, with what it holds.
ALLOWED_ADDS = {
    "runtime/public/data/daily_plan.json",            # readiness and counts (main, earlier missions)
    "state/daily_plan",                                # morning.json / update_*.json: statuses and counts
    "state/daily_plan/*/report_*.json",               # scheduled report delivery statuses (no fingerprints)
    "state/daily_plan/*/session_*.json",              # scheduled slot statuses
    "runtime/public/data/oracle_status.json",         # statuses only
    "state/telegram/telegram_commands_offset.json",   # update offset and command statuses
    "runtime/public/data/alpaca_iex_vcp_health.json",  # health statuses (earlier mission)
    "state/alpaca/vcp_private_delivery.json",         # delivery status (earlier mission)
    "state/opening_fib/sent.json", "state/opening_fib/shadow_sent.json",  # sent markers (earlier mission)
    "runtime/public/data/classical_direction.json",   # SOURCE_TERMS_BLOCKED digest (gated publisher)
}
ALLOWED_ARTIFACT_WORKFLOWS = {"private-data-access.yml"}  # provider-access metadata only (reviewed)


def _alpaca_workflows():
    for p in sorted((ROOT / ".github/workflows").glob("*.yml")):
        text = p.read_text(encoding="utf-8")
        if re.search(r"secrets\.ALPACA_(API|SECRET)_KEY \}\}", text):
            yield p, text


def test_event_engines_commit_nothing_and_use_no_cache():
    for name in ("smallcap-scan.yml", "options-hunter.yml"):
        text = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
        assert "git add" not in text and "git push" not in text and "actions/cache" not in text, name
        assert "contents: read" in text and "actions: read" in text, name
    assert not (ROOT / "options_radar/state_keys.py").exists()


def test_workflows_with_alpaca_keys_commit_only_reviewed_paths():
    for p, text in _alpaca_workflows():
        for m in re.finditer(r"git add ([^\n|&;]+)", text):
            for path in m.group(1).split():
                if path.startswith("-") or path in ("2>/dev/null", "||", "true"):
                    continue
                assert path in ALLOWED_ADDS, f"{p.name} commits {path}: review its storage rights first"


def test_workflows_with_alpaca_keys_upload_no_artifacts():
    for p, text in _alpaca_workflows():
        if "upload-artifact" in text:
            assert p.name in ALLOWED_ARTIFACT_WORKFLOWS, f"{p.name}: artifacts of a public repo are downloadable"


def test_no_encryption_at_rest_and_no_token_as_key_anywhere():
    for folder in ("scripts", "options_radar"):
        for p in (ROOT / folder).rglob("*.py"):
            text = p.read_text(encoding="utf-8")
            assert not re.search(r"openssl[^\n]*\benc\b", text), p
            for line in text.splitlines():
                if "TELEGRAM_BOT_TOKEN" in line:
                    assert not re.search(r"hmac|\btag\(|fingerprints\(|encrypt|SC_KEY", line), (p, line)


def test_public_status_has_no_outcome_counts(tmp_path):
    state = tmp_path / "state"
    day = state / "daily_plan" / "2026-11-30"
    day.mkdir(parents=True)
    (day / "session_POSTCLOSE.json").write_text(json.dumps({"status": "DELIVERED", "scorecard": {"t1": 3}}))
    out = bos.build(state, tmp_path / "data", NOW)
    text = json.dumps(out)
    assert "scorecard" not in text and "t1" not in text and "alert" not in text
    assert out["event_engines"] == "NO_STORED_STATE"


class _HTTP:
    def __init__(self, runs, code=200):
        self.runs, self.code = runs, code

    def get(self, url, **kw):
        return SimpleNamespace(status_code=self.code, json=lambda: {"workflow_runs": self.runs})


ENV = {"GITHUB_REPOSITORY": "o/r", "GITHUB_TOKEN": "t", "GITHUB_RUN_ID": "9"}


def test_previous_success_ignores_this_run_pushes_and_other_days():
    runs = [{"id": 9, "event": "workflow_dispatch", "run_started_at": "2026-11-30T16:55:00Z"},
            {"id": 8, "event": "push", "run_started_at": "2026-11-30T16:50:00Z"},
            {"id": 7, "event": "workflow_dispatch", "run_started_at": "2026-11-30T16:40:00Z"},
            {"id": 6, "event": "workflow_dispatch", "run_started_at": "2026-11-29T20:00:00Z"}]
    day = OPEN - timedelta(hours=8)
    assert rw.previous_success(ENV, "x.yml", NOW, day_start=day, http=_HTTP(runs)) == (
        "OK", datetime(2026, 11, 30, 16, 40, tzinfo=timezone.utc))
    assert rw.previous_success(ENV, "x.yml", NOW, day_start=day, http=_HTTP(runs[:2])) == ("NONE_TODAY", None)
    assert rw.previous_success(ENV, "x.yml", NOW, day_start=day, http=_HTTP([], 403))[0] == "UNKNOWN"
    assert rw.previous_success({}, "x.yml", NOW, day_start=day)[0] == "UNKNOWN"


def test_delivery_semantics_retry_only_when_nothing_was_accepted():
    sent = []
    statuses = rw.send_in_order(["a", "b", "c"], lambda t: sent.append(t) or ("SEND_FAILED" if t == "b" else "DELIVERED"))
    assert sent == ["a", "b"] and statuses == ["DELIVERED", "SEND_FAILED"]  # "c" is not sent after a refusal
    assert rw.exit_code(statuses) == 0          # "a" arrived: the run succeeds, so "a" is never resent
    assert rw.exit_code(["SEND_FAILED"]) == 1   # nothing arrived: the run fails, the next run retries it
    assert rw.exit_code(["UNCONFIRMED"]) == 0   # may have arrived: never resent automatically
    assert rw.exit_code([]) == 0


def test_data_horizon_is_the_last_completed_bucket():
    assert rw.data_horizon(datetime(2026, 11, 30, 15, 33, 20, tzinfo=timezone.utc)) == datetime(
        2026, 11, 30, 15, 15, tzinfo=timezone.utc)


def _bars(n, price=5.0, vol=2000):
    return [{"t": (OPEN + timedelta(minutes=i)).isoformat(), "o": price, "h": price * 1.01, "l": price * 0.99,
             "c": price, "v": vol, "vw": price} for i in range(n)]


def test_smallcap_new_since_sends_first_stage_and_upgrades_only(monkeypatch):
    cands = [{"symbol": "AAA", "stage": "BREAKOUT_WATCH"}, {"symbol": "BBB", "stage": "EARLY_ACTIVITY"},
             {"symbol": "CCC", "stage": "CONFIRMED_MOVE"}]
    before = {"AAA": "EARLY_ACTIVITY", "BBB": "EARLY_ACTIVITY", "CCC": "COMPRESSION"}
    monkeypatch.setattr(run.sc, "evaluate", lambda sym, snap, hist, el: {"stage": before[sym]})
    fetch = lambda syms, start, end, headers: {s: _bars(10) for s in syms}
    later = OPEN + timedelta(minutes=390)
    new = run.new_since(cands, {}, {}, OPEN + timedelta(minutes=60), OPEN, later, {}, fetch=fetch)
    assert [r["symbol"] for r in new] == ["AAA", "CCC"]  # BBB had the same stage at the previous run
    assert run.new_since(cands, {}, {}, None, OPEN, later, {}, fetch=fetch) == cands  # first run today


def test_pseudo_snapshot_is_what_a_scan_would_have_seen():
    snap = run.pseudo_snapshot(_bars(3, 4.0, 100), {"c": 3.5})
    assert snap["latestTrade"]["p"] == 4.0 and snap["dailyBar"]["v"] == 300 and snap["prevDailyBar"] == {"c": 3.5}


class _Routes:
    """Fake GitHub REST: workflow runs and per-run jobs/steps."""

    def __init__(self, runs, steps):
        self.runs, self.steps = runs, steps

    def get(self, url, **kw):
        if url.endswith("/jobs"):
            rid = url.split("/runs/")[1].split("/")[0]
            body = {"jobs": [{"steps": self.steps.get(rid, [])}]}
        else:
            body = {"workflow_runs": self.runs}
        return SimpleNamespace(status_code=200, json=lambda: body)


def test_window_edges_come_from_the_processing_step_not_the_run_start():
    runs = [{"id": 7, "event": "workflow_dispatch", "run_started_at": "2026-11-30T16:40:00Z",
             "updated_at": "2026-11-30T16:43:30Z"}]
    steps = {"7": [{"name": "Setup", "started_at": "2026-11-30T16:40:05Z"},
                   {"name": "Work", "started_at": "2026-11-30T16:41:20Z", "completed_at": "2026-11-30T16:42:10Z"}],
             "9": [{"name": "Work", "started_at": "2026-11-30T16:56:40Z"}]}
    http = _Routes(runs, steps)
    day = OPEN - timedelta(hours=8)
    t = lambda h, m, s=0: datetime(2026, 11, 30, h, m, s, tzinfo=timezone.utc)
    assert rw.previous_success(ENV, "x.yml", NOW, day_start=day, http=http, step="Work") == ("OK", t(16, 41, 20))
    assert rw.previous_success(ENV, "x.yml", NOW, day_start=day, http=http, step="Work",
                               mark="completed_at") == ("OK", t(16, 42, 10))
    # an unreadable step falls back conservatively: start -> run start, completion -> run update time
    assert rw.previous_success(ENV, "x.yml", NOW, day_start=day, http=http, step="Gone")[1] == t(16, 40)
    assert rw.previous_success(ENV, "x.yml", NOW, day_start=day, http=http, step="Gone",
                               mark="completed_at")[1] == t(16, 43, 30)
    assert rw.own_step_time(ENV, "Work", NOW, http=http) == t(16, 56, 40)


def test_step_names_used_for_the_run_history_exist_in_the_workflows():
    from scripts import run_session_tracker as rst

    tracker = (ROOT / ".github/workflows/session-tracker.yml").read_text(encoding="utf-8")
    small = (ROOT / ".github/workflows/smallcap-scan.yml").read_text(encoding="utf-8")
    assert f"- name: {rst.STEP}\n" in tracker
    assert "- name: Scan or post-close review (owner-private)\n" in small
    assert '"Scan or post-close review (owner-private)"' in (ROOT / "scripts/run_smallcap_scan.py").read_text(encoding="utf-8")


def test_engines_never_exit_success_without_processing_when_the_history_is_unknown():
    for name, marker in (("run_smallcap_scan.py", "RUN_HISTORY_UNKNOWN"), ("run_options_hunter.py", "RUN_HISTORY_UNKNOWN")):
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        i = text.index(marker)
        assert "return 1" in text[i:i + 250], name
    tracker = (ROOT / "scripts/run_session_tracker.py").read_text(encoding="utf-8")
    assert 'slot = "INTRADAY"' in tracker and 'window == "UNKNOWN":\n        return 1' in tracker
