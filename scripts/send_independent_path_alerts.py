from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _load(path: str | Path, default: Any) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _save(path: str | Path, payload: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(destination)


def _safe(value: Any, limit: int = 700) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return html.escape(text)


def _send(text: str) -> None:
    token = str(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = str(os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        raise RuntimeError("Telegram destination is not ready")
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        },
        timeout=20,
    )
    response.raise_for_status()
    body = response.json()
    if not body.get("ok"):
        raise RuntimeError(f"Telegram rejected message: {body}")


def _fingerprint(parts: list[Any]) -> str:
    raw = "|".join(str(value or "") for value in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _stock_message(row: dict[str, Any]) -> str:
    symbol = str(row.get("symbol") or "").upper()
    score = _number(row.get("score"))
    price = _number(row.get("price"))
    move = _number(row.get("move_pct"))
    stage = str(row.get("stage") or "WATCH").upper()
    cause = row.get("cause") if isinstance(row.get("cause"), dict) else {}
    cause_status = str(cause.get("status_ar") or "السبب الأساسي غير مثبت حتى الآن")
    cause_headline = str(cause.get("headline") or "").strip()
    cause_source = str(cause.get("source") or "").strip()
    source_tier = str(cause.get("source_tier") or "").strip()
    amplifiers = [str(value) for value in row.get("amplifiers", []) if str(value).strip()]
    halts = [value for value in row.get("market_status_evidence", []) if isinstance(value, dict)]

    lines = [
        "🚀 <b>بلاك بوكس Ω — مسار الأسهم</b>",
        "",
        f"<b>{_safe(symbol)}</b> — ${price:,.2f}",
        f"الحالة: <b>{_safe(stage)}</b> | الحركة: <b>{move:+.1f}%</b>",
        f"درجة الرادار: <b>{score:.0f}/100</b> <i>(ترتيب وليست نسبة نجاح)</i>",
        "",
        "🧨 <b>السبب الأساسي</b>",
        _safe(cause_status),
    ]
    if cause_headline:
        lines.append(f"{_safe(cause_headline, 500)}")
    if cause_source:
        tier_text = f" — {_safe(source_tier)}" if source_tier else ""
        lines.append(f"المصدر: <b>{_safe(cause_source)}</b>{tier_text}")
    if amplifiers:
        lines.extend(["", "🔥 <b>عوامل التضخيم/التأكيد</b>"])
        lines.extend(f"• {_safe(item, 260)}" for item in amplifiers[:5])
    if halts:
        lines.extend(["", "⏸ <b>حالة السوق</b>"])
        for event in halts[:2]:
            lines.append(
                f"• {_safe(event.get('reason'))}: {_safe(event.get('note_ar'), 360)}"
            )
    lines.extend(
        [
            "",
            "⚠️ <i>تنبيه رادار بحثي؛ السهم لا يحتاج وجود عقود أوبشن حتى يظهر في هذا المسار.</i>",
        ]
    )
    return "\n".join(lines)


def _option_message(row: dict[str, Any]) -> str:
    symbol = str(row.get("symbol") or "").upper()
    side = str(row.get("option_type") or "").upper()
    expiration = str(row.get("expiration") or "")[:10]
    dte = int(_number(row.get("dte")))
    strike = _number(row.get("strike"))
    bid = _number(row.get("bid"))
    ask = _number(row.get("ask"))
    volume = int(_number(row.get("volume")))
    oi = int(_number(row.get("open_interest")))
    ratio = _number(row.get("vol_to_oi_ratio") or row.get("vol_oi"))
    delta = _number(row.get("delta"))
    gamma = _number(row.get("gamma"))
    theta = _number(row.get("theta"))
    iv = _number(row.get("iv"))
    spread = _number(row.get("spread_pct"))
    score = _number(row.get("score"))
    flow_score = _number(row.get("flow_momentum_score"))
    evidence = row.get("flow_evidence") if isinstance(row.get("flow_evidence"), dict) else {}
    reasons = [str(value) for value in row.get("rationale_ar", []) if str(value).strip()]

    lines = [
        "🎯 <b>بلاك بوكس Ω — مسار عقود الأوبشن</b>",
        "",
        f"<b>{_safe(symbol)} {side} {strike:g}</b>",
        f"الانتهاء: <b>{_safe(expiration)}</b> — {dte} DTE",
        f"Bid/Ask: <b>${bid:.2f} / ${ask:.2f}</b> — Spread≈{spread * 100:.1f}%",
        f"Volume: <b>{volume:,}</b> | OI: <b>{oi:,}</b> | Vol/OI: <b>{ratio:.2f}×</b>",
        f"Delta: {delta:+.2f} | Gamma: {gamma:.4f} | Theta: {theta:.4f} | IV: {iv:.1%}",
        f"Contract score: <b>{score:.0f}/100</b> | Flow score: <b>{flow_score:.0f}/100</b>",
        "",
        "🧠 <b>ليش ظهر العقد؟</b>",
    ]
    lines.extend(f"• {_safe(item, 390)}" for item in reasons[:5])
    pressure = str(evidence.get("execution_pressure_note_ar") or "").strip()
    oi_note = str(evidence.get("volume_vs_prior_oi_note_ar") or "").strip()
    if pressure or oi_note:
        lines.extend(["", "🔬 <b>تفسير الفلو بدون مبالغة</b>"])
        if pressure:
            lines.append(f"• {_safe(pressure, 430)}")
        if oi_note:
            lines.append(f"• {_safe(oi_note, 430)}")
    lines.extend(
        [
            "",
            "⚠️ <b>Sweep:</b> غير مؤكد من Snapshot وحده.",
            "⚠️ <b>Opening position:</b> غير مؤكد حتى يظهر تغير OI بعد التسوية.",
            "<i>هذا المسار يكتشف العقد بنفسه ولا ينتظر إشارة من مسار الأسهم.</i>",
        ]
    )
    return "\n".join(lines)


def send_stocks(payload: dict[str, Any], state: dict[str, Any]) -> int:
    minimum = _number(os.getenv("STOCK_ALERT_MIN_SCORE", "72"), 72.0)
    maximum = max(1, min(5, int(_number(os.getenv("STOCK_ALERT_MAX", "3"), 3))))
    rows = [row for row in payload.get("stocks", []) if isinstance(row, dict)]
    rows.sort(key=lambda row: _number(row.get("score")), reverse=True)
    sent_map = state.setdefault("sent", {})
    sent = 0
    for row in rows:
        if sent >= maximum:
            break
        score = _number(row.get("score"))
        stage = str(row.get("stage") or "WATCH").upper()
        if score < minimum or stage == "WATCH":
            continue
        symbol = str(row.get("symbol") or "").upper()
        cause = row.get("cause") if isinstance(row.get("cause"), dict) else {}
        fp = _fingerprint(
            [symbol, stage, round(score / 4) * 4, cause.get("status"), cause.get("headline")]
        )
        if sent_map.get(symbol) == fp:
            continue
        _send(_stock_message(row))
        sent_map[symbol] = fp
        sent += 1
    state["last_run_at"] = datetime.now(timezone.utc).isoformat()
    state["last_sent_count"] = sent
    state["path"] = "stocks"
    return sent


def send_options(payload: dict[str, Any], state: dict[str, Any]) -> int:
    readiness = payload.get("provider_readiness") if isinstance(payload.get("provider_readiness"), dict) else {}
    quote_ready = readiness.get("production_quote_ready") is True
    if not quote_ready:
        state["last_run_at"] = datetime.now(timezone.utc).isoformat()
        state["last_sent_count"] = 0
        state["path"] = "options"
        state["send_blocked"] = True
        state["send_block_reason"] = (
            f"provider_readiness={readiness.get('status', 'MISSING')}; "
            "production_quote_ready is not true"
        )
        return 0

    minimum = _number(os.getenv("OPTIONS_ALERT_MIN_SCORE", "65"), 65.0)
    maximum = max(1, min(6, int(_number(os.getenv("OPTIONS_ALERT_MAX", "4"), 4))))
    rows = [row for row in payload.get("contracts", []) if isinstance(row, dict)]
    rows.sort(
        key=lambda row: (
            _number(row.get("flow_rank_score")),
            _number(row.get("flow_momentum_score")),
            _number(row.get("score")),
        ),
        reverse=True,
    )
    sent_map = state.setdefault("sent", {})
    sent = 0
    for row in rows:
        if sent >= maximum:
            break
        score = _number(row.get("score"))
        if score < minimum:
            continue
        contract = str(row.get("contract_symbol") or "").upper().strip()
        if not contract:
            contract = _fingerprint(
                [row.get("symbol"), row.get("option_type"), row.get("expiration"), row.get("strike")]
            )
        fp = _fingerprint(
            [
                contract,
                round(_number(row.get("flow_momentum_score")) / 5) * 5,
                round(_number(row.get("vol_to_oi_ratio") or row.get("vol_oi")), 1),
                round(_number(row.get("ask")), 2),
            ]
        )
        if sent_map.get(contract) == fp:
            continue
        _send(_option_message(row))
        sent_map[contract] = fp
        sent += 1
    state["last_run_at"] = datetime.now(timezone.utc).isoformat()
    state["last_sent_count"] = sent
    state["path"] = "options"
    state["send_blocked"] = False
    state.pop("send_block_reason", None)
    return sent


def main() -> None:
    parser = argparse.ArgumentParser(description="Send independent stock/options BLACK BOX alerts")
    parser.add_argument("--path", choices=("stocks", "options"), required=True)
    parser.add_argument("--payload", required=True)
    parser.add_argument("--state", required=True)
    args = parser.parse_args()

    payload = _load(args.payload, {})
    state = _load(args.state, {"sent": {}})
    if not isinstance(payload, dict) or not isinstance(state, dict):
        raise RuntimeError("Invalid payload/state")
    expected = "stocks" if args.path == "stocks" else "options"
    if payload.get("path") != expected:
        raise RuntimeError(f"Expected {expected} payload, got {payload.get('path')!r}")

    sent = send_stocks(payload, state) if args.path == "stocks" else send_options(payload, state)
    _save(args.state, state)
    print(f"Independent Telegram sender: path={args.path} sent={sent}")


if __name__ == "__main__":
    main()
