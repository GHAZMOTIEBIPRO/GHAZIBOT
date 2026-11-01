"""Operational market-recovery acceptance from already-published evidence.

This is NOT a signal scanner or an exchange-data entitlement. Published
outputs contain health counts and statuses only: no personal prices, option
contracts, account secrets, private symbol lists, or copied quote data.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = "ghazi.market_acceptance.v1"
MAX_INPUT_BYTES = 500_000
MAX_AGE_HOURS = 36


def _read(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > MAX_INPUT_BYTES:
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else None


def _fresh(report: dict[str, Any], now: datetime, hours: int = MAX_AGE_HOURS) -> bool:
    stamp = _timestamp(report.get("generated_at"))
    return bool(stamp and timedelta(0) <= now - stamp <= timedelta(hours=hours))


def _count(raw: Any) -> int:
    return raw if type(raw) is int and 0 <= raw <= 1_000_000 else 0


def evaluate(inputs: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """Four independent proofs: bars, levels, delivery and empirical edge.

    Fail closed on missing, old, malformed and source-blocked reports.
    No status becomes an option-trade authorization.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    plan = inputs.get("daily_plan") if isinstance(inputs.get("daily_plan"), dict) else {}
    operations = inputs.get("operations") if isinstance(inputs.get("operations"), dict) else {}
    scorecards = inputs.get("scorecards") if isinstance(inputs.get("scorecards"), dict) else {}
    trade = inputs.get("trading_readiness") if isinstance(inputs.get("trading_readiness"), dict) else {}
    plan_ok = plan.get("schema") == "ghazi.daily_plan_sheet.v1" and _fresh(plan, now)
    ops_ok = _fresh(operations, now) and operations.get("status") == "healthy"
    score_ok = scorecards.get("schema") == "ghazi.platform_scorecards.v1" and _fresh(scorecards, now)
    trade_ok = trade.get("schema") == "ghazi.trading_readiness.v1" and _fresh(trade, now)

    funnel = plan.get("analysis_funnel") or {} if plan_ok else {}
    if not isinstance(funnel, dict):
        funnel = {}
    private = plan.get("private_mode") or {} if plan_ok else {}
    if not isinstance(private, dict):
        private = {}
    readiness = plan.get("readiness") or {} if plan_ok else {}
    if not isinstance(readiness, dict):
        readiness = {}
    frames = readiness.get("multi_timeframe") or {}
    levels = readiness.get("price_levels") or {}
    if not isinstance(frames, dict):
        frames = {}
    if not isinstance(levels, dict):
        levels = {}
    fetched = _count((funnel.get("bars_fetched") or {}).get("count"))
    analysed = _count((funnel.get("analysed") or {}).get("count"))
    bars_proven = bool(plan_ok and private.get("enabled") is True and fetched >= 1)
    analysis_proven = bool(bars_proven and analysed >= 1
                          and frames.get("private_owner") == "FULL"
                          and levels.get("private_owner") == "COMPUTED")
    private_delivery = bool(analysis_proven and private.get("delivery") == "DELIVERED")
    cards = scorecards.get("scorecards") or {} if score_ok else {}
    if not isinstance(cards, dict):
        cards = {}
    telegram = cards.get("TELEGRAM_DELIVERY") or {}
    ops_delivery = bool(telegram.get("status") == "DELIVERED")
    # Successful ops messages are not proof of market-report or signal delivery.
    signals = cards.get("SIGNAL_PERFORMANCE") or {}
    empirical_edge = bool(trade_ok and signals.get("status") == "EDGE_PROVEN"
                          and (trade.get("checks") or {}).get("walk_forward_passed") is True
                          and (trade.get("checks") or {}).get("stock_edge_proven") is True)
    quote_ready = bool(trade_ok and (trade.get("checks") or {}).get("options_execution_sources") is True)
    # Unknown/expired reports never masquerade as a verified result.
    reason = str(private.get("reason") or "MISSING_OR_STALE_REPORT")
    required = []
    if not bars_proven:
        if reason == "DATA_USE_PERMISSION_REQUIRED":
            required.append({"id": "REVIEW_SOURCE_RIGHTS", "owner_action": True,
                             "message_ar": "راجع شروط Alpaca وسجّل الإقرار بالاستخدام الخاص فقط إن كانت تسمح به."})
        elif reason == "ACCOUNT_CREDENTIALS_NOT_CONFIGURED":
            required.append({"id": "SET_ALPACA_KEYS", "owner_action": True,
                             "message_ar": "أنشئ مفاتيح Alpaca وأضفها إلى GitHub Actions Secrets دون إرسالها لأي شخص."})
        else:
            required.append({"id": "VERIFY_COMPLETED_BARS", "owner_action": False,
                             "message_ar": "تحقق من الاستجابة الفعلية للمصدر وعدد الشموع المكتملة وصلاحية استخدامها."})
    if not analysis_proven:
        required.append({"id": "MEASURE_SUPPORT_AND_TRENDS", "owner_action": False,
                         "message_ar": "أثبت مستويات فعلية واتجاهات متعددة الأطر من الشموع المؤهلة، دون أسعار مصطنعة."})
    if not private_delivery:
        required.append({"id": "VERIFY_PRIVATE_MARKET_REPORT", "owner_action": True,
                         "message_ar": "فعّل الوجهة الخاصة المصرح بها وتحقق من قبول تيليجرام لتقرير أسعار خاص حقيقي."})
    if not empirical_edge:
        required.append({"id": "PROVE_OUT_OF_SAMPLE_EDGE", "owner_action": False,
                         "message_ar": "اجمع عينات مستقبلية مستقلة، ثم قارن النتائج بالمرجع وبعد تكاليف التنفيذ."})
    if not quote_ready:
        required.append({"id": "VERIFY_EXECUTION_OPTION_QUOTES", "owner_action": True,
                         "message_ar": "يتطلب تحليل تنفيذ الأوبشن تغذية مرخصة وعروض Bid/Ask مؤرخة؛ البيانات الإرشادية لا تكفي."})

    return {
        "schema": SCHEMA, "generated_at": now.isoformat(),
        "status": "RESEARCH_EVIDENCE_PENDING" if not (analysis_proven and empirical_edge)
                  else "RESEARCH_EVIDENCE_REPORTED",
        "scope": "owner_private_research_evidence_and_public_health_only",
        "checks": {
            "daily_plan_recent": plan_ok,
            "private_bars_observed": bars_proven,
            "private_multi_frame_levels_computed": analysis_proven,
            "private_market_report_telegram_accepted": private_delivery,
            "operational_telegram_digest_accepted": bool(score_ok and ops_delivery),
            "operational_pipeline_healthy": ops_ok,
            "out_of_sample_trading_edge_proven": empirical_edge,
            "execution_grade_option_quotes_verified": quote_ready,
        },
        "counts": {"price_bar_symbols_fetched": fetched if plan_ok else 0,
                   "symbols_with_computed_levels": analysed if plan_ok else 0},
        "latest_evidence": {
            "daily_plan_generated_at": plan.get("generated_at") if plan_ok else None,
            "operations_generated_at": operations.get("generated_at") if _fresh(operations, now) else None,
            "scorecards_generated_at": scorecards.get("generated_at") if score_ok else None,
        },
        "action_queue": required,
        "research_only": True,
        "execution_authority": False,
        "public_market_prices": None,
        "signal_success_probability": None,
        "note_ar": "نجاح GitHub أو إرسال موجز تشغيل لا يثبت توفر أسعار السوق أو إرسال توصية أو أفضلية تداول.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    for name in ("daily-plan", "operations", "scorecards", "trading-readiness"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate({"daily_plan": _read(args.daily_plan), "operations": _read(args.operations),
                       "scorecards": _read(args.scorecards), "trading_readiness": _read(args.trading_readiness)},
                      now=datetime.now(timezone.utc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(args.output)
    print("GHAZI market recovery acceptance:", json.dumps({
        "status": result["status"], "checks": result["checks"], "action_ids":
            [item["id"] for item in result["action_queue"]]
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
