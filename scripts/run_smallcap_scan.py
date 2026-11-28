"""Owner-private small-cap early-move scan on Alpaca IEX data; nothing about any detection is stored.

scan (regular session 09:45-15:45 New York): snapshots of the listed universe -> stages
(options_radar.smallcap_scan) -> Telegram for a first detection or a stage upgrade only.
Universe: NasdaqTrader listed equities and, once built, the SEC registrant list (NYSE, NYSE American).

Storage (owner and audit, RELEASE GATE): detections are Alpaca-derived, so no record, tag or count of
them is written anywhere (bot-state is public; Alpaca-key workflows never use actions/cache). Dedupe is
stateless (options_radar/run_window): for each current candidate the stage it had at this workflow's
last successful run today is recomputed from today's IEX minute bars, and only a first alert stage or an
upgrade is sent. Reconstruction from minute bars can differ slightly from the snapshot at a boundary:
a rare repeat or miss is possible and stated. Post-close accounting from the first detection cannot be
measured without an authorised private record and is not attempted. Dilution and shares outstanding
come from SEC (options_radar/smallcap_risk, real UA only); float and halts stay UNKNOWN and say so.
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

from options_radar import run_window as rw
from options_radar import smallcap_risk as risk
from options_radar import smallcap_scan as sc
from options_radar.output_policy import decide
from options_radar.telegram_ar import LRM, rtl_line, when_ar

NY = ZoneInfo("America/New_York")
DATA = "https://data.alpaca.markets"
ORDER = {s: i for i, s in enumerate(("COMPRESSION", "EARLY_ACTIVITY", "BREAKOUT_WATCH", "CONFIRMED_MOVE", "EXTENDED"))}


def pseudo_snapshot(bars: list[dict], prev_day: dict | None) -> dict:
    """The snapshot a scan would have seen at the end of these minute bars (today, in time order)."""
    v = sum(b["v"] for b in bars)
    vw = sum((b.get("vw") or b["c"]) * b["v"] for b in bars) / v if v else None
    return {"dailyBar": {"o": bars[0]["o"], "h": max(b["h"] for b in bars), "l": min(b["l"] for b in bars),
                         "c": bars[-1]["c"], "v": v, "vw": vw},
            "latestTrade": {"p": bars[-1]["c"]}, "prevDailyBar": prev_day or {}}


def minute_bars(symbols: list[str], start: datetime, end: datetime, headers: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for i in range(0, len(symbols), 50):
        token = None
        for _ in range(20):
            body = _get("/v2/stocks/bars", {"symbols": ",".join(symbols[i:i + 50]), "timeframe": "1Min", "feed": "iex",
                                            "start": start.isoformat(), "end": end.isoformat(), "limit": 10000,
                                            **({"page_token": token} if token else {})}, headers)
            for sym, bars in (body.get("bars") or {}).items():
                out.setdefault(sym, []).extend(bars)
            token = body.get("next_page_token")
            if not token:
                break
    return out


def new_since(candidates: list[dict], snaps: dict, hist: dict, prev: datetime | None, open_at: datetime,
              close_at: datetime, headers: dict, fetch=None) -> list[dict]:
    """Candidates whose alert stage is new since `prev` (None = first run today: every candidate is new)."""
    if prev is None or prev <= open_at:
        return list(candidates)
    bars = (fetch or minute_bars)([r["symbol"] for r in candidates], open_at, prev, headers)
    elapsed = min(max((prev - open_at) / (close_at - open_at), 0.0), 1.0)
    out = []
    for r in candidates:
        b = bars.get(r["symbol"]) or []
        before = sc.evaluate(r["symbol"], pseudo_snapshot(b, (snaps.get(r["symbol"]) or {}).get("prevDailyBar")),
                             hist.get(r["symbol"]) or [], elapsed).get("stage") if b else None
        if before not in sc.ALERT_STAGES or ORDER[r["stage"]] > ORDER[before]:
            out.append(r)
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
                               f"مؤهل {coverage['eligible']}. مراقبة بحثية: لا فرصة مؤكدة ما دامت المخاطر غير مفحوصة. ليست توصية.")])
    blocks = []
    for r in rows:
        lv = r.get("levels") or {}
        tg = "، ".join(f"T{i + 1} {t:,.2f}" for i, t in enumerate(lv.get("targets") or []))
        text = rtl_line(f"<b>{r['symbol']}</b>{LRM} {r['stage_ar']} — {r['price']:,.2f} ({r['move_pct']:+.1f}%) "
                        f"RVOL≈{r['rvol_time_adjusted']} — محفز {lv.get('trigger', 0):,.2f}؛ {tg}؛ "
                        f"إبطال {lv.get('invalidation', 0):,.2f}" + (f" — ⚠ {', '.join(r['risk_flags'])}" if r['risk_flags'] else ""))
        if r.get("sec_risk"):
            text += "\n" + rtl_line("SEC: " + risk.line_ar(r["sec_risk"]))
        blocks.append(text)  # a candidate and its SEC line never split across messages
    if not blocks:
        blocks.append(rtl_line("لا مرشحين جدد بهذه المعايير الآن."))
    return _pack(blocks, head)


def scan(env: dict, now: datetime, state_data: Path, headers: dict, *, dry_run: bool = False) -> dict | None:
    """One scan of the listed universe (also used on demand by /smallcaps). None when not a session day."""
    cal = xcals.get_calendar("XNYS")
    day = now.astimezone(NY).date()
    sched = cal.schedule.loc[str(day):str(day)]
    if sched.empty and not dry_run:
        return None
    if sched.empty:  # dry run off-session: use the last session for elapsed time
        sched = cal.schedule.loc[:str(day)].tail(1)
    open_at = pd.Timestamp(sched.iloc[0]["open"]).to_pydatetime()
    close_at = pd.Timestamp(sched.iloc[0]["close"]).to_pydatetime()
    elapsed = min(max((now - open_at) / (close_at - open_at), 0.0), 1.0)
    symbols = universe(state_data)
    snaps = snapshots(symbols, headers)
    pre = [s for s, v in snaps.items() if sc.PRICE_MIN <= ((v.get("latestTrade") or {}).get("p") or 0) <= sc.PRICE_MAX
           and ((v.get("dailyBar") or {}).get("v") or 0) * ((v.get("latestTrade") or {}).get("p") or 0) >= sc.MIN_IEX_DOLLAR_VOLUME]
    hist = daily_history(pre, (open_at - timedelta(days=120)).date().isoformat(),
                         (open_at - timedelta(days=1)).date().isoformat(), headers)
    rows = [sc.evaluate(s, snaps[s], hist.get(s) or [], elapsed) for s in pre]
    eligible = [r for r in rows if r.get("eligible")]
    candidates = [r for r in sorted(eligible, key=lambda x: -(x.get("score") or 0)) if r.get("stage") in sc.ALERT_STAGES]
    return {"open_at": open_at, "close_at": close_at, "snaps": snaps, "hist": hist, "candidates": candidates,
            "coverage": {"universe": len(symbols), "snapshots": len(snaps), "prefiltered": len(pre),
                         "eligible": len(eligible)}}


def main() -> int:
    from options_radar.output_policy import deliver_private
    from scripts.telegram_transport import get_chat, send_html_message

    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("auto", "scan", "postclose"))
    parser.add_argument("--state-data", type=Path, default=Path("../state/runtime/public/data"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    env = dict(os.environ)
    if not decide("alpaca_iex", "fetch", env).allowed or not env.get("ALPACA_API_KEY"):
        print("smallcaps: NOT_AUTHORIZED_OR_NO_KEYS")
        return 0
    if args.mode == "postclose":
        print("smallcaps postclose: NOT_MEASURABLE (no authorised private record of first detections)")
        return 0
    headers = {"APCA-API-KEY-ID": env["ALPACA_API_KEY"].strip(), "APCA-API-SECRET-KEY": env["ALPACA_SECRET_KEY"].strip()}
    now = datetime.now(timezone.utc)
    result = scan(env, now, args.state_data, headers, dry_run=args.dry_run)
    if result is None:
        print("smallcaps: not a session day")
        return 0
    # Public log: operational coverage only. Filter and stage counts describe the market (Alpaca-derived).
    print("smallcaps scan:", json.dumps({"universe": result["coverage"]["universe"],
                                         "snapshots": result["coverage"]["snapshots"]}))
    # The previous scan's stage is rebuilt at its step's COMPLETION (after its snapshot), never earlier:
    # a stage reached within those seconds is then treated as seen (a rare miss, never a duplicate).
    window, prev = rw.previous_success(env, "smallcap-scan.yml", now, day_start=result["open_at"] - timedelta(hours=8),
                                       step="Scan or post-close review (owner-private)", mark="completed_at")
    if window == "UNKNOWN" and not args.dry_run:
        print("smallcaps: RUN_HISTORY_UNKNOWN: alerts skipped (fail safe)")
        return 1  # nothing processed: never this run as the next baseline
    new = new_since(result["candidates"], result["snaps"], result["hist"], prev, result["open_at"],
                    result["close_at"], headers)[:8]
    attach_sec_risk(new, env, args.state_data, result["open_at"].date())
    if args.dry_run:
        print("smallcaps: run complete (dry run)")
        return 0
    statuses = rw.send_in_order(message(new, now, result["coverage"]) if new else [], lambda text: deliver_private(
        text, sources=["alpaca_iex"], env=env, get_chat=get_chat, send=lambda t, chat: send_html_message(t, chat_id=chat)))
    print("smallcaps: run complete")  # constant line: the public log never says whether anything fired
    return rw.exit_code(statuses)


def attach_sec_risk(rows: list[dict], env: dict, state_data: Path, as_of) -> None:
    """Official SEC dilution/share context for the (at most 8) new candidates; UNKNOWN without a real UA.

    Actual-issuance filings move a candidate behind the others (supported opportunities first).
    """
    from options_radar import sec_current_feed as scf

    ua = (env.get("SEC_USER_AGENT") or "").strip()
    reg = state_data / "sec_company_tickers.json"
    ciks = {t: c for c, t in scf.cik_map(json.loads(reg.read_text()) if reg.exists() else None,
                                          Path(__file__).resolve().parents[1] / "data/sec_cik_map.json").items()}
    for r in rows:
        subs, facts = risk.fetch(ciks.get(r["symbol"], ""), ua) if "@" in ua else (None, None)
        r["sec_risk"] = risk.assess(subs, facts, as_of=as_of)
        time.sleep(0.25)  # SEC fair access: well under 10 requests per second
    rows.sort(key=lambda r: r["sec_risk"]["dilution"] in risk.RANK_LAST)


if __name__ == "__main__":
    raise SystemExit(main())
