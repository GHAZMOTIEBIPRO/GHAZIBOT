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
