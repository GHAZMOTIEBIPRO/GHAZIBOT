"""Owner-private real-time first-look alerts from the Alpaca IEX minute-bar stream, the whole session.

Coverage (owner, PHASE 4): a regular session is 390 minutes and a hosted GitHub job is capped at 360, so
one job cannot cover it. The session is covered by consecutive segments of one workflow:
  * the orchestrator dispatches iex-stream.yml every ~30 minutes from 09:28 to 15:45 New York;
  * the workflow's concurrency group (cancel-in-progress: false) runs ONE segment at a time and keeps at
    most one pending, so the free plan's single stream connection is never opened twice (no overlap);
  * a segment listens until the close + 1 minute or IEX_STREAM_MAX_MINUTES (345), whichever is first,
    then the pending segment starts by itself;
  * a segment that starts after the open first replays today's IEX minute bars by REST. Up to 60 minutes
    after the open the replay alerts normally (nothing ran before it); later it is a handover and the
    replay is silent (the previous segment handled those buckets), so nothing is repeated;
  * every 60 s a REST backfill of the last 15 minutes fills bars lost in a reconnect (alpaca-py reconnects
    by itself); a bar that arrives twice can never fire twice.
Early closes and DST come from the XNYS calendar (bdp.calendar_facts); after the close a segment exits.
Symbols: SPY, QQQ and the owner's 12 leaders (Basic plan streaming limit: 30). Levels: the pre-open maps
(prior completed session; identical for every segment of the day, map id shown). Volume test: IEX vs an
IEX baseline (never a SIP baseline). Every message says "IEX — partial coverage"; SIP confirmation still
comes from the session tracker. The log prints counts and latency percentiles only.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

from options_radar import iex_live_alerts as live
from options_radar import premarket_map as pm
from options_radar.output_policy import deliver_private
from options_radar.telegram_ar import LRM, rtl_line, when_ar
from scripts import build_daily_plan as bdp

SYMBOLS = (*bdp.DETAIL_INDEX_FUNDS, *bdp.DETAIL_LEADERS)
DATA = "https://data.alpaca.markets"
HANDOVER_AFTER_MIN = 60
BACKFILL_EVERY_S = 60
BACKFILL_WINDOW_MIN = 15


def iex_baseline(symbols: tuple[str, ...], sessions: list[tuple[datetime, datetime]], headers: dict) -> dict:
    out = {}
    for sym in symbols:
        body = requests.get(f"{DATA}/v2/stocks/bars", params={"symbols": sym, "timeframe": "5Min", "feed": "iex",
                                                             "start": sessions[0][0].isoformat(),
                                                             "end": sessions[-1][1].isoformat(), "limit": 10000},
                            headers=headers, timeout=30).json()
        bars = [{"t": datetime.fromisoformat(b["t"].replace("Z", "+00:00")), "v": b["v"]}
                for b in (body.get("bars") or {}).get(sym) or []]
        out[sym] = live.baseline_from_bars(bars, sessions)
        time.sleep(0.4)
    return out


def minute_bars(symbols: tuple[str, ...], start: datetime, end: datetime, headers: dict) -> list[tuple]:
    """Today's IEX minute bars by REST, as (symbol, start, o, h, l, c, v), in time order."""
    out: list[tuple] = []
    token = None
    while True:
        params = {"symbols": ",".join(symbols), "timeframe": "1Min", "feed": "iex", "limit": 10000,
                  "start": start.isoformat(), "end": end.isoformat(), **({"page_token": token} if token else {})}
        body = requests.get(f"{DATA}/v2/stocks/bars", params=params, headers=headers, timeout=30).json()
        for sym, bars in (body.get("bars") or {}).items():
            out.extend((sym, datetime.fromisoformat(b["t"].replace("Z", "+00:00")), b["o"], b["h"], b["l"], b["c"], b["v"])
                       for b in bars)
        token = body.get("next_page_token")
        if not token:
            return sorted(out, key=lambda r: r[1])


def segment_plan(now: datetime, open_at: datetime, close_at: datetime, max_minutes: int) -> dict:
    """What this segment does: exit, or replay (alerting or silent) then listen until stop_at."""
    if now >= close_at + timedelta(minutes=1):
        return {"action": "exit", "reason": "session over"}
    stop_at = min(close_at + timedelta(minutes=1), now + timedelta(minutes=max_minutes))
    late = now > open_at + timedelta(minutes=1)
    handover = now > open_at + timedelta(minutes=HANDOVER_AFTER_MIN)
    return {"action": "listen", "stop_at": stop_at, "replay": late, "silent_replay": handover}


