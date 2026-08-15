import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd

from options_radar.options_consensus import build_directional_signals
from options_radar.outcome_learning import (
    apply_learning_adjustments,
    build_calibration,
    update_outcome_learning,
)
from options_radar.settings import Settings


CONTRACT = "XYZ260918C00100000"


def _signal(**overrides):
    row = {
        "symbol": "XYZ",
        "contract_symbol": CONTRACT,
        "direction": "CALL",
        "direction_label": "CALL",
        "option_type": "call",
        "signal_grade": "A+",
        "strict_grade": "A+",
        "strict_score": 92,
        "side_consensus_score": 91,
        "strike": 100,
        "expiration": "2026-09-18",
        "dte": 35,
        "bid": 4.90,
        "ask": 5.10,
        "last": 5.00,
        "spread_pct": 0.0392,
        "delta": 0.48,
        "gamma_context_alignment": 0.22,
        "gamma_concentration_pct": 16,
        "vol_to_oi_ratio": 2.4,
        "flow_momentum_score": 88,
        "data_quality": 0.72,
        "source": "test",
        "freshness_label": "test quote",
        "free_alert_eligible": True,
    }
    row.update(overrides)
    return row


def _payload(row=None):
    return {
        "path": "options",
        "provider_readiness": {"production_quote_ready": False, "status": "RESEARCH_ONLY"},
        "free_directional_signals": [row or _signal()],
    }


class FakeFetcher:
    def __init__(self):
        self.bid = 4.90
        self.ask = 5.10
        self.last = 5.00
        self.calls = 0

    def fetch_option_chain(self, symbol, **kwargs):
        self.calls += 1
        frame = pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "contract_symbol": CONTRACT,
                    "bid": self.bid,
                    "ask": self.ask,
                    "last": self.last,
                    "source": "fake",
                    "freshness_label": "live-test",
                    "data_quality": 0.9,
                }
            ]
        )
        return SimpleNamespace(data=frame)


def _settings(tmp_path, minimum=100):
    return Settings(
        signal_journal_path=tmp_path / "signals.jsonl",
        outcome_path=tmp_path / "outcomes.json",
        calibration_path=tmp_path / "calibration.json",
        calibration_minimum_sample=minimum,
    )


def test_learning_tracks_once_and_records_15m_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("OPTIONS_FREE_ALERT_MIN_SCORE", "87")
    settings = _settings(tmp_path)
    fetcher = FakeFetcher()
    created_at = datetime(2026, 8, 14, 14, 45, tzinfo=timezone.utc)

    first = update_outcome_learning(
        _payload(), settings=settings, fetcher=fetcher, now=created_at
    )
    assert first["tracked_new"] == 1
    assert first["calibration_active"] is False

    fetcher.bid = 5.50
    fetcher.ask = 5.70
    fetcher.last = 5.60
    second = update_outcome_learning(
        _payload(),
        settings=settings,
        fetcher=fetcher,
        now=created_at + timedelta(minutes=15),
    )
    assert second["tracked_new"] == 0

    state = json.loads(settings.outcome_path.read_text(encoding="utf-8"))
    assert len(state["signals"]) == 1
    signal = next(iter(state["signals"].values()))
    assert signal["entry_quote_method"] == "ask_to_bid"
    assert signal["entry_price"] == 5.10
    assert "15m" in signal["checkpoints"]
    assert signal["checkpoints"]["15m"]["return_pct"] > 0
    journal = settings.signal_journal_path.read_text(encoding="utf-8").splitlines()
    assert sum('"event": "signal_created"' in line for line in journal) == 1
    assert any('"checkpoint": "15m"' in line for line in journal)


def test_calibration_stays_inactive_below_minimum_sample():
    state = {"signals": {}}
    for index in range(25):
        state["signals"][str(index)] = {
            "entry_quote_method": "ask_to_bid",
            "features": {
                "delta": 0.40,
                "dte": 28,
                "gamma_context_alignment": 0.2,
                "vol_to_oi_ratio": 2.2,
                "spread_pct": 0.04,
            },
            "checkpoints": {"60m": {"quote_method": "ask_to_bid", "return_pct": 10}},
        }
    calibration = build_calibration(state, minimum_sample=100)
    assert calibration["active"] is False
    assert calibration["sample_size"] == 25
    rows = apply_learning_adjustments([_signal()], calibration)
    assert rows[0]["learning_adjustment"] == 0
    assert rows[0]["learning_active"] is False


def test_calibration_activates_with_shrinkage_and_bounded_adjustment():
    state = {"signals": {}}
    for index in range(120):
        strong = index < 60
        state["signals"][str(index)] = {
            "entry_quote_method": "ask_to_bid",
            "features": {
                "delta": 0.38 if strong else 0.58,
                "dte": 28,
                "gamma_context_alignment": 0.2,
                "vol_to_oi_ratio": 2.2,
                "spread_pct": 0.04,
            },
            "checkpoints": {
                "60m": {
                    "quote_method": "ask_to_bid",
                    "return_pct": 20 if strong else -10,
                }
            },
        }
    calibration = build_calibration(state, minimum_sample=100)
    assert calibration["active"] is True
    assert calibration["sample_size"] == 120
    strong_stats = calibration["features"]["abs_delta"]["0.35-0.42"]
    weak_stats = calibration["features"]["abs_delta"]["0.56-0.62"]
    assert strong_stats["adjustment"] > 0
    assert weak_stats["adjustment"] < 0

    adjusted = apply_learning_adjustments([_signal(delta=0.38)], calibration)[0]
    assert 0 < adjusted["learning_adjustment"] <= 4
    assert adjusted["learning_active"] is True


def test_learning_never_bypasses_hard_spread_blocker():
    row = {
        "symbol": "XYZ",
        "contract_symbol": CONTRACT,
        "option_type": "call",
        "score": 99,
        "flow_momentum_score": 99,
        "data_quality": 0.95,
        "execution_score": 30,
        "reward_risk_1": 2.0,
        "spread_pct": 0.14,
        "vol_to_oi_ratio": 4.0,
        "volume": 5000,
        "open_interest": 5000,
        "delta": 0.50,
        "dte": 28,
        "gamma_concentration_pct": 20,
        "gamma_context_alignment": 0.3,
        "gamma_coverage_pct": 95,
        "oi_coverage_pct": 95,
        "occ_side_context": {"available": False, "bonus": 0},
        "learning_active": True,
        "learning_adjustment": 4.0,
    }
    assert build_directional_signals([row], minimum_score=70) == []
