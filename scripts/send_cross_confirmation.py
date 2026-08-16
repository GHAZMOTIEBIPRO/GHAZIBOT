from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.telegram_transport import TELEGRAM_TEXT_MAX_CHARS, edit_html_message


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _load(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save(path: str | Path, payload: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(destination)


def _parse(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _fresh(payload: dict[str, Any], now: datetime, minutes: int) -> bool:
    generated = _parse(payload.get("generated_at"))
    if generated is None:
        return False
    age = (now - generated).total_seconds() / 60.0
    return -2 <= age <= minutes


def _safe(value: Any) -> str:
    return html.escape(str(value or "").strip())


def _fingerprint(values: list[Any]) -> str:
    raw = "|".join(str(value or "") for value in values)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _stage_ar(stage: str) -> str:
    return {
        "WATCH": "مراقبة",
        "PRESSURE_BUILDING": "بناء ضغط",
        "IGNITION": "بداية انطلاقة",
        "EXPLOSION": "حركة قوية",
        "EXTENDED": "ممتدة",
    }.get(stage.upper(), stage or "غير مصنف")


def _alignment(move_pct: float, side: str) -> str:
    side = side.upper()
    if move_pct > 0 and side == "CALL":
        return "متوافق ✅"
    if move_pct < 0 and side == "PUT":
        return "متوافق ✅"
    if move_pct == 0:
        return "محايد ⚪"
    return "غير متوافق ⚠️"


def build_matches(stock_payload: dict[str, Any], options_payload: dict[str, Any]) -> list[dict[str, Any]]:
    stocks = {
        str(row.get("symbol") or "").upper(): row
        for row in stock_payload.get("stocks", [])
        if isinstance(row, dict) and str(row.get("symbol") or "").strip()
    }
    contracts_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in options_payload.get("contracts", []):
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper().strip()
        if symbol:
            contracts_by_symbol.setdefault(symbol, []).append(row)

    matches: list[dict[str, Any]] = []
    for symbol in sorted(set(stocks) & set(contracts_by_symbol)):
        stock = stocks[symbol]
        contracts = sorted(
            contracts_by_symbol[symbol],
            key=lambda row: (
                _number(row.get("flow_rank_score")),
                _number(row.get("flow_momentum_score")),
                _number(row.get("score")),
            ),
            reverse=True,
        )
        if contracts:
            matches.append(
                {
                    "symbol": symbol,
                    "stock": stock,
                    "contract": contracts[0],
                    "combined_rank": _number(stock.get("score")) + _number(contracts[0].get("flow_momentum_score")),
                }
            )
    matches.sort(key=lambda row: row["combined_rank"], reverse=True)
    return matches


def _record_for_symbol(symbol: str, stock_state: dict[str, Any], options_state: dict[str, Any]) -> dict[str, Any] | None:
    # Prefer the richer strict-options card when it exists; otherwise update the stock card.
    option_records: list[dict[str, Any]] = []
    for key, value in (options_state.get("sent") or {}).items():
        if not isinstance(value, dict):
            continue
        record_symbol = str(value.get("symbol") or "").upper()
        if record_symbol == symbol or str(key).upper().startswith(f"{symbol}:"):
            if value.get("message_id") and value.get("text"):
                option_records.append(value)
    if option_records:
        option_records.sort(key=lambda value: str(value.get("sent_at") or ""), reverse=True)
        return option_records[0]

    stock_record = (stock_state.get("sent") or {}).get(symbol)
    if isinstance(stock_record, dict) and stock_record.get("message_id") and stock_record.get("text"):
        return stock_record
    return None


def _confirmation_note(stock: dict[str, Any], contract: dict[str, Any]) -> str:
    stage = str(stock.get("stage") or "WATCH").upper()
    stock_score = _number(stock.get("score"))
    move_pct = _number(stock.get("move_pct"))
    side = str(contract.get("option_type") or "").upper()
    flow_score = _number(contract.get("flow_momentum_score"))
    option_score = _number(contract.get("score"))
    return (
        "🔗 <b>تأكيد مستقل:</b> "
        f"السهم {_safe(_stage_ar(stage))} {move_pct:+.1f}%/{stock_score:.0f} + "
        f"الأوبشن {_safe(side)} {option_score:.0f} (Flow {flow_score:.0f}) — "
        f"<b>{_safe(_alignment(move_pct, side))}</b>"
    )


def send_matches(
    stock_payload: dict[str, Any],
    options_payload: dict[str, Any],
    state: dict[str, Any],
    *,
    stock_alert_state: dict[str, Any] | None = None,
    options_alert_state: dict[str, Any] | None = None,
    freshness_minutes: int = 45,
    maximum: int = 2,
) -> int:
    now = datetime.now(timezone.utc)
    if not _fresh(stock_payload, now, freshness_minutes) or not _fresh(options_payload, now, freshness_minutes):
        return 0

    readiness = options_payload.get("provider_readiness") if isinstance(options_payload.get("provider_readiness"), dict) else {}
    if readiness.get("production_quote_ready") is not True:
        state["last_run_at"] = now.isoformat()
        state["last_sent_count"] = 0
        state["blocked_reason"] = str(readiness.get("status") or "PROVIDER_NOT_READY")
        return 0

    stock_alert_state = stock_alert_state or {}
    options_alert_state = options_alert_state or {}
    sent_map = state.setdefault("sent", {})
    updated = 0
    no_registry = 0
    for match in build_matches(stock_payload, options_payload):
        if updated >= maximum:
            break
        stock = match["stock"]
        contract = match["contract"]
        symbol = match["symbol"]
        stock_score = _number(stock.get("score"))
        stage = str(stock.get("stage") or "WATCH").upper()
        option_score = _number(contract.get("score"))
        flow_score = _number(contract.get("flow_momentum_score"))
        if stock_score < 72 or stage == "WATCH" or option_score < 65:
            continue
        fp = _fingerprint(
            [
                symbol,
                stage,
                round(stock_score / 4) * 4,
                contract.get("contract_symbol"),
                round(flow_score / 5) * 5,
            ]
        )
        prior = sent_map.get(symbol)
        prior_fp = str(prior.get("fingerprint") or "") if isinstance(prior, dict) else str(prior or "")
        if prior_fp == fp:
            continue

        record = _record_for_symbol(symbol, stock_alert_state, options_alert_state)
        if record is None:
            # One-message policy: never create a third cross-confirmation message.
            no_registry += 1
            continue
        note = _confirmation_note(stock, contract)
        base_text = str(record.get("text") or "").strip()
        new_text = f"{base_text}\n{note}".strip()
        if len(new_text) > TELEGRAM_TEXT_MAX_CHARS:
            no_registry += 1
            continue
        result = edit_html_message(int(record["message_id"]), new_text)
        sent_map[symbol] = {
            "fingerprint": fp,
            "message_id": int(record["message_id"]),
            "edited_at": now.isoformat(),
            "telegram_edit_attempts": result.attempts,
        }
        updated += 1

    state["last_run_at"] = now.isoformat()
    state["last_sent_count"] = 0
    state["last_edited_count"] = updated
    state["skipped_without_message_registry"] = no_registry
    state["delivery_policy"] = "edit_existing_opportunity_message_only"
    state.pop("blocked_reason", None)
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Fold independent stock/options confirmation into an existing Telegram alert")
    parser.add_argument("--stocks", required=True)
    parser.add_argument("--options", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--stock-alert-state", required=False, default="")
    parser.add_argument("--options-alert-state", required=False, default="")
    args = parser.parse_args()
    stocks = _load(args.stocks)
    options = _load(args.options)
    state = _load(args.state) or {"sent": {}}
    stock_alert_state = _load(args.stock_alert_state) if args.stock_alert_state else {}
    options_alert_state = _load(args.options_alert_state) if args.options_alert_state else {}
    updated = send_matches(
        stocks,
        options,
        state,
        stock_alert_state=stock_alert_state,
        options_alert_state=options_alert_state,
    )
    _save(args.state, state)
    print(f"Cross-confirmation editor: updated={updated}")


if __name__ == "__main__":
    main()
