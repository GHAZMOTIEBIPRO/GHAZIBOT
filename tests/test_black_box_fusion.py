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

def test_fusion_excludes_explicitly_invalid_or_stale_evidence():
    payload = fuse_evidence(
        latest={
            "stock_recommendations": [
                {"symbol": "BAD", "score": 99, "direction": "BULLISH", "valid": False},
                {"symbol": "STALE", "score": 99, "direction": "BULLISH", "freshness_status": "stale"},
                {"symbol": "GOOD", "score": 90, "direction": "BULLISH", "provider": "test"},
            ]
        }
    )
    symbols = {item["symbol"] for item in payload["candidates"]}
    assert "BAD" not in symbols
    assert "STALE" not in symbols
    assert "GOOD" in symbols


def test_fusion_respects_declared_age_limit():
    payload = fuse_evidence(
        latest={
            "stock_recommendations": [
                {
                    "symbol": "OLD",
                    "score": 99,
                    "direction": "BULLISH",
                    "age_seconds": 120,
                    "max_age_seconds": 60,
                }
            ]
        }
    )
    assert payload["candidate_count"] == 0


def test_investigator_surfaces_directional_conflict():
    from options_radar.black_box_fusion import investigate_candidate
    result = investigate_candidate({
        "symbol": "XYZ", "direction": "BULLISH", "fusion_score": 70,
        "research_state": "RESEARCH_CANDIDATE",
        "evidence": {
            "chart": {"direction": "BULLISH", "evidence_score": 80},
            "options": {"direction": "BEARISH", "evidence_score": 70},
        },
    })
    assert result["conflict_state"] == "CONFLICT"
    assert result["automatic_execution"] is False


def test_market_regime_does_not_invent_missing_inputs():
    from options_radar.black_box_fusion import infer_market_regime
    result = infer_market_regime({})
    assert result["regime"] == "UNKNOWN"
    assert result["confidence"] == 0.0


def test_market_regime_uses_explicit_observations():
    from options_radar.black_box_fusion import infer_market_regime
    result = infer_market_regime({
        "spx_change_pct": 1.0,
        "ndx_change_pct": 0.5,
        "vix_change_pct": -2.0,
    })
    assert result["regime"] == "RISK_ON"


def test_investigator_creates_auditable_case_and_invalidation_rules():
    from options_radar.black_box_fusion import investigate_candidate
    result = investigate_candidate({
        "symbol": "ABC",
        "direction": "BULLISH",
        "fusion_score": 72,
        "research_state": "RESEARCH_CANDIDATE",
        "evidence": {
            "chart": {"direction": "BULLISH", "evidence_score": 80, "source": "chart-provider"},
            "options": {"direction": "BULLISH", "evidence_score": 75, "provider": "options-provider"},
        },
    })
    assert result["case_id"].startswith("omega-")
    assert result["thesis_status"] == "ACTIVE_RESEARCH"
    assert result["invalidation_rules"] == []
    assert result["audit"]["source_provenance_preserved"] is True


def test_investigator_pauses_on_missing_provenance():
    from options_radar.black_box_fusion import investigate_candidate
    result = investigate_candidate({
        "symbol": "ABC",
        "direction": "BULLISH",
        "fusion_score": 72,
        "research_state": "RESEARCH_CANDIDATE",
        "evidence": {
            "chart": {"direction": "BULLISH", "evidence_score": 80},
            "options": {"direction": "BULLISH", "evidence_score": 75, "provider": "options-provider"},
        },
    })
    codes = {item["code"] for item in result["invalidation_rules"]}
    assert "MISSING_PROVENANCE" in codes
    assert result["thesis_status"] == "PAUSE"
