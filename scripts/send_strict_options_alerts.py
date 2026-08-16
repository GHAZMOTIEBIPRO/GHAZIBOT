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


def _fingerprint(parts: list[Any]) -> str:
    raw = "|".join(str(value or "") for value in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _payload_age_minutes(payload: dict[str, Any]) -> float | None:
    generated = str(payload.get("generated_at") or "").strip()
    if not generated:
        return None
    try:
        timestamp = datetime.fromisoformat(generated.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds() / 60.0
    return max(0.0, age)


def _send(text: str):
    return send_html_message(text)


def _stored_fingerprint(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("fingerprint") or "")
    return str(value or "")


def _message(row: dict[str, Any], *, mode: str, readiness: dict[str, Any]) -> str:
    symbol = str(row.get("symbol") or "").upper()
    direction = str(row.get("direction_label") or row.get("direction") or row.get("option_type") or "").upper()
    expiration = str(row.get("expiration") or "")[:10]
    strike = _number(row.get("strike"))
    dte = int(_number(row.get("dte")))
    bid = _number(row.get("bid"))
    ask = _number(row.get("ask"))
    spread = _number(row.get("spread_pct"))
    strict = _number(row.get("strict_score"))
    grade = str(row.get("signal_grade") or row.get("strict_grade") or "")
    delta = _number(row.get("delta"))
    iv = _number(row.get("iv"))
    vol_oi = _number(row.get("vol_to_oi_ratio") or row.get("vol_oi"))
    flow = _number(row.get("flow_momentum_score"))
    rr = _number(row.get("reward_risk_1"))
    call_wall = row.get("call_wall")
    put_wall = row.get("put_wall")
    gamma_context = str(row.get("gamma_context") or "غير متاح")
    gamma_coverage = _number(row.get("gamma_coverage_pct"))
    oi_coverage = _number(row.get("oi_coverage_pct"))
    occ = row.get("occ_side_context") if isinstance(row.get("occ_side_context"), dict) else {}
    reasons = [str(value) for value in row.get("strict_reasons", []) if str(value).strip()]
    emoji = "🟢" if direction == "CALL" else "🔴"
    side_letter = "C" if direction == "CALL" else "P"
    mode_text = "إنتاجي" if mode == "production" else "مجاني/صارم"

    lines = [
        f"{emoji} <b>Ω | {symbol} {direction} {grade} | {strict:.0f}/100</b>",
        f"🎯 <b>{strike:g}{side_letter} • {expiration} • {dte}D</b> | B/A <b>${bid:.2f}/${ask:.2f}</b> | Spr <b>{spread * 100:.1f}%</b>",
        f"⚡ Flow <b>{flow:.0f}</b> | R/R <b>{rr:.2f}</b> | Δ <b>{delta:+.2f}</b> | IV <b>{iv:.0%}</b> | V/OI <b>{vol_oi:.2f}×</b>",
        f"🧲 GEX <b>{_safe(gamma_context, 80)}</b> | CW <b>{_safe(call_wall, 40)}</b> | PW <b>{_safe(put_wall, 40)}</b> | Γ/OI <b>{gamma_coverage:.0f}/{oi_coverage:.0f}%</b>",
    ]
    if occ.get("available") is True:
        lines.append(
            f"🏛 OCC C/P <b>{int(_number(occ.get('call_volume'))):,}/{int(_number(occ.get('put_volume'))):,}</b> | {_safe(occ.get('dominance_ratio'), 30)}×"
        )
    if reasons:
        lines.append(f"✅ {_safe(' | '.join(reasons[:2]), 520)}")
    lines.extend(
        [
            f"🛰 <b>{mode_text}</b> • {_safe(readiness.get('status') or 'UNKNOWN', 80)}",
            "⚠️ <i>GEX Proxy والترشيح احتمالي؛ مسار الأوبشن مستقل عن الأسهم.</i>",
        ]
    )
    return "\n".join(lines)


def select_rows(payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    readiness = payload.get("provider_readiness") if isinstance(payload.get("provider_readiness"), dict) else {}
    if readiness.get("production_quote_ready") is True:
        rows = payload.get("production_directional_signals") or payload.get("directional_signals") or []
        return "production", [row for row in rows if isinstance(row, dict)], readiness
    free_enabled = os.getenv("OPTIONS_FREE_ALERTS_ENABLED", "true").strip().lower() not in {"0", "false", "no"}
    if not free_enabled:
        return "blocked", [], readiness
    rows = payload.get("free_directional_signals") or []
    return "free", [row for row in rows if isinstance(row, dict)], readiness


def send(payload: dict[str, Any], state: dict[str, Any]) -> int:
    age_minutes = _payload_age_minutes(payload)
    max_age = _number(os.getenv("OPTIONS_PAYLOAD_MAX_AGE_MINUTES", "45"), 45.0)
    if age_minutes is None or age_minutes > max_age:
        state.update(
            {
                "last_run_at": datetime.now(timezone.utc).isoformat(),
                "last_sent_count": 0,
                "path": "options",
                "mode": "stale_blocked",
                "payload_age_minutes": age_minutes,
                "blocked_reason": "MISSING_OR_STALE_OPTIONS_PAYLOAD",
            }
        )
        return 0

    mode, rows, readiness = select_rows(payload)
    if mode == "blocked":
        state.update(
            {
                "last_run_at": datetime.now(timezone.utc).isoformat(),
                "last_sent_count": 0,
                "path": "options",
                "mode": mode,
                "payload_age_minutes": round(age_minutes, 2),
                "blocked_reason": str(readiness.get("status") or "PROVIDER_NOT_READY"),
            }
        )
        return 0

    minimum = _number(
        os.getenv("OPTIONS_FREE_ALERT_MIN_SCORE" if mode == "free" else "OPTIONS_ALERT_MIN_SCORE", "87" if mode == "free" else "85"),
        87.0 if mode == "free" else 85.0,
    )
    maximum = max(1, min(5, int(_number(os.getenv("OPTIONS_ALERT_MAX", "3"), 3))))
    rows.sort(
        key=lambda row: (
            _number(row.get("strict_score")),
            _number(row.get("side_consensus_score")),
            _number(row.get("flow_momentum_score")),
        ),
        reverse=True,
    )
    sent_map = state.setdefault("sent", {})
    sent_symbols: set[str] = set()
    sent = 0
    for row in rows:
        if sent >= maximum:
            break
        symbol = str(row.get("symbol") or "").upper().strip()
        direction = str(row.get("direction_label") or row.get("direction") or "").upper()
        strict = _number(row.get("strict_score"))
        grade = str(row.get("signal_grade") or row.get("strict_grade") or "")
        if not symbol or direction not in {"CALL", "PUT"} or symbol in sent_symbols:
            continue
        if strict < minimum or grade not in {"A", "A+"}:
            continue
        if mode == "free" and row.get("free_alert_eligible") is not True:
            continue
        contract = str(row.get("contract_symbol") or f"{symbol}:{direction}:{row.get('expiration')}:{row.get('strike')}")
        fp = _fingerprint(
            [symbol, direction, contract, round(strict / 3) * 3, round(_number(row.get("ask")), 2)]
        )
        key = f"{symbol}:{direction}"
        if _stored_fingerprint(sent_map.get(key)) == fp:
            continue
        text = _message(row, mode=mode, readiness=readiness)
        result = _send(text)
        message_id = getattr(result, "message_id", None)
        sent_map[key] = {
            "fingerprint": fp,
            "message_id": message_id,
            "text": text,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "direction": direction,
            "contract_symbol": contract,
            "kind": "options",
        }
        sent_symbols.add(symbol)
        sent += 1

    state.update(
        {
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "last_sent_count": sent,
            "path": "options",
            "mode": mode,
            "minimum_score": minimum,
            "payload_age_minutes": round(age_minutes, 2),
            "state_schema": "telegram_message_registry_v1",
        }
    )
    state.pop("blocked_reason", None)
    return sent


def main() -> None:
    parser = argparse.ArgumentParser(description="Send strict BLACK BOX CALL/PUT option alerts")
    parser.add_argument("--payload", required=True)
    parser.add_argument("--state", required=True)
    args = parser.parse_args()
    payload = _load(args.payload, {})
    state = _load(args.state, {"sent": {}})
    if not isinstance(payload, dict) or payload.get("path") != "options":
        raise RuntimeError("Expected independent options payload")
    if not isinstance(state, dict):
        state = {"sent": {}}
    sent = 0
    try:
        sent = send(payload, state)
    finally:
        # Persist successful sends even if a later message fails, so the next
        # run cannot duplicate already-delivered alerts.
        _save(args.state, state)
    print(f"Strict options Telegram sender: sent={sent} mode={state.get('mode')} min={state.get('minimum_score')}")


if __name__ == "__main__":
    main()
