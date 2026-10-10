from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from options_radar.catalyst_selection import best_catalyst_map
from options_radar import sec_attention
from options_radar.sec_attention import ATTENTION_QUERIES, _item_materiality
from options_radar.settings import Settings


def test_precision_queries_avoid_generic_acquisition_only_search():
    merger = next(query for query in ATTENTION_QUERIES if query.family == "definitive_ma")
    assert '"definitive merger agreement"' in merger.query
    assert merger.forms == "8-K,6-K,SC 13D,SC 13D/A"
    assert merger.confidence >= 0.90
    assert merger.query.strip() != '"acquisition"'


def test_8k_materiality_bonus_recognizes_transaction_items():
    bonus, reasons = _item_materiality(["1.01", "2.01", "8.01"])
    assert bonus == 6.0
    assert any("2.01" in reason for reason in reasons)


def test_fresh_precision_sec_event_outranks_stale_generic_event():
    today = date.today().isoformat()
    stale = (date.today() - timedelta(days=25)).isoformat()
    frame = pd.DataFrame(
        [
            {
                "symbol": "TEST",
                "score": 20,
                "confidence": 0.75,
                "source": "SEC EDGAR",
                "event_date": stale,
                "purpose": "keyword_event",
                "category": "Generic event",
                "headline": "Old filing",
                "url": "old",
                "form": "8-K",
            },
            {
                "symbol": "TEST",
                "score": 18,
                "confidence": 0.94,
                "source": "SEC EDGAR Precision Full-Text",
                "event_date": today,
                "purpose": "strategic_contract",
                "category": "Strategic agreement",
                "headline": "Fresh material filing",
                "url": "fresh",
                "form": "8-K",
                "query_family": "strategic_contract",
                "items": ["1.01"],
            },
        ]
    )
    selected = best_catalyst_map(frame)["TEST"]
    assert selected["url"] == "fresh"
    assert selected["freshness"] == 1.0
    assert selected["query_family"] == "strategic_contract"

def test_precision_sec_stops_all_query_families_after_source_failure(monkeypatch, tmp_path):
    calls = []

    def fail_once(settings, params, **kwargs):
        calls.append(params)
        raise RuntimeError("SEC EFTS circuit open")

    monkeypatch.setattr(sec_attention, "request_efts_json", fail_once)
    rows = sec_attention.discover_attention_events(
        Settings(database_path=tmp_path / "state.json"),
        lookback_days=30,
    )

    assert rows == []
    assert len(calls) == 1

