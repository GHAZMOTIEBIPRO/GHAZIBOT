"""Classify GitHub Actions failures and verified recovery transitions for Telegram.

Only a completed SUCCESS of the same monitored workflow can close an incident.
The classification is advisory to the notification channel, never trading authority.
"""
from __future__ import annotations

import argparse
import html
import os
from typing import Any

import requests

FAILURES = frozenset({"failure", "timed_out", "action_required", "startup_failure"})
TERMINAL = FAILURES | {"success"}


def _run_number(value: Any) -> int:
    try:
        result = int(value)
        return max(0, result)
    except (TypeError, ValueError):
        return 0


def _matching_runs(
    history: list[dict[str, Any]], workflow_id: int
) -> list[dict[str, Any]]:
    verified = []
    for row in history:
        if not isinstance(row, dict):
            continue
        if _run_number(row.get("workflow_id")) != workflow_id:
            continue
        if str(row.get("head_branch") or "") != "main":
            continue
        if str(row.get("status") or "") != "completed":
            continue
        if str(row.get("conclusion") or "") not in TERMINAL:
            continue
        if _run_number(row.get("id")):
            verified.append(row)
    return sorted(verified, key=lambda row: _run_number(row["id"]), reverse=True)


def classify_transition(
    *,
    run_id: int,
    workflow_id: int,
    conclusion: str,
    branch: str,
    history: list[dict[str, Any]] | None,
    manual: bool = False,
) -> tuple[str, int | None]:
    """Return (failure|recovery|manual|ignore, preceding failed run id).

    A late failure event must never override a newer completed outcome.
    Consecutive failures are one incident. A verified success after failure is
    the only automatic recovery notification, including for push-only scans.
    """
    if manual:
        return "manual", None
    if branch != "main" or conclusion not in TERMINAL:
        return "ignore", None
    if run_id <= 0 or workflow_id <= 0:
        return ("failure", None) if conclusion in FAILURES else ("ignore", None)
    if history is None:
        # GitHub API unavailable: retain the historical fail-alert behavior,
        # but never invent a recovery without a confirmed prior failure.
        return ("failure", None) if conclusion in FAILURES else ("ignore", None)

    rows = _matching_runs(history, workflow_id)
    if not any(_run_number(row["id"]) == run_id for row in rows):
        # A delayed event older than the bounded API window is not current.
        return "ignore", None
    if any(_run_number(row["id"]) > run_id for row in rows):
        return "ignore", None

    previous = next(
        (row for row in rows if _run_number(row["id"]) < run_id),
        None,
    )
    previous_conclusion = str(previous.get("conclusion") or "") if previous else ""
    previous_id = _run_number(previous.get("id")) if previous else None
    if conclusion in FAILURES:
        if previous_conclusion in FAILURES:
            return "ignore", None
        return "failure", None
    if conclusion == "success" and previous_conclusion in FAILURES:
        return "recovery", previous_id
    return "ignore", None


