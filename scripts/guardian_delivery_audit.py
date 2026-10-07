from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temp.replace(path)


def build_delivery_preflight(
    report: dict[str, Any],
    *,
    token_configured: bool,
    destination_ready: bool,
    now: datetime | None = None,
    max_report_age_minutes: float = 120.0,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    generated_at = str(report.get("generated_at") or "")
    age_minutes: float | None = None
    try:
        parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            age_minutes = (now - parsed.astimezone(timezone.utc)).total_seconds() / 60
    except ValueError:
        pass

    active = max(0, int(report.get("active_count") or 0))
    if not token_configured:
        status = "BLOCKED_MISSING_BOT_TOKEN"
    elif not destination_ready:
        status = "BLOCKED_MISSING_DESTINATION"
    elif age_minutes is None or age_minutes < 0 or age_minutes > max_report_age_minutes:
        status = "BLOCKED_STALE_GUARDIAN_REPORT"
    elif active == 0:
        status = "NO_ACTIVE_CONTRACTS"
    else:
        status = "READY_TO_DELIVER"
    return {
        "schema_version": 1,
        "checked_at": now.isoformat(),
        "status": status,
        "tracked_contracts": max(0, int(report.get("tracked_total") or 0)),
        "active_contracts": active,
        "report_age_minutes": round(age_minutes, 2) if age_minutes is not None else None,
        "max_report_age_minutes": max_report_age_minutes,
        "telegram_token_configured": token_configured,
        "telegram_destination_ready": destination_ready,
        "sent": 0,
        "edited": 0,
        "unchanged": 0,
        "message_ids_exposed": False,
        "contains_secrets": False,
        "note_ar": (
            "هذه حالة إرسال تيليجرام الفعلية؛ نجاح توليد الرادار وحده "
            "لا يثبت وصول رسالة."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Guardian Telegram readiness without leaking secrets")
    parser.add_argument("--report", default="public/data/contract_guardian.json")
    parser.add_argument("--output", default="data/live/guardian_delivery_audit.json")
    args = parser.parse_args()
    preflight = build_delivery_preflight(
        _load(Path(args.report)),
        token_configured=bool(os.getenv("TELEGRAM_BOT_TOKEN")),
        destination_ready=(
            os.getenv("TELEGRAM_READY", "").lower() == "true"
            and bool(os.getenv("TELEGRAM_CHAT_ID"))
        ),
    )
    _write(Path(args.output), preflight)
    print(
        f"Guardian Telegram readiness: {preflight['status']}; "
        f"tracked={preflight['tracked_contracts']}; "
        f"active={preflight['active_contracts']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
