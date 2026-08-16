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

from options_radar.telegram_transport import send_html_message


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


def _safe(value: Any, limit: int = 360) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return html.escape(text)


def _send(text: str):
    return send_html_message(text)


def _fingerprint(parts: list[Any]) -> str:
    raw = "|".join(str(value or "") for value in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _stored_fingerprint(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("fingerprint") or "")
    return str(value or "")


def _stage_ar(stage: str) -> str:
    return {
        "WATCH": "مراقبة",
        "PRESSURE_BUILDING": "بناء ضغط",
        "IGNITION": "بداية انطلاقة",
        "EXPLOSION": "حركة قوية",
        "EXTENDED": "ممتدة/متأخرة",
    }.get(stage.upper(), stage or "غير مصنف")


def _side_ar(side: str) -> str:
    return "CALL ↑" if side.upper() == "CALL" else "PUT ↓"


def _priority_ar(score: float) -> str:
    if score >= 88:
        return "عالية جدًا"
    if score >= 80:
        return "عالية"
    if score >= 72:
        return "متوسطة"
    return "منخفضة"


def _stock_message(row: dict[str, Any]) -> str:
    symbol = str(row.get("symbol") or "").upper()
    score = _number(row.get("score"))
    price = _number(row.get("price"))
    move = _number(row.get("move_pct"))
    stage = str(row.get("stage") or "WATCH").upper()
    cause = row.get("cause") if isinstance(row.get("cause"), dict) else {}
    cause_status = str(cause.get("status_ar") or "السبب الأساسي غير مثبت")
    cause_headline = str(cause.get("headline") or "").strip()
    amplifiers = [str(value) for value in row.get("amplifiers", []) if str(value).strip()]
    halts = [value for value in row.get("market_status_evidence", []) if isinstance(value, dict)]
    arrow = "↑" if move > 0 else ("↓" if move < 0 else "↔")

    lines = [
        f"🚀 <b>Ω | {symbol} | {_safe(_stage_ar(stage), 60)} | {score:.0f}/100</b>",
        f"💵 <b>${price:,.2f}</b> | {arrow} <b>{move:+.1f}%</b> | أولوية <b>{_safe(_priority_ar(score), 40)}</b>",
        f"🧨 <b>السبب:</b> {_safe(cause_status, 220)}",
    ]
    if cause_headline:
        lines.append(f"📰 {_safe(cause_headline, 320)}")
    if amplifiers:
        lines.append(f"⚡ <b>دعم:</b> {_safe(' | '.join(amplifiers[:2]), 240)}")
    if halts:
        event = halts[0]
        lines.append(f"⏸ {_safe(event.get('reason'), 80)} | {_safe(event.get('note_ar'), 180)}")

    if "غير مثبت" in cause_status or "NO_PRIMARY" in str(cause.get("status") or ""):
        risk = "السبب الرسمي غير مثبت؛ راقب استمرار السعر والحجم."
    elif stage == "EXTENDED":
        risk = "الحركة ممتدة؛ المطاردة أعلى مخاطرة."
    else:
        risk = "تضعف الفكرة إذا اختفى الحجم أو انعكس السعر."
    lines.extend(
        [
            f"⚠️ {_safe(risk, 220)}",
            "<i>درجة الرادار ترتيب وليست نسبة نجاح؛ مسار الأسهم مستقل عن الأوبشن.</i>",
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
    theta = _number(row.get("theta"))
    iv = _number(row.get("iv"))
    spread = _number(row.get("spread_pct"))
    score = _number(row.get("score"))
    flow_score = _number(row.get("flow_momentum_score"))
    reasons = [str(value) for value in row.get("rationale_ar", []) if str(value).strip()]
    readiness = row.get("_provider_readiness") if isinstance(row.get("_provider_readiness"), dict) else {}
    icon = "🟢" if side == "CALL" else "🔴"

    lines = [
        f"{icon} <b>Ω | {symbol} {_side_ar(side)} | {score:.0f}/100</b>",
        f"🎯 <b>{strike:g}{'C' if side == 'CALL' else 'P'} • {expiration} • {dte}D</b> | B/A <b>${bid:.2f}/${ask:.2f}</b> | Spr <b>{spread * 100:.1f}%</b>",
        f"⚡ Flow <b>{flow_score:.0f}</b> | Δ <b>{delta:+.2f}</b> | Θ <b>{theta:.3f}</b> | IV <b>{iv:.0%}</b> | V/OI <b>{ratio:.2f}×</b>",
        f"📊 Vol/OI <b>{volume:,}/{oi:,}</b> | بيانات <b>{_safe(readiness.get('status') or 'UNKNOWN', 80)}</b>",
    ]
    if reasons:
        lines.append(f"✅ {_safe(' | '.join(reasons[:2]), 420)}")
    lines.extend(
        [
            "⚠️ <i>السويب/فتح مركز جديد غير مؤكد من Snapshot وحده.</i>",
            "<i>مسار الأوبشن مستقل عن رادار الأسهم.</i>",
        ]
    )
    return "\n".join(lines)


def _record(fp: str, text: str, result: Any, **extra: Any) -> dict[str, Any]:
    return {
        "fingerprint": fp,
        "message_id": getattr(result, "message_id", None),
        "text": text,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        **extra,
    }


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
        fp = _fingerprint([symbol, stage, round(score / 4) * 4, cause.get("status"), cause.get("headline")])
        if _stored_fingerprint(sent_map.get(symbol)) == fp:
            continue
        text = _stock_message(row)
        result = _send(text)
        sent_map[symbol] = _record(fp, text, result, symbol=symbol, kind="stocks", stage=stage)
        sent += 1
    state["last_run_at"] = datetime.now(timezone.utc).isoformat()
    state["last_sent_count"] = sent
    state["path"] = "stocks"
    state["state_schema"] = "telegram_message_registry_v1"
    return sent


def send_options(payload: dict[str, Any], state: dict[str, Any]) -> int:
    readiness = payload.get("provider_readiness") if isinstance(payload.get("provider_readiness"), dict) else {}
    if readiness.get("production_quote_ready") is not True:
        state["last_run_at"] = datetime.now(timezone.utc).isoformat()
        state["last_sent_count"] = 0
        state["path"] = "options"
        state["blocked_reason"] = str(readiness.get("status") or "PROVIDER_NOT_READY")
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
            contract = _fingerprint([row.get("symbol"), row.get("option_type"), row.get("expiration"), row.get("strike")])
        fp = _fingerprint(
            [
                contract,
                round(_number(row.get("flow_momentum_score")) / 5) * 5,
                round(_number(row.get("vol_to_oi_ratio") or row.get("vol_oi")), 1),
                round(_number(row.get("ask")), 2),
            ]
        )
        if _stored_fingerprint(sent_map.get(contract)) == fp:
            continue
        message_row = dict(row)
        message_row["_provider_readiness"] = readiness
        text = _option_message(message_row)
        result = _send(text)
        sent_map[contract] = _record(
            fp,
            text,
            result,
            symbol=str(row.get("symbol") or "").upper(),
            direction=str(row.get("option_type") or "").upper(),
            contract_symbol=contract,
            kind="options",
        )
        sent += 1
    state["last_run_at"] = datetime.now(timezone.utc).isoformat()
    state["last_sent_count"] = sent
    state["path"] = "options"
    state["state_schema"] = "telegram_message_registry_v1"
    state.pop("blocked_reason", None)
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

    sent = 0
    try:
        sent = send_stocks(payload, state) if args.path == "stocks" else send_options(payload, state)
    finally:
        # Save successful messages even if a later send fails. This preserves
        # idempotency across retries and prevents duplicate already-sent alerts.
        _save(args.state, state)
    print(f"Independent Telegram sender: path={args.path} sent={sent}")


if __name__ == "__main__":
    main()
