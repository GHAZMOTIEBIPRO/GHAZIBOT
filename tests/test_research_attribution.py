from __future__ import annotations

import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd

from options_radar.research_attribution import (
    add_causal_replay_features,
    build_stock_research_features,
    evaluate_replay_feature_ablation,
    evaluate_stock_research_attribution,
    history_before_signal,
)


class _FakeSmc:
    @classmethod
    def fvg(cls, ohlc, join_consecutive=False):
        frame = pd.DataFrame(
            {
                "FVG": np.nan,
                "Top": np.nan,
                "Bottom": np.nan,
                "MitigatedIndex": np.nan,
            },
            index=ohlc.index,
        )
        if len(frame) > 5:
            frame.loc[frame.index[-3], ["FVG", "Top", "Bottom"]] = [1, 120.0, 118.0]
        if len(frame) > 12:
            frame.loc[frame.index[10], ["FVG", "Top", "Bottom"]] = [1, 105.0, 103.0]
        return frame

    @classmethod
    def swing_highs_lows(cls, ohlc, swing_length=20):
        frame = pd.DataFrame({"HighLow": np.nan, "Level": np.nan}, index=ohlc.index)
        if len(frame) > 12:
            frame.loc[frame.index[10], ["HighLow", "Level"]] = [-1, 95.0]
        return frame


def _history(rows: int = 100) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=rows, freq="D", tz="UTC")
    close = np.linspace(80.0, 130.0, rows)
    return pd.DataFrame(
        {
            "Open": close - 0.4,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.linspace(1_000_000, 2_000_000, rows),
        },
        index=index,
    )


def _record(**overrides):
    row = {
        "signal_id": "s1",
        "signal_time": "2026-04-11T15:00:00+00:00",
        "signal_session_valid": True,
        "symbol": "TEST",
        "direction": "up",
        "audit_status": "success",
        "coverage": {"60m": True},
        "checkpoints": {
            "60m": {
                "coverage_qualified": True,
                "directional_return_pct": 8.0,
            }
        },
        "official_cause": True,
        "cause_source": "SEC EDGAR",
        "cause_url": "https://www.sec.gov/Archives/example",
        "cause_tier": "A_OFFICIAL",
        "entry_evidence_state": "OFFICIAL_CONFIRMED",
        "cause_published_at": "2026-04-11T14:00:00+00:00",
        "cause_observed_at": "2026-04-11T15:00:00+00:00",
        "cause_accession": "0000000000-26-000001",
        "cause_point_in_time_frozen": True,
    }
    row.update(overrides)
    return row


def test_history_before_signal_excludes_signal_day_close():
    history = _history()
    signal_time = datetime(2026, 4, 10, 15, 0, tzinfo=timezone.utc)
    sliced = history_before_signal(history, signal_time)

    assert not sliced.empty
    assert all(stamp.date() < signal_time.date() for stamp in sliced.index)


def test_stock_features_join_sec_chart_and_hindsight_safe_smc(monkeypatch):
    monkeypatch.setitem(sys.modules, "smartmoneyconcepts", SimpleNamespace(smc=_FakeSmc))
    features = build_stock_research_features(_record(), _history())

    assert features["decision_authority"] is False
    assert features["sec"]["official_sec_evidence"] is True
    assert features["sec"]["point_in_time_sec_evidence"] is True
    assert features["sec"]["chronology_verified"] is True
    assert features["chart"]["direction_alignment"] is True
    assert features["smc"]["direction_alignment"] is True
    assert features["aligned_evidence_count"] == 3


def test_stock_attribution_measures_lift_without_live_authority():
    records = {}
    for index in range(24):
        aligned = index < 12
        records[str(index)] = _record(
            signal_id=str(index),
            audit_status="success" if aligned else "failed",
            research_features={
                "sec": {
                    "source_metadata_available": True,
                    "official_sec_evidence": aligned,
                    "point_in_time_sec_evidence": aligned,
                },
                "chart": {"direction_alignment": aligned},
                "smc": {"direction_alignment": aligned},
                "aligned_evidence_count": 3 if aligned else 0,
            },
            checkpoints={
                "60m": {
                    "coverage_qualified": True,
                    "directional_return_pct": 8.0 if aligned else -6.0,
                }
            },
        )
    report = evaluate_stock_research_attribution({"records": records}, minimum_sample=10)

    assert report["decision_authority"] is False
    assert report["live_alert_weights_changed"] is False
    assert report["factors"]["chart_direction_alignment"]["sample_ready"] is True
    assert report["factors"]["chart_direction_alignment"]["success_rate_lift_pp"] == 100.0
    assert report["factors"]["two_of_three_alignment"]["mean_60m_return_lift_pct"] == 14.0


def test_replay_smc_features_are_shifted_before_becoming_available(monkeypatch):
    monkeypatch.setitem(sys.modules, "smartmoneyconcepts", SimpleNamespace(smc=_FakeSmc))
    frame = _history(80)
    frame["replay_score"] = 70.0
    frame["future_5d_max_return_pct"] = 0.0
    frame["explosion_label"] = False

    enriched = add_causal_replay_features(frame, swing_length=20)

    assert bool(enriched.iloc[10]["research_smc_bullish_fvg"]) is False
    assert bool(enriched.iloc[11]["research_smc_bullish_fvg"]) is True
    assert bool(enriched.iloc[10]["research_smc_confirmed_swing_low"]) is False
    assert bool(enriched.iloc[30]["research_smc_confirmed_swing_low"]) is True


def test_replay_ablation_never_changes_threshold_authority():
    frame = _history(60)
    frame["replay_score"] = [70.0 if index % 2 == 0 else 50.0 for index in range(60)]
    frame["future_5d_max_return_pct"] = [120.0 if index % 4 == 0 else 0.0 for index in range(60)]
    frame["explosion_label"] = frame["future_5d_max_return_pct"] >= 100.0
    frame["research_chart_bullish"] = [index % 4 == 0 for index in range(60)]
    frame["research_smc_bullish_fvg"] = [index % 4 == 0 for index in range(60)]

    report = evaluate_replay_feature_ablation(frame, threshold=60.0)

    assert report["decision_authority"] is False
    assert report["live_threshold_auto_changed"] is False
    assert report["variants"]["chart_and_smc_fvg"]["precision"] >= report["baseline"]["precision"]
    assert report["sec_replay_status"] == "not_reconstructed_historically"

def test_future_sec_filing_is_not_upgraded_to_point_in_time_evidence(monkeypatch):
    monkeypatch.setitem(sys.modules, "smartmoneyconcepts", SimpleNamespace(smc=_FakeSmc))
    features = build_stock_research_features(
        _record(cause_published_at="2026-04-12T14:00:00+00:00"),
        _history(),
    )

    assert features["sec"]["official_sec_evidence"] is True
    assert features["sec"]["point_in_time_sec_evidence"] is False
    assert features["sec"]["chronology_verified"] is False

