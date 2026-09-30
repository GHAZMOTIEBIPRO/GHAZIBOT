from options_radar.black_box_fusion import FusionPolicy, fuse_evidence

def test_fusion_requires_independent_evidence():
    payload = fuse_evidence(latest={"stock_recommendations": [{"symbol": "AAPL", "score": 95, "direction": "BULLISH"}]})
    assert payload["candidates"][0]["research_state"] == "WATCH"

def test_fusion_combines_independent_evidence_without_probability_claim():
    payload = fuse_evidence(
        latest={
            "stock_recommendations": [{"symbol": "NVDA", "score": 90, "direction": "BULLISH"}],
            "contract_recommendations": [{"symbol": "NVDA", "score": 88, "direction": "CALL"}],
            "catalysts": [{"symbol": "NVDA", "score": 80, "direction": "BULLISH"}],
        },
        explosion={"candidates": [{"symbol": "NVDA", "score": 85, "direction": "BULLISH"}]},
        policy=FusionPolicy(min_independent_classes=2),
    )
    candidate = payload["candidates"][0]
    assert candidate["symbol"] == "NVDA"
    assert candidate["research_state"] == "RESEARCH_CANDIDATE"
    assert candidate["independent_class_count"] >= 2
    assert candidate["score_is_probability"] is False
    assert candidate["automatic_execution"] is False

def test_fusion_does_not_invent_missing_symbols():
    payload = fuse_evidence(latest={}, explosion={}, flow={})
    assert payload["candidate_count"] == 0
