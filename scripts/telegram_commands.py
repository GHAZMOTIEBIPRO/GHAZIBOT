"""Owner-only Telegram commands, answered by a short GitHub job (no always-on server, no LLM).

Two modes:
- `peek`  (inside the market orchestrator, every ~5 minutes): getUpdates WITHOUT an offset, which
  reads but does not consume. Prints only "PENDING <n>" for messages from the owner's private chat.
  Standard library only.
- `serve` (telegram-commands.yml): getUpdates from the stored offset, answers at most MAX_COMMANDS
  owner commands, then stores the next offset on bot-state (an integer, nothing else).

Commands (private chat with TELEGRAM_OWNER_CHAT_ID only; everything else is ignored):
  /map SYM     the pre-open price map image + caption for one symbol
  /stock SYM   the detailed card (levels, CALL/PUT, targets, invalidation) for one symbol
  /levels SYM  alias of /stock
  /market      the summary rows of SPY, QQQ and the owner's leaders
  /status      today's report delivery status (statuses only)
  /help        the list
Answers reuse options_radar.premarket_map / premarket_report / price_map_chart, the same engines
as the scheduled report. Delivery goes through output_policy.deliver_private. Latency is the
orchestrator pass (~5 minutes) plus the job start: on request, not instant.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

MAX_COMMANDS = 5
COMMANDS = ("map", "stock", "levels", "market", "status", "confirm", "options", "smallcaps", "news", "help")
SYMBOL = re.compile(r"^[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z])?$")
HELP_AR = ("الأوامر المتاحة (للمالك فقط):\n/map رمز — الخريطة السعرية\n/stock رمز — البطاقة التفصيلية\n"
           "/levels رمز — المستويات\n/market — ملخص المؤشرات والقياديين\n/status — حالة تقارير اليوم\n"
           "/options — أفضل العقود المؤهلة مع سبب الترشيح والرفض\n/smallcaps — رصد الأسهم الصغيرة اليوم\n"
           "/news — آخر إفصاحات SEC الرسمية للرموز المتابعة\n"
           "/confirm EARLY أو FINAL — تأكيد وصول رسائل سُجلت «غير مؤكدة» (لا إعادة إرسال تلقائية)\n"
           "الرد خلال دقائق (تشغيل مجدول كل ~5 دقائق)، والأسعار من شموع مكتملة متأخرة 16 دقيقة على الأقل.")


def parse(text: Any) -> tuple[str, str | None] | None:
    """'/map nvda' -> ('map', 'NVDA'); None when it is not a known command."""
    if not isinstance(text, str) or not text.startswith("/"):
        return None
    parts = text.strip().split()
    name = parts[0][1:].split("@", 1)[0].lower()
    if name not in COMMANDS:
        return ("help", None)
    arg = parts[1].upper() if len(parts) > 1 else None
    if name in ("map", "stock", "levels") and (not arg or not SYMBOL.fullmatch(arg)):
        return ("help", None)
    if name == "confirm" and arg not in ("EARLY", "FINAL"):
        return ("help", None)
    return (name, arg)


def owner_commands(updates: list[dict[str, Any]], owner_chat: str) -> list[tuple[int, str, str | None]]:
    """(update_id, command, arg) for text messages from the owner's private chat only."""
    out = []
    for update in updates or []:
        message = update.get("message") if isinstance(update, dict) else None
        if not isinstance(message, dict):
            continue
        chat = message.get("chat") or {}
        if str(chat.get("id")) != str(owner_chat) or chat.get("type") != "private":
            continue
        parsed = parse(message.get("text"))
        if parsed:
            out.append((int(update.get("update_id") or 0), *parsed))
    return out


def _get_updates(token: str, offset: int | None = None) -> list[dict[str, Any]]:
    params = {"timeout": "0", "limit": "50", "allowed_updates": json.dumps(["message"])}
    if offset is not None:
        params["offset"] = str(offset)
    url = f"https://api.telegram.org/bot{token}/getUpdates?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("result") or [] if payload.get("ok") else []


def peek(env: dict[str, str]) -> int:
    token, owner = (env.get("TELEGRAM_BOT_TOKEN") or "").strip(), (env.get("TELEGRAM_OWNER_CHAT_ID") or "").strip()
    if not token or not owner:
        print("PENDING 0 (not configured)")
        return 0
    try:
        pending = owner_commands(_get_updates(token), owner)
    except (OSError, ValueError):
        print("PENDING 0 (telegram unreachable)")
        return 0
    print(f"PENDING {len(pending)}")
    return 0