def text_for(alert: dict, map_ids: dict[str, str]) -> str:
    side_ar = "فوق محفز CALL" if alert["side"] == "CALL" else "تحت محفز PUT"
    end = datetime.fromisoformat(alert["bucket_end"])
    late = alert.get("source") != "stream"
    return "\n".join([
        rtl_line(f"<b>رصد أولي لحظي IEX — {alert['symbol']}</b>{LRM}" + (" (استدراك بعد انقطاع)" if late else "")),
        rtl_line(f"إغلاق 5د {alert['close']:,.2f} {side_ar} {alert['trigger']:,.2f} بحجم IEX {alert['rvol_iex']}× المعتاد "
                 f"(شمعة تنتهي {when_ar(end)}، رُصد بعد {alert['latency_s']} ث)."),
        rtl_line(f"المستويات من خريطة ما قبل الافتتاح نفسها (رقم {map_ids.get(alert['symbol'], '—')})؛ لا تُغيَّر أثناء الجلسة."),
        rtl_line("IEX منصة واحدة: تغطية جزئية وليست SIP. التأكيد على الشموع المجمّعة يصل لاحقًا من متتبع الجلسة."),
        rtl_line("تنبيه انتباه لا إشارة دخول: لم يثبت لهذه القاعدة عائد موجب خارج العينة (ديسمبر–يونيو). ليست توصية."),
    ])


def main() -> int:
    from alpaca.data.enums import DataFeed
    from alpaca.data.live import StockDataStream

    from scripts.telegram_transport import get_chat, send_html_message

    env = dict(os.environ)
    now = datetime.now(timezone.utc)
    facts = bdp.calendar_facts(now)
    if not facts.get("today_is_session"):
        print("iex stream: not a session day")
        return 0
    hh, mm = (int(x) for x in facts["today"]["open_new_york"].split(":"))
    ch, cm = (int(x) for x in facts["today"]["close_new_york"].split(":"))
    ny_now = now.astimezone(bdp.NY)
    open_at = ny_now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    close_at = ny_now.replace(hour=ch, minute=cm, second=0, microsecond=0)
    plan = segment_plan(now, open_at, close_at, int(env.get("IEX_STREAM_MAX_MINUTES", "345")))
    if plan["action"] == "exit":
        print("iex stream:", plan["reason"])
        return 0
    private = bdp.private_plans(facts, now, env=env, symbols=SYMBOLS)
    if not private.get("enabled"):
        print("iex stream:", private.get("reason"))
        return 0
    private["cards"] = bdp.cards_for(private, None, now, "NOT_REQUESTED")
    levels, map_ids = {}, {}
    for sym in SYMBOLS:
        m = pm.build_map(private["cards"].get(sym) or {}, private["plans"].get(sym) or {"symbol": sym, "available": False})
        if m.get("state") not in (None, "NO_DATA"):
            levels[sym] = {"call": m["call"]["trigger"], "put": m["put"]["trigger"]}
            map_ids[sym] = m.get("map_id")
    headers = {"APCA-API-KEY-ID": env["ALPACA_API_KEY"].strip(), "APCA-API-SECRET-KEY": env["ALPACA_SECRET_KEY"].strip()}
    prior = [s for s in bdp._sessions(now, 30) if s[1] <= now][-10:]  # completed sessions only (no today)
    state = live.LiveState(open_at=open_at, levels=levels, baseline=iex_baseline(tuple(levels), prior, headers))
    lock = threading.Lock()
    results: list[str] = []

    def deliver(alerts: list[dict]) -> None:
        for alert in alerts:
            decided = datetime.now(timezone.utc)
            out = deliver_private(text_for(alert, map_ids), sources=["alpaca_iex"], env=env, get_chat=get_chat,
                                  send=lambda text, chat: send_html_message(text, chat_id=chat))
            results.append(out)
            if out == "DELIVERED":
                state.send_latencies.append((datetime.now(timezone.utc) - decided).total_seconds())

    def feed_rest(start: datetime, *, silent: bool) -> None:
        try:
            rows = minute_bars(tuple(levels), start, datetime.now(timezone.utc), headers)
        except (requests.RequestException, ValueError) as exc:
            print("iex stream: backfill failed:", type(exc).__name__)
            return
        received = datetime.now(timezone.utc)
        with lock:
            alerts = [a for r in rows for a in state.on_bar(*r, received_at=received, source="rest", silent=silent)]
        deliver(alerts)

    if plan["replay"]:
        feed_rest(open_at, silent=plan["silent_replay"])
    stream = StockDataStream(headers["APCA-API-KEY-ID"], headers["APCA-API-SECRET-KEY"], feed=DataFeed.IEX)

    async def on_bar(bar) -> None:
        with lock:
            alerts = state.on_bar(bar.symbol, bar.timestamp, bar.open, bar.high, bar.low, bar.close, bar.volume,
                                  received_at=datetime.now(timezone.utc))
        deliver(alerts)

    stop = threading.Event()

    def backfill_loop() -> None:
        while not stop.wait(BACKFILL_EVERY_S):
            feed_rest(max(open_at, datetime.now(timezone.utc) - timedelta(minutes=BACKFILL_WINDOW_MIN)), silent=False)

    def finish() -> None:
        stop.set()
        stream.stop()

    stream.subscribe_bars(on_bar, *levels)
    threading.Thread(target=backfill_loop, daemon=True).start()
    threading.Timer(max((plan["stop_at"] - datetime.now(timezone.utc)).total_seconds(), 1), finish).start()
    print(f"iex stream: {len(levels)} symbols until {plan['stop_at'].isoformat()}",
          {"replay": plan["replay"], "silent_replay": plan["silent_replay"]})
    stream.run()
    stop.set()
    print("iex stream done:", state.latency_summary(),
          {"deliveries": results.count("DELIVERED"), "other": len(results) - results.count("DELIVERED")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
