from __future__ import annotations

from datetime import datetime, timedelta, timezone

from options_radar.execution_confidence import assess_execution_quote


NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def _row(**updates: object) -> dict:
    row = {
        "source": "licensed OPRA realtime",
        "freshness_label": "realtime",
        "bid": 2.0,
        "ask": 2.1,
        "updated_at": (NOW - timedelta(seconds=10)).isoformat(),
    }
    row.update(updates)
    return row


def test_fresh_opra_quote_is_execution_ready() -> None:
    gate = assess_execution_quote(_row(), now=NOW, max_quote_age_seconds=120)
    assert gate.confidence == "LIVE"
    assert gate.execution_ready is True
    assert gate.quote_age_seconds == 10.0
    assert gate.blockers == ()


def test_relative_age_without_absolute_timestamp_is_rejected() -> None:
    row = _row()
    row.pop("updated_at")
    row["stream_quote_age_seconds"] = 1.0
    gate = assess_execution_quote(row, now=NOW)
    assert gate.confidence == "RESEARCH"
    assert gate.execution_ready is False
    assert any("توقيت Quote" in blocker for blocker in gate.blockers)


def test_stale_quote_is_rejected_even_from_live_provider() -> None:
    gate = assess_execution_quote(
        _row(updated_at=(NOW - timedelta(minutes=5)).isoformat()),
        now=NOW,
        max_quote_age_seconds=120,
    )
    assert gate.confidence == "RESEARCH"
    assert gate.execution_ready is False
    assert any("قديم" in blocker for blocker in gate.blockers)


def test_delayed_marker_wins_over_live_words() -> None:
    gate = assess_execution_quote(
        _row(source="licensed OPRA realtime delayed"),
        now=NOW,
    )
    assert gate.confidence == "RESEARCH"
    assert gate.execution_ready is False


def test_verified_opra_stream_overlay_can_supersede_fallback_base_chain() -> None:
    gate = assess_execution_quote(
        _row(
            source="yahoo + alpaca_opra_stream",
            freshness_label="Alpaca OPRA stream; execution-grade quote overlay",
            fabric_quote_provider="alpaca_opra_stream",
            stream_feed="opra",
            stream_execution_grade=True,
        ),
        now=NOW,
    )
    assert gate.confidence == "LIVE"
    assert gate.execution_ready is True


def test_bare_tradier_label_is_not_assumed_live_without_entitlement_evidence() -> None:
    gate = assess_execution_quote(
        _row(source="tradier", freshness_label="current"),
        now=NOW,
    )
    assert gate.confidence == "RESEARCH"
    assert gate.execution_ready is False


def test_account_feed_needs_fresh_absolute_quote_time() -> None:
    gate = assess_execution_quote(
        _row(source="broker account feed", freshness_label="account entitlement"),
        now=NOW,
    )
    assert gate.confidence == "ACCOUNT"
    assert gate.execution_ready is True
