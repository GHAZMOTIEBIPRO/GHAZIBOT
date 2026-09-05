from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from options_radar.halt_news_engine import NewsEvent
from scripts.send_news_flash_24x7 import (
    classify_materiality,
    parse_published,
    price_reaction,
    reaction_state,
    should_edit,
    source_class,
)


def _event(headline: str, *, provider: str = "globenewswire_rss", sentiment: float = 0.0) -> NewsEvent:
    return NewsEvent(
        symbol="XYZ",
        headline=headline,
        source="Test source",
        url="https://example.com/release",
        published="2026-09-05T12:00:00Z",
        relevance=0.9,
        sentiment=sentiment,
        provider=provider,
    )


def _frame(values: list[tuple[str, float, float, float]]) -> pd.DataFrame:
    index = pd.to_datetime([row[0] for row in values], utc=True)
    return pd.DataFrame(
        {
            "Close": [row[1] for row in values],
            "High": [row[2] for row in values],
            "Low": [row[3] for row in values],
        },
        index=index,
    )


def test_parse_published_supports_rfc_and_iso() -> None:
    now = datetime(2026, 9, 5, 13, 0, tzinfo=timezone.utc)
    assert parse_published("Sat, 05 Sep 2026 12:30:00 GMT", now=now) == datetime(
        2026, 9, 5, 12, 30, tzinfo=timezone.utc
    )
    assert parse_published("2026-09-05T12:31:00Z", now=now) == datetime(
        2026, 9, 5, 12, 31, tzinfo=timezone.utc
    )


def test_materiality_and_source_class_do_not_turn_release_into_official_proof() -> None:
    bias, materiality, reasons = classify_materiality(
        _event("XYZ raises guidance after record revenue")
    )
    assert bias == "POSITIVE"
    assert materiality >= 4
    assert "raises guidance" in reasons
    assert source_class(_event("XYZ raises guidance")) == "DIRECT_COMPANY_RELEASE"
    assert source_class(_event("XYZ raises guidance", provider="finnhub")) == "SECONDARY_NEWS"


def test_negative_offering_is_material_and_directional() -> None:
    bias, materiality, _ = classify_materiality(
        _event("XYZ announces registered direct offering")
    )
    assert bias == "NEGATIVE"
    assert materiality == 5


def test_price_reaction_ignores_pre_news_move_and_detects_fade() -> None:
    event_at = datetime(2026, 9, 5, 12, 2, tzinfo=timezone.utc)
    frame = _frame(
        [
            ("2026-09-05T12:00:00Z", 90.0, 91.0, 89.0),
            ("2026-09-05T12:01:00Z", 100.0, 100.0, 99.0),
            ("2026-09-05T12:02:00Z", 108.0, 110.0, 105.0),
            ("2026-09-05T12:03:00Z", 104.0, 109.0, 103.0),
            ("2026-09-05T12:04:00Z", 102.0, 104.0, 101.0),
        ]
    )
    reaction = price_reaction(frame, event_at, "POSITIVE")
    assert reaction is not None
    assert reaction["baseline"] == 100.0
    assert reaction["signed_move_pct"] == 2.0
    assert reaction["peak_aligned_pct"] == 10.0
    assert reaction["fade_pct"] == 80.0
    assert reaction_state(reaction, bias="POSITIVE", age_minutes=5) == "FADED"


def test_extended_and_diverging_states_fail_against_chasing() -> None:
    extended = {
        "signed_move_pct": 9.2,
        "aligned_move_pct": 9.2,
        "peak_aligned_pct": 9.8,
        "fade_pct": 6.0,
    }
    assert reaction_state(extended, bias="POSITIVE", age_minutes=8) == "EXTENDED"

    diverging = {
        "signed_move_pct": -2.0,
        "aligned_move_pct": -2.0,
        "peak_aligned_pct": 1.0,
        "fade_pct": 0.0,
    }
    assert reaction_state(diverging, bias="POSITIVE", age_minutes=8) == "DIVERGING"


def test_same_message_is_edited_only_for_material_reaction_change() -> None:
    old = {
        "reaction_state": "EARLY",
        "reaction": {"signed_move_pct": 1.5, "fade_pct": 5.0},
    }
    tiny = {
        "reaction_state": "EARLY",
        "reaction": {"signed_move_pct": 2.0, "fade_pct": 10.0},
    }
    running = {
        "reaction_state": "RUNNING",
        "reaction": {"signed_move_pct": 3.0, "fade_pct": 10.0},
    }
    assert should_edit(old, tiny) is False
    assert should_edit(old, running) is True


def test_workflow_is_every_five_minutes_all_days_and_not_market_gated() -> None:
    workflow = Path(".github/workflows/news-flash-24x7.yml").read_text(encoding="utf-8")
    assert '2,7,12,17,22,27,32,37,42,47,52,57 * * * *' in workflow
    assert "* * * * 1-5" not in workflow
    assert "market_clock_gate" not in workflow
    assert "cancel-in-progress: false" in workflow
    assert "state/news/news_flash_24x7.json" in workflow


def test_old_timestamp_can_be_identified_before_send() -> None:
    now = datetime(2026, 9, 5, 13, 0, tzinfo=timezone.utc)
    published = parse_published("2026-09-05T10:00:00Z", now=now)
    assert published is not None
    assert (now - published) > timedelta(minutes=60)
