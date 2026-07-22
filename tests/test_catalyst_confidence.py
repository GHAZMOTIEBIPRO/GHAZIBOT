from __future__ import annotations

import pandas as pd

from options_radar.catalyst_selection import best_catalyst_map
from options_radar.live_scanners import ResilientCatalystScanner
from options_radar.strict_catalysts import StrictCatalystScanner


def test_official_event_outranks_secondary_keyword_article() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "TEST",
                "score": 18,
                "category": "Strategic partnership",
                "headline": "Official 8-K agreement",
                "source": "SEC EDGAR",
                "form": "8-K",
                "url": "https://sec.example",
                "event_date": "2026-07-22",
                "evidence": "official filing",
                "confidence": 0.95,
                "purpose": "keyword_event",
                "event_value": None,
            },
            {
                "symbol": "TEST",
                "score": 25,
                "category": "Acquisition",
                "headline": "Opinion article mentions acquisition",
                "source": "Yahoo Finance News",
                "form": "NEWS",
                "url": "https://news.example",
                "event_date": "2026-07-22",
                "evidence": "headline keyword",
                "confidence": 0.35,
                "purpose": "secondary_news",
                "event_value": None,
            },
        ]
    )
    selected = best_catalyst_map(frame)["TEST"]
    assert selected["source"] == "SEC EDGAR"
    assert selected["form"] == "8-K"
    assert selected["confidence"] == 0.95
    assert selected["score"] > 15


def test_secondary_news_is_capped_and_labeled(monkeypatch) -> None:
    source = pd.DataFrame(
        [
            {
                "symbol": "ROKU",
                "score": 20,
                "category": "Acquisition",
                "headline": "Article mentions a bid",
                "source": "Yahoo Finance News",
                "form": "NEWS",
                "url": "https://news.example",
                "event_date": "2026-07-22",
                "evidence": "to acquire",
                "confidence": 0.5,
                "purpose": "",
                "event_value": None,
            }
        ]
    )
    monkeypatch.setattr(
        ResilientCatalystScanner,
        "scan",
        lambda self, symbols, lookback_days=7: source.copy(),
    )
    scanner = object.__new__(StrictCatalystScanner)
    result = scanner.scan(["ROKU"])
    row = result.iloc[0]
    assert row["score"] == 8
    assert row["confidence"] == 0.35
    assert row["purpose"] == "secondary_news"
    assert str(row["category"]).startswith("Secondary mention")
