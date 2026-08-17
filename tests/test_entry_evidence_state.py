from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from options_radar.adaptive_learning import build_learning_model, stock_score_adjustment
from options_radar.stock_outcome_archive import update_stock_outcome_archive
from options_radar.stock_outcomes import StockOutcomeTracker


def _stock(*, status: str, official: bool = False, tier: str | None = None) -> dict:
    return {
        "symbol": "TEST",
        "price": 10.0,
        "move_pct": 4.0,
        "score": 82.0,
        "stage": "IGNITION",
        "cause": {
            "status": status,
            "category": "MERGER" if official else None,
            "source_tier": tier,
            "official_confirmed": official,
            "source": "SEC" if official else None,
        },
    }


def _mature(tracker: StockOutcomeTracker, stock: dict, start: datetime) -> dict:
    tracker.update([stock], now=start, market_regime="risk_on")
    follow = dict(stock)
    follow["price"] = 11.2
    return tracker.update([follow], now=start + timedelta(minutes=65), market_regime="risk_on")


def test_no_primary_cause_is_frozen_as_explicit_entry_evidence_state(tmp_path) -> None:
    tracker = StockOutcomeTracker(tmp_path / "stock_outcomes.json")
    payload = tracker.update(
        [_stock(status="NO_PRIMARY_CAUSE_PROVEN")],
        now=datetime(2026, 8, 17, 15, 0, tzinfo=timezone.utc),
        market_regime="risk_on",
    )
    state = next(iter(payload["signals"].values()))

    assert state["entry_evidence_state"] == "NO_PRIMARY_CAUSE_PROVEN"
    assert state["entry_cause_status"] == "NO_PRIMARY_CAUSE_PROVEN"
    assert state["cause_tier"] == "unknown"
    assert state["official_cause"] is False


def test_official_cause_freezes_official_entry_evidence_state(tmp_path) -> None:
    tracker = StockOutcomeTracker(tmp_path / "stock_outcomes.json")
    payload = tracker.update(
        [_stock(status="PRIMARY_CAUSE_PROVEN", official=True, tier="A_OFFICIAL")],
        now=datetime(2026, 8, 17, 15, 0, tzinfo=timezone.utc),
        market_regime="risk_on",
    )
    state = next(iter(payload["signals"].values()))

    assert state["entry_evidence_state"] == "OFFICIAL_CONFIRMED"
    assert state["cause_tier"] == "A_OFFICIAL"
    assert state["official_cause"] is True


def test_archive_keeps_legacy_evidence_unknown_instead_of_backfilling_future_info(tmp_path) -> None:
    outcomes = tmp_path / "stock_outcomes.json"
    archive = tmp_path / "archive.json"
    outcomes.write_text(
        json.dumps(
            {
                "signals": {
                    "legacy": {
                        "signal_id": "legacy",
                        "signal_time": "2026-08-13T14:00:00+00:00",
                        "symbol": "TEST",
                        "direction": "up",
                        "entry_price": 10.0,
                        "stage": "IGNITION",
                        "score": 82.0,
                        "score_band": "80-89",
                        "terminal_outcome": "success",
                        "checkpoints": {"60m": {"directional_return_pct": 10.0}},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    payload = update_stock_outcome_archive(outcomes, archive)
    row = payload["records"]["legacy"]
    assert row["entry_evidence_state"] == "LEGACY_UNKNOWN"
    assert row["entry_cause_status"] == "LEGACY_UNKNOWN"


def test_learning_reports_evidence_cohorts_but_live_adjustment_ignores_them(tmp_path) -> None:
    outcomes = tmp_path / "stock_outcomes.json"
    archive = tmp_path / "archive.json"
    tracker = StockOutcomeTracker(outcomes)
    start = datetime(2026, 8, 17, 15, 0, tzinfo=timezone.utc)
    _mature(tracker, _stock(status="NO_PRIMARY_CAUSE_PROVEN"), start)
    update_stock_outcome_archive(outcomes, archive)

    options_signals = tmp_path / "options.jsonl"
    options_signals.write_text("", encoding="utf-8")
    options_outcomes = tmp_path / "options_outcomes.json"
    options_outcomes.write_text('{"signals": {}}', encoding="utf-8")

    model = build_learning_model(
        stock_outcomes_path=outcomes,
        stock_archive_path=archive,
        options_signals_path=options_signals,
        options_outcomes_path=options_outcomes,
    )
    assert "NO_PRIMARY_CAUSE_PROVEN" in model["stock"]["evidence_states"]
    assert model["policy"]["entry_evidence_state_is_research_only_until_walk_forward"] is True

    # Even a deliberately extreme synthetic research cohort must have zero live authority.
    model["stock"]["ready"] = True
    model["stock"]["evidence_states"] = {
        "NO_PRIMARY_CAUSE_PROVEN": {
            "sample": 999,
            "successes": 999,
            "failures": 0,
            "success_rate": 1.0,
            "eligible": True,
            "score_adjustment": 8.0,
        }
    }
    model["stock"]["score_bands"] = {}
    model["stock"]["stages"] = {}
    model["stock"]["regimes"] = {}
    model["stock"]["cause_tiers"] = {}

    assert stock_score_adjustment(
        model,
        {
            "score": 82.0,
            "stage": "IGNITION",
            "market_regime": "risk_on",
            "cause": {"source_tier": "unknown"},
            "entry_evidence_state": "NO_PRIMARY_CAUSE_PROVEN",
        },
    ) == 0.0
