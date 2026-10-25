"""Owner-private market scan: universe -> batched data -> liquidity -> momentum -> setup conditions.

No single endpoint is required. Stages, each reported with its own status:
1. Universe: the account's active, tradable U.S. equities (Alpaca Trading API
   assets) -> FULL_MARKET. If that call fails, a declared LIMITED_LIST
   (index ETFs, the site's watch lists and official-catalyst symbols).
2. Daily history (batched multi-symbol bars, consolidated tape when allowed):
   20-session average dollar volume, last close, prior-day high; symbols
   with too little history, a stale last bar, low price or low liquidity are
   excluded with a reason.
3. Today (IEX snapshots, labelled IEX): change vs the prior close and trade
   freshness, used only to pick a shortlist. If snapshots are unavailable
   the shortlist falls back to liquidity order and says so.
4. Shortlist (5-minute bars, one feed per symbol for today and history):
   same-time relative volume (cumulative volume to the last completed bar vs
   the median at the same elapsed time over prior sessions), change, prior-
   day high, and data-quality checks (duplicates, pre-market excluded, bars
   seen vs session minutes elapsed, last-bar age).
5. Setup conditions: explicit booleans; no probability, no order, no target.

Official catalysts (public catalyst_watchlist.json) are context only. The
result goes to the owner's personal Telegram chat only
(output_policy.deliver_private). The log and the status carry stage
statuses and fetch success rates only: no symbols, prices or rankings.
Nothing is cached across runs (Alpaca data stays inside the run).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import exchange_calendars as xcals
import pandas as pd

from options_radar.bar_providers import AlpacaBars
from options_radar.output_policy import deliver_private

PRIOR_SESSIONS = 10
SHORTLIST = 30
MIN_PRICE = 1.0
MIN_AVG_DOLLAR_VOLUME = 2_000_000
MIN_DAILY_BARS = 15
LIMITED_LIST = ("SPY", "QQQ", "IWM", "DIA", "NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "TSLA", "AVGO", "AMD",
                "MU", "ORCL", "BAC", "SOUN", "RGTI", "IONQ", "RKLB", "ASTS", "PLTR", "SOFI", "RGC", "BNAI")


def sessions(now: datetime, days: int = 25) -> list[tuple[datetime, datetime]]:
    cal = xcals.get_calendar("XNYS")
    sched = cal.schedule.loc[str((now - timedelta(days=days)).date()):str(now.date())]
    return [(pd.Timestamp(r["open"]).to_pydatetime(), pd.Timestamp(r["close"]).to_pydatetime())
            for _, r in sched.iterrows() if pd.Timestamp(r["open"]).to_pydatetime() <= now]


def universe(provider: AlpacaBars, catalysts: Any) -> dict[str, Any]:
    assets = provider.assets()
    if assets["status"] == "OK" and assets["symbols"]:
        return {"mode": "FULL_MARKET", "symbols": assets["symbols"], "excluded": assets["excluded"], "status": "OK"}
    extra = [e.get("symbol") for e in (catalysts or {}).get("watchlist") or [] if isinstance(e, dict)]
    symbols = list(dict.fromkeys([*LIMITED_LIST, *[s for s in extra if isinstance(s, str)]]))
    return {"mode": "LIMITED_LIST", "symbols": symbols, "excluded": {}, "status": assets["status"]}


def _dedupe(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    by_time = {r["t"]: r for r in rows}
    return [by_time[t] for t in sorted(by_time)], len(rows) - len(by_time)


def daily_screen(data: dict[str, Any], symbols: list[str], last_closed: datetime) -> tuple[dict[str, Any], dict[str, int]]:
    liquid, excluded = {}, {}

    def drop(reason: str) -> None:
        excluded[reason] = excluded.get(reason, 0) + 1

    for sym in symbols:
        rows, _ = _dedupe(data["bars"].get(sym) or [])
        if not rows:
            drop("NO_DAILY_BARS")
            continue
        if len(rows) < MIN_DAILY_BARS:
            drop("SHORT_HISTORY")
            continue
        if rows[-1]["t"].date() < last_closed.date():
            drop("STALE_LAST_BAR")
            continue
        recent = rows[-20:]
        avg_dollar = statistics.fmean(r["c"] * r["v"] for r in recent)
        if rows[-1]["c"] < MIN_PRICE:
            drop("PRICE_BELOW_1")
            continue
        if avg_dollar < MIN_AVG_DOLLAR_VOLUME:
            drop("LOW_LIQUIDITY")
            continue
        liquid[sym] = {"avg_dollar_volume": avg_dollar, "prior_close": rows[-1]["c"], "prior_high": rows[-1]["h"],
                       "feed": data["feed"].get(sym)}
    return liquid, excluded


def measure(bars: list[dict[str, Any]], sess: list[tuple[datetime, datetime]], cutoff: datetime) -> dict[str, Any]:
    """Momentum facts from completed 5-minute bars of today's session and prior sessions (one feed)."""
    if len(sess) < 2:
        return {"status": "NO_SESSION"}
    today_open, today_close = sess[-1]
    if not today_open <= cutoff:
        return {"status": "SESSION_NOT_STARTED"}
    rows, duplicates = _dedupe(bars)
    done = [b for b in rows if b["t"] + timedelta(minutes=5) <= cutoff]
    regular = [b for b in done if any(o <= b["t"] < c for o, c in sess)]
    today = [b for b in regular if today_open <= b["t"] < today_close]
    if not today:
        return {"status": "NO_COMPLETED_BARS_TODAY"}
    elapsed = today[-1]["t"] + timedelta(minutes=5) - today_open
    prior_volumes, prior_day = [], None
    for open_, close in sess[-1 - PRIOR_SESSIONS:-1]:
        day = [b for b in regular if open_ <= b["t"] < close]
        if day:
            prior_volumes.append(sum(b["v"] for b in day if b["t"] < open_ + elapsed))
            prior_day = day
    if not prior_day:
        return {"status": "NO_PRIOR_SESSION"}
    prior_close, prior_high = prior_day[-1]["c"], max(b["h"] for b in prior_day)
    last = today[-1]["c"]
    median = statistics.median(prior_volumes) if len(prior_volumes) >= 5 else None
    rvol = round(sum(b["v"] for b in today) / median, 2) if median else None
    last_end = today[-1]["t"] + timedelta(minutes=5)
    return {"status": "OK", "last_bar_end": last_end.isoformat(),
            "change_pct": round((last / prior_close - 1) * 100, 2), "rvol_same_time": rvol,
            "rvol_basis": (f"median of {len(prior_volumes)} prior sessions at the same elapsed time, same feed"
                           if median else "INSUFFICIENT (fewer than 5 prior sessions)"),
            "above_prior_high": last > prior_high, "prior_high": prior_high, "last": last,
            "quality": {"duplicates_removed": duplicates, "outside_session_excluded": len(done) - len(regular),
                        "bars_today": len(today), "five_minute_slots_elapsed": int(elapsed.total_seconds() // 300),
                        "last_bar_age_min": round((cutoff - last_end).total_seconds() / 60 + 16, 1),
                        "note": "a missing 5-minute bar means no qualifying trade (Alpaca bar rules)"}}


def setup_conditions(m: dict[str, Any]) -> dict[str, bool]:
    return {"above_prior_day_high": bool(m.get("above_prior_high")),
            "same_time_rvol_at_least_2": (m.get("rvol_same_time") or 0) >= 2,
            "change_at_least_5pct": (m.get("change_pct") or 0) >= 5}


def run(now: datetime, env: Mapping[str, str], catalysts: Any, *, session: Any = None,
        send_private: Callable[[str], str] | None = None) -> dict[str, Any]:
    status: dict[str, Any] = {"schema": "ghazi.private_scan_status.v2", "checked_at": now.isoformat(),
                              "public_output": "STATUS_ONLY"}
    provider = AlpacaBars(env, now=now, **({"session": session} if session is not None else {}))
    ready = provider.status()
    if ready != "READY":
        return {**status, "status": ready}
    sess = sessions(now)
    if not sess or not sess[-1][0] <= now <= sess[-1][1] + timedelta(minutes=20):
        return {**status, "status": "OUTSIDE_SESSION"}
    uni = universe(provider, catalysts)
    status["universe"] = {"mode": uni["mode"], "status": uni["status"]}
    history = provider.multi_bars(uni["symbols"], "1d", now - timedelta(days=45), sess[-2][1] + timedelta(minutes=1))
    status["daily_batches"] = {"batches": history["batches"], "failed": history["failed_batches"]}
    if history["status"] != "OK":
        return {**status, "status": "DAILY_" + history["status"]}
    liquid, excluded = daily_screen(history, uni["symbols"], sess[-2][0])
    snaps = provider.snapshots(list(liquid))
    status["snapshots"] = snaps["status"]
    if snaps["status"] == "OK":
        movers = sorted((s for s in liquid if s in snaps["snapshots"]),
                        key=lambda s: snaps["snapshots"][s]["price"] / liquid[s]["prior_close"], reverse=True)
        pick_basis = "change vs prior close (IEX last trade)"
    else:
        movers = sorted(liquid, key=lambda s: liquid[s]["avg_dollar_volume"], reverse=True)
        pick_basis = "liquidity only (snapshots unavailable)"
    shortlist = movers[:SHORTLIST]
    minute = provider.multi_bars(shortlist, "5m", sess[-1 - PRIOR_SESSIONS][0], now, batch=10)
    official = {e.get("symbol"): e for e in (catalysts or {}).get("watchlist") or [] if isinstance(e, dict)}
    rows, failed = [], 0
    for sym in shortlist:
        m = measure(minute["bars"].get(sym) or [], sess, now - timedelta(minutes=16))
        if m["status"] != "OK":
            failed += 1
            continue
        rows.append({"symbol": sym, "feed": minute["feed"].get(sym), "liquidity": liquid[sym], "momentum": m,
                     "setup": setup_conditions(m), "official_catalyst": (official.get(sym) or {}).get("latest_date")})
    coverage = {"mode": uni["mode"], "universe": len(uni["symbols"]), "with_daily_bars": len(history["bars"]),
                "liquid": len(liquid), "excluded": excluded, "shortlist": len(shortlist), "measured": len(rows),
                "pick_basis": pick_basis, "calls": provider.calls}
    status["fetch_success"] = {"daily_symbols_pct": round(100 * len(history["bars"]) / max(1, len(uni["symbols"])), 1),
                               "intraday_measured_pct": round(100 * len(rows) / max(1, len(shortlist)), 1)}
    if not rows:
        return {**status, "status": "NO_MEASURABLE_CANDIDATES"}
    rows.sort(key=lambda r: (sum(r["setup"].values()), r["momentum"].get("rvol_same_time") or 0), reverse=True)
    text = message(rows, coverage)
    delivery = send_private(text) if send_private else "NOT_ATTEMPTED"
    return {**status, "status": "MEASURED", "delivery": delivery, "_private": {"rows": rows, "coverage": coverage,
                                                                               "message": text}}


def message(rows: list[dict[str, Any]], coverage: dict[str, Any]) -> str:
    excl = "، ".join(f"{k} {v}" for k, v in sorted(coverage["excluded"].items())) or "لا شيء"
    scope = "مسح السوق كامل" if coverage["mode"] == "FULL_MARKET" else "قائمة محدودة (تعذر جلب قائمة السوق)"
    lines = ["<b>فحص السوق الخاص (Alpaca)</b>",
             f"{scope}: {coverage['universe']} رمز · بتاريخ يومي {coverage['with_daily_bars']} · سيولة كافية "
             f"{coverage['liquid']} · مختصرة {coverage['shortlist']} · مقاسة {coverage['measured']}",
             f"الاستبعاد: {excl} · اختيار القائمة المختصرة: {coverage['pick_basis']}",
             "شموع 5 دقائق مكتملة، أحدثها أقدم من 16 دقيقة · استخدام شخصي؛ لا يُعاد نشره."]
    for r in rows[:10]:
        m, s = r["momentum"], r["setup"]
        met = [k for k, v in s.items() if v]
        vol = "كل البورصات" if r["feed"] == "sip" else "IEX فقط"
        lines.append(f"<b>{r['symbol']}</b> · حجم {vol}" + (f" · محفز رسمي {r['official_catalyst']}"
                                                            if r.get("official_catalyst") else ""))
        lines.append(f"  تغير {m['change_pct']}% · RVOL بنفس الوقت {m['rvol_same_time'] or 'غير كافٍ'}"
                     f" · فوق قمة أمس {m['prior_high']}: {'نعم' if m['above_prior_high'] else 'لا'}"
                     f" · آخر شمعة {m['last_bar_end'][11:16]} UTC")
        lines.append("  شروط الإعداد المتحققة: " + ("، ".join(met) if met else "لا شيء"))
    lines.append("الشروط وصف لا احتمال نجاح ولا أمر تداول.")
    return "\n".join(lines)[:3900]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalysts", type=Path)
    parser.add_argument("--status-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        catalysts = json.loads(args.catalysts.read_text(encoding="utf-8")) if args.catalysts else None
    except (OSError, ValueError):
        catalysts = None
    from scripts.telegram_transport import get_chat, send_html_message

    def send_private(text: str) -> str:
        return deliver_private(text, sources=["alpaca_iex"], env=os.environ, get_chat=get_chat,
                               send=lambda body, chat: send_html_message(body, chat_id=chat))

    result = run(datetime.now(timezone.utc), os.environ, catalysts, send_private=send_private)
    result.pop("_private", None)  # private rows never leave the process
    args.status_output.parent.mkdir(parents=True, exist_ok=True)
    args.status_output.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Private scan:", json.dumps({k: result.get(k) for k in ("status", "delivery", "universe", "snapshots",
                                                                   "fetch_success")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
