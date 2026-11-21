"""Every Telegram sender resolves its destination through the one shared path.

The bot token and the group id reach senders only through
scripts/telegram_connection_bootstrap.py (directly or via the
.github/actions/resolve-telegram-broadcast composite action). It reads
secrets.TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID, can restore the group id from the
encrypted connection artifact, and exports TELEGRAM_READY. A sender that reads
the raw secrets itself diverges: it stays silent when only the token is set while
every other sender works (found in standalone-intelligence-v10, 2026-11-12).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
SENDER = re.compile(r"scripts[./](send_[a-z0-9_]+|run_realtime_options_intelligence)")
RESOLVER = re.compile(r"resolve-telegram-broadcast|telegram_connection_bootstrap")


def _steps(job):
    return job.get("steps") or []


def _text(step):
    return " ".join(str(step.get(k) or "") for k in ("run", "uses"))


def test_every_sender_resolves_first_and_is_gated_on_telegram_ready():
    problems = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if "secrets.TELEGRAM_BOT_TOKEN" not in path.read_text(encoding="utf-8"):
            continue
        for job_name, job in (doc.get("jobs") or {}).items():
            resolved = False
            for step in _steps(job):
                text = _text(step)
                if RESOLVER.search(text):
                    resolved = True
                    continue
                if not SENDER.search(text) or "--dry-run" in text or "--help" in text:
                    continue
                where = f"{path.name}:{job_name}:{step.get('name')}"
                if not resolved:
                    problems.append(f"{where}: sends before resolving the destination")
                condition = str(step.get("if") or "")
                if "TELEGRAM_CHAT_ID" in condition or "TELEGRAM_BOT_TOKEN" in condition:
                    problems.append(f"{where}: gated on a raw secret instead of TELEGRAM_READY")
    assert not problems, "\n".join(problems)


def test_no_workflow_uses_an_alternative_secret_name():
    names = set()
    for path in WORKFLOWS.glob("*.yml"):
        if path.name == "telegram-diagnose.yml":  # probes alternative names on purpose
            continue
        names.update(re.findall(r"secrets\.([A-Z0-9_]*(?:TELEGRAM|TG_|BOT_TOKEN)[A-Z0-9_]*)",
                                path.read_text(encoding="utf-8")))
    assert names <= {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_OWNER_CHAT_ID"}, names


def test_no_job_is_bound_to_an_environment_that_would_hide_repository_secrets():
    # Jobs read repository secrets only; a secret saved in an Environment never reaches
    # them. The diagnose workflow is the one deliberate exception (it inspects them).
    for path in WORKFLOWS.glob("*.yml"):
        if path.name == "telegram-diagnose.yml":
            continue
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in (doc.get("jobs") or {}).items():
            assert "environment" not in job, f"{path.name}:{job_name}"
