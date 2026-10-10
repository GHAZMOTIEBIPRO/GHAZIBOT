from __future__ import annotations

from datetime import datetime, timedelta, timezone

from options_radar.stock_outcomes import StockOutcomeTracker


def _stock(price: float, *, stage: str = "IGNITION", score: float = 82.0):
    return {
        "symbol": "TEST",
        "price": price,
        "move_pct": 4.0,
        "score": score,
        "stage": stage,
        "cause": {
            "category": "MERGER",
            "source_tier": "A_OFFICIAL",
            "official_confirmed": True,
        },
        "microcap_hunter": {
            "stage": "PRIORITY",
            "score": 88,
            "flags": [],
            "research_only": True,
        },
        "time_normalized_rvol": {
            "available": True,
            "ratio": 2.5,
            "pace_percentile": 90,
            "sample_sessions": 12,
            "cutoff_clock_et": "10:15",
            "source_role": "same-clock regular-session cumulative 5m volume",
            "research_only": True,
            "live_score_adjustment": False,
        },
        "sec_dilution_v2": {
            "available": True,
            "risk_score": 82,
            "risk_label": "HIGH",
            "confidence": 80,
            "observed_at": "2026-08-13T13:55:00+00:00",
            "research_only": True,
            "decision_authority": False,
            "share_history": {"growth_pct": {"30d": 25.0, "90d": 60.0, "365d": 120.0}},
            "financing": {
                "announced_capacity_to_market_cap": 0.6,
                "explicit_overhang_to_float": 0.8,
                "remaining_capacity_verified": False,
            },
        },
    }


def test_stock_outcome_tracks_mature_follow_through(tmp_path):
    path = tmp_path / "stock_outcomes.json"
    tracker = StockOutcomeTracker(path)
    start = datetime(2026, 8, 13, 14, 0, tzinfo=timezone.utc)

    first = tracker.update([_stock(10.0)], now=start, market_regime="risk_on")
    assert first["summary"]["tracked"] == 1
    assert first["summary"]["matured_60m"] == 0

    tracker.update([_stock(10.5)], now=start + timedelta(minutes=20), market_regime="risk_on")
    matured = tracker.update([_stock(11.2)], now=start + timedelta(minutes=65), market_regime="risk_on")
    assert matured["summary"]["matured_60m"] == 1
    assert matured["summary"]["successes"] == 1
    state = next(iter(matured["signals"].values()))
    assert "15m" in state["checkpoints"]
    assert "60m" in state["checkpoints"]
    assert state["terminal_outcome"] == "success"
    assert state["mfe_pct"] >= 12.0
    assert state["microcap_hunter_entry"]["stage"] == "PRIORITY"
    assert state["time_normalized_rvol_entry"]["ratio"] == 2.5
    assert state["time_normalized_rvol_entry"]["live_score_adjustment"] is False
    assert state["sec_dilution_v2_entry"]["risk_score"] == 82
    assert state["sec_dilution_v2_entry"]["remaining_capacity_verified"] is False


def test_extended_stage_is_not_started_as_new_learning_signal(tmp_path):
    tracker = StockOutcomeTracker(tmp_path / "stock_outcomes.json")
    payload = tracker.update(
        [_stock(10.0, stage="EXTENDED", score=95.0)],
        now=datetime(2026, 8, 13, 14, 0, tzinfo=timezone.utc),
        market_regime="risk_on",
    )
    assert payload["summary"]["tracked"] == 0
