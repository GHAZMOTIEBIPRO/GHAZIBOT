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
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from options_radar import analysis_card as card
from options_radar import daily_plan as dp
from options_radar import ohlcv_quality as quality
from options_radar import premarket_map as pm
from options_radar import premarket_report as report
from options_radar import state_keys as sk
from options_radar import telegram_market_digest as digest
from options_radar.bar_aggregation import frames_from_5m
from options_radar.bar_providers import COVERAGE, AlpacaBars
from options_radar.focus_universe import FOCUS_STOCKS, SECONDARY_STOCKS
from options_radar.output_policy import decide, deliver_private
from options_radar.telegram_ar import clock_ar, day_month_ar
from options_radar.volume_liquidity import liquidity_context

NY = ZoneInfo("America/New_York")
RIYADH = ZoneInfo("Asia/Riyadh")
# U.S. market only: index funds, the owner-approved focus list (options_radar.focus_universe)
# and the other leading large caps shown in the investor-attention card. About 2 Alpaca
# requests per symbol, spaced by SYMBOL_PAUSE_S so this job alone stays far below the
# provider's per-minute limit while other private jobs share the same account.
INDEX_FUNDS = ("SPY", "QQQ", "IWM", "DIA")
OTHER_LEADERS = ("LLY", "V", "MA", "UNH", "WMT", "BRK.B", "INTC", "CRM", "ADBE", "BA", "DIS", "PFE")
PLAN_SYMBOLS = tuple(dict.fromkeys((*INDEX_FUNDS, *FOCUS_STOCKS, *SECONDARY_STOCKS, *OTHER_LEADERS)))
SYMBOL_PAUSE_S = 0.5
FETCH_BUDGET_S = 6 * 60  # the job has 10 minutes; the rest is analysis, writing and delivery
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
                            intraday: dict[str, list[dict[str, Any]]], now: datetime) -> dict[str, Any]:
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
    latest_day = datetime.fromisoformat(rows[-1]["start"]).astimezone(NY).date()
    last_daily_day = max(bar["t"].astimezone(NY).date() for bar in daily_q["clean"])
    if latest_day != now.astimezone(NY).date() or latest_day <= last_daily_day:
        # Before the next open and after the daily close, the most recent 15m
        # session cannot be compared to the current plan's prior-day levels.
        return {"status": "NO_ACTIVE_INTRADAY_SESSION", "inference_only": True}
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


