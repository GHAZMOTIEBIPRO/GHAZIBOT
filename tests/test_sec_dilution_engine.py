from datetime import datetime, timezone

from options_radar.sec_dilution_engine import (
    assess_sec_dilution,
    financing_overhang,
    share_count_history,
)


def _facts():
    return {
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {
                                "val": 1_000_000,
                                "end": "2026-01-01",
                                "filed": "2026-01-05",
                                "form": "10-K",
                            },
                            {
                                "val": 1_500_000,
                                "end": "2026-07-01",
                                "filed": "2026-07-05",
                                "form": "10-Q",
                            },
                            {
                                "val": 2_000_000,
                                "end": "2026-09-15",
                                "filed": "2026-09-20",
                                "form": "10-Q",
                            },
                            {
                                "val": 3_000_000,
                                "end": "2026-10-01",
                                "filed": "2026-10-12",
                                "form": "8-K",
                            },
                        ]
                    }
                }
            }
        }
    }


def test_share_history_uses_only_facts_filed_by_as_of_date():
    history = share_count_history(
        _facts(),
        as_of=datetime(2026, 10, 10, 16, 0, tzinfo=timezone.utc),
    )

    assert history["available"] is True
    assert history["latest_shares"] == 2_000_000
    assert history["latest_filed_at"] == "2026-09-20"
    assert round(history["growth_pct"]["30d"], 2) == 33.33
    assert round(history["growth_pct"]["90d"], 2) == 100.0
    assert history["growth_pct"]["365d"] is None
    assert history["split_adjusted"] is False


def test_financing_overhang_separates_announced_capacity_from_remaining_capacity():
    events = [
        {
            "form": "424B5",
            "purpose": "dilution",
            "event_date": "2026-10-07",
            "event_value": 20_000_000,
            "share_count": 3_000_000,
            "evidence": "ATM offering with warrant overhang",
        }
    ]

    result = financing_overhang(
        events,
        market_cap=40_000_000,
        float_shares=2_000_000,
        as_of=datetime(2026, 10, 10, 16, 0, tzinfo=timezone.utc),
    )

    assert result["active_financing_context"] is True
    assert result["announced_financing_capacity_usd"] == 20_000_000
    assert result["announced_capacity_to_market_cap"] == 0.5
    assert result["explicit_overhang_to_float"] == 1.5
    assert result["remaining_capacity_verified"] is False


def test_future_financing_event_is_excluded_point_in_time():
    result = financing_overhang(
        [
            {
                "form": "424B5",
                "purpose": "dilution",
                "event_date": "2026-10-12",
                "event_value": 100_000_000,
                "evidence": "ATM offering up to 10,000,000 shares",
            }
        ],
        market_cap=40_000_000,
        float_shares=2_000_000,
        as_of=datetime(2026, 10, 10, 16, 0, tzinfo=timezone.utc),
    )

    assert result["event_count"] == 0
    assert result["announced_financing_capacity_usd"] is None
    assert result["explicit_overhang_to_float"] is None


def test_sec_dilution_v2_combines_share_growth_capacity_and_share_overhang():
    result = assess_sec_dilution(
        _facts(),
        [
            {
                "form": "424B5",
                "purpose": "dilution",
                "event_date": "2026-10-07",
                "event_value": 20_000_000,
                "evidence": (
                    "registered direct offering and warrants to purchase "
                    "3,000,000 shares"
                ),
            }
        ],
        market_cap=40_000_000,
        float_shares=2_000_000,
        as_of=datetime(2026, 10, 10, 16, 0, tzinfo=timezone.utc),
    )

    assert result.risk_score >= 90
    assert result.risk_label == "HIGH"
    assert result.share_growth_risk > 0
    assert result.financing_risk > 0
    assert result.overhang_risk > 0
    assert result.research_only is True
    assert result.decision_authority is False
    assert result.score_is_probability is False
