from __future__ import annotations

import json

from options_radar.adaptive_learning import build_learning_model


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path, rows):
    text = "\n".join(json.dumps(row) for row in rows)
    path.write_text((text + "\n") if text else "", encoding="utf-8")


def test_empty_evidence_is_not_ready(tmp_path):
    stock_path = tmp_path / "stock.json"
    signals_path = tmp_path / "signals.jsonl"
    outcomes_path = tmp_path / "outcomes.json"
    _write_json(stock_path, {"signals": {}})
    _write_jsonl(signals_path, [])
    _write_json(outcomes_path, {"signals": {}})
    model = build_learning_model(
        stock_outcomes_path=stock_path,
        options_signals_path=signals_path,
        options_outcomes_path=outcomes_path,
    )
    assert model["stock"]["ready"] is False
    assert model["options"]["ready"] is False
    assert model["policy"]["no_live_weight_change_before_minimum_sample"] is True


def test_only_mature_decisive_rows_count(tmp_path):
    stock_rows = {}
    for index in range(60):
        stock_rows[f"s{index}"] = {
            "score": 85,
            "score_band": "80-89",
            "stage": "IGNITION",
            "market_regime": "risk_on",
            "cause_tier": "A_OFFICIAL",
            "terminal_outcome": "success" if index < 45 else "failed",
            "checkpoints": {"60m": {"directional_return_pct": 2.0}},
        }
    stock_path = tmp_path / "stock.json"
    _write_json(stock_path, {"signals": stock_rows})

    signals = []
    outcome_rows = {"signals": {}}
    for index in range(100):
        signal_id = f"o{index}"
        signals.append({"signal_id": signal_id, "score": 82, "market_regime": "risk_on", "option_type": "call"})
        outcome_rows["signals"][signal_id] = {
            "terminal_outcome": "success" if index < 70 else "failed",
            "checkpoints": {"1d": {"return_pct": 1.0}},
        }
    signals_path = tmp_path / "signals.jsonl"
    outcomes_path = tmp_path / "outcomes.json"
    _write_jsonl(signals_path, signals)
    _write_json(outcomes_path, outcome_rows)

    model = build_learning_model(
        stock_outcomes_path=stock_path,
        options_signals_path=signals_path,
        options_outcomes_path=outcomes_path,
    )
    assert model["stock"]["ready"] is True
    assert model["options"]["ready"] is True
    assert model["stock"]["matured_decisive"] == 60
    assert model["options"]["matured_decisive"] == 100
