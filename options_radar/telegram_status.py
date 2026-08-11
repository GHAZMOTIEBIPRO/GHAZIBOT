from __future__ import annotations

import argparse
import html
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

API_TIMEOUT_SECONDS = 20
DEFAULT_PAYLOAD = Path("public/data/latest.json")
DEFAULT_ALERT_STATE = Path("data/live/telegram_alert_state.json")
DEFAULT_ASYM_STATE = Path("data/live/asymmetric_alert_state.json")
DEFAULT_STATUS_STATE = Path("data/live/telegram_status_state.json")


def _load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    return n if math.isfinite(n) else default


def _safe(value: Any, limit: int = 180) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return html.escape(text)


def _telegram_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def _resolve_chat_id(token: str) -> str:
    configured = str(os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if configured:
        return configured
    response = requests.get(_telegram_url(token, "getUpdates"), timeout=API_TIMEOUT_SECONDS)
    response.raise_for_status()
    data = response.json()
    for update in reversed(data.get("result") or []):
        if not isinstance(update, dict):
            continue
        message = update.get("message") or update.get("edited_message") or update.get("channel_post")
        if not isinstance(message, dict):
            continue
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        if chat.get("id") is not None:
            return str(chat["id"])
    raise RuntimeError("Telegram chat id not found")


def _send(token: str, chat_id: str, text: str) -> None:
    response = requests.post(
        _telegram_url(token, "sendMessage"),
        data={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"},
        timeout=API_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError("Telegram sendMessage failed")


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _recent_real_alert(alert_state: dict[str, Any], asym_state: dict[str, Any]) -> bool:
    return _num(alert_state.get("last_sent_count")) > 0 or _num(asym_state.get("last_sent_count")) > 0


def _near_misses(payload: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    omega = payload.get("omega") if isinstance(payload.get("omega"), dict) else {}
    opportunities = omega.get("opportunities") if isinstance(omega.get("opportunities"), list) else []
    rows: list[dict[str, Any]] = []
    for raw in opportunities:
        if not isinstance(raw, dict):
            continue
        symbol = str(raw.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        direction = str(raw.get("direction") or "UPSIDE").upper()
        if direction not in {"UPSIDE", "LONG", "CALL"}:
            continue
        if raw.get("no_trade_state"):
            continue
        catalyst = raw.get("catalyst") if isinstance(raw.get("catalyst"), dict) else {}
        reaction = str(catalyst.get("reaction_state") or "").upper()
        if reaction == "EXTENDED_CHASING_RISK":
            continue
        rank = _num(raw.get("explosion_rank"))
        tier = str(raw.get("opportunity_tier") or "-")
        dimensions = raw.get("dimensions") if isinstance(raw.get("dimensions"), dict) else {}
        participation = _num(dimensions.get("participation"))
        supply = _num(dimensions.get("supply_structure"))
        rows.append({"symbol": symbol, "rank": rank, "tier": tier, "participation": participation, "supply": supply})

    if not rows:
        stocks = payload.get("stocks") if isinstance(payload.get("stocks"), list) else []
        for raw in stocks:
            if not isinstance(raw, dict):
                continue
            symbol = str(raw.get("symbol") or "").upper().strip()
            if not symbol or str(raw.get("rejection_reason") or "").strip():
                continue
            score = _num(raw.get("score"))
            rvol = max(_num(raw.get("finviz_relative_volume")), _num(raw.get("relative_volume")), _num(raw.get("rvol")))
            rows.append({"symbol": symbol, "rank": score, "tier": "WATCH", "participation": min(100.0, rvol * 30.0), "supply": 0.0})

    rows.sort(key=lambda r: (r["rank"], r["participation"], r["supply"]), reverse=True)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        if row["symbol"] in seen:
            continue
        seen.add(row["symbol"])
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _status_message(payload: dict[str, Any], near: list[dict[str, Any]]) -> str:
    generated = payload.get("generated_at") or payload.get("as_of") or "غير متوفر"
    lines = [
        "🛰 <b>BLACK BOX Ω — حالة الرادار</b>",
        "",
        "✅ النظام شغال والاتصال بتيليجرام سليم.",
        "🚫 ما فيه فرصة وصلت شروط التنبيه القوية في آخر فحص.",
        f"🕒 آخر بيانات: <b>{_safe(generated, 80)}</b>",
    ]
    if near:
        lines += ["", "👀 <b>أقرب الأسهم للشروط حاليًا:</b>"]
        for idx, row in enumerate(near, start=1):
            lines.append(
                f"{idx}) <b>{_safe(row['symbol'])}</b> — Ω {row['rank']:.0f}/100 | Tier {_safe(row['tier'])} | طلب {row['participation']:.0f}/100 | عرض {row['supply']:.0f}/100"
            )
        lines += ["", "هذي <b>مراقبة فقط</b>، مو إشارة دخول. إذا واحد اكتملت شروطه يجيك تنبيه مستقل فورًا."]
    else:
        lines += ["", "ما فيه حتى Near-Miss نظيف يستاهل العرض حاليًا."]
    return "\n".join(lines)


def run(payload_path: Path, alert_state_path: Path, asym_state_path: Path, status_state_path: Path) -> int:
    token = str(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        print("Status: TELEGRAM_BOT_TOKEN missing; skip")
        return 0

    payload = _load_json(payload_path, {})
    alert_state = _load_json(alert_state_path, {})
    asym_state = _load_json(asym_state_path, {})
    status_state = _load_json(status_state_path, {})
    if not isinstance(payload, dict) or not payload:
        print("Status: payload missing; skip")
        return 0
    if not isinstance(alert_state, dict):
        alert_state = {}
    if not isinstance(asym_state, dict):
        asym_state = {}
    if not isinstance(status_state, dict):
        status_state = {}

    # A real alert is already more useful than a heartbeat on this run.
    if _recent_real_alert(alert_state, asym_state):
        print("Status: real alert sent on this run; heartbeat suppressed")
        return 0

    now = datetime.now(timezone.utc)
    interval_hours = max(1.0, _num(os.getenv("TELEGRAM_STATUS_INTERVAL_HOURS", "4"), 4.0))
    last_sent = _parse_time(status_state.get("last_status_sent_at"))
    if last_sent and now - last_sent < timedelta(hours=interval_hours):
        remaining = timedelta(hours=interval_hours) - (now - last_sent)
        print(f"Status: cadence gate active; remaining={remaining}")
        return 0

    chat_id = _resolve_chat_id(token)
    near = _near_misses(payload, 3)
    _send(token, chat_id, _status_message(payload, near))
    status_state["last_status_sent_at"] = now.isoformat()
    status_state["last_near_misses"] = near
    status_state["interval_hours"] = interval_hours
    _write_json(status_state_path, status_state)
    print(f"Status: heartbeat sent near_misses={[row['symbol'] for row in near]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BLACK BOX Ω Telegram heartbeat")
    parser.add_argument("--payload", default=str(DEFAULT_PAYLOAD))
    parser.add_argument("--alert-state", default=str(DEFAULT_ALERT_STATE))
    parser.add_argument("--asym-state", default=str(DEFAULT_ASYM_STATE))
    parser.add_argument("--status-state", default=str(DEFAULT_STATUS_STATE))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return run(Path(args.payload), Path(args.alert_state), Path(args.asym_state), Path(args.status_state))
    except requests.RequestException as exc:
        print(f"Status Telegram network error: {exc}")
        return 2
    except Exception as exc:
        print(f"Status error: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
