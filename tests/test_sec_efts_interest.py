from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from options_radar.interest_factors import finviz_style_profile
from options_radar.sec_efts import (
    EftsQuery,
    _display_identity,
    _document_url,
    discover_sec_fulltext_events,
)
from options_radar.universe import build_dynamic_universe


def test_efts_identity_and_document_url():
    source = {
        "display_names": ["Example Therapeutics, Inc. (EXMP) (CIK 0001234567)"],
        "ciks": ["0001234567"],
        "adsh": "0001234567-26-000001",
    }
    symbol, company, cik = _display_identity(source)
    assert symbol == "EXMP"
    assert company == "Example Therapeutics, Inc."
    assert cik == "0001234567"

    url = _document_url(
        {
            "_id": "0001234567-26-000001:ex99-1.htm",
            "_source": source,
        }
    )
    assert url == (
        "https://www.sec.gov/Archives/edgar/data/1234567/"
        "000123456726000001/ex99-1.htm"
    )


def test_efts_discovery_builds_grounded_event(tmp_path, monkeypatch):
    query = EftsQuery(
        "fda_material",
        '"FDA approval"',
        "8-K",
        24,
        "FDA / clinical milestone",
        "fda_or_clinical_milestone",
        0.9,
    )
    monkeypatch.setattr("options_radar.sec_efts.EFTS_QUERIES", (query,))
    monkeypatch.setattr("options_radar.sec_efts.CACHE_PATH", tmp_path / "efts.json")

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "timed_out": False,
                "hits": {
                    "hits": [
                        {
                            "_id": "0001234567-26-000001:ex99-1.htm",
                            "_source": {
                                "display_names": [
                                    "Example Therapeutics, Inc. (EXMP) (CIK 0001234567)"
                                ],
                                "ciks": ["0001234567"],
                                "adsh": "0001234567-26-000001",
                                "form": "8-K",
                                "file_date": pd.Timestamp.today().date().isoformat(),
                                "file_type": "EX-99.1",
                                "file_description": "PRESS RELEASE",
                                "items": ["8.01", "9.01"],
                            },
                        }
                    ]
                },
            }

    monkeypatch.setattr("options_radar.sec_efts.requests.get", lambda *a, **k: Response())
    events = discover_sec_fulltext_events(
        SimpleNamespace(sec_user_agent="GHAZI test contact@example.com"),
        lookback_days=14,
    )
    assert len(events) == 1
    event = events[0]
    assert event["symbol"] == "EXMP"
    assert event["score"] == 24
    assert event["source"] == "SEC EDGAR Full-Text"
    assert event["confidence"] == 0.9
    assert "8-K items 8.01, 9.01" in event["evidence"]


def test_dynamic_universe_places_sec_before_general_movers(monkeypatch):
    monkeypatch.setattr(
        "options_radar.universe.sec_event_symbols",
        lambda settings: ["EVENT1", "EVENT2", "LATEST"],
    )
    monkeypatch.setattr(
        "options_radar.universe.nasdaq_mover_symbols",
        lambda: ["MOVE1", "MOVE2"],
    )
    monkeypatch.setattr(
        "options_radar.universe._load_alias_symbols",
        lambda: ["ALIAS"],
    )
    symbols, sources = build_dynamic_universe(
        ["BASE1", "BASE2"],
        SimpleNamespace(max_universe_size=6),
    )
    assert symbols == ["BASE1", "BASE2", "EVENT1", "EVENT2", "LATEST", "MOVE1"]
    assert sources["sec_events"] == 3


def test_finviz_style_profile_rewards_trend_breakout_and_volume():
    periods = 252
    index = pd.date_range("2025-01-01", periods=periods, freq="B")
    close = np.linspace(50.0, 100.0, periods)
    close[-1] = 104.0
    volume = np.full(periods, 1_000_000.0)
    volume[-1] = 2_500_000.0
    frame = pd.DataFrame(
        {
            "Open": close * 0.995,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": volume,
        },
        index=index,
    )

    profile = finviz_style_profile(frame)
    assert profile["attention_score"] >= 8
    assert profile["call_interest_score"] > profile["put_interest_score"]
    assert profile["breakout20"] is True
    assert profile["performance_month"] > 0
    assert "اختراق 20 يومًا" in profile["upside_factors"]


def test_finviz_style_profile_flags_low_price_weak_liquidity():
    periods = 100
    index = pd.date_range("2025-01-01", periods=periods, freq="B")
    close = np.linspace(0.8, 0.6, periods)
    frame = pd.DataFrame(
        {
            "Open": close,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": np.full(periods, 10_000.0),
        },
        index=index,
    )
    profile = finviz_style_profile(frame)
    assert profile["attention_score"] == 0
    assert "سهم منخفض السعر عالي المخاطر" in profile["attention_factors"]
