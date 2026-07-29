from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Direct execution as `python scripts/prime_sec_efts.py` puts only the scripts
# directory on sys.path. Add the repository root so options_radar is importable
# in GitHub Actions and local direct runs.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

STATUS_PATH = Path("data/cache/sec_efts_status.json")
EFTS_URL = "https://efts.sec.gov/LATEST/search-index"


def write_status(payload: dict) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATUS_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATUS_PATH)


def main() -> int:
    end_date = datetime.now(timezone.utc).date()
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
        "retry_policy": "429/5xx only; bounded exponential backoff; 403 is not hammered",
        "fallbacks_active": [
            "SEC latest-form Atom feeds",
            "SEC submissions and Company Facts",
            "last valid SEC EFTS event cache",
        ],
    }

    try:
        # Keep package imports inside the guarded block. SEC full-text is an
        # optional source and must never prevent the rest of the radar from
        # producing a dashboard when SEC or an optional import is unavailable.
        from options_radar.sec_efts import discover_sec_fulltext_events
        from options_radar.sec_efts_resilience import request_efts_json
        from options_radar.settings import Settings

        settings = Settings()
        payload = request_efts_json(
            settings,
            {
                "q": '"merger agreement"',
                "forms": "8-K,6-K,SC 13D,SC 13D/A",
                "startdt": start_date.isoformat(),
                "enddt": end_date.isoformat(),
                "from": 0,
            },
        )
        total = ((payload.get("hits") or {}).get("total") or {})
        total_value = total.get("value", 0) if isinstance(total, dict) else total
        status.update(
            {
                "available": True,
                "http_status": 200,
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
                "traceback_tail": traceback.format_exc(limit=8)[-4000:],
            }
        )

    write_status(status)
    print(json.dumps(status, ensure_ascii=False))
    # SEC EFTS is optional. Always allow cached/latest-form/fallback sources.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
