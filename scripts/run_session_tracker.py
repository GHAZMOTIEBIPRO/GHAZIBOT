"""Owner-private intraday cycle after the open: opening update, state-change alerts, last hour, post-close.

Slots (XNYS session of the day, early close aware; times New York):
  OPENING    open + 31 min (first 15m bar complete and >= 16 min old) .. open + 60 min
  LASTHOUR   close - 60 min .. close - 40 min
  POSTCLOSE  close + 20 min .. close + 120 min (the accountability scorecard)
Between OPENING and LASTHOUR each run sends only NEW stage events (options_radar.session_tracker),
deduplicated by a keyed hash of symbol/side/stage/date stored on bot-state (no symbol in clear).

Data: completed Alpaca SIP bars >= 16 minutes old (labelled as delayed, never "live"). Levels are the
pre-open map's (prior completed session) and never change during the day.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from options_radar import premarket_map as pm
from options_radar import premarket_report as report
from options_radar import session_tracker as st
from options_radar.telegram_ar import LRM, date_ar, rtl_line, when_ar
from scripts import build_daily_plan as bdp

SYMBOLS = (*bdp.DETAIL_INDEX_FUNDS, *bdp.DETAIL_LEADERS)
SLOT_AR = {"OPENING": "تحديث الافتتاح", "LASTHOUR": "قراءة الساعة الأخيرة", "POSTCLOSE": "محاسبة ما بعد الإغلاق",
           "INTRADAY": "تحديث الجلسة"}


def session_slot(now: datetime, open_at: datetime, close_at: datetime) -> str | None:
    if open_at + timedelta(minutes=31) <= now < open_at + timedelta(minutes=60):
        return "OPENING"
    if close_at - timedelta(minutes=60) <= now < close_at - timedelta(minutes=40):
        return "LASTHOUR"
    if close_at + timedelta(minutes=20) <= now < close_at + timedelta(minutes=120):
        return "POSTCLOSE"
    if open_at + timedelta(minutes=60) <= now < close_at - timedelta(minutes=60):
        return "INTRADAY"
    return None


def event_key(secret: str, day: str, symbol: str, event: dict[str, Any]) -> str:
    raw = f"{day}|{symbol}|{event['side']}|{event['stage']}".encode()
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()[:16]


def _event_line(symbol: str, e: dict[str, Any]) -> str:
    at = datetime.fromisoformat(e["at"])
    return rtl_line(f"<b>{symbol}</b>{LRM} {e['side']} — {st.STAGE_AR[e['stage']]} عند {e['level']:,.2f} "
                    f"(شمعة تنتهي {when_ar(at)})")


def build_messages(slot: str, maps: dict[str, dict], tracked: dict[str, dict], new_events: list[tuple[str, dict]],
                   now: datetime, day: str, closes: dict[str, float]) -> list[str]:
    head = [rtl_line(f"<b>{SLOT_AR[slot]} — {date_ar(day)}</b>"),
            rtl_line(f"أُعدّ {when_ar(now)}؛ شموع مكتملة متأخرة 16 دقيقة على الأقل (ليست لحظية). المستويات ثابتة من خريطة ما قبل الافتتاح."),
            rtl_line("المراحل للانتباه والمتابعة؛ لم يثبت لأي قاعدة اختراق عائد موجب خارج العينة. ليست توصية.")]
    if slot == "INTRADAY":
        if not new_events:
            return []
        return report._pack([_event_line(s, e) for s, e in new_events], "\n".join(head))
    body = []
    for symbol, m in maps.items():
        if m.get("state") in (None, "NO_DATA"):
            body.append(report.row(m))
            continue
        events = (tracked.get(symbol) or {}).get("events") or []
        last = (tracked.get(symbol) or {}).get("last_close")
        stages = "، ".join(f"{e['side']} {st.STAGE_AR[e['stage']]}" for e in events) or "لم يتجاوز أي محفز"
        body.append(rtl_line(f"<b>{symbol}</b>{LRM} آخر إغلاق 5د {last:,.2f} — {stages}" if last else
                             f"<b>{symbol}</b>{LRM} — لا شموع لليوم بعد"))
    if slot == "POSTCLOSE":
        card = st.scorecard(maps, tracked, closes)
        body.append(rtl_line(
            f"<b>المحاسبة:</b> خرائط {card['maps']}، تجاوز محفز {card['triggered']}، تأكيد {card['confirmed']}، "
            f"T1 {card['t1']}، T2 {card['t2']}، T3 {card['t3']}، إبطال {card['invalidated']}، ملتبس {card['ambiguous']}؛ "
            f"اتجاه رموز المراقبة: صحيح {card['watch_direction_right']} / خاطئ {card['watch_direction_wrong']} "
            f"من {card['watch_calls']}. أرقام يوم واحد وليست احتمالًا."))
    return report._pack(body, "\n".join(head))


def main() -> int:
    from options_radar.output_policy import deliver_private
    from scripts.telegram_transport import get_chat, send_html_message

    env = dict(os.environ)
    state_dir = Path(env.get("STATE_DIR", "../state/state/daily_plan"))
    now = datetime.now(timezone.utc)
    facts = bdp.calendar_facts(now)
    if not facts.get("today_is_session"):
        print("session tracker: not a session day")
        return 0
    private = bdp.private_plans(facts, now, env=env, symbols=SYMBOLS)
    if not private.get("enabled"):
        print("session tracker:", private.get("reason"))
        return 0
    plans = private["plans"]
    opening = next((p.get("session_open") for p in plans.values() if p.get("session_open")), None)
    if not opening:
        print("session tracker: no session bars yet")
        return 0
    open_at = datetime.fromisoformat(opening)
    hh, mm = (int(x) for x in facts["today"]["close_new_york"].split(":"))  # XNYS calendar, early closes included
    close_at = open_at.astimezone(bdp.NY).replace(hour=hh, minute=mm, second=0, microsecond=0)
    slot = session_slot(now, open_at, close_at)
    if slot is None:
        print("session tracker: outside every slot")
        return 0
    private["cards"] = bdp.cards_for(private, None, now, "NOT_REQUESTED")
    maps = {s: pm.build_map(private["cards"].get(s) or {}, plans.get(s) or {"symbol": s, "available": False,
                                                                                "reason": "no bars"}) for s in SYMBOLS}
    tracked = {s: st.track(maps[s], (plans.get(s) or {}).get("today_5m") or [], open_at,
                           (plans.get(s) or {}).get("vol_baseline_5m")) for s in SYMBOLS}
    closes = {s: t["last_close"] for s, t in tracked.items() if t.get("last_close")}
    day = facts["today"]["date"]
    day_dir = state_dir / day
    day_dir.mkdir(parents=True, exist_ok=True)
    secret = env.get("TELEGRAM_BOT_TOKEN", "")
    seen_path = day_dir / "session_events.json"
    seen = set(json.loads(seen_path.read_text()).get("sent", [])) if seen_path.exists() else set()
    new_events = [(s, e) for s, t in tracked.items() for e in t.get("events") or []
                  if event_key(secret, day, s, e) not in seen]
    marker_path = day_dir / f"session_{slot}.json"
    if slot != "INTRADAY" and marker_path.exists() and json.loads(marker_path.read_text()).get("status") == "DELIVERED":
        print("session tracker:", slot, "already delivered")
        return 0
    texts = build_messages(slot, maps, tracked, new_events, now, day, closes)
    results = [deliver_private(t, sources=["alpaca_iex"], env=env, get_chat=get_chat,
                               send=lambda text, chat: send_html_message(text, chat_id=chat)) for t in texts]
    if texts and all(r == "DELIVERED" for r in results):
        seen |= {event_key(secret, day, s, e) for s, e in new_events}
        seen_path.write_text(json.dumps({"sent": sorted(seen), "updated_at": now.isoformat()}, indent=1))
    if slot != "INTRADAY":
        status = "DELIVERED" if results and all(r == "DELIVERED" for r in results) else (results[0] if results else "EMPTY")
        marker = {"schema": "ghazi.session_slot_marker.v1", "slot": slot, "status": status, "sent_at": now.isoformat(),
                  "messages": len(texts), "accepted": results.count("DELIVERED")}
        if slot == "POSTCLOSE":
            marker["scorecard"] = st.scorecard(maps, tracked, closes)  # counts only
        marker_path.write_text(json.dumps(marker, indent=1))
    print("session tracker:", slot, json.dumps({"messages": len(texts), "results": results, "new_events": len(new_events)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
