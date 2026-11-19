"""Owner-private historical replay of the opening-Fibonacci rule: a fixed rule, never tuned here.

The daily shadow scorecard audits one session at a time and refuses a success rate below 30 cases,
so a meaningful sample would take months. This replays the last N completed XNYS sessions with the
same harness (options_radar.opening_fib_replay):
- decisions only on bars available by the 16-minute cutoff;
- the designed notice times;
- a fill at the first bar after the alert, a pessimistic stop-first rule inside one candle;
- 0.02 $/share round-trip cost.

It runs over the scan universe and sends ONE aggregate Arabic report to the owner's private chat.
The sessions are split chronologically into an earlier half and a later (holdout) half, reported
separately; the rule's parameters are not changed by anything here. Nothing is stored, and the log
carries statuses only (no symbols, prices or outcome metrics: Alpaca-derived data is not published).
"""
from __future__ import annotations

import argparse
import os
import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import exchange_calendars as xcals
import pandas as pd

from options_radar import telegram_ar as ar
from options_radar.bar_providers import AlpacaBars
from options_radar.explosion_stage_evaluation import wilson
from options_radar.opening_fib_replay import replay_session
from options_radar.output_policy import decide, deliver_private
from scripts.run_opening_fib_daily import load_symbols, owner_chat
from scripts.run_opening_fib_shadow import COST_PER_SHARE_ROUNDTRIP, _complete_future_bars
from scripts.telegram_transport import send_html_message

DESIGNED_NOTICE_MINUTES = (57, 72)  # replay_session's designed alert checks after the open
DECISIONS = ("WIN", "LOSS", "EXPIRED")
MIN_SAMPLE = 30


def completed_sessions(now: datetime, count: int) -> list[tuple[str, datetime, datetime]]:
    """The last `count` XNYS sessions whose close is at least 16 minutes old (early closes included)."""
    cal = xcals.get_calendar("XNYS")
    end = pd.Timestamp(now.astimezone(timezone.utc).date())
    labels = cal.sessions_in_range(end - pd.Timedelta(days=int(count * 1.6) + 10), end)
    out = []
    for label in labels:
        row = cal.schedule.loc[label]
        opening = pd.Timestamp(row["open"]).to_pydatetime().astimezone(timezone.utc)
        closing = pd.Timestamp(row["close"]).to_pydatetime().astimezone(timezone.utc)
        if closing + timedelta(minutes=16) <= now:
            out.append((str(label.date()), opening, closing))
    return out[-count:]


