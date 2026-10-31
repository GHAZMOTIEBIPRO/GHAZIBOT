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

from options_radar import analysis_card as card
from options_radar import daily_plan as dp
from options_radar import ohlcv_quality as quality
from options_radar import telegram_market_digest as digest
from options_radar.volume_liquidity import liquidity_context
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


def session_closes(now: datetime, days: int = 760) -> dict[str, datetime]:
    """XNYS session date -> its close (early closes included)."""
    cal = xcals.get_calendar("XNYS")
    sched = cal.schedule.loc[str((now - timedelta(days=days)).date()):str(now.date())]
    return {label.date().isoformat(): pd.Timestamp(r["close"]).to_pydatetime() for label, r in sched.iterrows()}


def _alpaca_rows(clean: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"t": b["t"], "o": b["open"], "h": b["high"], "l": b["low"], "c": b["close"], "v": b["volume"] or 0.0}
            for b in clean]


def checked(result: dict[str, Any], interval: str, as_of: datetime, need: int,
            closes: dict[str, datetime] | None = None) -> dict[str, Any]:
    """Quality report for one fetched series; downstream uses only its clean completed rows."""
    return quality.check_bars(result.get("bars") if result.get("status") == "OK" else None, interval=interval,
                              as_of=as_of, fetch_status=result.get("status", "UNAVAILABLE"), feed=result.get("feed"),
                              adjustment="split", need=need, session_close=(closes or {}).get)



def _private_volume_context(daily_q: dict[str, Any], minute_q: dict[str, Any],
                            intraday: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Use only complete, gap-free 15m candles from the same validated feed.

    Existing volume_liquidity handles RVOL, VWAP and prior-session breakouts.
    No order book, options tape or institutional executions are available.
    """
    if daily_q.get("status") != "OK" or minute_q.get("status") != "OK":
        return {"status": "QUALITY_GATE_BLOCKED", "inference_only": True}
    rows = [r for r in (intraday.get("15m") or [])
            if r.get("minutes") == 15 and r.get("bars_5m") == 3 and not r.get("partial")]
    if not rows or not daily_q.get("clean"):
        return {"status": "INSUFFICIENT_BARS", "inference_only": True}
    daily = pd.DataFrame([{"Date": b["t"].astimezone(NY).date().isoformat(),
                           "Open": b["open"], "High": b["high"], "Low": b["low"],
                           "Close": b["close"], "Volume": b["volume"] or 0}
                          for b in daily_q["clean"]])
    daily.index = pd.DatetimeIndex(pd.to_datetime(daily.pop("Date"))).tz_localize(NY)
    m15 = pd.DataFrame([{"Start": datetime.fromisoformat(b["start"]).astimezone(NY),
                         "Open": b["open"], "High": b["high"], "Low": b["low"],
                         "Close": b["close"], "Volume": b["volume"]}
                        for b in rows])
    m15.index = pd.DatetimeIndex(m15.pop("Start"))
    context = liquidity_context(daily, m15)
    context["inference_only"] = True
    context["bars_15m_used"] = len(rows)
    return context


def plan_from_provider(provider: Any, symbol: str, facts: dict[str, Any], sessions: list[tuple[datetime, datetime]],
                       now: datetime, closes: dict[str, datetime] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """One symbol: ~2 years of daily bars (a real weekly frame) and 30 sessions of 5-minute bars.

    Both series pass options_radar.ohlcv_quality first: bad rows are dropped with a code,
    forming bars never enter a frame, and the report travels with the plan.
    """
    closes = closes if closes is not None else session_closes(now)
    raw_daily = provider.bars(symbol, "1d", now - timedelta(days=740), now)
    intraday_start = sessions[-30][0] if len(sessions) >= 30 else (sessions[0][0] if sessions else now)
    raw_minute = provider.bars(symbol, "5m", intraday_start, now)
    daily_q = checked(raw_daily, "1d", now, dp.REQUIREMENTS["daily"]["trend_bars"], closes)
    minute_q = checked(raw_minute, "5m", now - timedelta(minutes=16), 1)
    daily = {**raw_daily, "bars": _alpaca_rows(daily_q["clean"])}
    minute = {**raw_minute, "bars": _alpaca_rows(minute_q["clean"])}
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
    plan["quality_checks"] = {"daily": quality.summary(daily_q), "5m": quality.summary(minute_q)}
    plan["liquidity_context"] = _private_volume_context(daily_q, minute_q, intraday)
    plan["volume_scope"] = meta["volume_scope"]
    status["quality"] = {"daily": daily_q["status"], "5m": minute_q["status"]}
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
    closes = session_closes(now)
    plans, statuses = {}, {}
    for symbol in symbols or PLAN_SYMBOLS:
        plans[symbol], statuses[symbol] = plan_from_provider(provider, symbol, facts, sessions, now, closes)
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


def symbol_news(watch: Any, symbol: str, now: datetime, days: int = 3) -> list[dict[str, Any]]:
    """Official events for one symbol from the catalyst list (dated, linked)."""
    cutoff = (now - timedelta(days=days)).date().isoformat()
    return [e for e in (watch or {}).get("events") or []
            if isinstance(e, dict) and e.get("symbol") == symbol and str(e.get("date") or "") >= cutoff
            and e.get("kind") != "TRIAL_REGISTRY_UPDATE"]


def options_status(data_dir: Path | None) -> str:
    """The options section's state; its failure never changes a stock reading."""
    sources = _load(data_dir / "free_options_sources.json") if data_dir else None
    tradier = str(((sources or {}).get("tradier") or {}).get("status") or "")
    return "OK" if tradier == "OK" else (tradier or "NO_OPTIONS_SOURCE")


def cards_for(private: dict[str, Any], watch: Any, now: datetime, opt_status: str) -> dict[str, Any]:
    return {sym: card.build_card(plan, news=symbol_news(watch, sym, now), options_status=opt_status)
            for sym, plan in (private.get("plans") or {}).items()}


def private_message(private: dict[str, Any], facts: dict[str, Any]) -> str:
    """Ranked, compact private digest. Never cuts a Telegram message mid-level."""
    return digest.render(private.get("cards") or {}, facts.get("last_closed_session"))


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
    watch = _load(args.data_dir / "catalyst_watchlist.json")
    private["cards"] = cards_for(private, watch, now, options_status(args.data_dir))
    sheet = build(now, watch, _load(args.data_dir / "public_macro.json"),
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
