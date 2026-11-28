"""Owner-private options hunter on the Alpaca indicative chains (research and watch, never execution).

Underlyings: SPXW and NDXP weeklies (0-7 DTE), SPY and QQQ, the owner's leaders (GOOG and GOOGL as two
classes) and batch 2 (IWM and the secondary list), 0-60 DTE.
Per contract: two-sided indicative quote, spread, day volume, prior-session open interest (Trading API),
Vol/OI, IV and greeks when Alpaca supplies them, strike concentration -> the existing option_explosion
score, best per DTE bucket, and one class (EARLY_WATCH / UNUSUAL_ACTIVITY / CONFIRMED_BY_AVAILABLE_DATA /
EXTENDED / REJECTED, options_radar.alpaca_chain.classify) with its reasons.

Delivery: the owner's private chat as scheduled digests (DIGESTS below) of the contracts currently in
UNUSUAL_ACTIVITY or CONFIRMED_BY_AVAILABLE_DATA; nothing about any alert is stored (no dedupe state).
The public log carries coverage counts only.
Messages say "indicative": not an OPRA quote, not an execution price; buyer/seller intent is unknown.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

import requests

from options_radar import alpaca_chain as ac
from options_radar import black76 as b76
from options_radar import parity_reference as pr
from options_radar import run_window as rw
from options_radar.output_policy import decide
from options_radar.telegram_ar import LRM, rtl_line, when_ar

NY = ZoneInfo("America/New_York")
DATA = "https://data.alpaca.markets"
TRADING = ("https://paper-api.alpaca.markets", "https://api.alpaca.markets")
INDEX_WEEKLIES = ("SPXW", "NDXP")
CORE = ("SPY", "QQQ", "NVDA", "TSLA", "AMD", "MU", "MSFT", "META", "GOOG", "GOOGL", "AAPL", "AMZN", "AVGO", "BABA")
# Batch 2 (owner, PHASE 4: expand in batches within quota): the most liquid remaining ETF and the existing
# secondary list. GOOG and GOOGL are separate share classes with separate chains, never merged.
BATCH_2 = ("IWM", "NFLX", "PLTR", "JPM", "COST", "ORCL", "QCOM", "XOM")
UNDERLYINGS = (*CORE, *BATCH_2)
ALERT_CLASSES = ("UNUSUAL_ACTIVITY", "CONFIRMED_BY_AVAILABLE_DATA")


def _get(url: str, params: dict[str, Any], headers: dict[str, str]) -> tuple[int, Any]:
    try:
        r = requests.get(url, params=params, headers=headers, timeout=25)
        return r.status_code, (r.json() if r.status_code == 200 else None)
    except (requests.RequestException, ValueError):
        return -1, None


def chain(underlying: str, until: str, headers: dict[str, str]) -> tuple[dict[str, Any], int]:
    snaps, token, pages = {}, None, 0
    for _ in range(15):
        params = {"feed": "indicative", "limit": 1000, "expiration_date_lte": until, **({"page_token": token} if token else {})}
        code, body = _get(f"{DATA}/v1beta1/options/snapshots/{underlying}", params, headers)
        if code != 200 or not isinstance(body, dict):
            break
        pages += 1
        snaps.update(body.get("snapshots") or {})
        token = body.get("next_page_token")
        if not token:
            break
    return snaps, pages


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


def underlying_changes(headers: dict[str, str]) -> dict[str, float]:
    """Day change % of the equity underlyings from IEX snapshots (index weeklies: none, never substituted)."""
    code, body = _get(f"{DATA}/v2/stocks/snapshots", {"symbols": ",".join(UNDERLYINGS), "feed": "iex"}, headers)
    out = {}
    for sym, v in (body or {}).items() if code == 200 else []:
        price, prev = (v.get("latestTrade") or {}).get("p"), (v.get("prevDailyBar") or {}).get("c")
        if price and prev:
            out[sym] = (price / prev - 1) * 100
    return out


def model_greeks(rows: list[dict[str, Any]], snaps_by: dict[str, dict], now: datetime) -> dict[str, str]:
    """Black-76 Greeks on the parity forward for SPXW/NDXP rows the provider left without Greeks, in place.

    Settlement: weeklies are PM-settled at the 16:00 New York close of expiry day, so time to expiry runs
    to that instant. Rate 0 (0-7 DTE: discounting moves a weekly premium by well under the indicative
    spread; stated, not hidden). One forward per root/expiry, only when the parity gates pass (status OK).
    Returns root:expiry -> forward status (log-safe: statuses only, no value).
    """
    from datetime import date as _date

    statuses: dict[str, str] = {}
    for root in INDEX_WEEKLIES:
        snaps = snaps_by.get(root) or {}
        for expiry in sorted({r["expiry"] for r in rows if r["root"] == root}):
            exp_close = datetime.combine(_date.fromisoformat(expiry), datetime.min.time(), NY).replace(hour=16)
            years = (exp_close - now).total_seconds() / (365 * 86400)
            if years <= 0:
                continue
            fwd = pr.implied_forward(snaps, root=root, expiry=_date.fromisoformat(expiry), years_to_expiry=years)
            statuses[f"{root}:{expiry}"] = fwd.get("status")
            if fwd.get("status") != "OK":
                continue
            for r in rows:
                if r["root"] == root and r["expiry"] == expiry and r.get("delta") is None:
                    g = b76.greeks(premium=r["mid"], forward=fwd["forward"], strike=r["strike"], years=years,
                                   rate=0.0, call=r["type"] == "CALL")
                    if g["status"] == "OK":
                        r.update(iv=g["iv"], delta=g["delta"], gamma=g["gamma"], vega=g["vega"], theta=g["theta"],
                                 greeks_source=b76.SOURCE, forward_basis="IMPLIED_FORWARD_NOT_CASH_INDEX")
    return statuses


def hunt(env: dict[str, str], now: datetime) -> dict[str, Any]:
    headers = {"APCA-API-KEY-ID": env["ALPACA_API_KEY"].strip(), "APCA-API-SECRET-KEY": env["ALPACA_SECRET_KEY"].strip()}
    now_ny = now.astimezone(NY)
    # after 16:00 New York today's contracts have settled: DTE counts from the next calendar day
    today = now_ny.date() + timedelta(days=1 if now_ny.hour >= 16 else 0)
    in_session = now_ny.weekday() < 5 and (9, 30) <= (now_ny.hour, now_ny.minute) < (16, 0)
    rows: list[dict[str, Any]] = []
    snaps_by: dict[str, dict] = {}
    pages: dict[str, int] = {}
    rejects: dict[str, int] = {}
    for underlying in (*INDEX_WEEKLIES, *UNDERLYINGS):
        until = (today + timedelta(days=7 if underlying in INDEX_WEEKLIES else 60)).isoformat()
        snaps, pages[underlying] = chain(underlying, until, headers)
        snaps_by[underlying] = snaps
        got = ac.rows(snaps, today=today, open_interest=open_interest(underlying, until, headers), rejects=rejects)
        rows.extend({**r, "underlying": underlying} for r in got)
    index_forwards = model_greeks(rows, snaps_by, now)
    cover = ac.coverage(snaps_by, rows, rejects, pages)
    cover["index_forwards"] = index_forwards
    changes = underlying_changes(headers)
    medians: dict[tuple, float] = {}
    for key in {(r["root"], ac.bucket(r["dte"]), r["type"]) for r in rows}:
        vols = [r["volume"] for r in rows if (r["root"], ac.bucket(r["dte"]), r["type"]) == key and r["volume"] > 0]
        medians[key] = median(vols) if vols else 0.0
    ranked = ac.rank(rows)
    for items in ranked.values():
        for r in items:
            try:
                age = (now - datetime.fromisoformat(str(r["quote_time"]).replace("Z", "+00:00"))).total_seconds()
            except ValueError:
                age = None
            r["class"], r["class_reasons"] = ac.classify(
                r, bucket_median_volume=medians.get((r["root"], ac.bucket(r["dte"]), r["type"]), 0.0),
                underlying_change_pct=changes.get(r["underlying"]), quote_age_s=age, in_session=in_session)
    return {"ranked": ranked, "coverage": cover, "freshness": ac.freshness(rows, now), "in_session": in_session}


def line(r: dict[str, Any]) -> str:
    oi = f"OI {int(r['open_interest']):,} ({r['open_interest_date']})" if r.get("open_interest") else "OI غير متاح"
    src = {"provider_indicative": "من المزود (إرشادية)",
           "model_black76_forward": "نموذج Black-76 على السعر الآجل الضمني (ليس المؤشر النقدي)"}
    greeks = (f"دلتا {r['delta']:+.2f}، IV {r['iv'] * 100:.0f}% {src.get(r.get('greeks_source'), '')}"
              if r.get("delta") is not None and r.get("iv") else "Greeks غير متاحة")
    return rtl_line(f"<b>{r['contract']}</b>{LRM} {ac.CLASS_AR[r['class']]} — عرض/طلب {r['bid']:.2f}/{r['ask']:.2f} "
                    f"(سبريد {r['spread_pct'] * 100:.0f}%)، حجم {int(r['volume']):,}، {oi}، {greeks}؛ "
                    f"السبب: {'؛ '.join(r['class_reasons'])}")


def render(result: dict[str, Any], now: datetime, only: tuple[str, ...] | None = None) -> list[str]:
    from options_radar.premarket_report import _pack

    fresh, cover = result["freshness"], result["coverage"]
    stale = fresh["age_s"] is None or fresh["age_s"] > 900
    head = [rtl_line(f"<b>صياد العقود — {when_ar(now)}</b>"),
            rtl_line("بيانات Alpaca الإرشادية (indicative) وليست OPRA ولا أسعار تنفيذ؛ OI من الجلسة السابقة؛ "
                     "النشاط مرصود ونية الشراء/البيع غير معروفة. بحث ومراقبة، لا أمر تنفيذ."),
            rtl_line(f"المؤهل بعد الاستبعاد (سبريد ≤25% وغير منتهٍ): {cover.get('eligible', 0):,} عقدًا؛ "
                     "العدد حجم مسح لا دليل سيولة."),
            rtl_line(f"التغطية: {cover['unique_two_sided']:,} عقدًا بعرض ثنائي من {cover['contracts_seen']:,} "
                     f"({len(cover['roots'])} جذرًا، {cover['expiries']} استحقاقًا). أحدث عرض: {fresh['newest_quote'] or 'غير متاح'}"
                     + (" — <b>قديم: خارج الجلسة</b>" if stale else ""))]
    blocks = []
    for name, items in result["ranked"].items():
        chosen = [r for r in items if not only or r["class"] in only]
        if chosen:
            blocks.append(rtl_line(f"<b>{name}</b>"))
            blocks.extend(line(r) for r in chosen)
    if not blocks:
        blocks.append(rtl_line("لا عقود مؤهلة بنشاط جوهري الآن."))
    return _pack(blocks, "\n".join(head))


# Scheduled digests (audit, RELEASE GATE): no dedupe state is stored anywhere, so options alerts are a
# digest at fixed New York times, always sent (also when nothing qualifies, so neither the message nor
# the run reveals whether anything did). Each window sends once (run history, options_radar/run_window).
# /options answers on demand at any time.
DIGESTS = ((10, 15), (11, 30), (13, 0), (14, 30), (15, 30))
DIGEST_WINDOW_MIN = 25


def digest_window(now: datetime) -> datetime | None:
    ny = now.astimezone(NY)
    for h, m in DIGESTS:
        start = ny.replace(hour=h, minute=m, second=0, microsecond=0)
        if start <= ny < start + timedelta(minutes=DIGEST_WINDOW_MIN):
            return start
    return None


def main() -> int:
    from options_radar.output_policy import deliver_private
    from scripts.telegram_transport import get_chat, send_html_message

    env = dict(os.environ)
    if not decide("alpaca_iex", "fetch", env).allowed or not env.get("ALPACA_API_KEY"):
        print("options hunter: NOT_AUTHORIZED_OR_NO_KEYS")
        return 0
    now = datetime.now(timezone.utc)
    dry = env.get("OPTIONS_HUNTER_DRY_RUN") == "true"
    start = digest_window(now)
    if start is None and not dry:
        print("options hunter: outside the digest windows")
        return 0
    if not dry:
        window, prev = rw.previous_success(env, "options-hunter.yml", now, day_start=start - timedelta(hours=8))
        if window == "UNKNOWN":
            print("options hunter: RUN_HISTORY_UNKNOWN: digest skipped (fail safe)")
            return 1  # not a sent digest: the next run in this window must still send it
        if window == "OK" and prev >= start:
            print("options hunter: digest already sent for this window")
            return 0
    result = hunt(env, now)
    # Public log: coverage and freshness only; classes describe the chain (indicative, Alpaca): Telegram only.
    print("options hunter:", json.dumps({"coverage": result["coverage"], "freshness": result["freshness"]}))
    if dry:
        print("options hunter: run complete (dry run)")
        return 0
    statuses = rw.send_in_order(render(result, now, only=ALERT_CLASSES), lambda text: deliver_private(
        text, sources=["alpaca_iex", "alpaca_indicative_options"], env=env, get_chat=get_chat,
        send=lambda t, chat: send_html_message(t, chat_id=chat)))
    print("options hunter: digest statuses", ",".join(sorted(set(statuses))))  # always sent: says nothing about the chain
    return rw.exit_code(statuses)


if __name__ == "__main__":
    raise SystemExit(main())