def _symbol_map(symbol: str, now, env) -> tuple[dict[str, Any], dict[str, Any]]:
    from scripts import build_daily_plan as bdp

    facts = bdp.calendar_facts(now)
    private = bdp.private_plans(facts, now, env=env, symbols=(symbol,))
    if not private.get("enabled"):
        return {"symbol": symbol, "state": "NO_DATA", "reason": private.get("reason")}, {}
    private["cards"] = bdp.cards_for(private, None, now, "NOT_REQUESTED")
    plan = private["plans"].get(symbol) or {"symbol": symbol, "available": False, "reason": "no bars"}
    return bdp.pm.build_map(private["cards"].get(symbol) or {}, plan, premarket=plan.get("premarket")), plan


def answer(command: str, arg: str | None, now, env, state_dir: Path) -> dict[str, Any]:
    """Build the reply: {'text': ...} or {'photo': (png, caption)}."""
    from options_radar import premarket_report as report
    from options_radar.telegram_ar import rtl_line

    if command == "help":
        return {"text": "\n".join(rtl_line(x) for x in HELP_AR.split("\n"))}
    if command == "status":
        from scripts.build_daily_plan import NY
        day = now.astimezone(NY).date().isoformat()
        plans_dir = state_dir.parent / "daily_plan" / day  # markers written by daily-plan.yml
        lines = [f"حالة تقارير {day}:"]
        for slot in ("EARLY", "FINAL"):
            path = plans_dir / f"report_{slot}.json"
            marker = json.loads(path.read_text()) if path.exists() else {}
            pending = [k for k, v in (marker.get("items") or {}).items() if v.get("status") == "UNCONFIRMED"]
            if pending:
                lines.append(f"{slot}: {len(pending)} رسالة غير مؤكدة — راجع المحادثة ثم أرسل /confirm {slot}")
            lines.append(f"{slot}: {marker.get('status', 'لا سجل')}" + (" (متأخر)" if marker.get("late") else ""))
        return {"text": "\n".join(rtl_line(x) for x in lines)}
    if command == "confirm":
        from scripts.build_daily_plan import NY

        day = now.astimezone(NY).date().isoformat()
        path = state_dir.parent / "daily_plan" / day / f"report_{arg}.json"
        marker = json.loads(path.read_text()) if path.exists() else {}
        changed = 0
        for item in (marker.get("items") or {}).values():
            if item.get("status") == "UNCONFIRMED":
                item.update(status="DELIVERED", confirmed_by_owner_at=now.isoformat())
                changed += 1
        if changed:
            marker["status"] = "DELIVERED" if all(v.get("status") == "DELIVERED" for v in marker["items"].values()) \
                else marker.get("status")
            path.write_text(json.dumps(marker, indent=1), encoding="utf-8")
        return {"text": rtl_line(f"{arg}: أُكّد وصول {changed} رسالة بتأكيدك.") if changed
                else rtl_line(f"{arg}: لا رسائل غير مؤكدة اليوم.")}
    if command == "options":
        from scripts import run_options_hunter as hunter

        texts = hunter.render(hunter.hunt(env, now), now)
        return {"text": texts[0]}
    if command == "smallcaps":
        from options_radar import smallcap_scan as sc
        from options_radar import state_keys as sk
        from scripts import run_smallcap_scan as small
        from scripts.build_daily_plan import NY

        day = now.astimezone(NY).date().isoformat()
        key = sk.state_key(env)
        if key is None:
            return {"text": rtl_line("سجل الأسهم الصغيرة معطّل: أضف السر المستقل GHAZI_STATE_HMAC_KEY.")}
        tags = small.load_tags(state_dir.parent / "smallcaps" / f"{day}.tags.json", key, day)
        if tags is None:
            return {"text": rtl_line("تغيّر مفتاح الحالة اليوم: سجل اليوم غير مقروء، والتنبيهات متوقفة حتى الجلسة التالية.")}
        found = small.detections_from_tags(key, day, tags, small.universe(state_dir.parents[1] / "runtime/public/data"))
        if not found:
            return {"text": rtl_line(f"لا رصد مرسل للأسهم الصغيرة في {day} (المسح يعمل في الجلسة كل ~15 دقيقة).")}
        lines = [rtl_line(f"<b>رصد الأسهم الصغيرة — {day}</b> (Alpaca IEX، أول رصد؛ الأسعار في رسائل التنبيه)")]
        for sym, det in sorted(found.items(), key=lambda kv: kv[1]["minute"]):
            lines.append(rtl_line(f"<b>{sym}</b> {sc.STAGE_AR[det['stage']]} بعد {det['minute']} دقيقة من الافتتاح"
                                  + (f"؛ أعلى مرحلة {sc.STAGE_AR[det['top_stage']]}" if det["top_stage"] != det["stage"] else "")))
        return {"text": "\n".join(lines)[:3900]}
    if command == "news":
        from options_radar import sec_current_feed as scf
        from scripts.build_daily_plan import DETAIL_INDEX_FUNDS, DETAIL_LEADERS

        if "@" not in (env.get("SEC_USER_AGENT") or ""):
            return {"text": rtl_line("مصدر SEC الرسمي غير مفعّل: أضف السر SEC_USER_AGENT (اسم وبريد حقيقي).")}
        watch = {*DETAIL_INDEX_FUNDS, *DETAIL_LEADERS}
        events = [e for e in scf.fetch(env) if e["symbol"] in watch][:10]
        if not events:
            return {"text": rtl_line("لا إفصاحات SEC جديدة للرموز المتابعة في آخر 100 قيد لكل نوع.")}
        return {"text": "\n".join(rtl_line(f"<b>{e['symbol']}</b> {e['form']} — {'، '.join(e['items_ar']) or e['form_ar']} "
                                             f"(نُشر {e['published'] or 'غير معروف'}) {e['url'] or ''}") for e in events)}
    if command == "market":
        from scripts import build_daily_plan as bdp
        facts = bdp.calendar_facts(now)
        symbols = (*bdp.DETAIL_INDEX_FUNDS, *bdp.DETAIL_LEADERS)
        private = bdp.private_plans(facts, now, env=env, symbols=symbols)
        private["cards"] = bdp.cards_for(private, None, now, "NOT_REQUESTED")
        maps = {s: m for s, m in bdp.maps_for(private).items() if s in symbols}
        return {"text": "\n".join([rtl_line("<b>ملخص عند الطلب</b> — شموع مكتملة متأخرة 16 دقيقة على الأقل"),
                                   *(report.row(m) for m in maps.values())])[:3900]}
    m, plan = _symbol_map(str(arg), now, env)
    if m.get("state") == "NO_DATA":
        return {"text": rtl_line(f"{arg}: لا بيانات — {m.get('reason')}")}
    if command == "map":
        from options_radar import price_map_chart as chart
        from options_radar.telegram_ar import clock_ar, day_month_ar
        from scripts.build_daily_plan import NY
        png = chart.render_png(m, plan.get("recent_daily"), title_ar=f"{arg} — الخريطة السعرية عند الطلب",
                               footer_ar=f"Alpaca SIP متأخر 16 دقيقة على الأقل — شموع حتى "
                                         f"{day_month_ar(str(m.get('data_as_of')))} — {clock_ar(now, NY)} نيويورك")
        return {"photo": (png, report.chart_caption(m))}
    return {"text": report.card(m)}


