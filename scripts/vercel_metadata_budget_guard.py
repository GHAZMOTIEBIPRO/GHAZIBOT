"""Throttle static Vercel health metadata mirrors without slowing live bot-state.

The canonical runtime data stays on bot-state and updates at the existing
cadence. Only the public static fallback is mirrored to main at most once
per 6 hours, reducing Vercel Hobby deployment quota pressure.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

MIN_INTERVAL_MINUTES = 360  # Four static fallbacks/day; live runtime continues on bot-state.


def _stamp(data: dict) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(data.get("generated_at") or "").replace("Z", "+00:00"))
        return value.astimezone(timezone.utc) if value.tzinfo else None
    except (TypeError, ValueError):
        return None


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"metadata must be JSON object: {path}")
    return payload


def should_mirror(old_health: dict, old_status: dict,
                  new_health: dict, new_status: dict,
                  *, min_interval_minutes: int = MIN_INTERVAL_MINUTES) -> bool:
    if min_interval_minutes < 30:
        raise ValueError("minimum interval must be at least 30m")
    new_times = [_stamp(new_health), _stamp(new_status)]
    if any(item is None for item in new_times):
        raise ValueError("incoming runtime metadata missing valid timezone-aware generated_at")
    prior_times = [_stamp(old_health), _stamp(old_status)]
    if any(item is None for item in prior_times):
        return True  # Missing/corrupt previous static fallback: safe repair.
    old_latest = max(prior_times)
    new_earliest = min(new_times)
    if new_earliest <= old_latest:
        return False  # Never replace static fallback with older data.
    return new_earliest - old_latest >= timedelta(minutes=min_interval_minutes)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-health", type=Path, required=True)
    parser.add_argument("--old-status", type=Path, required=True)
    parser.add_argument("--new-health", type=Path, required=True)
    parser.add_argument("--new-status", type=Path, required=True)
    args = parser.parse_args()
    decision = should_mirror(_read(args.old_health), _read(args.old_status),
                             _read(args.new_health), _read(args.new_status))
    print("PUBLISH" if decision else "SKIP")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
