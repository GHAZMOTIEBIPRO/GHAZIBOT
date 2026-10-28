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

Owner-private mode (provider -> compute -> output policy -> sink):
- Provider: options_radar.bar_providers.AlpacaBars (IEX feed), called only
  when output_policy allows `fetch` (ALPACA_INTERNAL_DATA_USE_AUTHORIZED) and
  keys exist. Daily bars plus 5-minute bars; 15m/1H/4H are built from the
  5-minute bars on XNYS session boundaries (options_radar.bar_aggregation),
  weekly from completed daily sessions.
- Compute: options_radar.daily_plan (levels name their source and bar).
- Sink: the owner's personal Telegram chat only, through
  output_policy.deliver_private (needs ALPACA_PRIVATE_ALERTS_AUTHORIZED, a
  TELEGRAM_OWNER_CHAT_ID different from the broadcast chat, and Telegram
  confirming the chat is private). Nothing from the private plans reaches the
  public sheet, bot-state, artifacts or logs; the public sheet records only
  the delivery status.
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
from options_radar.bar_aggregation import frames_from_5m
from options_radar.bar_providers import COVERAGE, AlpacaBars
from options_radar.output_policy import decide, deliver_private

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
        # an administrative registry edit is not a catalyst for the session
        recent = [c for c in (entry.get("catalysts") or []) if isinstance(c, dict) and str(c.get("date")) >= cutoff
                  and c.get("kind") != "TRIAL_REGISTRY_UPDATE"]
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


def _sessions(now: datetime, days: int) -> list[tuple[datetime, datetime]]:
    cal = xcals.get_calendar("XNYS")
    sched = cal.schedule.loc[str((now - timedelta(days=days)).date()):str(now.date())]
    return [(pd.Timestamp(r["open"]).to_pydatetime(), pd.Timestamp(r["close"]).to_pydatetime())
            for _, r in sched.iterrows() if pd.Timestamp(r["open"]).to_pydatetime() < now]


def _daily_rows(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"date": b["t"].astimezone(NY).date().isoformat(), "open": b["o"], "high": b["h"], "low": b["l"],
             "close": b["c"], "volume": b["v"]} for b in bars]


