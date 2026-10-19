from options_radar.similar_cases import find_similar_cases


def _opportunity():
    return {
        "symbol": "NOW",
        "price": 100.0,
        "direction": "UPSIDE",
        "opportunity_tier": "A",
        "explosion_rank": 84.0,
        "explosion_cause": {"primary": "CATALYST_REPRICING"},
        "target_map": {"t1": {"price": 106.0}},
        "target_horizon": {"primary_horizon": "SHORT_1_3D"},
    }


def _state(count: int = 12, hits: int = 8, *, direction: str = "UPSIDE"):
    signals = {}
    for i in range(count):
        status = "HIT" if i < hits else "MATURED_MISS"
        signals[str(i)] = {
            "signal_id": str(i),
            "symbol": f"H{i}",
            "signal_time": f"2026-09-{(i % 20) + 1:02d}T14:30:00+00:00",
            "direction": direction,
            "entry_price": 100.0,
            "opportunity_tier": "A" if i % 2 == 0 else "B",
            "explosion_rank": 80.0 + (i % 6),
            "explosion_cause": "CATALYST_REPRICING",
            "primary_horizon": "SHORT_1_3D",
            "targets": {
                "T1": {
                    "price": 105.0 + (i % 2),
                    "horizon_bucket": "SHORT_1_3D",
                    "matured": True,
                    "status": status,
                    "sessions_to_hit": 2 if status == "HIT" else None,
                    "elapsed_hours_to_hit": 10 if status == "HIT" else None,
                }
            },
        }
    return {"signals": signals}


def test_similar_cases_are_descriptive_not_probability():
    result = find_similar_cases(_opportunity(), _state())
    assert result["status"] == "READY"
    assert result["sample"] == 12
    assert result["descriptive_t1_hit_rate_pct"] == 66.7
    assert result["median_t1_sessions_to_hit"] == 2.0
    assert result["is_probability"] is False
    assert all(row["similarity"] >= 55 for row in result["cases"])


def test_similar_cases_do_not_publish_rate_below_minimum_sample():
    result = find_similar_cases(_opportunity(), _state(count=6, hits=5))
    assert result["status"] == "INSUFFICIENT_SAMPLE"
    assert result["descriptive_t1_hit_rate"] is None
    assert result["sample"] == 6


def test_opposite_direction_cases_are_excluded():
    result = find_similar_cases(_opportunity(), _state(direction="DOWNSIDE"))
    assert result["sample"] == 0
    assert result["status"] == "INSUFFICIENT_SAMPLE"


def test_as_of_excludes_cases_whose_outcome_was_not_yet_known():
    from datetime import datetime, timezone

    import pytest

    state = _state(count=12, hits=12)
    for i, signal in enumerate(state["signals"].values()):
        # Hit stamped 1 day after the signal; first 4 signals resolve after as_of.
        signal["targets"]["T1"]["hit_at"] = f"2026-09-{(i % 20) + 2:02d}T15:00:00+00:00"
    as_of = datetime(2026, 9, 9, 0, 0, tzinfo=timezone.utc)
    result = find_similar_cases(_opportunity(), state, as_of=as_of)
    assert result["as_of"] == "2026-09-09T00:00:00+00:00"
    times = [case["signal_time"] for case in result["cases"]]
    assert all(t < "2026-09-08" for t in times)
    assert result["excluded_outcome_unknown_at_as_of"] == 5  # signals 9/8-9/12
    with pytest.raises(ValueError):
        find_similar_cases(_opportunity(), state, as_of=as_of.replace(tzinfo=None))


def test_matured_miss_without_timestamp_needs_full_window_and_same_symbol_overlap_is_excluded():
    from datetime import datetime, timezone

    state = _state(count=12, hits=0)  # all MATURED_MISS, no resolution timestamp
    state["signals"]["0"]["symbol"] = "NOW"
    # 20-session window ~ 32 calendar days: September signals are not yet
    # known on Oct 1, all are known on Nov 1.
    early = find_similar_cases(_opportunity(), state, as_of=datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert early["sample"] == 0 and early["excluded_outcome_unknown_at_as_of"] == 12
    late = find_similar_cases(_opportunity(), state, as_of=datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert late["excluded_outcome_unknown_at_as_of"] == 0
    recent = _state(count=1, hits=1)
    sig = recent["signals"]["0"]
    sig.update(symbol="NOW", signal_time="2026-10-30T14:30:00+00:00")
    sig["targets"]["T1"]["hit_at"] = "2026-10-30T16:00:00+00:00"
    overlap = find_similar_cases(_opportunity(), recent, as_of=datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert overlap["excluded_same_symbol_overlap"] == 1 and overlap["sample"] == 0
