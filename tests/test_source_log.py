from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from scripts import build_source_log as sl

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _commit(repo, name, payload, msg):
    path = repo / "runtime/public/data" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg)


def test_ratio_counts_attempts_only_and_last_success_is_the_last_good_run(tmp_path):
    _git(tmp_path, "init", "-q")
    stamps = [NOW - timedelta(days=d) for d in (20, 3, 2, 1)]
    _commit(tmp_path, "usaspending_contracts.json", {"generated_at": stamps[0].isoformat(),
            "counts": {"companies": 10, "companies_ok": 10}}, "old, outside the window")
    _commit(tmp_path, "usaspending_contracts.json", {"generated_at": stamps[1].isoformat(),
            "counts": {"companies": 10, "companies_ok": 10}}, "ok")
    _commit(tmp_path, "usaspending_contracts.json", {"generated_at": stamps[2].isoformat(),
            "counts": {"companies": 10, "companies_ok": 4}}, "partial")
    _commit(tmp_path, "usaspending_contracts.json", {"generated_at": stamps[3].isoformat(),
            "counts": {"companies": 10, "companies_ok": 0}}, "failed")
    _commit(tmp_path, "daily_plan.json", {"generated_at": stamps[3].isoformat(),
            "private_mode": {"enabled": False, "reason": "ACCOUNT_CREDENTIALS_NOT_CONFIGURED"}}, "gated")
    rights = json.loads((ROOT / "data/source_rights.json").read_text(encoding="utf-8"))
    report = sl.build(tmp_path, NOW, rights)
    by = {s["key"]: s for s in report["sources"]}
    gov = by["usaspending"]
    assert (gov["runs_seen"], gov["attempted"], gov["succeeded"], gov["fully_ok"]) == (3, 3, 2, 1)
    assert gov["success_ratio"] == round(2 / 3, 3) and gov["last_outcome"] == "FAILED"
    assert gov["last_success_at"] == stamps[2].isoformat()            # the partial run, not the failed one
    assert "عرض النتائج المشتقة" in gov["uses"]["verified"]
    alp = by["alpaca_bars"]                                             # a gate is not a failure
    assert alp["last_outcome"] == "NOT_ATTEMPTED" and alp["attempted"] == 0 and alp["success_ratio"] is None
    assert alp["last_detail"] == "ACCOUNT_CREDENTIALS_NOT_CONFIGURED"
    assert by["fred"]["last_outcome"] == "NOT_CONFIGURED"
    assert by["sec_edgar"]["last_outcome"] == "NO_RUN_RECORDED"
    assert [s["priority"] for s in report["sources"]] == sorted(s["priority"] for s in report["sources"])


def test_the_evidence_workflow_is_the_only_writer():
    # writers commit it to bot-state; a preview copy in a temp folder is not a writer
    writers = [p.name for p in (ROOT / ".github/workflows").glob("*.yml")
               if any("source_log.json" in line and ("git add" in line or "--output state/" in line)
                      for line in p.read_text(encoding="utf-8").splitlines())]
    assert writers == ["site-evidence-strength.yml"]
    wf = yaml.safe_load((ROOT / ".github/workflows/site-evidence-strength.yml").read_text(encoding="utf-8"))
    state = next(s for s in wf["jobs"]["evidence-readiness"]["steps"] if (s.get("with") or {}).get("ref") == "bot-state")
    assert state["with"]["fetch-depth"] == 0                            # history is needed for the ratio
