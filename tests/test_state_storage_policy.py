"""Storage rights (owner, PHASE 4): restricted data never reaches public bot-state, logs or artifacts.

bot-state is public. Encryption is not a storage licence, and the Telegram token is a transport
credential, never a key. Only operational records and keyed tags under an independent secret may be stored.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from options_radar import state_keys as sk
from scripts import build_oracle_status as bos
from scripts import run_smallcap_scan as run

ROOT = Path(__file__).resolve().parents[1]
KEY = b"k" * 40
NOW = datetime(2026, 11, 30, 15, 0, tzinfo=timezone.utc)

# Every path a workflow holding the Alpaca secret may commit to bot-state, with what it holds.
ALLOWED_ADDS = {
    "runtime/public/data/daily_plan.json",            # readiness and counts (main, earlier missions)
    "state/daily_plan",                                # morning.json / update_*.json: statuses and counts
    "state/daily_plan/*/report_*.json",               # delivery statuses and keyed fingerprints
    "state/daily_plan/*/session_*.json",              # slot statuses and keyed event tags
    "runtime/public/data/oracle_status.json",         # statuses and operational counts
    "state/options_hunter/last_top.json",             # keyed alert tags
    "state/telegram/telegram_commands_offset.json",   # update offset and command statuses
    "state/smallcaps/*.tags.json",                    # keyed tags and an alert count
    "state/smallcaps/*.postclose.json",               # detection count and time
    "runtime/public/data/alpaca_iex_vcp_health.json",  # health statuses (earlier mission)
    "state/alpaca/vcp_private_delivery.json",         # delivery status (earlier mission)
    "state/opening_fib/sent.json", "state/opening_fib/shadow_sent.json",  # sent markers (earlier mission)
    "runtime/public/data/classical_direction.json",   # SOURCE_TERMS_BLOCKED digest (gated publisher)
}
# Artifacts from a job that holds the Alpaca secret value; reviewed: provider-access metadata only.
ALLOWED_ARTIFACT_WORKFLOWS = {"private-data-access.yml"}


def _alpaca_workflows():
    for p in sorted((ROOT / ".github/workflows").glob("*.yml")):
        text = p.read_text(encoding="utf-8")
        if re.search(r"secrets\.ALPACA_(API|SECRET)_KEY \}\}", text):
            yield p, text


def test_state_key_is_independent_and_never_the_telegram_token():
    assert sk.state_key({}) is None
    assert sk.state_key({"TELEGRAM_BOT_TOKEN": "1234:" + "x" * 40}) is None
    assert sk.state_key({sk.ENV: "short"}) is None
    assert sk.state_key({sk.ENV: "z" * 32}) == b"z" * 32


def test_recover_reads_back_only_with_the_key():
    tags = {sk.tag(KEY, "smallcap", "2026-11-30", "AAA", "EARLY_ACTIVITY", 17)}
    cands = [("AAA", "EARLY_ACTIVITY", m) for m in range(30)] + [("BBB", "EARLY_ACTIVITY", 17)]
    assert sk.recover(KEY, tags, ("smallcap", "2026-11-30"), cands) == [("AAA", "EARLY_ACTIVITY", 17)]
    assert sk.recover(b"other" * 8, tags, ("smallcap", "2026-11-30"), cands) == []


def test_smallcap_state_holds_tags_and_a_count_only(tmp_path):
    path = tmp_path / "2026-11-30.tags.json"
    tags = {sk.tag(KEY, "smallcap", "2026-11-30", "AAAA", "CONFIRMED_MOVE", 42)}
    run.save_tags(path, "2026-11-30", tags, 1, NOW)
    saved = json.loads(path.read_text())
    assert set(saved) == {"schema", "day", "tags", "alerts_sent", "updated_at"}
    assert b"AAAA" not in path.read_bytes() and b"CONFIRMED" not in path.read_bytes()
    found = run.detections_from_tags(KEY, "2026-11-30", set(saved["tags"]), ["AAAA", "BBBB"])
    assert found == {"AAAA": {"stage": "CONFIRMED_MOVE", "minute": 42, "top_stage": "CONFIRMED_MOVE"}}


def test_smallcap_dedupe_and_upgrade_from_tags():
    day = "2026-11-30"
    tags = {sk.tag(KEY, "smallcap", day, "AAA", "EARLY_ACTIVITY", 20)}
    assert run.already_alerted(KEY, day, "AAA", "EARLY_ACTIVITY", tags, 60)
    assert not run.already_alerted(KEY, day, "AAA", "BREAKOUT_WATCH", tags, 60)  # an upgrade is new
    tags.add(sk.tag(KEY, "smallcap", day, "AAA", "BREAKOUT_WATCH", 50))
    assert run.already_alerted(KEY, day, "AAA", "EARLY_ACTIVITY", tags, 60)  # a later stage covers it
    first = run.detections_from_tags(KEY, day, tags, ["AAA"])["AAA"]
    assert first == {"stage": "EARLY_ACTIVITY", "minute": 20, "top_stage": "BREAKOUT_WATCH"}


def test_no_encryption_at_rest_and_no_token_as_key_anywhere():
    for folder in ("scripts", "options_radar"):
        for p in (ROOT / folder).rglob("*.py"):
            text = p.read_text(encoding="utf-8")
            assert not re.search(r"openssl[^\n]*\benc\b", text), p
            for line in text.splitlines():
                if "TELEGRAM_BOT_TOKEN" in line:
                    assert not re.search(r"hmac|\btag\(|fingerprints\(|encrypt|SC_KEY", line), (p, line)


def test_workflows_with_alpaca_keys_commit_only_reviewed_paths():
    seen = set()
    for p, text in _alpaca_workflows():
        for m in re.finditer(r"git add ([^\n|&;]+)", text):
            for path in m.group(1).split():
                if path.startswith("-") or path in ("2>/dev/null", "||", "true"):
                    continue
                seen.add(path)
                assert path in ALLOWED_ADDS, f"{p.name} commits {path}: review its storage rights first"
    assert "state/smallcaps/*.tags.json" in seen


def test_workflows_with_alpaca_keys_upload_no_artifacts():
    for p, text in _alpaca_workflows():
        if "upload-artifact" in text:
            assert p.name in ALLOWED_ARTIFACT_WORKFLOWS, f"{p.name}: artifacts of a public repo are downloadable"


def test_public_status_has_no_outcome_counts(tmp_path):
    state = tmp_path / "state"
    day = state / "daily_plan" / "2026-11-30"
    day.mkdir(parents=True)
    (day / "session_POSTCLOSE.json").write_text(json.dumps({"status": "DELIVERED", "scorecard": {"t1": 3}}))
    small = state / "smallcaps"
    small.mkdir()
    run.save_tags(small / "2026-11-30.tags.json", "2026-11-30", {"ab"}, 2, NOW)
    out = bos.build(state, tmp_path / "data", NOW)
    text = json.dumps(out)
    assert "scorecard" not in text and "t1" not in text and "positive" not in text
    assert out["smallcaps"]["alerts_sent"] == 2 and "tags" not in out["smallcaps"]
