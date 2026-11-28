"""Owner-private real-time first-look alerts from the Alpaca IEX minute-bar stream (one job per session).

Runs inside one GitHub Actions job from the open for up to ~6 hours (the job limit), so alerts follow a
completed 5-minute IEX bucket by seconds instead of the orchestrator's minutes plus SIP's 16-minute delay.
Symbols: SPY, QQQ and the owner's 12 leaders (Basic plan streaming limit is 30 symbols). Levels: the pre-open
maps (SIP history, prior completed session). Volume test: IEX vs IEX baseline. Every message says
"IEX — partial coverage, real time"; SIP confirmation still comes from the session tracker.
At the end the log prints counts and latency P50/P95 only.
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


def text_for(alert: dict) -> str:
    side_ar = "فوق محفز CALL" if alert["side"] == "CALL" else "تحت محفز PUT"
    end = datetime.fromisoformat(alert["bucket_end"])
    return "\n".join([
        rtl_line(f"<b>رصد أولي لحظي IEX — {alert['symbol']}</b>{LRM}"),
        rtl_line(f"إغلاق 5د {alert['close']:,.2f} {side_ar} {alert['trigger']:,.2f} بحجم IEX {alert['rvol_iex']}× المعتاد "
                 f"(شمعة تنتهي {when_ar(end)}، رُصد بعد {alert['latency_s']} ث)."),
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
    private = bdp.private_plans(facts, now, env=env, symbols=SYMBOLS)
    if not private.get("enabled"):
        print("iex stream:", private.get("reason"))
        return 0
    private["cards"] = bdp.cards_for(private, None, now, "NOT_REQUESTED")
    levels = {}
    for sym in SYMBOLS:
        m = pm.build_map(private["cards"].get(sym) or {}, private["plans"].get(sym) or {"symbol": sym, "available": False})
        if m.get("state") not in (None, "NO_DATA"):
            levels[sym] = {"call": m["call"]["trigger"], "put": m["put"]["trigger"]}
    hh, mm = (int(x) for x in facts["today"]["open_new_york"].split(":"))
    ch, cm = (int(x) for x in facts["today"]["close_new_york"].split(":"))
    ny_now = now.astimezone(bdp.NY)
    open_at = ny_now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    close_at = ny_now.replace(hour=ch, minute=cm, second=0, microsecond=0)
    headers = {"APCA-API-KEY-ID": env["ALPACA_API_KEY"].strip(), "APCA-API-SECRET-KEY": env["ALPACA_SECRET_KEY"].strip()}
    prior = [s for s in bdp._sessions(now, 30) if s[1] <= now][-10:]  # completed sessions only (no today)
    state = live.LiveState(open_at=open_at, levels=levels, baseline=iex_baseline(tuple(levels), prior, headers))
    stream = StockDataStream(headers["APCA-API-KEY-ID"], headers["APCA-API-SECRET-KEY"], feed=DataFeed.IEX)
    results: list[str] = []

    async def on_bar(bar) -> None:
        for alert in state.on_bar(bar.symbol, bar.timestamp, bar.open, bar.high, bar.low, bar.close, bar.volume,
                                  received_at=datetime.now(timezone.utc)):
            results.append(deliver_private(text_for(alert), sources=["alpaca_iex"], env=env, get_chat=get_chat,
                                           send=lambda text, chat: send_html_message(text, chat_id=chat)))

    stream.subscribe_bars(on_bar, *levels)
    stop_at = min(close_at - timedelta(minutes=5), now + timedelta(minutes=int(env.get("IEX_STREAM_MAX_MINUTES", "350"))))
    threading.Timer(max((stop_at - datetime.now(timezone.utc)).total_seconds(), 1), stream.stop).start()
    print(f"iex stream: {len(levels)} symbols until {stop_at.isoformat()}")
    stream.run()
    print("iex stream done:", state.latency_summary(), {"deliveries": results.count("DELIVERED"), "other": len(results)
                                                        - results.count("DELIVERED")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
