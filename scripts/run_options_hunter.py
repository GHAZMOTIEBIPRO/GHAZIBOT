"""Owner-private options hunter on the Alpaca indicative chains (research and watch, never execution).

Underlyings: SPXW and NDXP weeklies (0-7 DTE), SPY and QQQ, and the owner's leaders (0-60 DTE).
Per contract: two-sided indicative quote, spread, day volume, prior-session open interest (Trading API),
Vol/OI, IV and greeks when Alpaca supplies them, strike concentration -> the existing
option_explosion score, best per DTE bucket (0DTE, 1DTE, 2-7, 8-30, 31-60).

Delivery: the owner's private chat only, and only when the top set changed since the last message
(keyed hash on bot-state). The public log carries counts and freshness only. Messages say "indicative"
and give the quote time: an indicative quote is not an OPRA quote and not an execution price.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

from options_radar import alpaca_chain as ac
from options_radar.output_policy import decide
from options_radar.telegram_ar import LRM, rtl_line, when_ar

NY = ZoneInfo("America/New_York")
DATA = "https://data.alpaca.markets"
TRADING = ("https://paper-api.alpaca.markets", "https://api.alpaca.markets")
INDEX_WEEKLIES = ("SPXW", "NDXP")
UNDERLYINGS = ("SPY", "QQQ", "NVDA", "TSLA", "AMD", "MU", "MSFT", "META", "GOOGL", "AAPL", "AMZN", "AVGO", "BABA")


def _get(url: str, params: dict[str, Any], headers: dict[str, str]) -> tuple[int, Any]:
    try:
        r = requests.get(url, params=params, headers=headers, timeout=25)
        return r.status_code, (r.json() if r.status_code == 200 else None)
    except (requests.RequestException, ValueError):
        return -1, None


def chain(underlying: str, until: str, headers: dict[str, str]) -> dict[str, Any]:
    snaps, token = {}, None
    for _ in range(15):
        params = {"feed": "indicative", "limit": 1000, "expiration_date_lte": until, **({"page_token": token} if token else {})}
        code, body = _get(f"{DATA}/v1beta1/options/snapshots/{underlying}", params, headers)
        if code != 200 or not isinstance(body, dict):
            break
        snaps.update(body.get("snapshots") or {})
        token = body.get("next_page_token")
        if not token:
            break
    return snaps


def open_interest(underlying: str, until: str, headers: dict[str, str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for base in TRADING:
        token = None
        for _ in range(10):
            params = {"underlying_symbols": underlying, "expiration_date_lte": until, "limit": 10000,
                      **({"page_token": token} if token else {})}
            code, body = _get(f"{base}/v2/options/contracts", params, headers)
            if code != 200 or not isinstance(body, dict):
                break
            for c in body.get("option_contracts") or []:
                out[str(c.get("symbol"))] = {"open_interest": c.get("open_interest"),
                                             "open_interest_date": c.get("open_interest_date")}
            token = body.get("next_page_token")
            if not token:
                break
        if out:
            return out
    return out


def line(r: dict[str, Any]) -> str:
    oi = f"OI {int(r['open_interest']):,} ({r['open_interest_date']})" if r.get("open_interest") else "OI غير متاح"
    greeks = f"دلتا {r['delta']:+.2f}" if r.get("delta") is not None else "بلا Greeks من المزود"
    return rtl_line(f"<b>{r['contract']}</b>{LRM} {r['type']} {r['strike']:g} — عرض/طلب {r['bid']:.2f}/{r['ask']:.2f} "
                    f"(سبريد {r['spread_pct'] * 100:.0f}%)، حجم {int(r['volume']):,}، {oi}، {greeks}، "
                    f"تقييم {r['score']} ({r['label']})")


def main() -> int:
    from options_radar.output_policy import deliver_private
    from scripts.telegram_transport import get_chat, send_html_message

    env = dict(os.environ)
    if not decide("alpaca_iex", "fetch", env).allowed or not env.get("ALPACA_API_KEY"):
        print("options hunter: NOT_AUTHORIZED_OR_NO_KEYS")
        return 0
    headers = {"APCA-API-KEY-ID": env["ALPACA_API_KEY"].strip(), "APCA-API-SECRET-KEY": env["ALPACA_SECRET_KEY"].strip()}
    now = datetime.now(timezone.utc)
    today = now.astimezone(NY).date()
    rows: list[dict[str, Any]] = []
    coverage: dict[str, int] = {}
    for underlying in (*INDEX_WEEKLIES, *UNDERLYINGS):
        days = 7 if underlying in INDEX_WEEKLIES else 60
        until = (today + timedelta(days=days)).isoformat()
        snaps = chain(underlying, until, headers)
        got = ac.rows(snaps, today=today, open_interest=open_interest(underlying, until, headers))
        coverage[underlying] = len(got)
        rows.extend({**r, "underlying": underlying} for r in got)
    ranked = ac.rank(rows)
    fresh = ac.freshness(rows, now)
    print("options hunter:", json.dumps({"two_sided_contracts": coverage, "freshness": fresh,
                                         "ranked_per_bucket": {b: len(v) for b, v in ranked.items()}}))
    top = [r for b in ranked.values() for r in b]
    if not top or env.get("OPTIONS_HUNTER_DRY_RUN") == "true":
        print("options hunter: no delivery (dry run or nothing ranked)",
              json.dumps({"labels": [r["label"] for r in top], "blockers": sorted({x for r in top for x in r["blockers"]}),
                          "unavailable": sorted({x for r in top for x in (r.get("unavailable_inputs") or [])})}))
        return 0
    state = Path(env.get("STATE_DIR", "../state/state/options_hunter"))
    state.mkdir(parents=True, exist_ok=True)
    key = hmac.new(env.get("TELEGRAM_BOT_TOKEN", "").encode(),
                   "|".join(sorted(r["contract"] for r in top)).encode(), hashlib.sha256).hexdigest()[:16]
    seen_file = state / "last_top.json"
    if seen_file.exists() and json.loads(seen_file.read_text()).get("key") == key:
        print("options hunter: top set unchanged; nothing sent")
        return 0
    stale = fresh["age_s"] is None or fresh["age_s"] > 900
    head = [rtl_line(f"<b>صياد العقود — {when_ar(now)}</b>"),
            rtl_line("بيانات Alpaca الإرشادية (indicative) وليست OPRA؛ الصفقات متأخرة 15 دقيقة؛ OI من الجلسة السابقة؛ "
                     "Vol/OI سياق لا دليل فتح مراكز. بحث ومراقبة، لا أمر تنفيذ."),
            rtl_line(f"أحدث عرض: {fresh['newest_quote'] or 'غير متاح'}" + (" — <b>قديم: خارج الجلسة</b>" if stale else ""))]
    blocks = []
    for name, items in ranked.items():
        if items:
            blocks.append(rtl_line(f"<b>{name}</b>"))
            blocks.extend(line(r) for r in items)
    from options_radar.premarket_report import _pack
    texts = _pack(blocks, "\n".join(head))
    results = [deliver_private(t, sources=["alpaca_iex"], env=env, get_chat=get_chat,
                               send=lambda text, chat: send_html_message(text, chat_id=chat)) for t in texts]
    if all(r == "DELIVERED" for r in results):
        seen_file.write_text(json.dumps({"key": key, "sent_at": now.isoformat(), "messages": len(texts)}))
    print("options hunter delivery:", results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
