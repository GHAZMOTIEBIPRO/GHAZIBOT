from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from scripts.options_performance_auditor import (
    build_report,
    notification_decision,
    render_telegram,
    update_notification_state,
)


def _signal(
    *,
    direction: str = "CALL",
    return_60m: float = 10.0,
    training: bool = True,
    quote_method: str = "ask_to_bid",
    signal_id: str = "sig",
) -> dict:
    return {
        "signal_id": signal_id,
        "created_at": "2026-08-14T15:00:00+00:00",
        "session_date": "2026-08-14",
        "direction": direction,
        "status": "closed",
        "entry_quote_method": quote_method,
        "entry_training_eligible": training,
        "features": {
            "source": "alpaca_opra" if training else "alpaca_indicative",
            "freshness_label": "live" if training else "indicative",
        },
        "checkpoints": {
            "15m": {
                "at": "2026-08-14T15:15:00+00:00",
                "return_pct": return_60m / 2,
                "quote_method": quote_method,
                "training_quote_eligible": training,
            },
            "30m": {
                "at": "2026-08-14T15:30:00+00:00",
                "return_pct": return_60m * 0.8,
                "quote_method": quote_method,
                "training_quote_eligible": training,
            },
            "60m": {
                "at": "2026-08-14T16:00:00+00:00",
                "return_pct": return_60m,
                "quote_method": quote_method,
                "training_quote_eligible": training,
            },
            "eod": {
                "at": "2026-08-14T19:55:00+00:00",
                "return_pct": return_60m * 1.2,
                "quote_method": quote_method,
                "training_quote_eligible": training,
            },
        },
        "observations": [
            {"at": "2026-08-14T15:15:00+00:00", "return_pct": -4.0},
            {"at": "2026-08-14T16:00:00+00:00", "return_pct": return_60m},
        ],
        "mfe_pct": max(return_60m, 0.0),
        "mae_pct": min(-4.0, return_60m),
    }


def _calibration(*, active: bool = False, minimum: int = 100) -> dict:
    return {
        "active": active,
        "minimum_sample": minimum,
        "training_checkpoint": "60m",
        "training_quote_method": "ask_to_bid",
        "max_total_adjustment": 4.0,
        "features": {},
    }


def test_report_separates_shadow_from_training_and_uses_executable_quotes():
    outcomes = {
        "signals": {
            "eligible": _signal(signal_id="eligible", return_60m=12.0, training=True),
            "shadow": _signal(signal_id="shadow", return_60m=-6.0, training=False),
            "mid": _signal(signal_id="mid", return_60m=99.0, training=True, quote_method="mid_to_mid"),
        }
    }
    report = build_report(
        outcomes,
        _calibration(),
        now=datetime(2026, 8, 17, tzinfo=timezone.utc),
    )
    sixty = report["checkpoint_performance"]["60m"]
    assert sixty["shadow"]["n"] == 2
    assert sixty["training"]["n"] == 1
    assert sixty["shadow"]["positive_rate_pct"] == 50.0
    assert sixty["training"]["mean_return_pct"] == 12.0
    assert report["calibration"]["training_sample_size"] <= report["calibration"]["shadow_sample_size"]
    assert report["decision_authority"] is False
    assert report["independent_from_stock_radar"] is True


def test_shadow_only_status_does_not_activate_learning():
    outcomes = {"signals": {"shadow": _signal(training=False, return_60m=8.0)}}
    report = build_report(outcomes, _calibration(active=False))
    assert report["report_status"] == "SHADOW_ONLY"
    assert report["calibration"]["training_sample_size"] == 0
    assert report["calibration"]["shadow_sample_size"] == 1
    message = render_telegram(report, weekly=False, reason="اختبار")
    assert "جودة/حداثة المصدر لا تسمح لها بتعديل السكور" in message
    assert "Ask → Bid" in message


