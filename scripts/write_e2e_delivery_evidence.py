from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from options_radar.v11_gate import evaluate_v11_signal


def _load(path: Path, default: Any) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return value


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _signal_id(row: dict[str, Any]) -> str:
    raw = "|".join(
        str(row.get(key) or "")
        for key in ("symbol", "direction", "option_type", "contract_symbol", "expiration", "strike")
    )
    return "sig_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _candidate_evidence(row: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    v11 = evaluate_v11_signal(row)
    symbol = str(row.get("symbol") or "").upper()
    direction = str(row.get("direction_label") or row.get("direction") or row.get("option_type") or "").upper()
    sent = state.get("sent") if isinstance(state.get("sent"), dict) else {}
    delivery = sent.get(f"{symbol}:{direction}") if isinstance(sent, dict) else {}
    provider = str(row.get("source") or row.get("quote_source") or "unknown")
    fields = {
        "bid": row.get("bid") is not None,
        "ask": row.get("ask") is not None,
        "quote_timestamp": bool(row.get("quote_timestamp")),
        "strike": row.get("strike") is not None,
        "expiration": bool(row.get("expiration")),
        "dte": row.get("dte") is not None,
        "volume": row.get("volume") is not None,
        "open_interest": row.get("open_interest") is not None,
        "greeks": any(row.get(key) is not None for key in ("delta", "gamma", "theta", "vega", "iv")),
        "spread": row.get("spread_pct") is not None,
    }
    return {
        "signal_id": str(row.get("signal_id") or _signal_id(row)),
        "symbol": symbol,
        "direction": direction,
        "analysis": {
            "strict_score": _number(row.get("strict_score")),
            "signal_grade": str(row.get("signal_grade") or row.get("strict_grade") or ""),
            "catalyst_present": bool(row.get("catalyst") or row.get("catalyst_url") or row.get("event_date")),
        },
        "provider_validation": {
            "provider": provider,
            "source_provenance": provider,
            "quote_timestamp": row.get("quote_timestamp"),
            "field_presence": fields,
            "fabric_independent_source_count": int(_number(row.get("fabric_independent_source_count")) or 0),
        },
        "contract_selection": {
            "contract_symbol": str(row.get("contract_symbol") or ""),
            "strike": _number(row.get("strike")),
            "expiration": str(row.get("expiration") or "")[:10],
            "dte": _number(row.get("dte")),
            "volume": _number(row.get("volume")),
            "open_interest": _number(row.get("open_interest")),
            "spread_pct": _number(row.get("spread_pct")),
        },
        "v11": {
            "version": v11.get("version"),
            "state": v11.get("state"),
            "approved": bool(v11.get("approved")),
            "telegram_eligible": bool(v11.get("telegram_eligible")),
            "independent_sources": v11.get("independent_sources"),
            "blockers": v11.get("blockers", []),
        },
        "telegram": {
            "eligible_delivery_record": bool(delivery),
            "message_id": delivery.get("message_id") if isinstance(delivery, dict) else None,
        },
    }


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value.astimezone(timezone.utc) if value.tzinfo else None


def _delivery_diagnosis(
    payload: dict[str, Any],
    state: dict[str, Any],
    *,
    market_open: bool | None,
    candidates: int,
    readiness: dict[str, Any],
) -> tuple[str, str]:
    if market_open is False:
        return "MARKET_CLOSED", "السوق الأمريكي مغلق؛ لم يبدأ فحص العقود ولم يحاول البوت إرسال توصيات."
    if market_open is None:
        return "SESSION_UNVERIFIED", "تعذّر التحقق من جلسة السوق؛ لا يمكن إثبات تنفيذ فحص العقود."
    if not payload:
        return "PAYLOAD_MISSING", "الفحص لم ينتج ملف عقود قابلًا للتحقق."
    if readiness.get("production_quote_ready") is not True:
        return "NO_EXECUTION_GRADE_QUOTES", (
            "بيانات الأوبشن المتوفرة بحثية أو متأخرة؛ لا تتوافر أسعار تنفيذية موثقة. "
            "نجاح التشغيل لا يعني وجود عقود مؤهلة للإرسال."
        )
    if candidates == 0:
        return "NO_CANDIDATES", "مصدر الأسعار جاهز، لكن لم تظهر عقود مرشحة في هذه الدورة."
    if state.get("blocked_reason"):
        return "SENDER_BLOCKED", "أوقف مرسل العقود عملية الإرسال وسجل سبب الحظر."
    if state.get("last_sent_count", 0):
        return "SENDER_REPORTED_MESSAGES", "ذكر مرسل Telegram إرسال رسائل؛ يلزم ربط التقرير بنفس دورة التشغيل."
    return "NO_REPORTED_SEND", "لم يُسجل إرسال جديد؛ قد تكون الإشارات غير مؤهلة أو مكررة."


