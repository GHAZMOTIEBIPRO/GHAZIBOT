from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd

from options_radar.omega_target_learning import (
    _evaluate_target,
    build_target_calibration,
    record_target_signals,
    target_probability,
    update_target_outcomes,
)
from options_radar.target_horizon import estimate_target_horizon


def _opportunity():
    return {
        "symbol": "TEST",
        "price": 100.0,
        "direction": "UPSIDE",
        "opportunity_tier": "A",
        "explosion_rank": 84,
        "explosion_cause": {"primary": "MULTI_FACTOR_EXPLOSION"},
        "target_map": {
            "invalidation": {"price": 95.0},
            "t1": {"price": 105.0, "source": "resistance20", "provenance": "SOURCE_DERIVED"},
            "t2": {"price": 110.0, "source": "atr", "provenance": "MODELED"},
            "t3": {"price": 115.0, "source": "atr", "provenance": "MODELED"},
        },
        "target_horizon": {
            "primary_horizon": "SHORT_1_3D",
            "targets": [
                {"target": "T1", "horizon_bucket": "SHORT_1_3D", "estimated_time_ar": "1–3 جلسات"},
                {"target": "T2", "horizon_bucket": "SWING_3_7D", "estimated_time_ar": "3–7 جلسات"},
                {"target": "T3", "horizon_bucket": "POSITION_1_4W", "estimated_time_ar": "1–4 أسابيع"},
            ],
        },
    }


def _bars(rows):
    index = pd.date_range("2026-10-01 14:30", periods=len(rows), freq="5min", tz="UTC")
    return pd.DataFrame(rows, index=index)


def test_target_path_hit_before_stop():
    frame = _bars([
        {"High": 102, "Low": 99},
        {"High": 106, "Low": 98},
    ])
    result = _evaluate_target(
        frame=frame,
        signal_time=datetime(2026, 10, 1, 14, 30, tzinfo=timezone.utc),
        direction="UPSIDE",
        target_price=105,
        invalidation=95,
        maturity_sessions=3,
    )
    assert result["status"] == "HIT"
    assert result["sessions_to_hit"] == 1
    assert result["matured"] is True


def test_target_path_stop_before_target():
    frame = _bars([
        {"High": 102, "Low": 94},
        {"High": 108, "Low": 96},
    ])
    result = _evaluate_target(
        frame=frame,
        signal_time=datetime(2026, 10, 1, 14, 30, tzinfo=timezone.utc),
        direction="UPSIDE",
        target_price=105,
        invalidation=95,
        maturity_sessions=3,
    )
    assert result["status"] == "FAILED"
    assert result["hit_at"] is None


def test_target_path_same_bar_is_ambiguous_not_win():
    frame = _bars([{"High": 106, "Low": 94}])
    result = _evaluate_target(
        frame=frame,
        signal_time=datetime(2026, 10, 1, 14, 30, tzinfo=timezone.utc),
        direction="UPSIDE",
        target_price=105,
        invalidation=95,
        maturity_sessions=1,
    )
    assert result["status"] == "AMBIGUOUS"
    assert result["matured"] is True


def test_target_path_matured_miss_after_required_sessions():
    frame = pd.DataFrame(
        [{"High": 102, "Low": 98}, {"High": 103, "Low": 97}],
        index=pd.to_datetime(["2026-10-01T15:00:00Z", "2026-10-02T15:00:00Z"]),
    )
    result = _evaluate_target(
        frame=frame,
        signal_time=datetime(2026, 10, 1, 14, 30, tzinfo=timezone.utc),
        direction="UPSIDE",
        target_price=110,
        invalidation=95,
        maturity_sessions=2,
    )
    assert result["status"] == "MATURED_MISS"


def test_signal_recording_dedupes_repeated_scan_inside_four_hours():
    state = {"signals": {}}
    start = datetime(2026, 10, 1, 14, 30, tzinfo=timezone.utc)
    assert record_target_signals([_opportunity()], state, generated_at=start) == 1
    assert record_target_signals(
        [_opportunity()],
        state,
        generated_at=start + timedelta(minutes=30),
    ) == 0
    assert len(state["signals"]) == 1


def _calibration_state(count: int, hits: int):
    signals = {}
    for index in range(count):
        status = "HIT" if index < hits else "MATURED_MISS"
        signals[str(index)] = {
            "targets": {
                "T1": {
                    "target": "T1",
                    "horizon_bucket": "SHORT_1_3D",
                    "matured": True,
                    "status": status,
                    "sessions_to_hit": 2 if status == "HIT" else None,
                    "elapsed_hours_to_hit": 9.5 if status == "HIT" else None,
                }
            }
        }
    return {"signals": signals}


def test_calibration_requires_global_100_sample_gate():
    model = build_target_calibration(_calibration_state(99, 70))
    assert model["calibration_ready"] is False
    assert target_probability(model, target="T1", horizon_bucket="SHORT_1_3D") is None


def test_calibration_exposes_rate_ci_and_time_after_sample_gates():
    model = build_target_calibration(_calibration_state(100, 70))
    row = target_probability(model, target="T1", horizon_bucket="SHORT_1_3D")
    assert model["calibration_ready"] is True
    assert row is not None
    assert row["historical_sample"] == 100
    assert row["historical_hit_rate"] == 0.7
    assert row["ci95_low"] < 0.7 < row["ci95_high"]
    assert row["median_sessions_to_hit"] == 2.0


def test_target_horizon_shows_probability_only_when_calibrated():
    model = build_target_calibration(_calibration_state(100, 70))
    stock = {"symbol": "TEST", "price": 100, "atr": 3, "setup_side": "call"}
    target_map = {"t1": {"price": 106}}
    result = estimate_target_horizon(stock, target_map, calibration=model)
    assert result["is_probability"] is True
    assert result["targets"][0]["historical_hit_rate_pct"] == 70.0
    assert result["targets"][0]["historical_sample"] == 100
    assert "وسيط تاريخي" in result["targets"][0]["estimated_time_ar"]


def test_update_target_outcomes_uses_underlying_bars_only():
    start = datetime(2026, 10, 1, 14, 30, tzinfo=timezone.utc)
    state = {"signals": {}}
    record_target_signals([_opportunity()], state, generated_at=start)

    class Fetcher:
        def fetch_stock_bars(self, symbol, *, start, end, interval):
            frame = pd.DataFrame(
                [
                    {"High": 102, "Low": 99},
                    {"High": 106, "Low": 98},
                ],
                index=pd.to_datetime(["2026-10-01T14:35:00Z", "2026-10-01T14:40:00Z"]),
            )
            return SimpleNamespace(data=frame, source="test")

    updated = update_target_outcomes(
        state,
        now=start + timedelta(hours=1),
        fetcher=Fetcher(),
    )
    signal = next(iter(updated["signals"].values()))
    assert signal["targets"]["T1"]["status"] == "HIT"
    assert signal["measurement_basis"] == "underlying_ohlc_path"
