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


def _send(text: str) -> None:
    token = str(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = str(os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        raise RuntimeError("Telegram destination is not ready")
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"},
        timeout=20,
    )
    response.raise_for_status()
    if not response.json().get("ok"):
        raise RuntimeError("Telegram rejected cross-confirmation message")


def _stage_ar(stage: str) -> str:
    return {
        "WATCH": "مراقبة",
        "PRESSURE_BUILDING": "بناء ضغط قبل الحركة",
        "IGNITION": "بداية انطلاقة",
        "EXPLOSION": "حركة قوية",
        "EXTENDED": "حركة ممتدة",
    }.get(stage.upper(), stage or "غير مصنف")


def _side_ar(side: str) -> str:
    return "CALL — صعود" if side.upper() == "CALL" else "PUT — هبوط"


def _alignment(move_pct: float, side: str) -> str:
    side = side.upper()
    if move_pct > 0 and side == "CALL":
        return "متوافق ✅ — السهم صاعد والعقد CALL"
    if move_pct < 0 and side == "PUT":
        return "متوافق ✅ — السهم هابط والعقد PUT"
    if move_pct == 0:
        return "غير واضح — حركة السهم محايدة"
    return "غير متوافق ⚠️ — اتجاه السهم والعقد لا يؤكدان بعضهما"


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
        if not contracts:
            continue
        contract = contracts[0]
        matches.append(
            {
                "symbol": symbol,
                "stock": stock,
                "contract": contract,
                "combined_rank": _number(stock.get("score")) + _number(contract.get("flow_momentum_score")),
            }
        )
    matches.sort(key=lambda row: row["combined_rank"], reverse=True)
    return matches


def send_matches(
    stock_payload: dict[str, Any],
    options_payload: dict[str, Any],
    state: dict[str, Any],
    *,
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

    sent_map = state.setdefault("sent", {})
    sent = 0
    for match in build_matches(stock_payload, options_payload):
        if sent >= maximum:
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
        if sent_map.get(symbol) == fp:
            continue

        side = str(contract.get("option_type") or "").upper()
        expiration = str(contract.get("expiration") or "")[:10]
        strike = _number(contract.get("strike"))
        bid = _number(contract.get("bid"))
        ask = _number(contract.get("ask"))
        move_pct = _number(stock.get("move_pct"))
        cause = stock.get("cause") if isinstance(stock.get("cause"), dict) else {}
        cause_text = str(cause.get("status_ar") or "السبب الأساسي غير مثبت حتى الآن")

        text = "\n".join(
            [
                "🔗 <b>بلاك بوكس Ω | تأكيد مزدوج</b>",
                "",
                f"<b>{_safe(symbol)}</b> ظهر بشكل مستقل في رادار الأسهم ورادار الأوبشن.",
                "",
                "📈 <b>إشارة السهم</b>",
                f"• المرحلة: <b>{_safe(_stage_ar(stage))}</b>",
                f"• الحركة: <b>{move_pct:+.1f}%</b>",
                f"• درجة الرادار: <b>{stock_score:.0f}/100</b>",
                f"• السبب: {_safe(cause_text)}",
                "",
                "🎯 <b>إشارة العقد</b>",
                f"• الاتجاه: <b>{_safe(_side_ar(side))}</b>",
                f"• التنفيذ المرصود: <b>{_safe(symbol)} {side} {strike:g}</b>",
                f"• الانتهاء: <b>{_safe(expiration)}</b>",
                f"• Bid/Ask: <b>${bid:.2f} / ${ask:.2f}</b>",
                f"• درجة العقد: <b>{option_score:.0f}/100</b> | التدفق: <b>{flow_score:.0f}/100</b>",
                "",
                "🧭 <b>هل الإشارتان متوافقتان؟</b>",
                _safe(_alignment(move_pct, side)),
                "",
                "💡 <b>وش الفايدة؟</b>",
                "ظهور الرمز في مسارين مستقلين يرفعه في أولوية المتابعة، لكنه لا يحوله إلى صفقة مضمونة ولا يلغي ضرورة فحص السعر والسيولة والسبب.",
            ]
        )
        _send(text)
        sent_map[symbol] = fp
        sent += 1

    state["last_run_at"] = now.isoformat()
    state["last_sent_count"] = sent
    state.pop("blocked_reason", None)
    return sent


def main() -> None:
    parser = argparse.ArgumentParser(description="Send independent stock/options cross-confirmation context")
    parser.add_argument("--stocks", required=True)
    parser.add_argument("--options", required=True)
    parser.add_argument("--state", required=True)
    args = parser.parse_args()
    stocks = _load(args.stocks)
    options = _load(args.options)
    state = _load(args.state) or {"sent": {}}
    sent = send_matches(stocks, options, state)
    _save(args.state, state)
    print(f"Cross-confirmation sender: sent={sent}")


if __name__ == "__main__":
    main()