def build_evidence(
    payload: dict[str, Any], state: dict[str, Any], *, run_id: str,
    now: datetime, market_open: bool | None = True,
) -> dict[str, Any]:
    readiness = payload.get("provider_readiness") if isinstance(payload.get("provider_readiness"), dict) else {}
    rows: list[dict[str, Any]] = []
    for key in ("production_directional_signals", "free_directional_signals", "research_directional_signals", "directional_signals"):
        value = payload.get(key)
        if isinstance(value, list):
            rows.extend(row for row in value if isinstance(row, dict))
            if rows:
                break
    diagnosis, diagnosis_ar = _delivery_diagnosis(
        payload, state, market_open=market_open,
        candidates=len(rows), readiness=readiness,
    )
    state_run = _parse_utc(state.get("last_run_at"))
    payload_time = _parse_utc(payload.get("generated_at"))
    # State restored from earlier runs can contain valid historic message IDs.
    # It must not be called evidence of delivery in this scan.
    state_matches_payload = (
        market_open is True
        and state_run is not None
        and payload_time is not None
        and payload_time - state_run <= timedelta(minutes=2)
        and state_run >= payload_time - timedelta(minutes=2)
        and state_run <= now.astimezone(timezone.utc) + timedelta(minutes=5)
    )
    return {
        "diagnosis": {
            "reason_code": diagnosis,
            "note_ar": diagnosis_ar,
            "market_open_verified": market_open,
            "delivery_state_current_scan": state_matches_payload,
            "new_messages_confirmed_for_scan": (
                int(_number(state.get("last_sent_count")) or 0) if state_matches_payload else None
            ),
        },
        "schema_version": 1,
        "decision_authority": False,
        "contains_secrets": False,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "run_id": str(run_id),
        "market_scan": {
            "payload_generated_at": payload.get("generated_at"),
            "candidate_count": len(rows),
            "path": payload.get("path", "options"),
        },
        "provider_readiness": {
            "status": readiness.get("status"),
            "production_quote_ready": bool(readiness.get("production_quote_ready")),
            "production_flow_ready": bool(readiness.get("production_flow_ready")),
        },
        "candidates": [_candidate_evidence(row, state) for row in rows[:25]],
        "telegram": {
            "telegram_ready": os.getenv("TELEGRAM_READY", "false").strip().lower() == "true",
            "sent_count": int(_number(state.get("last_sent_count")) or 0),
            "message_ids": sorted(
                int(item.get("message_id"))
                for item in (state.get("sent", {}) or {}).values()
                if isinstance(item, dict) and str(item.get("message_id") or "").isdigit()
            ),
            "mode": state.get("mode"),
            "blocked_reason": state.get("blocked_reason"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Write bounded, non-sensitive BLACK BOX E2E evidence")
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--run-id", default=os.getenv("GITHUB_RUN_ID", "unknown"))
    parser.add_argument("--now", default=None)
    parser.add_argument(
        "--market-open", choices=("true", "false", "unknown"), default="true",
        help="Verified XNYS session gate from the originating workflow",
    )
    args = parser.parse_args()
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc)
    market_open = {"true": True, "false": False, "unknown": None}[args.market_open]
    evidence = build_evidence(
        _load(args.payload, {}), _load(args.state, {"sent": {}}),
        run_id=args.run_id, now=now, market_open=market_open,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Options E2E diagnosis: {evidence['diagnosis']['reason_code']}; sender-run-evidence={evidence['diagnosis']['delivery_state_current_scan']}")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
