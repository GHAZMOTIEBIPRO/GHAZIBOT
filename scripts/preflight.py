"""Session preflight: rights, keys, private chat, data access, schedule, clocks and outbox. Sends nothing.

Owner (PHASE 5): before any live send, check everything a session depends on. Rights are checked apart
from key presence (an attestation is the owner's record, a key is not permission). The log prints status
words, booleans, HTTP codes, the next session's windows and a key id (an HMAC of a constant) only: no
value of any secret, no price, no chat id. No message is sent and no synthetic price is ever produced.
Exit 0 = ready, 1 = something blocks a stage (named), 2 = not a session day ahead within 4 days.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd
import requests

from options_radar import output_policy as op
from options_radar import state_keys as sk

NY = ZoneInfo("America/New_York")
RIYADH = ZoneInfo("Asia/Riyadh")
DATA = "https://data.alpaca.markets"
TRADING = "https://api.alpaca.markets"
SEC_FEED = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&count=10&output=atom"


def _both(t: datetime) -> str:
    return f"{t.astimezone(NY):%a %H:%M} NY / {t.astimezone(RIYADH):%a %H:%M} RUH"


def schedule(now: datetime) -> dict[str, Any]:
    sched = xcals.get_calendar("XNYS").schedule.loc[now.date().isoformat():(now + timedelta(days=5)).date().isoformat()]
    for _, row in sched.iterrows():
        open_at = pd.Timestamp(row["open"]).to_pydatetime()
        close_at = pd.Timestamp(row["close"]).to_pydatetime()
        if close_at + timedelta(hours=2) < now:
            continue
        d = open_at.astimezone(NY)

        def at(h: int, m: int, d: datetime = d) -> datetime:
            return d.replace(hour=h, minute=m, second=0, microsecond=0)

        return {"session": d.date().isoformat(), "early_close": close_at.astimezone(NY).hour < 16,
                "EARLY": _both(at(8, 30)), "FINAL": _both(at(9, 0)), "open": _both(open_at),
                "opening_range_15m_complete_sip": _both(open_at + timedelta(minutes=31)),
                "LASTHOUR": _both(close_at - timedelta(minutes=60)), "close": _both(close_at)}
    return {}


def _code(method, url: str, **kw) -> tuple[int | str, requests.Response | None]:
    try:
        r = method(url, timeout=20, **kw)
        return r.status_code, r
    except requests.RequestException as exc:
        return type(exc).__name__, None


def checks(env: dict[str, str], now: datetime, *, state: Path, get_chat, http=requests) -> dict[str, Any]:
    out: dict[str, Any] = {}
    def right(src: str, use: str) -> str:
        d = op.decide(src, use, env)
        return "ALLOWED" if d.allowed else ("NOT_ATTESTED" if d.status == op.OWNER_AUTHORIZED else d.status)

    out["rights"] = {f"{src}.{use}": right(src, use)
                     for src in ("alpaca_iex", "alpaca_indicative_options")
                     for use in ("fetch", "compute", "telegram_private", "publish_derived", "telegram_public")}
    key = sk.state_key(env)
    ua = (env.get("SEC_USER_AGENT") or "").strip()
    out["keys"] = {"alpaca": bool(env.get("ALPACA_API_KEY") and env.get("ALPACA_SECRET_KEY")),
                   "telegram_bot": bool(env.get("TELEGRAM_BOT_TOKEN")),
                   "owner_chat": bool(env.get("TELEGRAM_OWNER_CHAT_ID") or env.get("TELEGRAM_OWNER_USERNAME")),
                   "state_key": key is not None, "state_key_id": sk.key_id(key) if key else None,
                   "sec_user_agent": "@" in ua}
    out["private_chat"] = op.destination_status(env, get_chat)[0] if out["keys"]["telegram_bot"] else "NO_TOKEN"
    if out["keys"]["alpaca"]:
        h = {"APCA-API-KEY-ID": env["ALPACA_API_KEY"].strip(), "APCA-API-SECRET-KEY": env["ALPACA_SECRET_KEY"].strip()}
        iex, _ = _code(http.get, f"{DATA}/v2/stocks/snapshots", params={"symbols": "SPY", "feed": "iex"}, headers=h)
        end = (now - timedelta(minutes=20)).isoformat()
        sip, _ = _code(http.get, f"{DATA}/v2/stocks/bars", params={"symbols": "SPY", "timeframe": "1Day", "feed": "sip",
                                                                   "limit": 2, "end": end}, headers=h)
        opt, _ = _code(http.get, f"{DATA}/v1beta1/options/snapshots/SPY", params={"feed": "indicative", "limit": 1},
                       headers=h)
        clock, r = _code(http.get, f"{TRADING}/v2/clock", headers=h)
        skew = None
        if r is not None and r.status_code == 200:
            ts = datetime.fromisoformat(str(r.json().get("timestamp")).replace("Z", "+00:00"))
            skew = round((ts - datetime.now(timezone.utc)).total_seconds(), 1)
        out["alpaca"] = {"iex_snapshot": iex, "sip_history": sip, "indicative_options": opt, "clock": clock,
                         "clock_skew_s": skew}
    if "@" in ua:
        code, _ = _code(http.get, SEC_FEED, headers={"User-Agent": ua, "Accept-Encoding": "gzip"})
        out["sec_current_feed"] = code
    else:
        out["sec_current_feed"] = "NOT_CONFIGURED"
    out["schedule"] = schedule(now)
    out["outbox_unconfirmed"] = _unconfirmed(state)
    return out


def _unconfirmed(state: Path) -> dict[str, int]:
    """UNCONFIRMED items still awaiting the owner's manual review (/status, /confirm), per recent day."""
    out: dict[str, int] = {}
    days = sorted((state / "daily_plan").glob("20*")) if (state / "daily_plan").exists() else []
    for day in days[-5:]:
        n = 0
        for f in day.glob("report_*.json"):
            try:
                items = (json.loads(f.read_text()).get("items") or {}).values()
            except ValueError:
                continue
            n += sum(1 for i in items if i.get("status") == "UNCONFIRMED")
        if n:
            out[day.name] = n
    return out


