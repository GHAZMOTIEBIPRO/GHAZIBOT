from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from options_radar.sec_efts import EFTS_URL, discover_sec_fulltext_events
from options_radar.settings import Settings

STATUS_PATH = Path("data/cache/sec_efts_status.json")


def write_status(payload: dict) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATUS_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATUS_PATH)


def main() -> int:
    settings = Settings()
    end_date = date.today()
    start_date = end_date - timedelta(days=14)
    status = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "available": False,
        "source": "SEC EDGAR Full-Text Search",
        "endpoint": EFTS_URL,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "event_count": 0,
        "message": "not checked",
    }
    try:
        response = requests.get(
            EFTS_URL,
            params={
                "q": '"merger agreement"',
                "forms": "8-K,6-K,SC 13D,SC 13D/A",
                "startdt": start_date.isoformat(),
                "enddt": end_date.isoformat(),
                "from": 0,
            },
            headers={
                "User-Agent": settings.sec_user_agent,
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate",
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        total = ((payload.get("hits") or {}).get("total") or {})
        total_value = total.get("value", 0) if isinstance(total, dict) else total
        status.update(
            {
                "available": True,
                "http_status": response.status_code,
                "probe_hits": int(total_value or 0),
                "message": "SEC full-text endpoint responded successfully",
            }
        )
        events = discover_sec_fulltext_events(settings, lookback_days=14)
        status["event_count"] = len(events)
    except Exception as exc:
        status.update(
            {
                "available": False,
                "http_status": getattr(getattr(exc, "response", None), "status_code", None),
                "error_type": type(exc).__name__,
                "message": str(exc)[:500],
            }
        )
    write_status(status)
    print(json.dumps(status, ensure_ascii=False))
    # The radar must continue with cached/latest-form sources when EFTS is blocked.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