def today_open(now: datetime) -> datetime | None:
    """Today's XNYS regular open when it is still ahead (pre-open), else None."""
    cal = xcals.get_calendar("XNYS")
    day = now.astimezone(NY).date().isoformat()
    sched = cal.schedule.loc[day:day]
    if sched.empty:
        return None
    opening = pd.Timestamp(sched.iloc[0]["open"]).to_pydatetime()
    return opening if now < opening else None


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
    plan["liquidity_context"] = _private_volume_context(daily_q, minute_q, intraday, now)
    plan["volume_scope"] = meta["volume_scope"]
    # the last completed sessions, for support/resistance and the chart's observed candles (private only)
    plan["recent_daily"] = [{k: r[k] for k in ("date", "open", "high", "low", "close")}
                            for r in _daily_rows(daily["bars"]) if r["date"] <= str(facts["last_closed_session"])][-20:]
    if minute["status"] == "OK" and minute.get("feed") == daily.get("feed") and sessions:
        # intraday tracking inputs (private only): today's regular 5m bars and a time-of-day volume baseline
        today = [s for s in sessions if s[0].astimezone(NY).date() == now.astimezone(NY).date()]
        if today:
            o, c = today[-1]
            plan["today_5m"] = [b for b in minute["bars"] if o <= b["t"] < c]
            plan["session_open"] = o.isoformat()
        prior = [s for s in sessions if not today or s[0] < today[-1][0]][-10:]
        slots: dict[int, list[float]] = {}
        for o, c in prior:
            for b in minute["bars"]:
                if o <= b["t"] < c:
                    slots.setdefault(int((b["t"] - o).total_seconds() // 300), []).append(b["v"])
        plan["vol_baseline_5m"] = {i: sum(v) / len(v) for i, v in slots.items() if v}
    opening = today_open(now)
    if opening is not None and sessions and minute["status"] == "OK" and minute.get("feed") == daily.get("feed"):
        # extended-hours bars after the prior close, completed before the provider's delay boundary
        plan["premarket"] = pm.premarket_reference(minute["bars"], session_open=opening, prior_close_at=sessions[-1][1],
                                                   usable_until=now - timedelta(minutes=16))
    status["quality"] = {"daily": daily_q["status"], "5m": minute_q["status"]}
    return plan, status


def private_plans(facts: dict[str, Any], now: datetime, *, session: Any = None,
                  env: Any = None, symbols: tuple[str, ...] | None = None,
                  pause: Callable[[float], None] = time.sleep,
                  clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    env = os.environ if env is None else env
    provider = AlpacaBars(env, **({"session": session} if session is not None else {}), now=now)
    status = provider.status()
    if status != "READY" or not facts.get("last_closed_session"):
        reason = ("DATA_USE_PERMISSION_REQUIRED" if status == "DENIED_BY_POLICY" else
                  "ACCOUNT_CREDENTIALS_NOT_CONFIGURED" if status == "CREDENTIALS_MISSING" else "NO_CLOSED_SESSION")
        return {"enabled": False, "reason": reason, "plans": {}}
    sessions = _sessions(now, 60)
    closes = session_closes(now)
    plans, statuses, skipped = {}, {}, []
    started = clock()
    for index, symbol in enumerate(symbols or PLAN_SYMBOLS):
        # a slow or hanging provider must not cost the whole plan: stop starting new symbols
        # once the budget is spent, keep what finished, and say which were not fetched
        if clock() - started > FETCH_BUDGET_S:
            skipped.append(symbol)
            continue
        if index:
            pause(SYMBOL_PAUSE_S)
        plans[symbol], statuses[symbol] = plan_from_provider(provider, symbol, facts, sessions, now, closes)
    out = {"enabled": True, "reason": "OWNER_AUTHORIZED_INTERNAL_USE", "plans": plans, "fetch_status": statuses}
    if skipped:
        out["skipped_for_time"] = {"count": len(skipped), "budget_seconds": FETCH_BUDGET_S}
    return out


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
    # name the feed the bars actually came from (SIP history is the default; IEX only on refusal)
    feeds = sorted({f for s in (private.get("fetch_status") or {}).values() if isinstance(s, dict)
                    for f in s.get("feeds") or []})
    feed_label = "/".join(f.upper() for f in feeds) or "unknown feed"
    status = {}
    for frame in FRAMES:
        status[frame] = {"public": "UNAVAILABLE",
                         "private_owner": "AVAILABLE" if frame in available else "UNAVAILABLE",
                         "reason": (f"Alpaca {feed_label} bars: owner's internal use only, not redistributed"
                                    if frame in available
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


MAX_SLOT_ATTEMPTS = 3
MARKER_SCHEMA = "ghazi.premarket_report_marker.v2"
# owner's list for detailed cards (2026-11-28): index funds, then these leaders
DETAIL_INDEX_FUNDS = ("SPY", "QQQ")
DETAIL_LEADERS = ("NVDA", "TSLA", "AMD", "MU", "MSFT", "META", "GOOG", "GOOGL", "AAPL", "AMZN",
                  "AVGO", "BABA")


def maps_for(private: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every planned symbol in PLAN_SYMBOLS order, including those not fetched (a row with the reason)."""
    plans, cards = private.get("plans") or {}, private.get("cards") or {}
    out = {}
    for symbol in PLAN_SYMBOLS:
        if symbol not in plans:
            out[symbol] = {"schema": pm.SCHEMA, "symbol": symbol, "state": "NO_DATA",
                           "reason": "not fetched within the run's time budget"}
            continue
        plan = plans[symbol]
        out[symbol] = pm.build_map(cards.get(symbol) or {}, plan, premarket=plan.get("premarket"))
    return out


def fingerprints(maps: dict[str, dict[str, Any]], secret: bytes | None) -> dict[str, str]:
    """Keyed hash per symbol of what a card says (state, position, triggers, targets).

    Kept in memory per symbol; bot-state (public) only ever gets them as a sealed, padded set
    (options_radar.state_keys.seal, independent GHAZI_STATE_HMAC_KEY, never the Telegram token), so the
    EARLY and FINAL markers cannot be compared to learn which symbol's card changed. No key, none.
    """
    if not secret:
        return {}
    out = {}
    for symbol, m in maps.items():
        core = {k: m.get(k) for k in ("state", "position", "call", "put", "reason")}
        out[symbol] = sk.tag(secret, "map", symbol, json.dumps(core, sort_keys=True, default=str))
    return out


def chart_symbols(maps: dict[str, dict[str, Any]], limit: int = 3) -> list[str]:
    """Default images (owner, 2026-11-28): the index funds, then the `limit` leaders most worth watching.

    Leaders are ranked WATCH first, then by distance to the nearer trigger in ATR. Every other chart
    is available on request (/map SYMBOL). SPX/NDX have no licensed price map yet, so none is drawn.
    """
    funds = [s for s in DETAIL_INDEX_FUNDS if (maps.get(s) or {}).get("state") not in (None, "NO_DATA")]
    leaders = [m for s, m in maps.items() if s not in DETAIL_INDEX_FUNDS and m.get("state") not in (None, "NO_DATA")]
    leaders.sort(key=lambda m: (m["state"] not in ("CALL_WATCH", "PUT_WATCH"), m.get("distance_atr", 99), m["symbol"]))
    return funds + [m["symbol"] for m in leaders[:limit]]


def detail_symbols(maps: dict[str, dict[str, Any]]) -> list[str]:
    """Owner's fixed list (index funds + DETAIL_LEADERS) first, then up to five other WATCH names."""
    fixed = [s for s in (*DETAIL_INDEX_FUNDS, *DETAIL_LEADERS) if (maps.get(s) or {}).get("state") not in (None, "NO_DATA")]
    others = pm.rank_details({s: m for s, m in maps.items() if s not in fixed}, pinned=())
    return fixed + others


def chart_items(maps: dict[str, dict[str, Any]], private: dict[str, Any], symbols: list[str], now: datetime,
                session_date: str) -> tuple[list[list[tuple[bytes, str]]], str]:
    """PNG albums (<= 10 each). Charts are optional: any failure leaves the text untouched."""
    try:
        from options_radar import price_map_chart as chart
    except ImportError:
        return [], "CHARTS_LIBRARY_MISSING"
    photos = []
    for symbol in symbols:
        m = maps[symbol]
        plan = (private.get("plans") or {}).get(symbol) or {}
        try:
            png = chart.render_png(
                m, plan.get("recent_daily"), title_ar=f"{symbol} — الخريطة السعرية قبل الافتتاح",
                footer_ar=f"Alpaca SIP متأخر 16 دقيقة على الأقل — شموع حتى {day_month_ar(str(m.get('data_as_of')))}"
                          f" — أُعدّت {clock_ar(now, NY)} نيويورك")
        except Exception:  # noqa: BLE001, S112 - one bad chart never blocks the report
            continue
        photos.append((png, report.chart_caption(m)))
    albums = [photos[i:i + 10] for i in range(0, len(photos), 10)]
    return albums, "OK" if photos else "NO_CHARTS"


def _outcome(items: dict[str, dict[str, Any]], planned: list[str]) -> str:
    """Over every planned item: one not yet attempted keeps the slot open (SENDING)."""
    statuses = [(items.get(i) or {}).get("status") for i in planned]
    if any(s is None for s in statuses):
        return "PARTIAL" if "DELIVERED" in statuses else "SENDING"
    if statuses and all(s == "DELIVERED" for s in statuses):
        return "DELIVERED"
    if "UNCONFIRMED" in statuses and not any(s not in ("DELIVERED", "UNCONFIRMED") for s in statuses):
        return "UNCONFIRMED"
    return "PARTIAL" if "DELIVERED" in statuses else next((s for s in statuses if s), "NOT_SENT")


def run_report_slot(private: dict[str, Any], facts: dict[str, Any], now: datetime, day_dir: Path, *,
                    env: Any, get_chat: Callable[[str], Any], send: Callable[[str, str], Any],
                    send_album: Callable[[list[tuple[bytes, str]], str], Any] | None = None) -> dict[str, Any] | None:
    """Send the due pre-open report; every message has its own id and its own delivery record.

    Marker per slot: state/daily_plan/<date>/report_<SLOT>.json, rewritten after each message so an
    interrupted run leaves an exact record. Item ids are `<date>:<slot>:<kind>:<n>`; a later run in
    the same window sends only items not yet DELIVERED, never one recorded UNCONFIRMED (the request
    may have reached Telegram), up to MAX_SLOT_ATTEMPTS runs. A window that passed without delivery
    is recorded MISSED and never sent late. FINAL repeats the summary and sends cards and charts
    only for symbols whose keyed fingerprint changed since EARLY.
    """
    session_today = bool(facts.get("today_is_session"))
    done = set()
    for path in day_dir.glob("report_*.json"):
        saved = _load(path) or {}
        if saved.get("status") in ("DELIVERED", "MISSED"):
            done.add(str(saved.get("slot")))
    for name in report.missed_slots(now, session_today, done):
        missed = day_dir / f"report_{name}.json"
        earlier = _load(missed) or {}  # a failed attempt keeps its details
        missed.write_text(json.dumps(
            {"schema": MARKER_SCHEMA, **earlier, "slot": name, "status": "MISSED",
             "last_attempt_status": earlier.get("status"), "recorded_at": now.isoformat(),
             "late": True, "late_minutes": None}, indent=1), encoding="utf-8")
    slot = report.slot_for(now, session_today)
    if slot is None:
        return None
    path = day_dir / f"report_{slot['slot']}.json"
    previous = _load(path) or {}
    if previous.get("status") in ("DELIVERED", "UNCONFIRMED"):
        return previous
    attempt = int(previous.get("attempt") or 0) + 1
    if attempt > MAX_SLOT_ATTEMPTS:
        return previous
    marker = {"schema": MARKER_SCHEMA, **slot, "attempt": attempt, "recorded_at": now.isoformat(),
              "telegram_acceptance_is_not_read_receipt": True, "items": dict(previous.get("items") or {})}
    if not private.get("enabled") or not any(p.get("available") for p in (private.get("plans") or {}).values()):
        marker.update(status="NO_PRIVATE_DATA", reason=private.get("reason"))
        path.write_text(json.dumps(marker, indent=1), encoding="utf-8")
        return marker
    session_date = facts["today"]["date"]
    maps = maps_for(private)
    key = sk.state_key(env)
    prints = fingerprints(maps, key)  # no key: no fingerprints, FINAL sends every card
    scope = f"map|{session_date}"
    details = detail_symbols(maps)
    charted = chart_symbols(maps)
    changed_note = None
    if slot["slot"] == "FINAL":
        sealed = (_load(day_dir / "report_EARLY.json") or {}).get("fingerprints")
        early = sk.unseal(key, scope, sealed) if key and isinstance(sealed, dict) else None
        if early and prints:  # unchanged = the same keyed fingerprint is in EARLY's sealed set
            details = [s for s in details if prints.get(s) not in early]
            charted = [s for s in charted if prints.get(s) not in early]
            changed_note = len(details)
    statuses = private.get("fetch_status") or {}
    texts = report.render(maps, slot=slot, now=now, session_date=session_date, index_funds=INDEX_FUNDS,
                          detail_symbols=details, attempted=len(PLAN_SYMBOLS), changed_since_early=changed_note,
                          fetched=sum(1 for s in statuses.values() if isinstance(s, dict) and s.get("daily") == "OK"))
    albums, charts_status = chart_items(maps, private, charted, now, session_date) if send_album else ([], "NOT_REQUESTED")
    n_text = len(texts)
    outbox: list[tuple[str, Callable[[str], Any]]] = []
    for index, text in enumerate(texts):
        outbox.append((f"{session_date}:{slot['slot']}:text:{index}", lambda chat, t=text: send(t, chat)))
    for index, album in enumerate(albums):
        outbox.append((f"{session_date}:{slot['slot']}:charts:{index}", lambda chat, a=album: send_album(a, chat)))
    marker.update(fingerprints=sk.seal(key, scope, prints.values()) if prints else None, charts=charts_status, planned_items=len(outbox), text_messages=n_text,
                  map_versions=pm.map_id({"ids": sorted(str(m.get("map_id")) for m in maps.values())}))
    planned = [item_id for item_id, _ in outbox]
    for item_id, action in outbox:
        if marker["items"].get(item_id, {}).get("status") in ("DELIVERED", "UNCONFIRMED"):
            continue
        result = deliver_private(item_id, sources=["alpaca_iex"], env=env, get_chat=get_chat,
                                 send=lambda _text, chat, act=action: act(chat))
        marker["items"][item_id] = {"status": result, "at": now.isoformat()}
        marker["status"] = _outcome(marker["items"], planned)
        path.write_text(json.dumps(marker, indent=1), encoding="utf-8")  # one record per message
    marker["status"] = _outcome(marker["items"], planned)
    marker["accepted"] = sum(1 for i in planned if (marker["items"].get(i) or {}).get("status") == "DELIVERED")
    marker["messages"] = len(planned)
    path.write_text(json.dumps(marker, indent=1), encoding="utf-8")
    return marker


def private_message(private: dict[str, Any], facts: dict[str, Any]) -> str:
    """Ranked, compact private digest. Never cuts a Telegram message mid-level."""
    return digest.render(private.get("cards") or {}, facts.get("last_closed_session"), pinned=INDEX_FUNDS)


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
                         "skipped_for_time": (private.get("skipped_for_time") or {}).get("count", 0),
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
    session_date = (facts.get("today") or {}).get("date")
    day_dir = args.morning_dir / session_date if session_date else None
    if day_dir is not None:
        day_dir.mkdir(parents=True, exist_ok=True)
        from scripts.telegram_transport import get_chat, send_html_message, send_media_group
        marker = run_report_slot(private, facts, now, day_dir, env=os.environ, get_chat=get_chat,
                                 send=lambda text, chat: send_html_message(text, chat_id=chat),
                                 send_album=lambda album, chat: send_media_group(album, chat_id=chat))
        if marker is not None:
            sheet["private_mode"]["delivery"] = marker["status"]
            sheet["private_mode"]["report"] = {k: marker.get(k) for k in ("slot", "status", "late", "late_minutes")}
    args.output.write_text(json.dumps(sheet, ensure_ascii=False, indent=1), encoding="utf-8")
    if day_dir is not None:
        # written after any send, so the stored copy carries the real delivery status
        morning = day_dir / "morning.json"
        target = morning if not morning.exists() else day_dir / f"update_{now.strftime('%H%MZ')}.json"
        target.write_text(json.dumps(sheet, ensure_ascii=False, indent=1), encoding="utf-8")
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
