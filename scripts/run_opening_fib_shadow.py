"""Owner-private, post-session shadow scorecard of the opening-Fibonacci alert.

Never a fill audit or options backtest: simulated *stock* paths after a private
Telegram delivery, using only consolidated SIP historical bars. No quote,
per-ticker outcome or market-data derived metrics are persisted or logged.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import exchange_calendars as xcals
import pandas as pd

from options_radar.bar_providers import AlpacaBars
from options_radar.opening_fib_replay import replay_session
from options_radar.output_policy import decide, deliver_private
from scripts.run_opening_fib_daily import load_symbols, owner_chat
from scripts.telegram_transport import send_html_message

SCHEMA = "ghazi.opening_fib.shadow.v1"
BAR_MINUTES = 5
COST_PER_SHARE_ROUNDTRIP = 0.02
STATES = ("WIN", "LOSS", "EXPIRED", "NO_TRADE", "SKIPPED_LATE_FILL",
          "UNFILLED", "INVALID_DUPLICATE_BARS")


def _stamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def read_sent_marker(path: Path, *, now: datetime) -> tuple[str, datetime | None, datetime | None, datetime | None]:
    """Choose only a session with a proven actual private alert timestamp."""
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return "SHADOW_NO_CONFIRMED_ALERT", None, None, None
    if not isinstance(marker, dict):
        return "SHADOW_NO_CONFIRMED_ALERT", None, None, None
    session = marker.get("sent_session")
    delivered_at = _stamp(marker.get("sent_at_utc"))
    if not isinstance(session, str) or delivered_at is None:
        return "SHADOW_NO_TIMESTAMPED_ALERT", None, None, None
    try:
        label = pd.Timestamp(session)
        if str(label.date()) != session:
            return "SHADOW_INVALID_SESSION", None, None, None
        cal = xcals.get_calendar("XNYS")
        if not cal.is_session(label):
            return "SHADOW_INVALID_SESSION", None, None, None
        row = cal.schedule.loc[session]
        opening = pd.Timestamp(row["open"]).to_pydatetime().astimezone(timezone.utc)
        closing = pd.Timestamp(row["close"]).to_pydatetime().astimezone(timezone.utc)
    except (ValueError, KeyError, TypeError, OverflowError):
        return "SHADOW_INVALID_SESSION", None, None, None
    if not (opening + timedelta(minutes=20) < delivered_at < closing):
        return "SHADOW_INVALID_DELIVERY_TIME", None, None, None
    if not (closing + timedelta(minutes=16) <= now <= closing + timedelta(days=4)):
        return "SHADOW_WAIT_FOR_COMPLETED_SESSION", None, None, None
    return session, delivered_at, opening, closing


def _complete_future_bars(raw: list[dict[str, Any]], *, notice: datetime,
                          close: datetime) -> bool:
    """Do not award a target if missing bars could hide an earlier stop.

    A no-trades 5m bar can be legitimately absent for illiquid securities.
    Exclude these symbols rather than presenting optimistic performance.
    """
    times = set()
    for bar in raw:
        stamp = bar.get("t") if isinstance(bar, dict) else None
        if not isinstance(stamp, datetime) or stamp.tzinfo is None:
            return False
        stamp = stamp.astimezone(timezone.utc)
        if stamp in times:
            return False
        times.add(stamp)
    first_start = notice.replace(second=0, microsecond=0)
    if first_start < notice:
        first_start += timedelta(minutes=1)
    m = first_start.minute % BAR_MINUTES
    if m:
        first_start += timedelta(minutes=BAR_MINUTES - m)
    expected = range(0, int((close - first_start).total_seconds() // 300))
    return all(first_start + timedelta(minutes=5 * x) in times for x in expected)


def shadow_summary(symbols: list[str], bars: dict[str, list[dict[str, Any]]],
                   feeds: dict[str, str], *, opening: datetime, closing: datetime,
                   delivered_at: datetime) -> dict[str, Any]:
    notice_minute = math.ceil((delivered_at - opening).total_seconds() / 60)
    notice = opening + timedelta(minutes=notice_minute)
    counts: Counter[str] = Counter()
    eligible = 0
    sampled = 0
    for symbol in symbols:
        if feeds.get(symbol) != "sip" or not bars.get(symbol):
            counts["SOURCE_UNAVAILABLE"] += 1
            continue
        raw = bars[symbol]
        if not _complete_future_bars(raw, notice=notice, close=closing):
            counts["INCOMPLETE_BAR_COVERAGE"] += 1
            continue
        eligible += 1
        result = replay_session(symbol, raw, session_open=opening,
                                session_close=closing, feed="sip",
                                notices_minutes=(notice_minute,),
                                cost_per_share_roundtrip=COST_PER_SHARE_ROUNDTRIP)
        status = str(result.get("status") or "UNKNOWN")
        counts[status] += 1
        if status in ("WIN", "LOSS", "EXPIRED"):
            sampled += 1
    return {"scanned": len(symbols), "complete_sip": eligible, "outcomes": dict(counts),
            "hypothetical_trades": sampled, "notice_delay_minutes": notice_minute}


def render_shadow_message(summary: dict[str, Any], *, session: str) -> str:
    v = Counter(summary["outcomes"])
    decisions = sum(v[k] for k in ("WIN", "LOSS", "EXPIRED"))
    lines = [
        f"<b>غازي رادار | رقابة فيبوناتشي بعد جلسة {session}</b>",
        "<b>محاكاة سهم فقط؛ ليست أداء عقود خيارات، وليست صفقات تم تنفيذها.</b>",
        f"المسح: {summary['scanned']} سهم | تغطية SIP كاملة لآخر الجلسة: {summary['complete_sip']}",
        f"حالات المحاكاة: هدف 2 = {v['WIN']} | وقف = {v['LOSS']} | إغلاق جلسة = {v['EXPIRED']}",
        f"لم تتوفر إشارة = {v['NO_TRADE']} | دخول متأخر = {v['SKIPPED_LATE_FILL']} | لم ينفذ افتراضيًا = {v['UNFILLED']}",
        f"استبعاد نقص الشموع = {v['INCOMPLETE_BAR_COVERAGE']} | مصدر SIP غير متاح = {v['SOURCE_UNAVAILABLE']}",
        f"الحالات الحاسمة أو المنتهية الصالحة للمقارنة: {decisions}.",
        f"أُعيد الحساب من وقت لا يسبق تسليم التنبيه، مع تأخير SIP واستخدام افتتاح لاحق وتكلفة افتراضية 0.02 دولار/سهم.",
    ]
    if decisions < 30:
        lines.append("العينة أقل من 30 صفقة افتراضية؛ لا ننشر نسبة نجاح ولا نستنتج أفضلية.")
    else:
        lines.append("الأرقام أعلاه وصفية، ولا تثبت أفضلية مستقلة أو ربحية خيارات.")
    lines.append("لم تُحفظ الأسعار أو نتائج الأسهم الفردية في GitHub. استمرار الاختبار خارج العينة مطلوب.")
    return "\n".join(lines)


def run(*, now: datetime, sent_marker: Path, state_path: Path, universe: Path,
        dry_run: bool = False, provider_factory=AlpacaBars) -> str:
    if now.tzinfo is None:
        return "SHADOW_INVALID_CLOCK"
    now = now.astimezone(timezone.utc)
    session, delivered_at, opening, closing = read_sent_marker(sent_marker, now=now)
    if session.startswith("SHADOW_"):
        return session
    try:
        written = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        written = {}
    if isinstance(written, dict) and written.get("audited_session") == session:
        return "SHADOW_ALREADY_DELIVERED"

    env = dict(os.environ)
    provider = provider_factory(env, now=now)
    if provider.status() != "READY":
        return "SHADOW_PROVIDER_UNAVAILABLE"
    for use in ("compute", "telegram_private"):
        if not decide(provider.rights_source, use, env).allowed:
            return "SHADOW_PRIVATE_RIGHTS_NOT_AUTHORIZED"
    try:
        symbols = load_symbols(universe, maximum=150)
    except (OSError, UnicodeDecodeError):
        return "SHADOW_UNIVERSE_UNAVAILABLE"
    if not symbols:
        return "SHADOW_EMPTY_UNIVERSE"
    report = provider.multi_bars(symbols, "5m", opening, closing + timedelta(minutes=5), batch=70)
    if report.get("status") != "OK" or report.get("failed_batches"):
        return "SHADOW_FETCH_INCOMPLETE"
    summary = shadow_summary(symbols, report.get("bars") or {}, report.get("feed") or {},
                             opening=opening, closing=closing, delivered_at=delivered_at)
    if summary["complete_sip"] == 0:
        return "SHADOW_NO_COMPLETE_SIP"
    if dry_run:
        # Never log ticker-level or derived licensed outcome metrics.
        return "SHADOW_DRY_RUN_COMPUTED"
    if not env.get("TELEGRAM_BOT_TOKEN"):
        return "SHADOW_TELEGRAM_TOKEN_MISSING"
    text = render_shadow_message(summary, session=session)
    status = deliver_private(text, sources=[provider.rights_source], env=env,
                             get_chat=owner_chat,
                             send=lambda message, chat_id: send_html_message(message, chat_id=chat_id))
    if status != "DELIVERED":
        return "SHADOW_" + status
    state_path.parent.mkdir(parents=True, exist_ok=True)
    # Public bot-state stores only completed session date; no provider-derived facts.
    state_path.write_text(json.dumps({"audited_session": session}, ensure_ascii=False) + "\n",
                          encoding="utf-8")
    return "SHADOW_DELIVERED"


def main() -> int:
    p = argparse.ArgumentParser(description="Private post-market opening Fibonacci shadow scorecard")
    p.add_argument("--sent-marker", type=Path, required=True)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--universe", type=Path, required=True)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    status = run(now=datetime.now(timezone.utc), sent_marker=args.sent_marker,
                 state_path=args.state, universe=args.universe, dry_run=args.dry_run)
    print("Opening Fib post-session status:", status)
    return 0 if status.startswith(("SHADOW_NO_CONFIRMED", "SHADOW_NO_TIMESTAMPED",
                                    "SHADOW_WAIT_", "SHADOW_ALREADY_",
                                    "SHADOW_DRY_RUN_")) or status == "SHADOW_DELIVERED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
