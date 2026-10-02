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


DEFAULT_STATE = Path("data/live/omega_watch_alert_state.json")


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
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(destination)


def _safe(value: Any, limit: int = 600) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return html.escape(text)


def _age_minutes(payload: dict[str, Any]) -> float | None:
    raw = str(payload.get("generated_at") or payload.get("updated_at") or "").strip()
    if not raw:
        return None
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - stamp.astimezone(timezone.utc)).total_seconds() / 60.0)


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    intelligence = payload.get("option_contract_intelligence")
    if not isinstance(intelligence, dict):
        return []
    by_symbol = intelligence.get("by_symbol")
    if not isinstance(by_symbol, dict):
        return []

    rows: list[dict[str, Any]] = []
    for symbol, item in by_symbol.items():
        if not isinstance(item, dict):
            continue
        primary = item.get("primary")
        if not isinstance(primary, dict):
            continue
        if str(primary.get("alert_stage") or "").upper() != "WATCH":
            continue
        watch = primary.get("watch_decision") if isinstance(primary.get("watch_decision"), dict) else {}
        if watch.get("approved") is not True:
            continue
        row = dict(primary)
        row["_symbol"] = str(symbol).upper()
        row["_target_dte"] = item.get("target_dte")
        row["_preferred_dte_band"] = item.get("preferred_dte_band") or []
        row["_catalyst_verification"] = item.get("catalyst_verification")
        rows.append(row)

    rows.sort(
        key=lambda row: (
            _number((row.get("watch_decision") or {}).get("evidence_score")),
            _number((row.get("option_explosion") or {}).get("score")),
            _number(row.get("contract_rank")),
        ),
        reverse=True,
    )
    return rows


