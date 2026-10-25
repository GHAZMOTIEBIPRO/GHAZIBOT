"""Alpaca Basic *internal* completed-daily VCP research, no public OHLC publication.

No key/attested non-display authorization -> zero API requests. This is not an
automatic workaround for Yahoo terms; Alpaca trading/data access and private
derived alerts require the account's applicable permissions.

Never write prices, volume, pivot, named securities, or raw candle series to
public bot-state. IEX is single-venue; historical SIP requires separate authorization.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from scripts.telegram_transport import send_html_message

NY = ZoneInfo("America/New_York")
SCHEMA = "ghazi.alpaca_iex_vcp_health.v1"
SYMBOLS = ("RGC", "BNAI", "RGTI", "SOUN", "RKLB", "ASTS", "NVDA", "TSLA")
ENDPOINT = "https://data.alpaca.markets/v2/stocks"
SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,7}$")
MAX_PAGES = 2


def authorization(env: Mapping[str, str]) -> str:
    if (env.get("ALPACA_INTERNAL_DATA_USE_AUTHORIZED") or "").lower() != "true":
        return "PROVIDER_TERMS_UNATTESTED"
    if not (env.get("ALPACA_API_KEY") or "").strip() or not (
        env.get("ALPACA_SECRET_KEY") or ""
    ).strip():
        return "CREDENTIALS_MISSING"
    return "AUTHORIZED_INTERNAL_ONLY"


def authorized_feed(env: Mapping[str, str]) -> str:
    """Historical SIP is opt-in only, not permission to read real-time SIP.

    Both sources stay within the same Alpaca account/source family;
    historical SIP can improve coverage but cannot confirm independent prices.
    """
    return ("sip" if (env.get("ALPACA_HISTORICAL_SIP_INTERNAL_AUTHORIZED") or "")
            .lower() == "true" else "iex")


def sanitize_daily_bars(bars: Any, *, now: datetime) -> pd.DataFrame:
    """Exclude current NY day *even after close* and disallow fabricated/stale bar dates."""
    names = ["Open", "High", "Low", "Close", "Volume"]
    empty = pd.DataFrame(columns=names)
    if now.tzinfo is None or not isinstance(bars, list) or not 70 <= len(bars) <= 1000:
        return empty
    rows: list[list[float]] = []
    times: list[pd.Timestamp] = []
    for item in bars:
        if not isinstance(item, dict):
            return empty
        try:
            ts = pd.Timestamp(item.get("t"))
            values = [float(item[k]) for k in ("o", "h", "l", "c", "v")]
        except (ValueError, TypeError, KeyError, OverflowError):
            return empty
        if ts.tzinfo is None:
            return empty
        ts = ts.tz_convert(NY)
        if ts.hour != 0 or ts.minute != 0 or ts.second != 0:
            return empty
        if ts.date() >= now.astimezone(NY).date():
            continue
        if not all(pd.notna(v) and abs(v) != float("inf") for v in values):
            return empty
        o, h, l, c, v = values
        if min(o, h, l, c) <= 0 or v < 0 or h < max(o, c) or l > min(o, c):
            return empty
        times.append(ts)
        rows.append(values)
    if len(rows) < 70 or len(rows) > 500 or times != sorted(set(times)):
        return empty
    age = (now.astimezone(NY).date() - times[-1].date()).days
    if not 1 <= age <= 7:
        return empty
    return pd.DataFrame(rows, columns=names, index=pd.DatetimeIndex(times))


def fetch_daily_bars(symbol: str, *, now: datetime, api_key: str, api_secret: str,
                     session: Any = requests, feed: str = "iex") -> list[dict]:
    """Official Alpaca completed daily bars; explicit IEX or authorized historical SIP only."""
    if feed not in {"iex", "sip"}:
        raise ValueError("only IEX or owner-authorized historical SIP supported")
    if not SYMBOL_RE.fullmatch(symbol):
        raise ValueError("invalid stock symbol")
    if now.tzinfo is None:
        raise ValueError("aware timestamp required")
    params: dict[str, Any] = {
        "timeframe": "1Day",
        "feed": feed,  # SIP only after separate owner attestation, historical previous session
        "adjustment": "raw",
        "start": (now - timedelta(days=235)).date().isoformat(),
        # Exclude the entire still-forming NY trading day for *both* feeds.
        # Free historical SIP is delayed and never authorizes real-time reads.
        "end": now.astimezone(NY).date().isoformat(),
        "limit": 500,
        "sort": "asc",
    }
    headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret}
    seen: set[str] = set()
    gathered: list[dict] = []
    for _ in range(MAX_PAGES):
        response = session.get(
            f"{ENDPOINT}/{symbol}/bars", params=params, headers=headers, timeout=15
        )
        response.raise_for_status()  # 401/403/429/5xx: fail closed, no spinning retry
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("bars"), list):
            raise TypeError("malformed Alpaca bars response")
        batch = data["bars"]
        if len(batch) > 500 or len(gathered) + len(batch) > 1000:
            raise ValueError("unexpected Alpaca response volume")
        gathered.extend(batch)
        token = data.get("next_page_token")
        if not token:
            return gathered
        if not isinstance(token, str) or len(token) > 2048 or token in seen:
            raise ValueError("invalid next-page token")
        seen.add(token)
        params["page_token"] = token
    # Never silently analyze a truncated history.
    raise ValueError("Alpaca history exceeded bounded pagination")


def _public_status(reason: str, *, now: datetime, bars_seen: int = 0,
                   valid_symbols: int = 0, failed: int = 0,
                   feed: str = "iex") -> dict[str, Any]:
    note_ar = ("بحث VCP داخلي من شموع SIP تاريخية مكتملة فقط؛ لا أسعار منشورة "
               if feed == "sip"
               else "بحث VCP داخلي من شموع IEX اليومية المكتملة فقط؛ لا أسعار منشورة ")
    note_ar += "ولا دليل مصدر مستقل أو عرض سعر لحظي. الحالة ليست توقيت عرض سعر."
    return {
        "schema": SCHEMA, "generated_at": now.astimezone(timezone.utc).isoformat(),
        "status": reason, "provider": ("Alpaca historical consolidated SIP (past completed sessions)"
                                          if feed == "sip" else "Alpaca Basic IEX (one US exchange only)"),
        "access_scope": "OWNER_AUTHORIZED_PRIVATE_NON_DISPLAY_RESEARCH",
        "raw_market_data_published": False, "tickers_published": False,
        "indicators_published": False, "trade_signals_published": False,
        "execution_authority": False, "option_quote_verified": False,
        "independent_source_confirmation": False,
        "requested_symbols": len(SYMBOLS) if reason.startswith("INTERNAL_") else 0,
        "valid_daily_histories": valid_symbols, "bar_samples_received": bars_seen,
        "fetch_errors": failed,
        "source_kind": ("HISTORICAL_SIP_ONLY_NOT_REALTIME" if feed == "sip"
                        else "IEX_ONLY_NOT_CONSOLIDATED"),
        "note_ar": (note_ar if reason.startswith("INTERNAL_") else
                    "المصدر متوقف حتى توفر مفاتيح Alpaca وإقرار صلاحية الاستخدام الداخلي."),
    }


def private_message(picks: list[dict[str, str]], session_day: str, *, feed: str = "iex") -> str:
    lines = [
        ("<b>GHAZI RADAR · VCP بحثي خاص · SIP تاريخي مكتمل</b>" if feed == "sip"
         else "<b>GHAZI RADAR · VCP بحثي خاص · IEX فقط</b>"),
        f"جلسة الشموع المكتملة: {html.escape(session_day)}",
        ("بيانات SIP تاريخية أقدم من الجلسة الحالية؛ ليست بثًا لحظيًا ولا مصدرًا مستقلًا."
         if feed == "sip" else "بيانات Alpaca IEX تغطي بورصة واحدة، لا السوق الأمريكي كله."),
        "المؤشرات ليست إشارات شراء ولا توصيات CALL/PUT.",
    ]
    for pick in picks[:5]:
        lines.append(f"• <b>{html.escape(pick['symbol'])}</b> · ترقب VCP تاريخي")
        weekly_label = {
            "DAILY_WEEKLY_ALIGNED": "توافق يومي وأسبوعي من نفس المصدر",
            "NO_WEEKLY_CONFIRMATION": "لا تأكيد أسبوعي للنموذج اليومي",
        }.get(pick.get("weekly_status", ""), "الشموع الأسبوعية غير كافية")
        lines.append(f"  {weekly_label}")
    lines.append("لا يوجد تأكيد من مزود مستقل أو تدفق خيارات أو أسعار تنفيذية لهذه القائمة.")
    return "\n".join(lines)


def clean_delivery_state(value: Any) -> dict[str, Any]:
    """Publish only dated delivery receipt metadata, even if access is revoked."""
    state = value if isinstance(value, dict) else {}
    clean: dict[str, Any] = {}
    session = state.get("last_private_session")
    try:
        session_date = date.fromisoformat(str(session))
        if session_date.isoformat() == session:
            clean["last_private_session"] = session
    except ValueError:
        pass
    message_id = state.get("private_message_id")
    if type(message_id) is int and message_id > 0:
        clean["private_message_id"] = message_id
    return clean


def run(*, now: datetime, env: Mapping[str, str], state: dict | None = None,
        client: Any = requests, send: Callable[[str], Any] = send_html_message,
        private_ready: bool = False) -> tuple[dict, dict]:
    if now.tzinfo is None:
        raise ValueError("aware now required")
    gate = authorization(env)
    state = clean_delivery_state(state)
    if gate != "AUTHORIZED_INTERNAL_ONLY":
        # Denied access must not import optional market adapters or touch Alpaca;
        # retain safe receipt metadata so reauthorization cannot resend a day.
        return _public_status(gate, now=now), state
    # The options package initializer pulls in many unrelated, optional market
    # adapters. Load it only after verified credentials/permission, when the
    # workflow installs the full requirements.txt dependency set.
    from options_radar.vcp_minervini_shadow import vcp_trend_shadow

    feed = authorized_feed(env)
    # Receipt state was reduced to an allowlisted schema before any provider IO.
    failures = 0
    bars_seen = 0
    valid = 0
    picks: list[dict[str, str]] = []
    latest: str | None = None
    for symbol in SYMBOLS:
        try:
            bars = fetch_daily_bars(symbol, now=now,
                                    api_key=env["ALPACA_API_KEY"],
                                    api_secret=env["ALPACA_SECRET_KEY"],
                                    session=client, feed=feed)
            bars_seen += len(bars)
            frame = sanitize_daily_bars(bars, now=now)
            shadow = vcp_trend_shadow(frame, source_family=(
                "alpaca_historical_sip" if feed == "sip" else "alpaca_iex"))
            if not shadow["available"]:
                continue
            valid += 1
            day = shadow["source_last_daily_bar"]
            if latest is None or day > latest:
                latest = day
            if shadow["stage"] == "TIGHT_WATCH":
                weekly = shadow.get("weekly_context") or {}
                picks.append({"symbol": symbol, "day": day,
                              "weekly_status": str(weekly.get("status") or "INSUFFICIENT")})
        except (ValueError, requests.RequestException, KeyError, TypeError):
            # Do not leak endpoint error text or API credentials to public logs.
            failures += 1
    reason = "INTERNAL_RESEARCH" if valid else "INTERNAL_NO_VALID_BARS"
    result = _public_status(reason, now=now, bars_seen=bars_seen,
                            valid_symbols=valid, failed=failures, feed=feed)
    # The original source session date is private. No tickers, pivots, or
    # derived signal counts are included in the published bot-state.
    if (latest and picks and private_ready
            and env.get("ALPACA_PRIVATE_ALERTS_AUTHORIZED", "").lower() == "true"
            and state.get("last_private_session") != latest):
        recent = [p for p in picks if p["day"] == latest]
        if recent:
            try:
                receipt = send(private_message(recent, latest, feed=feed))
            except Exception:  # noqa: BLE001 - retries preserve state on Telegram error
                result["private_delivery"] = "FAILED"
            else:
                message_id = getattr(receipt, "message_id", None)
                if type(message_id) is int and message_id > 0:
                    state["last_private_session"] = latest
                    state["private_message_id"] = message_id
                    result["private_delivery"] = "ACCEPTED"
                else:
                    # A successful function return without Telegram's receipt
                    # is not delivery proof and must not poison deduplication.
                    result["private_delivery"] = "UNCONFIRMED"
    return result, state


def owner_send(env: Mapping[str, str]) -> Callable[[str], Any]:
    """Send only to the owner's personal chat, never the broadcast chat.

    output_policy.deliver_private checks the policy, that TELEGRAM_OWNER_CHAT_ID
    differs from TELEGRAM_CHAT_ID and that Telegram reports a private chat.
    """
    from options_radar.output_policy import deliver_private
    from scripts.telegram_transport import get_chat

    def send(text: str) -> Any:
        receipt: dict[str, Any] = {}

        def _send(body: str, chat: str) -> Any:
            receipt["r"] = send_html_message(body, chat_id=chat)
            return receipt["r"]

        status = deliver_private(text, sources=["alpaca_iex"], env=env, get_chat=get_chat, send=_send)
        if status != "DELIVERED":
            raise RuntimeError(status)
        return receipt["r"]

    return send


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--private-ready", action="store_true")
    args = parser.parse_args()
    try:
        state = json.loads(args.state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    report, new_state = run(now=datetime.now(timezone.utc), env=os.environ,
                            state=state, private_ready=args.private_ready, send=owner_send(os.environ))
    for path, payload in ((args.status, report), (args.state, new_state)):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        temp.replace(path)
    print("Alpaca completed daily internal VCP:", report["status"],
          "eligible histories:", report["valid_daily_histories"],
          "errors:", report["fetch_errors"],
          "private:", report.get("private_delivery", "NOT_SENT"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
