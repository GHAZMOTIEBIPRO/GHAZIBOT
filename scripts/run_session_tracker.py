"""Owner-private intraday cycle after the open: opening update, state-change alerts, last hour, post-close.

Slots (XNYS session of the day, early close aware; times New York):
  OPENING    open + 31 min (first 15m bar complete and >= 16 min old) .. open + 60 min
  LASTHOUR   close - 60 min .. close - 40 min
  POSTCLOSE  close + 20 min .. close + 120 min (the accountability scorecard)
Between OPENING and LASTHOUR each run sends only NEW stage events (options_radar.session_tracker),
deduplicated statelessly: events whose completed bucket ends after the last successful run's data horizon
(options_radar/run_window; nothing about any event is stored).

Data: completed Alpaca SIP bars >= 16 minutes old (labelled as delayed, never "live"). Levels are the
pre-open map's (prior completed session) and never change during the day.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from options_radar import premarket_map as pm
from options_radar import premarket_report as report
from options_radar import run_window as rw
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


STEP = "Track the session (owner-private delivery)"  # the workflow step name read from the run history


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
    # Stateless dedupe (options_radar/run_window): an event is new when its completed bucket ends after the
    # data horizon of this workflow's last successful run today and within this run's horizon.
    # Both edges come from the processing step's start (this run and the previous one), so a boundary
    # bucket is never counted twice or skipped between runs.
    window, prev = rw.previous_success(env, "session-tracker.yml", now, day_start=open_at - timedelta(hours=8),
                                       step=STEP)
    upper = rw.data_horizon(rw.own_step_time(env, STEP, now))
    lower = rw.data_horizon(prev) if window == "OK" else open_at
    if window == "UNKNOWN":  # run history unreadable: no event alerts (fail safe), slot reports still go
        print("session tracker: RUN_HISTORY_UNKNOWN: intraday events skipped")
        new_events = []
    else:
        new_events = [(s, e) for s, t in tracked.items() for e in t.get("events") or []
                      if lower < datetime.fromisoformat(e["at"]) <= upper]
    marker_path = day_dir / f"session_{slot}.json"
    if slot != "INTRADAY" and marker_path.exists() and json.loads(marker_path.read_text()).get("status") == "DELIVERED":
        # The slot report went earlier; this run still covers its event window (an early exit here would
        # count as a processing run and lose the events in its window).
        slot = "INTRADAY"
    texts = build_messages(slot, maps, tracked, new_events, now, day, closes)
    results = rw.send_in_order(texts, lambda text: deliver_private(
        text, sources=["alpaca_iex"], env=env, get_chat=get_chat, send=lambda t, chat: send_html_message(t, chat_id=chat)))
    if slot != "INTRADAY":
        status = ("EMPTY" if not results else "DELIVERED" if all(r == "DELIVERED" for r in results)
                  else next(r for r in results if r != "DELIVERED"))  # a partial delivery is never DELIVERED
        marker = {"schema": "ghazi.session_slot_marker.v1", "slot": slot, "status": status, "sent_at": now.isoformat(),
                  "messages": len(texts), "accepted": results.count("DELIVERED")}
        marker_path.write_text(json.dumps(marker, indent=1))
    # Scheduled slots are reported; intraday runs print a constant line (whether an event fired stays private).
    print("session tracker:", slot, ("statuses " + ",".join(sorted(set(results)))) if slot != "INTRADAY" else "run complete")
    if slot == "INTRADAY" and window == "UNKNOWN":
        return 1  # nothing processed: never let this run become the next run's baseline
    return rw.exit_code(results) if slot == "INTRADAY" else 0


if __name__ == "__main__":
    raise SystemExit(main())
