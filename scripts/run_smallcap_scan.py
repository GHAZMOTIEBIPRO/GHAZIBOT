"""Owner-private small-cap early-move scan on Alpaca IEX data; nothing restricted is stored.

Modes (auto = postclose from close + 20 minutes, else scan):
  scan       (regular session 09:45-15:45 New York) snapshots of the listed universe -> stages
             (options_radar.smallcap_scan) -> Telegram for a first detection or a stage upgrade only.
  postclose  forward moves 5/15/30/60 minutes and at the close from each first-detection price.
Universe: NasdaqTrader listed equities and, once built, the SEC registrant list (NYSE, NYSE American).
Storage (owner, PHASE 4): detections are Alpaca-derived, so no record of symbol, stage, price or time
is written anywhere, encrypted or not. bot-state holds only state/smallcaps/<date>.tags.json: keyed tags
(options_radar.state_keys, independent secret GHAZI_STATE_HMAC_KEY) of (symbol, stage, minute after the
open) plus an alert count. The scan and the post-close review recompute the preimages from the listed
universe, and the post-close review refetches the minute bars from Alpaca at run time; the detection price
is the close of the last completed IEX minute bar before the detection (not the snapshot trade price).
Without the key no tags are kept, so no alert is sent (it could not be deduplicated) and the post-close
review is skipped. Halts, dilution and float are NOT checked here and say so.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd
import requests

from options_radar import smallcap_scan as sc
from options_radar import state_keys as sk
from options_radar.output_policy import decide
from options_radar.telegram_ar import LRM, rtl_line, when_ar

NY = ZoneInfo("America/New_York")
DATA = "https://data.alpaca.markets"
ORDER = {s: i for i, s in enumerate(("COMPRESSION", "EARLY_ACTIVITY", "BREAKOUT_WATCH", "CONFIRMED_MOVE", "EXTENDED"))}


TAGS_SCHEMA = "ghazi.smallcap_tags.v1"
MAX_MINUTE = 400  # a regular session is 390 minutes


def load_tags(path: Path) -> dict:
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError):
        return {"schema": TAGS_SCHEMA, "tags": [], "alerts_sent": 0}
    return d if d.get("schema") == TAGS_SCHEMA else {"schema": TAGS_SCHEMA, "tags": [], "alerts_sent": 0}


def save_tags(path: Path, day: str, tags: set[str], alerts_sent: int, now: datetime) -> None:
    """Keyed tags and an operational count only: no symbol, stage, price or time of any detection."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": TAGS_SCHEMA, "day": day, "tags": sorted(tags),
                                "alerts_sent": alerts_sent, "updated_at": now.isoformat()}))


def already_alerted(key: bytes, day: str, symbol: str, stage: str, tags: set[str], upto_minute: int) -> bool:
    """True when this symbol was already alerted today at this stage or a later one."""
    later = [s for s in ORDER if ORDER[s] >= ORDER[stage] and s in sc.ALERT_STAGES]
    cands = [(symbol, s, m) for s in later for m in range(min(upto_minute, MAX_MINUTE) + 1)]
    return bool(sk.recover(key, tags, ("smallcap", day), cands))


def detections_from_tags(key: bytes, day: str, tags: set[str], symbols: list[str]) -> dict[str, dict]:
    """First detection (earliest minute) and the highest stage per symbol, recomputed from the keyed tags."""
    cands = ((sym, st, m) for sym in symbols for st in sc.ALERT_STAGES for m in range(MAX_MINUTE + 1))
    out: dict[str, dict] = {}
    for sym, st, m in sk.recover(key, tags, ("smallcap", day), cands):
        d = out.setdefault(sym, {"stage": st, "minute": m, "top_stage": st})
        if m < d["minute"]:
            d.update(stage=st, minute=m)
        if ORDER[st] > ORDER[d["top_stage"]]:
            d["top_stage"] = st
    return out


def universe(state_data: Path) -> list[str]:
    symbols: set[str] = set()
    nasdaq = state_data / "nasdaq_listed.json"
    if nasdaq.exists():
        d = json.loads(nasdaq.read_text())
        f = d["fields"]
        symbols |= {r[f.index("symbol")] for r in d["rows"] if r[f.index("equity")] == 1 and r[f.index("etf")] == 0}
    sec = state_data / "sec_company_tickers.json"
    if sec.exists():
        symbols |= {r[0] for r in json.loads(sec.read_text())["rows"] if r[3] in ("NYSE", "NYSE American")}
    return sorted(s for s in symbols if s.isalpha() and len(s) <= 5)


def _get(path: str, params: dict, headers: dict) -> dict:
    r = requests.get(DATA + path, params=params, headers=headers, timeout=30)
    return r.json() if r.status_code == 200 else {}


