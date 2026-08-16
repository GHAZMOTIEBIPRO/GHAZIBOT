from __future__ import annotations

import argparse
import html
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

from scripts.telegram_transport import send_html_message

SCHEMA_VERSION = 1
CHECKPOINTS = ("15m", "30m", "60m", "eod")
TRAINING_MILESTONES = (10, 25, 50, 75, 100, 150, 250, 500, 1000)
MIN_DIRECTION_SAMPLE = 10


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _utc(value: Any | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _load(path: str | Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    fallback = dict(default or {})
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return fallback
    return payload if isinstance(payload, dict) else fallback


def _save(path: str | Path, payload: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(destination)


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _stats(values: list[float]) -> dict[str, Any]:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return {
            "n": 0,
            "positive_rate_pct": 0.0,
            "mean_return_pct": 0.0,
            "median_return_pct": 0.0,
            "p25_return_pct": 0.0,
            "p75_return_pct": 0.0,
            "best_return_pct": 0.0,
            "worst_return_pct": 0.0,
        }
    return {
        "n": len(clean),
        "positive_rate_pct": round(100.0 * sum(value > 0 for value in clean) / len(clean), 2),
        "mean_return_pct": round(sum(clean) / len(clean), 4),
        "median_return_pct": round(float(median(clean)), 4),
        "p25_return_pct": round(_percentile(clean, 0.25), 4),
        "p75_return_pct": round(_percentile(clean, 0.75), 4),
        "best_return_pct": round(max(clean), 4),
        "worst_return_pct": round(min(clean), 4),
    }


def _signals(outcomes: dict[str, Any]) -> list[dict[str, Any]]:
    raw = outcomes.get("signals") if isinstance(outcomes.get("signals"), dict) else {}
    return [value for value in raw.values() if isinstance(value, dict)]


def _checkpoint(signal: dict[str, Any], label: str) -> dict[str, Any] | None:
    checkpoints = signal.get("checkpoints") if isinstance(signal.get("checkpoints"), dict) else {}
    value = checkpoints.get(label)
    return value if isinstance(value, dict) else None


def _executable(signal: dict[str, Any], checkpoint: dict[str, Any]) -> bool:
    return (
        str(signal.get("entry_quote_method") or "") == "ask_to_bid"
        and str(checkpoint.get("quote_method") or "") == "ask_to_bid"
    )


def _training_eligible(signal: dict[str, Any], checkpoint: dict[str, Any]) -> bool:
    return (
        _executable(signal, checkpoint)
        and signal.get("entry_training_eligible") is True
        and checkpoint.get("training_quote_eligible") is True
    )


def _return_value(checkpoint: dict[str, Any]) -> float | None:
    value = _number(checkpoint.get("return_pct"), float("nan"))
    return value if math.isfinite(value) else None


def _checkpoint_values(
    signals: list[dict[str, Any]],
    label: str,
    *,
    training_only: bool,
    since: datetime | None = None,
    direction: str | None = None,
) -> list[float]:
    values: list[float] = []
    for signal in signals:
        if direction and str(signal.get("direction") or "").upper() != direction.upper():
            continue
        checkpoint = _checkpoint(signal, label)
        if checkpoint is None:
            continue
        if since is not None:
            raw = checkpoint.get("at") or signal.get("created_at")
            try:
                if _utc(raw) < since:
                    continue
            except Exception:
                continue
        eligible = _training_eligible(signal, checkpoint) if training_only else _executable(signal, checkpoint)
        if not eligible:
            continue
        value = _return_value(checkpoint)
        if value is not None:
            values.append(value)
    return values


def _source_diagnostics(signals: list[dict[str, Any]]) -> dict[str, Any]:
    sources: dict[str, int] = {}
    freshness: dict[str, int] = {}
    entry_executable = 0
    entry_training = 0
    for signal in signals:
        if str(signal.get("entry_quote_method") or "") == "ask_to_bid":
            entry_executable += 1
        if signal.get("entry_training_eligible") is True:
            entry_training += 1
        features = signal.get("features") if isinstance(signal.get("features"), dict) else {}
        source = str(features.get("source") or "unknown").strip() or "unknown"
        fresh = str(features.get("freshness_label") or "unknown").strip() or "unknown"
        sources[source] = sources.get(source, 0) + 1
        freshness[fresh] = freshness.get(fresh, 0) + 1
    return {
        "entry_executable_count": entry_executable,
        "entry_training_eligible_count": entry_training,
        "entry_training_eligible_pct": round(100.0 * entry_training / entry_executable, 2)
        if entry_executable
        else 0.0,
        "sources": dict(sorted(sources.items(), key=lambda item: (-item[1], item[0]))[:8]),
        "freshness_labels": dict(sorted(freshness.items(), key=lambda item: (-item[1], item[0]))[:8]),
    }


def _excursion_stats(signals: list[dict[str, Any]]) -> dict[str, Any]:
    mfe: list[float] = []
    mae: list[float] = []
    for signal in signals:
        observations = signal.get("observations") if isinstance(signal.get("observations"), list) else []
        if not observations or str(signal.get("entry_quote_method") or "") != "ask_to_bid":
            continue
        mfe.append(_number(signal.get("mfe_pct")))
        mae.append(_number(signal.get("mae_pct")))
    return {
        "n": len(mfe),
        "median_mfe_pct": round(float(median(mfe)), 4) if mfe else 0.0,
        "mean_mfe_pct": round(sum(mfe) / len(mfe), 4) if mfe else 0.0,
        "median_mae_pct": round(float(median(mae)), 4) if mae else 0.0,
        "mean_mae_pct": round(sum(mae) / len(mae), 4) if mae else 0.0,
    }


def _direction_stats(signals: list[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for direction in ("CALL", "PUT"):
        shadow = _stats(_checkpoint_values(signals, "60m", training_only=False, direction=direction))
        training = _stats(_checkpoint_values(signals, "60m", training_only=True, direction=direction))
        enough = int(shadow.get("n", 0)) >= MIN_DIRECTION_SAMPLE
        output[direction] = {
            "sample_sufficient": enough,
            "minimum_sample": MIN_DIRECTION_SAMPLE,
            "shadow": shadow if enough else {"n": shadow.get("n", 0), "status": "insufficient_sample"},
            "training": training if int(training.get("n", 0)) >= MIN_DIRECTION_SAMPLE else {
                "n": training.get("n", 0),
                "status": "insufficient_sample",
            },
        }
    return output


def _top_calibration_buckets(calibration: dict[str, Any], limit: int = 6) -> list[dict[str, Any]]:
    if calibration.get("active") is not True:
        return []
    candidates: list[dict[str, Any]] = []
    features = calibration.get("features") if isinstance(calibration.get("features"), dict) else {}
    for feature, buckets in features.items():
        if not isinstance(buckets, dict):
            continue
        for label, stats in buckets.items():
            if not isinstance(stats, dict):
                continue
            adjustment = _number(stats.get("adjustment"))
            n = int(_number(stats.get("n")))
            minimum = int(_number(stats.get("minimum_group_sample")))
            if not adjustment or n < minimum:
                continue
            candidates.append(
                {
                    "feature": str(feature),
                    "bucket": str(label),
                    "n": n,
                    "adjustment": round(adjustment, 3),
                    "positive_rate_pct": _number(stats.get("hit_rate")),
                    "mean_return_pct": _number(stats.get("mean_return_pct")),
                }
            )
    candidates.sort(key=lambda row: abs(_number(row.get("adjustment"))), reverse=True)
    return candidates[:limit]


def build_report(
    outcomes: dict[str, Any],
    calibration: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = _utc(now)
    signals = _signals(outcomes)
    checkpoint_performance: dict[str, Any] = {}
    for label in CHECKPOINTS:
        checkpoint_performance[label] = {
            "shadow": _stats(_checkpoint_values(signals, label, training_only=False)),
            "training": _stats(_checkpoint_values(signals, label, training_only=True)),
        }

    training_n = int(_number(checkpoint_performance["60m"]["training"].get("n")))
    shadow_n = int(_number(checkpoint_performance["60m"]["shadow"].get("n")))
    minimum = max(0, int(_number(calibration.get("minimum_sample"))))
    active = calibration.get("active") is True
    progress = 100.0 if active else (min(100.0, 100.0 * training_n / minimum) if minimum else 0.0)
    if active:
        status = "CALIBRATION_ACTIVE"
    elif training_n > 0:
        status = "TRAINING_SAMPLE_BUILDING"
    elif shadow_n > 0:
        status = "SHADOW_ONLY"
    else:
        status = "NO_60M_SAMPLE_YET"

    seven_days = now - timedelta(days=7)
    thirty_days = now - timedelta(days=30)
    counts = {
        "tracked_total": len(signals),
        "open": sum(signal.get("status") == "open" for signal in signals),
        "closed": sum(signal.get("status") == "closed" for signal in signals),
        "expired_unobserved": sum(signal.get("status") == "expired_unobserved" for signal in signals),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "path": "options_performance_auditor",
        "independent_from_stock_radar": True,
        "decision_authority": False,
        "report_status": status,
        "counts": counts,
        "calibration": {
            "active": active,
            "training_sample_size": training_n,
            "shadow_sample_size": shadow_n,
            "minimum_sample": minimum,
            "progress_pct": round(progress, 2),
            "training_checkpoint": str(calibration.get("training_checkpoint") or "60m"),
            "training_quote_method": str(calibration.get("training_quote_method") or "ask_to_bid"),
            "max_total_adjustment": _number(calibration.get("max_total_adjustment"), 4.0),
        },
        "checkpoint_performance": checkpoint_performance,
        "recent_60m": {
            "last_7_days": {
                "shadow": _stats(_checkpoint_values(signals, "60m", training_only=False, since=seven_days)),
                "training": _stats(_checkpoint_values(signals, "60m", training_only=True, since=seven_days)),
            },
            "last_30_days": {
                "shadow": _stats(_checkpoint_values(signals, "60m", training_only=False, since=thirty_days)),
                "training": _stats(_checkpoint_values(signals, "60m", training_only=True, since=thirty_days)),
            },
        },
        "direction_60m": _direction_stats(signals),
        "excursion": _excursion_stats(signals),
        "data_quality": _source_diagnostics(signals),
        "validated_calibration_buckets": _top_calibration_buckets(calibration),
        "interpretation_policy": {
            "metric_name": "positive outcome rate, not predictive accuracy",
            "execution_model": "long option entry at ask and evaluation/exit at bid when available",
            "shadow_policy": "free/delayed/indicative executable outcomes may be measured but cannot train score calibration",
            "training_policy": "only timely high-quality ask-to-bid entry and 60m outcomes can activate learning",
            "risk_policy": "performance auditing never bypasses strict execution or risk blockers",
        },
    }


def _fmt_pct(value: Any, signed: bool = False) -> str:
    number = _number(value)
    return f"{number:+.1f}%" if signed else f"{number:.1f}%"


def _checkpoint_line(label: str, stats: dict[str, Any]) -> str:
    n = int(_number(stats.get("n")))
    if not n:
        return f"• {label}: لا توجد عينة مكتملة"
    return (
        f"• {label}: n={n} | موجب {_fmt_pct(stats.get('positive_rate_pct'))} | "
        f"متوسط {_fmt_pct(stats.get('mean_return_pct'), signed=True)} | "
        f"وسيط {_fmt_pct(stats.get('median_return_pct'), signed=True)}"
    )


def render_telegram(report: dict[str, Any], *, weekly: bool, reason: str) -> str:
    calibration = report.get("calibration") if isinstance(report.get("calibration"), dict) else {}
    checkpoints = report.get("checkpoint_performance") if isinstance(report.get("checkpoint_performance"), dict) else {}
    excursion = report.get("excursion") if isinstance(report.get("excursion"), dict) else {}
    training_n = int(_number(calibration.get("training_sample_size")))
    shadow_n = int(_number(calibration.get("shadow_sample_size")))
    minimum = int(_number(calibration.get("minimum_sample")))
    active = calibration.get("active") is True
    status_ar = {
        "CALIBRATION_ACTIVE": "المعايرة مفعلة ✅",
        "TRAINING_SAMPLE_BUILDING": "عينة التعلم قيد البناء 🧪",
        "SHADOW_ONLY": "قياس Shadow فقط ⚠️",
        "NO_60M_SAMPLE_YET": "لم تكتمل عينة 60 دقيقة بعد",
    }.get(str(report.get("report_status") or ""), "قيد القياس")

    title = "التقرير الأسبوعي" if weekly else "تحديث مرحلة القياس"
    lines = [
        f"🧪 <b>بلاك بوكس Ω | {title}</b>",
        "",
        f"الحالة: <b>{html.escape(status_ar)}</b>",
        f"Shadow 60د: <b>{shadow_n}</b> | Training: <b>{training_n}/{minimum}</b>",
        f"تقدم عينة التعلم: <b>{_fmt_pct(calibration.get('progress_pct'))}</b>",
        "",
        "📊 <b>نتائج العقود — تنفيذ Ask → Bid</b>",
        _checkpoint_line("15 دقيقة", (checkpoints.get("15m") or {}).get("shadow") or {}),
        _checkpoint_line("30 دقيقة", (checkpoints.get("30m") or {}).get("shadow") or {}),
        _checkpoint_line("60 دقيقة", (checkpoints.get("60m") or {}).get("shadow") or {}),
        _checkpoint_line("نهاية الجلسة", (checkpoints.get("eod") or {}).get("shadow") or {}),
    ]
    if int(_number(excursion.get("n"))) > 0:
        lines.extend(
            [
                "",
                "📈 <b>حركة العقود أثناء المتابعة</b>",
                f"• وسيط أفضل حركة MFE: {_fmt_pct(excursion.get('median_mfe_pct'), signed=True)}",
                f"• وسيط أسوأ حركة MAE: {_fmt_pct(excursion.get('median_mae_pct'), signed=True)}",
            ]
        )
    lines.extend(["", "🧠 <b>التعلم</b>"])
    if active:
        lines.append("• المعايرة الإحصائية أصبحت فعالة، لكنها تبقى محدودة ±4 درجات ولا تتجاوز Hard Blockers.")
    elif training_n == 0 and shadow_n > 0:
        lines.append("• النتائج الحالية مفيدة للقياس فقط؛ جودة/حداثة المصدر لا تسمح لها بتعديل السكور.")
    else:
        lines.append(f"• المعايرة لن تتفعل قبل اكتمال {minimum} عينة 60 دقيقة مؤهلة.")
    lines.extend(
        [
            "",
            f"سبب الرسالة: {html.escape(reason)}",
            "",
            "⚖️ هذا تدقيق نتائج افتراضية وليس نسبة دقة أو ضمان ربح. القياس يحاسب البوت ولا يخفف شروط المخاطر.",
        ]
    )
    text = "\n".join(lines)
    if len(text) > 4096:
        raise ValueError("performance report exceeds Telegram limit")
    return text


def _highest_milestone(value: int) -> int:
    reached = [milestone for milestone in TRAINING_MILESTONES if value >= milestone]
    return max(reached) if reached else 0


def notification_decision(
    report: dict[str, Any],
    state: dict[str, Any],
    *,
    now: datetime | None = None,
    force: bool = False,
) -> dict[str, Any]:
    now = _utc(now)
    calibration = report.get("calibration") if isinstance(report.get("calibration"), dict) else {}
    shadow_n = int(_number(calibration.get("shadow_sample_size")))
    training_n = int(_number(calibration.get("training_sample_size")))
    active = calibration.get("active") is True
    week_key = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
    weekly_due = now.weekday() == 4 and shadow_n > 0 and state.get("last_weekly_key") != week_key
    first_shadow = shadow_n > 0 and state.get("first_shadow_notified") is not True
    current_milestone = _highest_milestone(training_n)
    previous_milestone = int(_number(state.get("highest_training_milestone")))
    milestone_due = current_milestone > previous_milestone
    activation_due = active and state.get("calibration_active_notified") is not True

    if force:
        return {"send": True, "weekly": now.weekday() == 4, "reason": "تشغيل يدوي للتدقيق"}
    if activation_due:
        return {"send": True, "weekly": False, "reason": "تفعيل المعايرة بعد اكتمال العينة المؤهلة"}
    if milestone_due:
        return {"send": True, "weekly": False, "reason": f"وصول عينة التعلم إلى مرحلة {current_milestone}"}
    if first_shadow:
        return {"send": True, "weekly": False, "reason": "بدأ نظام Outcome Tracking بتسجيل نتائج 60 دقيقة"}
    if weekly_due:
        return {"send": True, "weekly": True, "reason": "التقرير الأسبوعي التلقائي"}
    return {"send": False, "weekly": False, "reason": "لا يوجد حدث يستحق إشعارًا جديدًا"}


def update_notification_state(
    state: dict[str, Any],
    report: dict[str, Any],
    decision: dict[str, Any],
    *,
    now: datetime | None = None,
    sent: bool,
) -> dict[str, Any]:
    now = _utc(now)
    output = dict(state)
    output.setdefault("schema_version", SCHEMA_VERSION)
    calibration = report.get("calibration") if isinstance(report.get("calibration"), dict) else {}
    shadow_n = int(_number(calibration.get("shadow_sample_size")))
    training_n = int(_number(calibration.get("training_sample_size")))
    output["last_seen_shadow_60m"] = shadow_n
    output["last_seen_training_60m"] = training_n
    output["updated_at"] = now.isoformat()
    if not sent:
        return output
    if shadow_n > 0:
        output["first_shadow_notified"] = True
    output["highest_training_milestone"] = max(
        int(_number(output.get("highest_training_milestone"))),
        _highest_milestone(training_n),
    )
    if calibration.get("active") is True:
        output["calibration_active_notified"] = True
    if decision.get("weekly") is True:
        iso = now.isocalendar()
        output["last_weekly_key"] = f"{iso.year}-W{iso.week:02d}"
    output["last_sent_at"] = now.isoformat()
    output["last_sent_reason"] = str(decision.get("reason") or "")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit BLACK BOX options outcomes without changing trading decisions")
    parser.add_argument("--outcomes", default="data/live/options_outcomes.json")
    parser.add_argument("--calibration", default="data/live/options_calibration.json")
    parser.add_argument("--output", default="public/data/options_performance_report.json")
    parser.add_argument("--state", default="data/live/options_performance_report_state.json")
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    outcomes = _load(args.outcomes, {"signals": {}})
    calibration = _load(args.calibration, {})
    state = _load(args.state, {"schema_version": SCHEMA_VERSION})
    report = build_report(outcomes, calibration, now=now)
    _save(args.output, report)

    decision = notification_decision(report, state, now=now, force=args.force)
    sent = False
    if args.send and decision.get("send") is True:
        message = render_telegram(
            report,
            weekly=decision.get("weekly") is True,
            reason=str(decision.get("reason") or "تدقيق الأداء"),
        )
        send_html_message(message, disable_notification=decision.get("weekly") is True)
        sent = True

    next_state = update_notification_state(state, report, decision, now=now, sent=sent)
    _save(args.state, next_state)
    print(
        json.dumps(
            {
                "status": report.get("report_status"),
                "shadow_60m": report.get("calibration", {}).get("shadow_sample_size", 0),
                "training_60m": report.get("calibration", {}).get("training_sample_size", 0),
                "notification_due": bool(decision.get("send")),
                "sent": sent,
                "reason": decision.get("reason"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
