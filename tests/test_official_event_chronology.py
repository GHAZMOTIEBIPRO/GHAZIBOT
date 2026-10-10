from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

import options_radar.official_event_scan as official_event_scan
import scripts.run_stock_radar_independent as stock_runner
from options_radar.catalysts import CatalystEvent
from options_radar.official_catalyst_intelligence import build_catalyst_intelligence
from options_radar.settings import Settings
from options_radar.stock_outcomes import StockOutcomeTracker


class _StrictScanner:
    def __init__(self, settings):
        self._event_meta = {
            ("TEST", "https://www.sec.gov/Archives/test", "8-K"): {
                "event_value": None,
                "share_count": None,
                "confidence": 0.95,
                "purpose": "definitive_merger_acquisition",
                "accession_number": "0000000000-26-123456",
                "published_at": "2026-10-09T14:20:00+00:00",
                "observed_at": "2026-10-09T14:22:00+00:00",
            }
        }

    def _sec_events(self, allowed):
        assert "TEST" in allowed
        return [
            CatalystEvent(
                symbol="TEST",
                company="Test Corp",
                event_date="2026-10-09",
                category="Merger agreement",
                headline="Test Corp enters definitive merger agreement",
                score=24,
                source="SEC EDGAR",
                form="8-K",
                url="https://www.sec.gov/Archives/test",
                evidence="definitive merger agreement",
            )
        ]

    def _ticker_map(self):
        return {}, {"TEST": "Test Corp"}

    def _fda_events(self, allowed, company_names, lookback_days):
        return []

    def _clinicaltrials_events(self, allowed, company_names, lookback_days):
        return []


def _official_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "TEST",
                "company": "Test Corp",
                "event_date": "2026-10-09",
                "category": "Merger agreement",
                "headline": "Test Corp enters definitive merger agreement",
                "score": 24,
                "source": "SEC EDGAR",
                "form": "8-K",
                "url": "https://www.sec.gov/Archives/test",
                "evidence": "definitive merger agreement",
                "event_value": None,
                "share_count": None,
                "confidence": 0.95,
                "purpose": "definitive_merger_acquisition",
                "accession_number": "0000000000-26-123456",
                "published_at": "2026-10-09T14:20:00+00:00",
                "observed_at": "2026-10-09T14:22:00+00:00",
            }
        ]
    )


def test_official_event_scan_preserves_strict_sec_chronology(monkeypatch):
    monkeypatch.setattr(
        official_event_scan,
        "StrictCatalystScanner",
        _StrictScanner,
    )
    frame = official_event_scan.scan_official_events(
        Settings(),
        ["TEST"],
        lookback_days=7,
    )

    row = frame.iloc[0]
    assert row["accession_number"] == "0000000000-26-123456"
    assert row["published_at"] == "2026-10-09T14:20:00+00:00"
    assert row["observed_at"] == "2026-10-09T14:22:00+00:00"
    assert row["purpose"] == "definitive_merger_acquisition"


def test_catalyst_cluster_carries_primary_event_chronology():
    intelligence = build_catalyst_intelligence(
        _official_frame().to_dict(orient="records"),
        [],
    )
    cluster = intelligence["by_symbol"]["TEST"]

    assert cluster["published_at"] == "2026-10-09T14:20:00+00:00"
    assert cluster["observed_at"] == "2026-10-09T14:22:00+00:00"
    assert cluster["accession_number"] == "0000000000-26-123456"


def test_stock_pipeline_freezes_real_sec_chronology_into_outcomes(
    monkeypatch,
    tmp_path,
):
    fast = tmp_path / "fast.json"
    output = tmp_path / "stocks.json"
    fast.write_text(
        json.dumps(
            {
                "generated_at": "2026-10-09T14:25:00+00:00",
                "market_rows_seen": 1,
                "actionable": [
                    {
                        "symbol": "TEST",
                        "company_name": "Test Corp",
                        "price": 10.0,
                        "move_pct": 4.0,
                        "score": 82.0,
                        "stage": "IGNITION",
                        "supply_score": 80,
                        "turnover_pct": 0.8,
                        "volume": 1_000_000,
                    }
                ],
                "halts": [],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(stock_runner, "scan_official_events", lambda *a, **k: _official_frame())
    monkeypatch.setattr(stock_runner.Settings, "validate", lambda self: None)

    payload = stock_runner.run(fast_path=fast, output_path=output)
    stock = payload["stocks"][0]

    assert stock["cause"]["published_at"] == "2026-10-09T14:20:00+00:00"
    assert stock["cause"]["observed_at"] == "2026-10-09T14:22:00+00:00"
    assert stock["cause"]["accession_number"] == "0000000000-26-123456"

    tracker = StockOutcomeTracker(tmp_path / "outcomes.json")
    tracked = tracker.update(
        [stock],
        now=datetime(2026, 10, 9, 14, 30, tzinfo=timezone.utc),
        market_regime="risk_on",
    )
    state = next(iter(tracked["signals"].values()))

    assert state["cause_published_at"] == "2026-10-09T14:20:00+00:00"
    assert state["cause_observed_at"] == "2026-10-09T14:22:00+00:00"
    assert state["cause_accession"] == "0000000000-26-123456"