def snapshots(symbols: list[str], headers: dict, pause=time.sleep) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(symbols), 100):
        out.update(_get("/v2/stocks/snapshots", {"symbols": ",".join(symbols[i:i + 100]), "feed": "iex"}, headers))
        pause(0.35)
    return out


def daily_history(symbols: list[str], start: str, end: str, headers: dict, pause=time.sleep) -> dict[str, list]:
    out: dict[str, list] = {}
    for i in range(0, len(symbols), 50):
        token = None
        for _ in range(10):
            body = _get("/v2/stocks/bars", {"symbols": ",".join(symbols[i:i + 50]), "timeframe": "1Day", "feed": "iex",
                                            "start": start, "end": end, "limit": 10000, "adjustment": "split",
                                            **({"page_token": token} if token else {})}, headers)
            for sym, bars in (body.get("bars") or {}).items():
                out.setdefault(sym, []).extend({"o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"]}
                                               for b in bars)
            token = body.get("next_page_token")
            pause(0.35)
            if not token:
                break
    return out


def message(rows: list[dict], now: datetime, coverage: dict) -> list[str]:
    from options_radar.premarket_report import _pack

    head = "\n".join([rtl_line(f"<b>رادار الأسهم الصغيرة — {when_ar(now)}</b>"),
                      rtl_line(f"Alpaca IEX (منصة واحدة، حجم جزئي؛ RVOL مقارن بحجم IEX نفسه). الكون {coverage['universe']}، "
                               f"مؤهل {coverage['eligible']}. التوقفات والتخفيف والأسهم الحرة غير مفحوصة هنا. ليست توصية.")])
    blocks = []
    for r in rows:
        lv = r.get("levels") or {}
        tg = "، ".join(f"T{i + 1} {t:,.2f}" for i, t in enumerate(lv.get("targets") or []))
        blocks.append(rtl_line(f"<b>{r['symbol']}</b>{LRM} {r['stage_ar']} — {r['price']:,.2f} ({r['move_pct']:+.1f}%) "
                               f"RVOL≈{r['rvol_time_adjusted']} — محفز {lv.get('trigger', 0):,.2f}؛ {tg}؛ "
                               f"إبطال {lv.get('invalidation', 0):,.2f}" + (f" — ⚠ {', '.join(r['risk_flags'])}" if r['risk_flags'] else "")))
    if not blocks:
        blocks.append(rtl_line("لا مرشحين جدد بهذه المعايير الآن."))
    return _pack(blocks, head)


