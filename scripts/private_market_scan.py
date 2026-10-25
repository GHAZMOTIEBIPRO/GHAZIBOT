"""Owner-private market scan: discovery -> measured momentum -> setup conditions.

Pipeline (each stage replaceable, each output governed by output_policy):
1. Discovery (options_radar.discovery_providers): why a symbol is looked at
   (top gainer / most active). The Nasdaq.com screener is denied by policy,
   so the first allowed provider is used; no score comes from discovery.
2. Measured momentum (5-minute IEX bars via options_radar.bar_providers):
   change vs the prior close, same-time relative volume (cumulative volume to
   the last completed 5-minute bar vs the median of the same elapsed time over
   the prior sessions), and position vs the prior-day high.
3. Setup conditions: explicit booleans (above prior-day high, same-time RVOL
   >= 2, change >= 5%). No probability, no order, no target.

Official catalysts (catalyst_watchlist.json, public) are attached as context
only. The result goes to the owner's personal Telegram chat only
(output_policy.deliver_private). Logs and the public status file carry
statuses only: no symbols, prices or counts derived from Alpaca data.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import exchange_calendars as xcals
import pandas as pd

from options_radar.bar_providers import AlpacaBars
from options_radar.discovery_providers import (
    AlpacaScreenerDiscovery,
    NasdaqScreenerDiscovery,
    select,
)
from options_radar.output_policy import deliver_private

MAX_SYMBOLS = 15
PRIOR_SESSIONS = 10


def sessions(now: datetime, days: int = 25) -> list[tuple[datetime, datetime]]:
    cal = xcals.get_calendar("XNYS")
    sched = cal.schedule.loc[str((now - timedelta(days=days)).date()):str(now.date())]
    return [(pd.Timestamp(r["open"]).to_pydatetime(), pd.Timestamp(r["close"]).to_pydatetime())
            for _, r in sched.iterrows() if pd.Timestamp(r["open"]).to_pydatetime() <= now]


def measure(bars: list[dict[str, Any]], sess: list[tuple[datetime, datetime]], cutoff: datetime) -> dict[str, Any]:
    """Momentum facts from completed 5-minute bars of today's session and prior sessions."""
    if len(sess) < 2:
        return {"status": "NO_SESSION"}
    today_open, today_close = sess[-1]
    if not today_open <= cutoff:
        return {"status": "SESSION_NOT_STARTED"}
    done = [b for b in bars if b["t"] + timedelta(minutes=5) <= cutoff]
    today = [b for b in done if today_open <= b["t"] < today_close]
    if not today:
        return {"status": "NO_COMPLETED_BARS_TODAY"}
    elapsed = today[-1]["t"] + timedelta(minutes=5) - today_open
    prior_volumes, prior_day = [], None
    for open_, close in sess[-1 - PRIOR_SESSIONS:-1]:
        rows = [b for b in done if open_ <= b["t"] < close]
        if rows:
            prior_volumes.append(sum(b["v"] for b in rows if b["t"] < open_ + elapsed))
            prior_day = rows
    if not prior_day:
        return {"status": "NO_PRIOR_SESSION"}
    prior_close, prior_high = prior_day[-1]["c"], max(b["h"] for b in prior_day)
    last = today[-1]["c"]
    median = statistics.median(prior_volumes) if len(prior_volumes) >= 5 else None
    rvol = round(sum(b["v"] for b in today) / median, 2) if median else None
    return {"status": "OK", "last_bar_end": (today[-1]["t"] + timedelta(minutes=5)).isoformat(),
            "change_pct": round((last / prior_close - 1) * 100, 2), "rvol_same_time": rvol,
            "rvol_basis": f"median of {len(prior_volumes)} prior sessions at the same elapsed time" if median else
                          "INSUFFICIENT (fewer than 5 prior sessions)",
            "above_prior_high": last > prior_high, "prior_high": prior_high, "last": last}


def setup_conditions(m: dict[str, Any]) -> dict[str, bool]:
    return {"above_prior_day_high": bool(m.get("above_prior_high")),
            "same_time_rvol_at_least_2": (m.get("rvol_same_time") or 0) >= 2,
            "change_at_least_5pct": (m.get("change_pct") or 0) >= 5}


