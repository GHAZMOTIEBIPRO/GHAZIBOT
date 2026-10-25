"""Session-aligned intraday frames from 5-minute bars (pure, no network).

Buckets start at the regular-session open of each XNYS session and stop at
its close, so an early-close day ends its last bucket early instead of
borrowing bars from the next day:

- 15m / 1H: consecutive buckets from 09:30 New York (1H: 09:30, 10:30, ...,
  15:30-16:00 is a half bucket).
- 4H: 09:30-13:30 and 13:30-close (two buckets per day). The regular
  session is 6.5 hours, so the second bucket is 2.5 hours (shorter still on
  early-close days): it is marked `partial` with its real `minutes`, never
  presented as a full four-hour bar.

A bucket is published only when it is complete: its end is at or before the
cutoff (now minus the provider delay) and it holds at least one bar. The
current, unfinished bucket is never included. Pre- and post-market bars are
ignored. Each bucket records how many 5-minute bars it was built from, since
a single-venue feed (IEX) can have gaps.
"""
from __future__ import annotations

import math
from bisect import bisect_left
from datetime import datetime, timedelta
from typing import Any

FRAME_MINUTES = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}


def _valid(bar: Any) -> bool:
    if not isinstance(bar, dict) or not isinstance(bar.get("t"), datetime) or bar["t"].tzinfo is None:
        return False
    nums = [bar.get(k) for k in ("o", "h", "l", "c")]
    if any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or n <= 0 for n in nums):
        return False
    o, h, low, c = nums
    vol = bar.get("v", 0)
    return h >= max(o, c, low) and low <= min(o, c, h) and isinstance(vol, (int, float)) and vol >= 0


def aggregate(bars_5m: list[dict[str, Any]], sessions: list[tuple[datetime, datetime]], frame: str,
              cutoff: datetime) -> list[dict[str, Any]]:
    """Completed session-aligned buckets. `sessions` are (open, close) aware datetimes."""
    minutes = FRAME_MINUTES[frame]
    bars = sorted((b for b in bars_5m if _valid(b)), key=lambda b: b["t"])
    stamps = [b["t"] for b in bars]
    out = []
    for open_, close in sessions:
        start = open_
        while start < close:
            end = min(start + timedelta(minutes=minutes), close)
            if end > cutoff:
                break
            rows = bars[bisect_left(stamps, start):bisect_left(stamps, end)]
            if rows:
                length = int((end - start).total_seconds() // 60)
                out.append({"start": start.isoformat(), "end": end.isoformat(), "minutes": length,
                            "partial": length < minutes,
                            "open": rows[0]["o"], "high": max(b["h"] for b in rows),
                            "low": min(b["l"] for b in rows), "close": rows[-1]["c"],
                            "volume": sum(b.get("v", 0) for b in rows), "bars_5m": len(rows)})
            start = end
    return out


def frames_from_5m(bars_5m: list[dict[str, Any]], sessions: list[tuple[datetime, datetime]],
                   cutoff: datetime) -> dict[str, list[dict[str, Any]]]:
    return {frame: aggregate(bars_5m, sessions, frame, cutoff) for frame in FRAME_MINUTES}