def replay_sessions(symbols: list[str], sessions: list[tuple[str, datetime, datetime]], provider: Any, *,
                    pause: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Outcome rows (session index, status, net_r); symbols are never kept in the result."""
    rows: list[tuple[int, str, float | None]] = []
    counts: Counter[str] = Counter()
    fetch_failures = 0
    for index, (_, opening, closing) in enumerate(sessions):
        if index:
            pause(0.3)
        report = provider.multi_bars(symbols, "5m", opening, closing + timedelta(minutes=5), batch=70)
        if report.get("status") != "OK" or report.get("failed_batches"):
            fetch_failures += 1
            continue
        bars, feeds = report.get("bars") or {}, report.get("feed") or {}
        notice = opening + timedelta(minutes=min(DESIGNED_NOTICE_MINUTES))
        for symbol in symbols:
            raw = bars.get(symbol)
            if feeds.get(symbol) != "sip" or not raw:
                counts["SOURCE_UNAVAILABLE"] += 1
                continue
            if not _complete_future_bars(raw, notice=notice, close=closing):
                counts["INCOMPLETE_BAR_COVERAGE"] += 1
                continue
            result = replay_session(symbol, raw, session_open=opening, session_close=closing, feed="sip",
                                    notices_minutes=DESIGNED_NOTICE_MINUTES,
                                    cost_per_share_roundtrip=COST_PER_SHARE_ROUNDTRIP)
            status = str(result.get("status") or "UNKNOWN")
            counts[status] += 1
            net = result.get("net_r")
            rows.append((index, status, float(net) if isinstance(net, (int, float)) else None))
    return {"rows": rows, "counts": dict(counts), "fetch_failures": fetch_failures}


def half_summary(rows: list[tuple[int, str, float | None]]) -> dict[str, Any]:
    decided = [(s, r) for _, s, r in rows if s in DECISIONS]
    wins = sum(1 for s, _ in decided if s == "WIN")
    n = len(decided)
    rs = [r for _, r in decided if r is not None]
    interval = wilson(wins, n) if n else None
    return {"decisions": n, "wins": wins, "losses": sum(1 for s, _ in decided if s == "LOSS"),
            "expired": sum(1 for s, _ in decided if s == "EXPIRED"),
            "win_rate": wins / n if n else None, "win_ci95": interval,
            "mean_r": sum(rs) / len(rs) if rs else None, "enough": n >= MIN_SAMPLE}


def summarize(replayed: dict[str, Any], sessions: list[tuple[str, datetime, datetime]]) -> dict[str, Any]:
    split = len(sessions) // 2
    rows = replayed["rows"]
    first = half_summary([r for r in rows if r[0] < split])
    later = half_summary([r for r in rows if r[0] >= split])
    both_positive = (first["enough"] and later["enough"] and (first["mean_r"] or 0) > 0
                     and (later["mean_r"] or 0) > 0)
    return {"sessions": len(sessions), "first": first, "holdout": later,
            "first_range": (sessions[0][0], sessions[split - 1][0]) if split else None,
            "holdout_range": (sessions[split][0], sessions[-1][0]) if sessions[split:] else None,
            "counts": replayed["counts"], "fetch_failures": replayed["fetch_failures"],
            "mean_r_positive_in_both_halves": both_positive}


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.0f}٪"


def _half_line(title: str, rng: tuple[str, str] | None, h: dict[str, Any]) -> list[str]:
    period = f" ({ar.date_ar(rng[0])} – {ar.date_ar(rng[1])})" if rng else ""
    lines = [f"<b>{title}{period}</b>"]
    if not h["decisions"]:
        return [*lines, "• لا حالات صالحة في هذه الفترة."]
    ci = h["win_ci95"]
    ci_text = f"، ومدى الثقة 95٪: {_pct(ci[0])} – {_pct(ci[1])}" if ci else ""
    lines += [f"• حالات افتراضية: {h['decisions']} — وصلت الهدف الثاني {h['wins']} ({_pct(h['win_rate'])}{ci_text})",
              f"• لمست الإلغاء: {h['losses']} · انتهت الجلسة دونهما: {h['expired']}",
              "• متوسط الصافي بوحدات المخاطرة R: " + ("—" if h["mean_r"] is None else f"{h['mean_r']:+.2f}")]
    if not h["enough"]:
        lines.append(f"• العينة أقل من {MIN_SAMPLE}؛ لا نستنتج منها شيئًا.")
    return lines


def render_message(s: dict[str, Any]) -> str:
    c = Counter(s["counts"])
    lines = [f"🧪 <b>اختبار تاريخي لقاعدة فيبوناتشي الافتتاح — آخر {s['sessions']} جلسة</b>",
             "<b>محاكاة على حركة السهم فقط — ليست أداء عقود خيارات، وليست صفقات تم تنفيذها.</b>",
             "القاعدة ثابتة كما هي في الماسح؛ لم تُعدَّل أي معلمة بناءً على هذه النتائج.", ""]
    lines += _half_line("الفترة الأولى", s["first_range"], s["first"]) + [""]
    lines += _half_line("الفترة اللاحقة (للتحقق)", s["holdout_range"], s["holdout"]) + [""]
    lines.append("• متوسط R موجب في الفترتين معًا بعينة كافية: " +
                 ("نعم — وصف تاريخي فقط، لا يضمن نتائج مستقبلية." if s["mean_r_positive_in_both_halves"]
                  else "لا — لا أفضلية مثبتة."))
    lines.append(f"• لم تظهر إشارة: {c['NO_TRADE']} · دخول متأخر: {c['SKIPPED_LATE_FILL']}"
                 f" · لم يتحقق سعر الدخول: {c['UNFILLED']} · مستبعدة لنقص البيانات: "
                 f"{c['INCOMPLETE_BAR_COVERAGE'] + c['SOURCE_UNAVAILABLE']}"
                 + (f" · جلسات تعذر جلبها: {s['fetch_failures']}" if s["fetch_failures"] else ""))
    lines += ["",
              ("<b>طريقة الحساب:</b> قرار على شموع SIP المكتملة المتاحة بعد 16 دقيقة من التأخير، عند أوقات التنبيه "
               "المصممة؛ الدخول من الشمعة التالية؛ إن لمست الشمعة الهدف والإلغاء معًا تُحسب خسارة؛ "
               "تكلفة 0.02 دولار للسهم."),
              "لا تُحفظ الأسعار ولا نتائج الأسهم الفردية في GitHub."]
    return ar.render(lines)


def run(*, now: datetime, universe: Path, sessions: int, dry_run: bool,
        provider_factory: Callable[..., Any] = AlpacaBars, env: dict[str, str] | None = None) -> str:
    env = dict(os.environ) if env is None else env
    if now.tzinfo is None:
        return "HISTORY_INVALID_CLOCK"
    provider = provider_factory(env, now=now)
    if provider.status() != "READY":
        return "HISTORY_PROVIDER_UNAVAILABLE"
    for use in ("compute", "telegram_private"):
        if not decide(provider.rights_source, use, env).allowed:
            return "HISTORY_PRIVATE_RIGHTS_NOT_AUTHORIZED"
    try:
        symbols = load_symbols(universe, maximum=150)
    except (OSError, UnicodeDecodeError):
        return "HISTORY_UNIVERSE_UNAVAILABLE"
    window = completed_sessions(now, max(2, min(sessions, 120)))
    replayed = replay_sessions(symbols, window, provider)
    summary = summarize(replayed, window)
    if not replayed["rows"]:
        return "HISTORY_NO_COMPLETE_SIP"
    if dry_run:
        return "HISTORY_DRY_RUN_COMPUTED"  # never log outcome metrics derived from licensed bars
    if not env.get("TELEGRAM_BOT_TOKEN"):
        return "HISTORY_TELEGRAM_TOKEN_MISSING"
    status = deliver_private(render_message(summary), sources=[provider.rights_source], env=env,
                             get_chat=owner_chat,
                             send=lambda message, chat_id: send_html_message(message, chat_id=chat_id))
    return "HISTORY_" + status


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--universe", type=Path, required=True)
    p.add_argument("--sessions", type=int, default=60)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    status = run(now=datetime.now(timezone.utc), universe=args.universe, sessions=args.sessions,
                 dry_run=args.dry_run)
    print("Opening Fib history status:", status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
