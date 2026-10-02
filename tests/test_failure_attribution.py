from __future__ import annotations

import json

from options_radar.adaptive_learning import (
    build_learning_model,
    options_score_adjustment,
)
from options_radar.failure_attribution import (
    build_failure_factor_stats,
    failure_factor_penalty,
    option_failure_flags,
    stock_failure_flags,
)


def test_option_failure_flags_capture_execution_and_convexity_risks():
    flags = option_failure_flags(
        {
            "dte": 2,
            "spread_pct": 0.18,
            "iv": 1.7,
            "delta": 0.18,
            "vol_oi": 0.2,
            "option_type": "call",
            "market_regime": "risk_off",
        }
    )
    assert "VERY_SHORT_DTE" in flags
    assert "VERY_WIDE_SPREAD" in flags
    assert "EXTREME_IV" in flags
    assert "LOW_DELTA" in flags
    assert "LOW_RELATIVE_ACTIVITY" in flags
    assert "REGIME_SIDE_CONFLICT" in flags


def test_official_stock_cause_is_not_marked_weak():
    flags = stock_failure_flags(
        {
            "stage": "IGNITION",
            "score": 82,
            "market_regime": "risk_on",
            "cause": {
                "official_confirmed": True,
                "source_tier": "A_OFFICIAL",
                "status": "OFFICIAL_CONFIRMED",
            },
        }
    )
    assert "WEAK_CAUSE_EVIDENCE" not in flags


def test_failure_factor_has_no_penalty_below_minimum_sample():
    rows = [
        {
            "terminal_outcome": "failed" if i < 8 else "success",
            "iv": 1.2,
        }
        for i in range(10)
    ]
    model = build_failure_factor_stats(rows, option_failure_flags)
    evidence = model["factors"]["HIGH_IV"]
    assert evidence["sample"] == 10
    assert evidence["eligible"] is False
    assert evidence["score_penalty"] == 0.0
    penalty, applied = failure_factor_penalty(model, {"iv": 1.2}, domain="options")
    assert penalty == 0.0
    assert applied == []


def test_failure_factor_penalizes_only_excess_failure_after_sample_gate():
    rows = []
    # 20 high-IV cases, 16 fail => 80% failure.
    for i in range(20):
        rows.append(
            {
                "terminal_outcome": "failed" if i < 16 else "success",
                "iv": 1.2,
            }
        )
    # 80 ordinary cases, 24 fail => total baseline 40%.
    for i in range(80):
        rows.append(
            {
                "terminal_outcome": "failed" if i < 24 else "success",
                "iv": 0.4,
            }
        )
    model = build_failure_factor_stats(rows, option_failure_flags)
    evidence = model["factors"]["HIGH_IV"]
    assert evidence["eligible"] is True
    assert evidence["harmful_association"] is True
    assert evidence["failure_rate"] == 0.8
    assert evidence["baseline_failure_rate"] == 0.4
    penalty, applied = failure_factor_penalty(model, {"iv": 1.2}, domain="options")
    assert penalty > 0
    assert "HIGH_IV" in applied


def test_adaptive_learning_uses_failure_association_after_100_decisive_options(tmp_path):
    stock_path = tmp_path / "stock.json"
    stock_path.write_text('{"signals":{}}', encoding="utf-8")
    signals_path = tmp_path / "signals.jsonl"
    outcomes_path = tmp_path / "outcomes.json"

    signals = []
    outcomes = {"signals": {}}
    for i in range(100):
        high_iv = i < 20
        failed = i < 16 or (20 <= i < 44)
        signal_id = f"s{i}"
        signals.append(
            {
                "signal_id": signal_id,
                "score": 75,
                "market_regime": "mixed",
                "option_type": "call",
                "iv": 1.2 if high_iv else 0.4,
                "dte": 21,
                "spread_pct": 0.05,
                "delta": 0.45,
                "vol_oi": 1.2,
            }
        )
        outcomes["signals"][signal_id] = {
            "terminal_outcome": "failed" if failed else "success",
            "checkpoints": {"1d": {"return_pct": -5 if failed else 8}},
        }

    signals_path.write_text(
        "\n".join(json.dumps(row) for row in signals) + "\n",
        encoding="utf-8",
    )
    outcomes_path.write_text(json.dumps(outcomes), encoding="utf-8")

    model = build_learning_model(
        stock_outcomes_path=stock_path,
        options_signals_path=signals_path,
        options_outcomes_path=outcomes_path,
    )
    factor = model["options"]["failure_factors"]["factors"]["HIGH_IV"]
    assert model["options"]["ready"] is True
    assert factor["harmful_association"] is True

    common = {
        "score": 75,
        "market_regime": "mixed",
        "option_type": "call",
        "dte": 21,
        "spread_pct": 0.05,
        "delta": 0.45,
        "vol_oi": 1.2,
    }
    high = options_score_adjustment(model, {**common, "iv": 1.2})
    normal = options_score_adjustment(model, {**common, "iv": 0.4})
    assert high < normal