def main() -> int:
    from options_radar.output_policy import deliver_private
    from scripts.telegram_transport import get_chat, send_html_message

    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("auto", "scan", "postclose"))
    parser.add_argument("--state-dir", type=Path, default=Path("../state/state/smallcaps"))
    parser.add_argument("--state-data", type=Path, default=Path("../state/runtime/public/data"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    env = dict(os.environ)
    if not decide("alpaca_iex", "fetch", env).allowed or not env.get("ALPACA_API_KEY"):
        print("smallcaps: NOT_AUTHORIZED_OR_NO_KEYS")
        return 0
    headers = {"APCA-API-KEY-ID": env["ALPACA_API_KEY"].strip(), "APCA-API-SECRET-KEY": env["ALPACA_SECRET_KEY"].strip()}
    now = datetime.now(timezone.utc)
    cal = xcals.get_calendar("XNYS")
    day = now.astimezone(NY).date()
    sched = cal.schedule.loc[str(day):str(day)]
    if sched.empty and not args.dry_run:
        print("smallcaps: not a session day")
        return 0
    if sched.empty:  # dry run off-session: use the last session for elapsed time
        sched = cal.schedule.loc[:str(day)].tail(1)
    open_at = pd.Timestamp(sched.iloc[0]["open"]).to_pydatetime()
    close_at = pd.Timestamp(sched.iloc[0]["close"]).to_pydatetime()
    elapsed = min(max((now - open_at) / (close_at - open_at), 0.0), 1.0)
    day_s = open_at.astimezone(NY).date().isoformat()
    key = sk.state_key(env)
    tags_path = args.state_dir / f"{day_s}.tags.json"
    saved = load_tags(tags_path) if saved_day_ok(tags_path, day_s) else {"tags": [], "alerts_sent": 0}
    tags = set(saved.get("tags") or [])
    if args.mode == "auto":
        args.mode = "postclose" if now >= close_at + timedelta(minutes=20) else "scan"
    symbols = universe(args.state_data)
    if args.mode == "postclose":
        return postclose(key, day_s, tags, symbols, open_at, close_at, headers, env, args, now)
    snaps = snapshots(symbols, headers)
    pre = [s for s, v in snaps.items() if sc.PRICE_MIN <= ((v.get("latestTrade") or {}).get("p") or 0) <= sc.PRICE_MAX
           and ((v.get("dailyBar") or {}).get("v") or 0) * ((v.get("latestTrade") or {}).get("p") or 0) >= sc.MIN_IEX_DOLLAR_VOLUME]
    hist = daily_history(pre, (open_at - timedelta(days=120)).date().isoformat(),
                         (open_at - timedelta(days=1)).date().isoformat(), headers)
    rows = [sc.evaluate(s, snaps[s], hist.get(s) or [], elapsed) for s in pre]
    eligible = [r for r in rows if r.get("eligible")]
    stages = {k: sum(1 for r in eligible if r.get("stage") == k) for k in ORDER}
    coverage = {"universe": len(symbols), "snapshots": len(snaps), "prefiltered": len(pre), "eligible": len(eligible)}
    print("smallcaps scan:", json.dumps({"coverage": coverage, "stages": stages, "elapsed": round(elapsed, 3)}))
    minute = int((now - open_at).total_seconds() // 60)
    candidates = [r for r in sorted(eligible, key=lambda x: -(x.get("score") or 0)) if r.get("stage") in sc.ALERT_STAGES]
    if key is None:
        print("smallcaps: STATE_KEY_MISSING (GHAZI_STATE_HMAC_KEY): alerts disabled, nothing stored;",
              "candidates", len(candidates))
        return 0
    new = [r for r in candidates if not already_alerted(key, day_s, r["symbol"], r["stage"], tags, minute)][:8]
    if args.dry_run:
        print("smallcaps dry run: new detections", len(new))
        return 0
    if not new:
        return 0
    results = [deliver_private(t, sources=["alpaca_iex"], env=env, get_chat=get_chat,
                               send=lambda text, chat: send_html_message(text, chat_id=chat))
               for t in message(new, now, coverage)]
    print("smallcaps delivery:", results)
    if any(r in ("DELIVERED", "UNCONFIRMED") for r in results):  # never resend what may have arrived
        tags |= {sk.tag(key, "smallcap", day_s, r["symbol"], r["stage"], minute) for r in new}
        save_tags(tags_path, day_s, tags, int(saved.get("alerts_sent") or 0) + len(new), now)
    return 0


def saved_day_ok(path: Path, day: str) -> bool:
    return path.exists() and load_tags(path).get("day") == day


def postclose(key: bytes | None, day: str, tags: set[str], symbols: list[str], open_at: datetime,
              close_at: datetime, headers: dict, env: dict, args, now) -> int:
    from options_radar.output_policy import deliver_private
    from scripts.telegram_transport import get_chat, send_html_message

    done = args.state_dir / f"{day}.postclose.json"
    if done.exists():
        print("smallcaps postclose: already done today")
        return 0
    if key is None:
        print("smallcaps postclose: STATE_KEY_MISSING (GHAZI_STATE_HMAC_KEY): skipped")
        return 0
    record = detections_from_tags(key, day, tags, symbols)
    if not record:
        print("smallcaps postclose: no detections recorded")
        return 0
    results = {}
    for sym, det in record.items():
        body = _get("/v2/stocks/bars", {"symbols": sym, "timeframe": "1Min", "feed": "iex", "limit": 10000,
                                        "start": open_at.isoformat(), "end": close_at.isoformat()}, headers)
        bars = (body.get("bars") or {}).get(sym) or []
        by_min = {int((datetime.fromisoformat(b["t"].replace("Z", "+00:00")) - open_at).total_seconds() // 60): b["c"]
                  for b in bars}
        before = [m for m in by_min if m < det["minute"]]
        if not before:
            continue  # no completed bar before the detection: no reference price
        det = {**det, "price": by_min[max(before)]}
        results[sym] = {**det, **sc.forward_moves(det["price"], det["minute"], by_min, bars[-1]["c"] if bars else None)}
    lines = [rtl_line("<b>محاسبة الأسهم الصغيرة — من سعر أول رصد</b> (IEX؛ المرجع إغلاق آخر شمعة دقيقة مكتملة قبل الرصد)")]
    for sym, r in results.items():
        lines.append(rtl_line(f"<b>{sym}</b>{LRM} {sc.STAGE_AR[r['stage']]} عند {r['price']:,.2f}: "
                              + "، ".join(f"{k} {v:+.1f}%" if v is not None else f"{k} —" for k, v in r.items()
                                          if k in ("5m", "15m", "30m", "60m", "close"))))
    if not args.dry_run:
        from options_radar.premarket_report import _pack

        for text in _pack(lines[1:], lines[0]):
            deliver_private(text, sources=["alpaca_iex"], env=env, get_chat=get_chat,
                            send=lambda t, chat: send_html_message(t, chat_id=chat))
    counts = {"detections": len(results), "at": now.isoformat()}  # operational count; outcomes stay in Telegram
    print("smallcaps postclose:", json.dumps(counts))
    if not args.dry_run:
        done.parent.mkdir(parents=True, exist_ok=True)
        done.write_text(json.dumps(counts))  # counts only: once per session day
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