def fetch_completed_runs(
    *, repository: str, workflow_id: int, token: str
) -> list[dict[str, Any]] | None:
    """Fetch bounded, completed, main-branch runs using the Action's read token."""
    if not repository or workflow_id <= 0 or not token:
        return None
    try:
        response = requests.get(
            f"https://api.github.com/repos/{repository}/actions/workflows/{workflow_id}/runs",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            params={"branch": "main", "status": "completed", "per_page": 50},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("workflow_runs") if isinstance(payload, dict) else None
        return rows if isinstance(rows, list) else None
    except (requests.RequestException, ValueError, TypeError):
        return None


def render_message(kind: str, event: dict[str, str], previous_failed: int | None = None) -> str:
    """Escape all GitHub-provided text before emitting Telegram HTML."""
    name = str(event.get("name") or "unknown")
    status = str(event.get("conclusion") or "unknown")
    branch = str(event.get("branch") or "unknown")
    event_type = str(event.get("event") or "unknown")
    run_id = str(event.get("id") or "unknown")
    url = str(event.get("url") or "").strip()
    if not url.startswith("https://github.com/"):
        url = "https://github.com/GHAZMOTIEBIPRO/GHAZIBOT/actions"

    if kind == "manual":
        title = "اختبار مراقب فشل التشغيل"
        details = "تم تشغيل مراقب Telegram يدويًا للتحقق من اتصال التنبيهات."
    elif kind == "recovery":
        title = "تعافي تشغيل Omega"
        details = (
            f"المسار: {name}\n"
            f"التشغيل المتعافي: {run_id}\n"
            f"التشغيل الفاشل السابق: {previous_failed or 'غير معروف'}\n"
            f"الفرع: {branch}\n"
            "الحالة: success (GitHub Actions)\n"
            "نجاح الفحص لا يثبت وصول توصيات Telegram أو صلاحية أسعار العقود للتنفيذ."
        )
    else:
        title = "فشل تشغيل Omega"
        details = (
            f"المسار: {name}\n"
            f"الحالة: {status}\n"
            f"الفرع: {branch}\n"
            f"نوع التشغيل: {event_type}\n"
            f"Run ID: {run_id}\n"
            "هذا التحذير يخص التشغيل المذكور؛ قد ينجح تشغيل أحدث بعده."
        )
    icon = "✅" if kind == "recovery" else "🚨" if kind == "failure" else "ℹ️"
    return (
        f"<b>{icon} {html.escape(title)}</b>\n\n"
        f"{html.escape(details)}\n\n"
        f'<a href="{html.escape(url, quote=True)}">فتح تفاصيل التشغيل</a>'
    )


def _event_from_env() -> dict[str, str]:
    return {
        "name": os.getenv("RUN_NAME", "unknown"),
        "conclusion": os.getenv("RUN_CONCLUSION", "unknown"),
        "branch": os.getenv("RUN_BRANCH", "unknown"),
        "event": os.getenv("RUN_EVENT", "unknown"),
        "id": os.getenv("RUN_ID", "unknown"),
        "url": os.getenv("RUN_URL", ""),
    }


def _output(values: dict[str, str]) -> None:
    path = os.getenv("GITHUB_OUTPUT", "").strip()
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("".join(f"{key}={value}\n" for key, value in values.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify/send guarded Omega failure and recovery notices")
    parser.add_argument("--send", action="store_true", help="Send already classified Telegram notice")
    args = parser.parse_args()
    event = _event_from_env()
    if args.send:
        kind = os.getenv("WATCHDOG_KIND", "")
        if kind not in {"manual", "failure", "recovery"}:
            raise SystemExit("No verified notice to send")
        previous = _run_number(os.getenv("WATCHDOG_PREVIOUS_FAILED")) or None
        from scripts.telegram_transport import send_html_message

        receipt = send_html_message(render_message(kind, event, previous), max_attempts=3)
        print(f"Omega {kind} notification delivered to Telegram API: message_id={receipt.message_id}; attempts={receipt.attempts}")
        return 0

    manual = os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch"
    workflow_id = _run_number(os.getenv("RUN_WORKFLOW_ID"))
    run_id = _run_number(event["id"])
    history = None if manual else fetch_completed_runs(
        repository=str(os.getenv("GITHUB_REPOSITORY") or ""),
        workflow_id=workflow_id,
        token=str(os.getenv("GH_TOKEN") or ""),
    )
    kind, prior_id = classify_transition(
        run_id=run_id,
        workflow_id=workflow_id,
        conclusion=event["conclusion"],
        branch=event["branch"],
        history=history,
        manual=manual,
    )
    _output({
        "notify": "true" if kind != "ignore" else "false",
        "kind": kind,
        "previous_failed": str(prior_id or ""),
    })
    print(f"Watchdog transition: {kind}; prior_failed={prior_id}; API_history={'available' if history is not None else 'unavailable'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