def run(now: datetime, env: Mapping[str, str], catalysts: Any, *, session: Any = None,
        send_private: Callable[[str], str] | None = None) -> dict[str, Any]:
    kwargs = {"session": session} if session is not None else {}
    providers = [NasdaqScreenerDiscovery(env), AlpacaScreenerDiscovery(env, **kwargs)]
    provider, tried = select(providers, "telegram_private", env)
    status: dict[str, Any] = {"schema": "ghazi.private_scan_status.v1", "checked_at": now.isoformat(),
                              "providers_tried": [{"provider": t["provider"], "allowed": t["allowed"]} for t in tried],
                              "public_output": "STATUS_ONLY"}
    if provider is None:
        return {**status, "status": "NO_QUALIFIED_SOURCE"}
    found = provider.candidates(now)
    if found["status"] != "OK":
        return {**status, "status": "DISCOVERY_" + found["status"]}
    sess = sessions(now)
    if not sess or not sess[-1][0] <= now <= sess[-1][1] + timedelta(minutes=20):
        return {**status, "status": "OUTSIDE_SESSION"}
    bars_provider = AlpacaBars(env, now=now, **kwargs)
    cutoff = now - timedelta(minutes=16)
    official = {e.get("symbol"): e for e in (catalysts or {}).get("watchlist") or [] if isinstance(e, dict)}
    rows = []
    for cand in found["candidates"][:MAX_SYMBOLS]:
        got = bars_provider.bars(cand["symbol"], "5m", sess[0][0], now)
        if got["status"] != "OK":
            continue
        m = measure(got["bars"], sess, cutoff)
        if m["status"] != "OK":
            continue
        rows.append({**cand, "momentum": m, "setup": setup_conditions(m),
                     "official_catalyst": (official.get(cand["symbol"]) or {}).get("latest_date")})
    if not rows:
        return {**status, "status": "NO_MEASURABLE_CANDIDATES"}
    rows.sort(key=lambda r: (sum(r["setup"].values()), r["momentum"].get("rvol_same_time") or 0), reverse=True)
    text = message(rows, found.get("provider_time"))
    delivery = send_private(text) if send_private else "NOT_ATTEMPTED"
    return {**status, "status": "MEASURED", "delivery": delivery}


def message(rows: list[dict[str, Any]], provider_time: Any) -> str:
    why = {"TOP_GAINER": "ضمن الأعلى صعودًا", "MOST_ACTIVE": "ضمن الأنشط تداولًا"}
    lines = ["<b>فحص السوق الخاص (Alpaca IEX)</b>",
             f"وقت قائمة المزود: {provider_time} · شموع 5 دقائق مكتملة فقط · استخدام شخصي؛ لا يُعاد نشره."]
    for r in rows[:10]:
        m, s = r["momentum"], r["setup"]
        met = [k for k, v in s.items() if v]
        lines.append(f"<b>{r['symbol']}</b> · سبب الظهور: {why.get(r['why'], r['why'])}"
                     + (f" · محفز رسمي {r['official_catalyst']}" if r.get("official_catalyst") else ""))
        lines.append(f"  الزخم المقاس: تغير {m['change_pct']}% · RVOL بنفس الوقت {m['rvol_same_time'] or 'غير كافٍ'}"
                     f" · آخر شمعة {m['last_bar_end'][11:16]} UTC")
        lines.append("  شروط الإعداد المتحققة: " + ("، ".join(met) if met else "لا شيء"))
    lines.append("الشروط وصف لا احتمال نجاح ولا أمر تداول.")
    return "\n".join(lines)[:3900]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalysts", type=Path)
    parser.add_argument("--status-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        catalysts = json.loads(args.catalysts.read_text(encoding="utf-8")) if args.catalysts else None
    except (OSError, ValueError):
        catalysts = None
    from scripts.telegram_transport import get_chat, send_html_message

    def send_private(text: str) -> str:
        return deliver_private(text, sources=["alpaca_iex"], env=os.environ, get_chat=get_chat,
                               send=lambda body, chat: send_html_message(body, chat_id=chat))

    result = run(datetime.now(timezone.utc), os.environ, catalysts, send_private=send_private)
    args.status_output.parent.mkdir(parents=True, exist_ok=True)
    args.status_output.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Private scan:", result["status"], result.get("delivery", ""))  # statuses only
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