def _fingerprint(row: dict[str, Any]) -> str:
    watch = row.get("watch_decision") if isinstance(row.get("watch_decision"), dict) else {}
    explosion = row.get("option_explosion") if isinstance(row.get("option_explosion"), dict) else {}
    raw = "|".join(
        [
            str(row.get("_symbol") or row.get("symbol") or ""),
            str(row.get("side") or ""),
            str(row.get("contract_symbol") or ""),
            str(row.get("dte") or ""),
            str(round(_number(watch.get("evidence_score")) / 4.0) * 4),
            str(round(_number(explosion.get("score")) / 4.0) * 4),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _message(row: dict[str, Any]) -> str:
    symbol = str(row.get("_symbol") or row.get("symbol") or "").upper()
    side = str(row.get("side") or "").upper()
    strike = _number(row.get("strike"))
    dte = int(_number(row.get("dte")))
    expiration = str(row.get("expiration") or "")[:10]
    bid = _number(row.get("bid"))
    ask = _number(row.get("ask"))
    spread = _number(row.get("spread_pct"))
    rank = _number(row.get("contract_rank"))
    watch = row.get("watch_decision") if isinstance(row.get("watch_decision"), dict) else {}
    explosion = row.get("option_explosion") if isinstance(row.get("option_explosion"), dict) else {}
    explosion_score = _number(explosion.get("score"))
    explosion_label = str(explosion.get("label") or "LOW")
    target_dte = _number(row.get("_target_dte"))
    band = row.get("_preferred_dte_band") if isinstance(row.get("_preferred_dte_band"), list) else []
    band_text = "—"
    if len(band) >= 2:
        band_text = f"{_number(band[0]):g}–{_number(band[1]):g}D"
    v11 = row.get("v11_decision") if isinstance(row.get("v11_decision"), dict) else {}
    blockers = [str(x) for x in v11.get("blockers", []) if str(x).strip()]
    risks = [str(x) for x in row.get("risks_ar", []) if str(x).strip()]
    side_reason = str(row.get("side_reason_ar") or "")
    expiry_reason = str(row.get("expiry_reason_ar") or "")
    flow_reason = str(row.get("flow_reason_ar") or "")
    delta = _number(row.get("delta"))
    gamma = _number(row.get("gamma"))
    iv = _number(row.get("iv"))
    vol_oi = _number(row.get("vol_to_oi_ratio"))

    side_emoji = "🟢" if side == "CALL" else "🔴"
    blocker_text = " | ".join(blockers[:4]) if blockers else "بيانات التنفيذ لم تكتمل بعد"
    risk_text = " | ".join(risks[:3]) if risks else "لا يوجد مانع بحثي حرج ظاهر"

    return "\n".join(
        [
            "🟡 <b>BLACK BOX Ω — مراقبة مبكرة OPTIONS</b>",
            f"{side_emoji} <b>{_safe(symbol)} {side}</b> • Evidence <b>{_number(watch.get('evidence_score')):.0f}/100</b>",
            f"🎯 العقد: <b>{strike:g} {side}</b> • {expiration} • <b>{dte}D</b>",
            f"💵 B/A <b>{bid:.2f}/{ask:.2f}</b> • Spread <b>{spread * 100:.1f}%</b>",
            f"⏱ أفق العقد: Target <b>{target_dte:g}D</b> • Preferred <b>{band_text}</b>",
            f"⚡ قابلية تمدد البريميوم: <b>{explosion_score:.0f}/100 {_safe(explosion_label, 20)}</b> • Contract Rank <b>{rank:.0f}</b>",
            f"📐 Δ <b>{delta:+.2f}</b> • Γ <b>{gamma:.4f}</b> • IV <b>{iv:.0%}</b> • V/OI <b>{vol_oi:.2f}×</b>",
            f"🧭 {_safe(side_reason, 500)}",
            f"📅 {_safe(expiry_reason, 600)}",
            f"🔎 {_safe(flow_reason, 700)}",
            f"⚠️ المخاطر: {_safe(risk_text, 650)}",
            f"🛡 سبب عدم التأكيد V11: {_safe(blocker_text, 750)}",
            "",
            "<b>الحالة: WATCH فقط — ليست إشارة دخول مؤكدة.</b>",
            "<i>إذا اكتملت أدلة التنفيذ تنتقل الإشارة إلى CONFIRMED بدل تخفيف بوابة V11.</i>",
        ]
    )


def send(payload: dict[str, Any], state: dict[str, Any]) -> int:
    age = _age_minutes(payload)
    max_age = _number(os.getenv("OMEGA_WATCH_PAYLOAD_MAX_AGE_MINUTES", "90"), 90.0)
    if age is None or age > max_age:
        state.update(
            {
                "last_run_at": datetime.now(timezone.utc).isoformat(),
                "last_sent_count": 0,
                "mode": "stale_blocked",
                "payload_age_minutes": age,
            }
        )
        return 0

    maximum = int(_number(os.getenv("OMEGA_WATCH_ALERT_MAX", "20"), 20.0))
    maximum = max(1, min(maximum, 50))
    sent_map = state.setdefault("sent", {})
    sent = 0
    for row in _rows(payload):
        if sent >= maximum:
            break
        symbol = str(row.get("_symbol") or row.get("symbol") or "").upper()
        side = str(row.get("side") or "").upper()
        key = f"WATCH:{symbol}:{side}"
        fp = _fingerprint(row)
        previous = sent_map.get(key)
        previous_fp = str(previous.get("fingerprint") or "") if isinstance(previous, dict) else str(previous or "")
        if previous_fp == fp:
            continue
        result = send_html_message(_message(row))
        sent_map[key] = {
            "fingerprint": fp,
            "message_id": getattr(result, "message_id", None),
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "side": side,
            "contract_symbol": row.get("contract_symbol"),
            "stage": "WATCH",
        }
        sent += 1

    state.update(
        {
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "last_sent_count": sent,
            "mode": "omega_watch",
            "payload_age_minutes": round(age, 2),
            "state_schema": "omega_watch_registry_v1",
        }
    )
    return sent


def main() -> None:
    parser = argparse.ArgumentParser(description="Send early Omega WATCH option alerts without weakening V11.")
    parser.add_argument("--payload", default="public/data/latest.json")
    parser.add_argument("--state", default=str(DEFAULT_STATE))
    args = parser.parse_args()
    payload = _load(args.payload, {})
    state = _load(args.state, {"sent": {}})
    if not isinstance(payload, dict):
        raise RuntimeError("Omega payload is not a JSON object")
    if not isinstance(state, dict):
        state = {"sent": {}}
    try:
        count = send(payload, state)
    finally:
        _save(args.state, state)
    print(f"Omega WATCH sender: sent={count} mode={state.get('mode')}")


if __name__ == "__main__":
    main()