def plan_from_provider(provider: Any, symbol: str, facts: dict[str, Any], sessions: list[tuple[datetime, datetime]],
                       now: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    """One symbol: ~2 years of daily bars (a real weekly frame) and 30 sessions of 5-minute bars."""
    daily = provider.bars(symbol, "1d", now - timedelta(days=740), now)
    intraday_start = sessions[-30][0] if len(sessions) >= 30 else (sessions[0][0] if sessions else now)
    minute = provider.bars(symbol, "5m", intraday_start, now)
    feeds = {daily.get("feed"), minute.get("feed")} - {None}
    status = {"daily": daily["status"], "5m": minute["status"], "feeds": sorted(feeds)}
    feed = daily.get("feed") or minute.get("feed") or "unknown"
    meta = {"name": f"alpaca_{feed}", "scope": COVERAGE.get(feed, feed),
            "volume_scope": "all U.S. exchanges" if feed == "sip" else "IEX only (partial volume)",
            "delay_note": "completed bars only; nothing from the latest 16 minutes is requested"}
    intraday = (frames_from_5m(minute["bars"], sessions, now - timedelta(minutes=16))
                if minute["status"] == "OK" and minute.get("feed") == daily.get("feed") else {})
    if minute["status"] == "OK" and minute.get("feed") != daily.get("feed"):
        status["note"] = "intraday dropped: its feed differs from the daily history"
    plan = dp.plan_for_symbol(symbol, _daily_rows(daily["bars"]), last_closed_session=facts["last_closed_session"],
                              last_closed_week_end=facts["last_closed_week_end"] or "", provider=meta,
                              intraday=intraday)
    return plan, status


def private_plans(facts: dict[str, Any], now: datetime, *, session: Any = None,
                  env: Any = None, symbols: tuple[str, ...] | None = None) -> dict[str, Any]:
    env = os.environ if env is None else env
    provider = AlpacaBars(env, **({"session": session} if session is not None else {}), now=now)
    status = provider.status()
    if status != "READY" or not facts.get("last_closed_session"):
        reason = ("DATA_USE_PERMISSION_REQUIRED" if status == "DENIED_BY_POLICY" else
                  "ACCOUNT_CREDENTIALS_NOT_CONFIGURED" if status == "CREDENTIALS_MISSING" else "NO_CLOSED_SESSION")
        return {"enabled": False, "reason": reason, "plans": {}}
    sessions = _sessions(now, 60)
    plans, statuses = {}, {}
    for symbol in symbols or PLAN_SYMBOLS:
        plans[symbol], statuses[symbol] = plan_from_provider(provider, symbol, facts, sessions, now)
    return {"enabled": True, "reason": "OWNER_AUTHORIZED_INTERNAL_USE", "plans": plans, "fetch_status": statuses}


def readiness(private: dict[str, Any], catalysts: list[Any], macro: dict[str, Any]) -> dict[str, Any]:
    """Three separate answers; a fresh file is not a fresh technical analysis."""
    available = [p for p in (private.get("plans") or {}).values() if p.get("available")]
    frames = sorted({f for p in available for f in p.get("frames_available") or []})
    mtf = ("FULL" if set(FRAMES) <= set(frames) else "PARTIAL" if frames else "UNAVAILABLE")
    return {
        "session_and_catalysts": "AVAILABLE" if (catalysts or macro.get("curve_date")) else "UNAVAILABLE",
        "multi_timeframe": {"public": "UNAVAILABLE", "private_owner": mtf, "frames_private": frames},
        "price_levels": {"public": "NOT_COMPUTED", "private_owner": "COMPUTED" if available else "NOT_COMPUTED"},
    }


def frames_status(private: dict[str, Any]) -> dict[str, Any]:
    available = {f for p in (private.get("plans") or {}).values() if p.get("available")
                 for f in p.get("frames_available") or []}
    status = {}
    for frame in FRAMES:
        status[frame] = {"public": "UNAVAILABLE",
                         "private_owner": "AVAILABLE" if frame in available else "UNAVAILABLE",
                         "reason": ("Alpaca IEX bars: owner's internal use only, not redistributed" if frame in available
                                    else "no free source verified yet for computing and redistributing prices publicly; owner-private frames need Alpaca keys and"
                                         " ALPACA_INTERNAL_DATA_USE_AUTHORIZED" if not private.get("enabled")
                                    else "not enough completed bars for this frame")}
    return status


def private_message(private: dict[str, Any], facts: dict[str, Any]) -> str:
    lines = [f"<b>خطة اليوم الخاصة — {facts.get('last_closed_session')}</b>",
             "مصدر: Alpaca (شموع مكتملة، لا شيء من آخر 16 دقيقة). استخدام شخصي فقط؛ لا يُعاد نشره."]
    for symbol, plan in (private.get("plans") or {}).items():
        if not plan.get("available"):
            continue
        frames = plan.get("frames") or {}
        trend = " · ".join(f"{k}:{dp.TREND_AR.get(v.get('trend'), v.get('trend'))}" for k, v in frames.items()
                           if v.get("trend") not in ("UNAVAILABLE",))
        day = plan.get("prior_session") or {}
        votes = [f.get("trend") for f in frames.values() if f.get("trend") in ("UP", "DOWN", "MIXED")]
        ups, downs = votes.count("UP"), votes.count("DOWN")
        agree = ("متفقة صعودًا" if ups and not downs else "متفقة هبوطًا" if downs and not ups else
                 f"متعارضة ({ups} صاعد / {downs} هابط)" if ups and downs else "بلا اتجاه واضح")
        lines.append(f"<b>{symbol}</b> ({plan.get('provider_scope')}) {trend}")
        lines.append(f"  الفريمات: {agree} من {len(votes)}")
        lines.append(f"  أمس ({day.get('date')}): قمة {day.get('high')} · قاع {day.get('low')} · إغلاق {day.get('close')}")
        for sc in plan.get("scenarios") or []:
            if sc.get("trigger_level") is not None:
                lines.append(f"  {sc['kind']}: محفز {sc['trigger_level']} · إبطال {sc['invalidation']}"
                             f" · هدف {sc['target'] if sc['target'] is not None else 'لا مستوى مقاس'}")
    lines.append("لا احتمال نجاح ولا توصية تنفيذ.")
    return "\n".join(lines)[:3900]


def funnel(nasdaq: Any, directory: Any, watch: Any, private: dict[str, Any]) -> dict[str, Any]:
    """Counts per stage of the price-analysis path; a directory of symbols is not a price scan.

    known -> with official news -> bars fetched -> analysed (frames + levels) -> qualified.
    Counts only (no symbols, no prices): the private stages come from Alpaca data
    that is not redistributed.
    """
    listed = {r[0] for r in (nasdaq or {}).get("rows") or [] if isinstance(r, list) and r}
    members = {r.get("symbol") for r in (directory or {}).get("symbols") or [] if isinstance(r, dict)}
    news = {e.get("symbol") for e in (watch or {}).get("events") or [] if isinstance(e, dict) and e.get("symbol")}
    statuses = private.get("fetch_status") or {}
    fetched = sum(1 for s in statuses.values() if isinstance(s, dict) and s.get("daily") == "OK")
    analysed = sum(1 for p in (private.get("plans") or {}).values() if p.get("available"))
    return {
        "known_symbols": {"count": len(listed | members), "nasdaq_listed": len(listed), "sp500_directory": len(members),
                          "basis": "NasdaqTrader Nasdaq Listed file and the S&P 500 directory (no prices)"},
        "with_official_news": {"count": len(news), "basis": "catalyst_watchlist.json events (30 days)"},
        "bars_fetched": {"count": fetched, "attempted": len(statuses), "status": private.get("reason"),
                         "basis": "completed daily bars from the owner-private Alpaca path"},
        "analysed": {"count": analysed, "basis": "frames, levels and conditional scenarios computed"},
        "qualified": {"count": None, "status": "NOT_EVALUATED_IN_THIS_PATH",
                      "basis": "setup conditions are evaluated by the private market scan, not the daily plan"},
    }


def build(now: datetime, watch: Any, macro: Any, regimes: Any, private: dict[str, Any],
          universe: tuple[Any, Any] = (None, None)) -> dict[str, Any]:
    facts = calendar_facts(now)
    catalysts = catalysts_today(watch, now)
    macro_ctx = macro_context(macro, regimes)
    ready = readiness(private, catalysts, macro_ctx)
    full_public = ready["multi_timeframe"]["public"] == "FULL"
    return {
        "schema": "ghazi.daily_plan_sheet.v1", "generated_at": now.isoformat(),
        # without public frames this is a session brief, not a technical plan
        "title_ar": "خطة اليوم" if full_public else "موجز الجلسة والمحركات",
        "readiness": ready,
        "analysis_funnel": funnel(universe[0], universe[1], watch, private),
        "session": facts, "frames": frames_status(private),
        "catalysts": catalysts, "macro": macro_ctx,
        "private_mode": {"enabled": private.get("enabled", False), "reason": private.get("reason"),
                         "symbols": sorted(private.get("plans") or {}) if private.get("enabled") else [],
                         "published": False, "delivery": private.get("delivery", "NOT_ATTEMPTED")},
        "public_price_plans": {},
        "notes_ar": ["الموجز العام بلا أسعار: لم نتحقق حتى الآن من مصدر مجاني مناسب لتغذية محركنا وإعادة توزيع مخرجاته ضمن الاستخدام المطلوب. الشارت الخارجي (TradingView) متاح في الأقسام لكنه لا يغذي تحليلنا.",
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
                  _load(args.data_dir / "macro_regimes.json"), private,
                  (_load(args.data_dir / "nasdaq_listed.json"), _load(args.data_dir / "symbol_directory.json")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sheet, ensure_ascii=False, indent=1), encoding="utf-8")
    session_date = (facts.get("today") or {}).get("date")
    morning_run = False
    if session_date:
        day_dir = args.morning_dir / session_date
        morning = day_dir / "morning.json"
        day_dir.mkdir(parents=True, exist_ok=True)
        if not morning.exists():  # the morning copy is never rewritten
            morning.write_text(json.dumps(sheet, ensure_ascii=False, indent=1), encoding="utf-8")
            morning_run = True
        else:  # later runs add dated updates beside it
            (day_dir / f"update_{now.strftime('%H%MZ')}.json").write_text(
                json.dumps(sheet, ensure_ascii=False, indent=1), encoding="utf-8")
    # one private message per session (the morning run); updates stay in the dated copies
    if morning_run and private.get("enabled") and any(p.get("available") for p in private["plans"].values()):
        from scripts.telegram_transport import get_chat, send_html_message
        delivered = deliver_private(private_message(private, facts), sources=["alpaca_iex"], env=os.environ,
                                    get_chat=get_chat, send=lambda text, chat: send_html_message(text, chat_id=chat))
        sheet["private_mode"]["delivery"] = delivered
        args.output.write_text(json.dumps(sheet, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.private_output and private.get("enabled") and decide("alpaca_iex", "store_private", os.environ).allowed:
        args.private_output.write_text(json.dumps(private, ensure_ascii=False, default=str), encoding="utf-8")
    # counts and statuses only: no symbol-level private values in the (public) log
    print("Daily plan:", json.dumps({"today": session_date, "last_closed": facts.get("last_closed_session"),
                                      "private": private.get("reason"), "catalysts": len(sheet["catalysts"]),
                                      "readiness": sheet["readiness"]["multi_timeframe"]["private_owner"],
                                      "delivery": sheet["private_mode"]["delivery"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