def serve(env: dict[str, str], state_dir: Path) -> int:
    from datetime import datetime, timezone

    from options_radar.output_policy import deliver_private
    from scripts.telegram_transport import get_chat, send_html_message, send_media_group

    token, owner = (env.get("TELEGRAM_BOT_TOKEN") or "").strip(), (env.get("TELEGRAM_OWNER_CHAT_ID") or "").strip()
    offset_file = state_dir / "telegram_commands_offset.json"
    stored = json.loads(offset_file.read_text()) if offset_file.exists() else {}
    offset = stored.get("next_offset")
    updates = _get_updates(token, offset)
    if not updates:
        print("commands: none")
        return 0
    next_offset = max(int(u.get("update_id") or 0) for u in updates) + 1
    now = datetime.now(timezone.utc)
    results = []
    for update_id, command, arg in owner_commands(updates, owner)[:MAX_COMMANDS]:
        try:
            reply = answer(command, arg, now, env, state_dir)
        except Exception as exc:  # noqa: BLE001 - one failing command never blocks the others
            reply = {"text": f"تعذر تنفيذ /{command}: {type(exc).__name__}"}
        if "photo" in reply:
            def send(_t, chat, r=reply):
                return send_media_group([r["photo"]], chat_id=chat)
        else:
            def send(_t, chat, r=reply):
                return send_html_message(r["text"], chat_id=chat)
        status = deliver_private(f"cmd:{update_id}", sources=["alpaca_iex"], env=env, get_chat=get_chat, send=send)
        results.append({"update_id": update_id, "command": command, "status": status})
    # consumed even when not owner commands: strangers' messages are never answered or re-read
    offset_file.parent.mkdir(parents=True, exist_ok=True)
    offset_file.write_text(json.dumps({"next_offset": next_offset, "updated_at": now.isoformat(),
                                       "last_results": results}, indent=1), encoding="utf-8")
    print("commands:", json.dumps(results))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("peek", "serve"))
    parser.add_argument("--state-dir", type=Path, default=Path("state/telegram"))
    args = parser.parse_args()
    env = dict(os.environ)
    return peek(env) if args.mode == "peek" else serve(env, args.state_dir)


if __name__ == "__main__":
    sys.exit(main())
