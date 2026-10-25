"""Pre-open daily plan sheet (public) and optional owner-private price plans.

Public sheet (runtime/public/data/daily_plan.json), no prices:
- XNYS session facts for New York and Riyadh: open/close, early close,
  holiday, next session; last closed session and week.
- The day's official catalysts (catalyst_watchlist.json) and the rate
  backdrop (public_macro.json, macro_regimes.json).
- Per frame (weekly, daily, 4H, 1H, 15m, 5m): which provider could supply
  it and why it is or is not available.
- A morning copy is written once per session date and never rewritten
  (state/daily_plan/<date>/morning.json); later runs only refresh the
  latest sheet.

Owner-private mode: when Alpaca credentials exist and the owner set
ALPACA_INTERNAL_DATA_USE_AUTHORIZED=true, completed IEX daily bars are
fetched (options_radar.alpaca_delayed_research) and options_radar.daily_plan
computes the plans. Those plans are written only to --private-output
(outside the published state) because Alpaca data may not be
redistributed; nothing from them reaches the public sheet.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from options_radar import daily_plan as dp
from options_radar.alpaca_delayed_research import fetch_completed_daily, policy_state

NY = ZoneInfo("America/New_York")
RIYADH = ZoneInfo("Asia/Riyadh")
PLAN_SYMBOLS = ("SPY", "QQQ", "IWM", "DIA", "NVDA", "AAPL", "MSFT", "AMZN", "META", "TSLA", "AMD", "GOOGL")
FRAMES = ("weekly", "daily", "4h", "1h", "15m", "5m")


def _load(path: Path | None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path else None
    except (OSError, ValueError):
        return None


def calendar_facts(now: datetime) -> dict[str, Any]:
    cal = xcals.get_calendar("XNYS")
    ny_now = now.astimezone(NY)
    sched = cal.schedule.loc[str((ny_now - timedelta(days=40)).date()):str((ny_now + timedelta(days=12)).date())]
    rows = [(label.date(), pd.Timestamp(r["open"]).to_pydatetime(), pd.Timestamp(r["close"]).to_pydatetime())
            for label, r in sched.iterrows()]
    closed = [d for d, _, close in rows if close <= now]
    weeks: dict[tuple[int, int], date] = {}
    for d, _, _ in rows:
        key = d.isocalendar()[:2]
        weeks[key] = max(weeks.get(key, d), d)
    closed_week_ends = [end for end in weeks.values() if closed and end <= closed[-1]]
    today = next(((d, o, c) for d, o, c in rows if d == ny_now.date()), None)
    upcoming = next(((d, o, c) for d, o, c in rows if o > now), None)

    def times(entry: tuple[date, datetime, datetime] | None) -> dict[str, Any] | None:
        if entry is None:
            return None
        d, o, c = entry
        return {"date": d.isoformat(),
                "open_new_york": o.astimezone(NY).strftime("%H:%M"), "close_new_york": c.astimezone(NY).strftime("%H:%M"),
                "open_riyadh": o.astimezone(RIYADH).strftime("%H:%M"), "close_riyadh": c.astimezone(RIYADH).strftime("%H:%M"),
                "early_close": c.astimezone(NY).strftime("%H:%M") != "16:00",
                "utc_offset_new_york": o.astimezone(NY).strftime("%z")}

    return {"today_is_session": today is not None, "today": times(today), "next_session": times(upcoming),
            "last_closed_session": closed[-1].isoformat() if closed else None,
            "last_closed_week_end": max(closed_week_ends).isoformat() if closed_week_ends else None,
            "calendar": "exchange_calendars XNYS", "timezone": "America/New_York"}


def catalysts_today(watch: Any, now: datetime, limit: int = 6) -> list[dict[str, Any]]:
    cutoff = (now - timedelta(days=3)).date().isoformat()
    out = []
    for entry in (watch or {}).get("watchlist") or []:
        recent = [c for c in (entry.get("catalysts") or []) if isinstance(c, dict) and str(c.get("date")) >= cutoff]
        if not isinstance(entry, dict) or not recent:
            continue
        top = recent[0]  # catalysts are ordered by importance, so this is the most important recent one
        out.append({"symbol": entry.get("symbol"), "kind": top.get("kind"), "date": top.get("date"),
                    "source": top.get("source"), "source_url": top.get("source_url"),
                    "score": entry.get("catalyst_score"), "risk_flags": entry.get("risk_flags") or [],
                    "size": entry.get("universe")})
    return out[:limit]


def macro_context(macro: Any, regimes: Any) -> dict[str, Any]:
    curve = (macro or {}).get("treasury_curve") or {}
    breaks = {k: len(v.get("breaks") or []) for k, v in ((regimes or {}).get("series") or {}).items()
              if isinstance(v, dict) and v.get("available")}
    return {"curve_date": curve.get("curve_date"), "spreads_bp": curve.get("spreads_bp"),
            "yields_pct": curve.get("yields_pct"), "regime_series_with_breaks": sum(1 for n in breaks.values() if n),
            "regime_series": len(breaks)}


def private_plans(facts: dict[str, Any], now: datetime, *, session: Any = None) -> dict[str, Any]:
    key, secret = os.getenv("ALPACA_API_KEY", ""), os.getenv("ALPACA_SECRET_KEY", "")
    allowed = os.getenv("ALPACA_INTERNAL_DATA_USE_AUTHORIZED", "").strip().lower() == "true"
    state = policy_state(api_key=key, secret=secret, internal_use_allowed=allowed)
    if not state["enabled"] or not facts.get("last_closed_session"):
        return {"enabled": False, "reason": state["reason"], "plans": {}}
    end = date.fromisoformat(facts["last_closed_session"])
    provider = {"name": "alpaca_iex", "scope": "IEX_ONLY_COMPLETED_DAILY", "volume_scope": "IEX only (partial volume)",
                "delay_note": "completed sessions only; latest 15 minutes never requested"}
    plans = {}
    for symbol in PLAN_SYMBOLS:
        bars: list[dict[str, Any]] = []
        for chunk in range(3):  # three 30-day windows, about 63 sessions
            chunk_end = end - timedelta(days=31 * chunk)
            kwargs = {"session": session} if session is not None else {}
            got = fetch_completed_daily(symbol, start=chunk_end - timedelta(days=30), end=chunk_end, api_key=key,
                                        secret=secret, internal_use_allowed=allowed, now=now, **kwargs)
            bars.extend(got.get("bars") or [])
        plans[symbol] = dp.plan_for_symbol(symbol, bars, last_closed_session=facts["last_closed_session"],
                                           last_closed_week_end=facts["last_closed_week_end"] or "",
                                           provider=provider)
    return {"enabled": True, "reason": state["reason"], "plans": plans}


def frames_status(private: dict[str, Any]) -> dict[str, Any]:
    status = {}
    for frame in FRAMES:
        if frame in ("weekly", "daily") and private.get("enabled"):
            status[frame] = {"public": "UNAVAILABLE", "private_owner": "AVAILABLE",
                             "reason": "Alpaca IEX completed daily bars: internal use only, no redistribution"}
        else:
            status[frame] = {"public": "UNAVAILABLE",
                             "private_owner": "UNAVAILABLE",
                             "reason": ("no permitted public price source; Yahoo/Nasdaq.com automation not permitted"
                                        if frame in ("weekly", "daily") and not private.get("enabled") else
                                        "no permitted intraday bars (Alpaca free intraday is IEX-only and"
                                        " not configured)")}
    return status


def build(now: datetime, watch: Any, macro: Any, regimes: Any, private: dict[str, Any]) -> dict[str, Any]:
    facts = calendar_facts(now)
    return {
        "schema": "ghazi.daily_plan_sheet.v1", "generated_at": now.isoformat(),
        "session": facts, "frames": frames_status(private),
        "catalysts": catalysts_today(watch, now), "macro": macro_context(macro, regimes),
        "private_mode": {"enabled": private.get("enabled", False), "reason": private.get("reason"),
                         "symbols": sorted(private.get("plans") or {}) if private.get("enabled") else [],
                         "published": False},
        "public_price_plans": {},
        "notes_ar": ["خطة اليوم العامة لا تحتوي أسعارًا: لا يوجد مصدر أسعار يسمح بالعرض العام.",
                     "الأوقات من تقويم بورصة نيويورك (XNYS) بتوقيت نيويورك والرياض، مع الإغلاق المبكر والعطل.",
                     "المحفزات رسمية وليست اتجاهًا؛ السيناريوهات السعرية تظهر فقط عند توفر شموع مسموحة."],
        "research_only": True, "decision_authority": False, "execution_authority": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--morning-dir", type=Path, required=True)
    parser.add_argument("--private-output", type=Path)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    facts = calendar_facts(now)
    private = private_plans(facts, now)
    sheet = build(now, _load(args.data_dir / "catalyst_watchlist.json"), _load(args.data_dir / "public_macro.json"),
                  _load(args.data_dir / "macro_regimes.json"), private)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sheet, ensure_ascii=False, indent=1), encoding="utf-8")
    session_date = (facts.get("today") or {}).get("date")
    if session_date:
        morning = args.morning_dir / session_date / "morning.json"
        if not morning.exists():  # the morning copy is never rewritten
            morning.parent.mkdir(parents=True, exist_ok=True)
            morning.write_text(json.dumps(sheet, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.private_output and private.get("enabled"):
        args.private_output.write_text(json.dumps(private, ensure_ascii=False), encoding="utf-8")
    print("Daily plan:", json.dumps({"today": session_date, "last_closed": facts.get("last_closed_session"),
                                      "private": private.get("reason"), "catalysts": len(sheet["catalysts"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