def test_first_shadow_sample_triggers_one_notification_then_stays_quiet():
    report = build_report({"signals": {"s": _signal(training=False)}}, _calibration())
    now = datetime(2026, 8, 17, 22, 37, tzinfo=timezone.utc)
    decision = notification_decision(report, {}, now=now)
    assert decision["send"] is True
    assert "Outcome Tracking" in decision["reason"]
    state = update_notification_state({}, report, decision, now=now, sent=True)
    second = notification_decision(report, state, now=now)
    assert second["send"] is False


def test_training_milestone_notification_is_bounded_and_stateful():
    signals = {
        f"s{i}": _signal(signal_id=f"s{i}", return_60m=float(i + 1), training=True)
        for i in range(10)
    }
    report = build_report({"signals": signals}, _calibration(minimum=100))
    now = datetime(2026, 8, 17, 22, 37, tzinfo=timezone.utc)
    state = {"first_shadow_notified": True, "highest_training_milestone": 0}
    decision = notification_decision(report, state, now=now)
    assert decision["send"] is True
    assert "10" in decision["reason"]
    updated = update_notification_state(state, report, decision, now=now, sent=True)
    assert updated["highest_training_milestone"] == 10
    assert notification_decision(report, updated, now=now)["send"] is False


def test_friday_weekly_report_only_once_per_iso_week():
    report = build_report({"signals": {"s": _signal(training=False)}}, _calibration())
    friday = datetime(2026, 8, 21, 22, 37, tzinfo=timezone.utc)
    state = {"first_shadow_notified": True}
    decision = notification_decision(report, state, now=friday)
    assert decision == {"send": True, "weekly": True, "reason": "التقرير الأسبوعي التلقائي"}
    updated = update_notification_state(state, report, decision, now=friday, sent=True)
    assert notification_decision(report, updated, now=friday)["send"] is False


def test_calibration_activation_has_priority_over_weekly_digest():
    signals = {
        f"s{i}": _signal(signal_id=f"s{i}", training=True, return_60m=2.0)
        for i in range(100)
    }
    report = build_report({"signals": signals}, _calibration(active=True, minimum=100))
    friday = datetime(2026, 8, 21, 22, 37, tzinfo=timezone.utc)
    state = {
        "first_shadow_notified": True,
        "highest_training_milestone": 100,
        "calibration_active_notified": False,
    }
    decision = notification_decision(report, state, now=friday)
    assert decision["send"] is True
    assert decision["weekly"] is False
    assert "تفعيل المعايرة" in decision["reason"]


def test_direction_breakdown_is_hidden_below_minimum_sample():
    report = build_report(
        {"signals": {"s": _signal(direction="PUT", training=False)}},
        _calibration(),
    )
    assert report["direction_60m"]["PUT"]["sample_sufficient"] is False
    assert report["direction_60m"]["PUT"]["shadow"] == {"n": 1, "status": "insufficient_sample"}


def test_interpretation_policy_explicitly_rejects_accuracy_claim():
    report = build_report({"signals": {}}, _calibration())
    assert report["interpretation_policy"]["metric_name"] == "positive outcome rate, not predictive accuracy"
    assert "cannot train" in report["interpretation_policy"]["shadow_policy"]
    assert report["interpretation_policy"]["risk_policy"].startswith("performance auditing never bypasses")


def test_workflow_is_free_independent_and_restores_only_options_learning_state():
    root = Path(__file__).resolve().parents[1]
    text = (root / ".github" / "workflows" / "options-performance-auditor.yml").read_text(encoding="utf-8")
    assert 'cron: "37 22 * * 1-5"' in text
    assert "push:" in text
    assert "branches: [main]" in text
    assert "options-contract-radar.yml" in text
    assert "options-contract-state" in text
    assert "options_outcomes.json" in text
    assert "options_calibration.json" in text
    assert "PAID_MARKET_DATA_ALLOWED: \"false\"" in text
    assert "stock-radar.yml" not in text
    assert "--send" in text
    assert '"${GITHUB_EVENT_NAME:-}" != "push"' in text
    assert "github.event_name != 'push'" in text
    assert "options-performance-audit" in text
    assert "No persisted options outcome state exists yet" in text
