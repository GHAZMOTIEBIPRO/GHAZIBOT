from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

import scripts.send_news_flash_24x7 as flash
from scripts.news_flash_reclaiming import reclaim_metrics


def _install_reclaim_overlay(state_path: Path) -> None:
    before = flash._load(state_path)
    previous_events = before.get("events") if isinstance(before.get("events"), dict) else {}
    original_record = flash._record_from_event
    original_status_ar = flash._status_ar
    original_action_ar = flash._action_ar

    def status_ar(status: str) -> tuple[str, str]:
        if status == "RECLAIMING":
            return "♻️", "إعادة تمركز — استعادة VWAP وبنية 5 دقائق مع فوليوم"
        return original_status_ar(status)

    def action_ar(status: str) -> str:
        if status == "RECLAIMING":
            return (
                "إعادة اهتمام فقط: السهم سبق وهدأ بعد الخبر، والآن استعاد VWAP وبنية 5m "
                "بفوليوم أفضل. راقب تثبيت الاستعادة؛ لا تدخل لمجرد هذا التنبيه."
            )
        return original_action_ar(status)

    def record_from_event(
        event: Any,
        *,
        published: datetime,
        now: datetime,
        frame: pd.DataFrame | None,
    ) -> dict[str, Any]:
        current = original_record(event, published=published, now=now, frame=frame)
        fp = flash.event_fingerprint(event)
        previous = previous_events.get(fp) if isinstance(previous_events, dict) else None
        previous = previous if isinstance(previous, dict) else {}
        had_faded = bool(previous.get("ever_faded")) or str(previous.get("reaction_state")) == "FADED"
        if str(current.get("reaction_state")) == "FADED":
            had_faded = True
        current["ever_faded"] = had_faded

        if not had_faded:
            return current
        metrics = reclaim_metrics(frame, published, str(current.get("bias") or "NEUTRAL"))
        if metrics:
            current["reclaim"] = metrics
            if metrics.get("reclaiming") is True:
                current["reaction_state"] = "RECLAIMING"
        return current

    flash._record_from_event = record_from_event
    flash._status_ar = status_ar
    flash._action_ar = action_ar


def main() -> None:
    parser = argparse.ArgumentParser(
        description="24x7 company-news flash with fade and post-news reclaim lifecycle"
    )
    parser.add_argument("--state", default="data/live/news_flash_24x7.json")
    parser.add_argument(
        "--max-age-minutes",
        type=int,
        default=int(os.getenv("NEWS_FLASH_MAX_AGE_MINUTES", "60")),
    )
    parser.add_argument(
        "--update-window-minutes",
        type=int,
        default=int(os.getenv("NEWS_FLASH_UPDATE_WINDOW_MINUTES", "240")),
    )
    parser.add_argument(
        "--max-new-alerts",
        type=int,
        default=int(os.getenv("NEWS_FLASH_MAX_NEW_ALERTS", "5")),
    )
    args = parser.parse_args()
    state_path = Path(args.state)
    _install_reclaim_overlay(state_path)
    stats = flash.run(
        state_path=state_path,
        max_age_minutes=max(10, min(args.max_age_minutes, 180)),
        update_window_minutes=max(30, min(args.update_window_minutes, 480)),
        max_new_alerts=max(1, min(args.max_new_alerts, 8)),
    )
    print(
        "News Flash 24x7 + reclaim: "
        + " ".join(f"{key}={value}" for key, value in stats.items())
    )


if __name__ == "__main__":
    main()