def blockers(c: dict[str, Any]) -> list[str]:
    b = []
    if c["rights"].get("alpaca_iex.telegram_private") != "ALLOWED":
        b.append("RIGHTS: owner attestation for private Alpaca alerts")
    for name in ("alpaca", "telegram_bot", "owner_chat"):
        if not c["keys"][name]:
            b.append(f"KEY: {name}")
    if c["private_chat"] != "OK":
        b.append(f"CHAT: {c['private_chat']}")
    for name, code in (c.get("alpaca") or {}).items():
        if name in ("iex_snapshot", "sip_history", "indicative_options", "clock") and code != 200:
            b.append(f"ALPACA: {name} {code}")
    if abs((c.get("alpaca") or {}).get("clock_skew_s") or 0) > 5:
        b.append("CLOCK: runner vs Alpaca skew above 5 s")
    if not c["keys"]["state_key"]:
        b.append("DEGRADED: GHAZI_STATE_HMAC_KEY missing (event alerts off; reports still go)")
    if c["sec_current_feed"] != 200:
        b.append(f"DEGRADED: SEC feed {c['sec_current_feed']} (SEC news off)")
    return b


def main() -> int:
    from scripts.telegram_transport import get_chat

    now = datetime.now(timezone.utc)
    c = checks(dict(os.environ), now, state=Path(os.environ.get("STATE_DIR", "../state/state")), get_chat=get_chat)
    b = blockers(c)
    print("preflight:", json.dumps(c, ensure_ascii=False))
    print("preflight blockers:", json.dumps(b, ensure_ascii=False))
    if not c["schedule"]:
        return 2
    return 1 if any(not x.startswith("DEGRADED") for x in b) else 0


if __name__ == "__main__":
    raise SystemExit(main())
