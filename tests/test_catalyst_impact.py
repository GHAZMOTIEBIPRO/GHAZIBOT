from options_radar.catalyst_impact import score_catalyst_impact


def test_official_material_catalyst_with_market_confirmation_scores_high():
    cluster = {
        "category": "MERGER_DEFINITIVE",
        "directional_bias": "bullish",
        "source_tier": "A_OFFICIAL",
        "catalyst_quality": 94,
        "materiality": 95,
        "age_days": 0,
        "reaction_state": "NOT_YET_REPRICED",
        "dilution_risk": 0,
    }
    stock = {
        "relative_volume": 3.2,
        "breakout_pressure_score": 82,
        "float_shares": 4_000_000,
        "short_float_pct": 0.18,
        "avg_dollar_volume": 25_000_000,
        "gap_pct": 3,
    }

    result = score_catalyst_impact(cluster, stock)

    assert result["score"] >= 80
    assert result["label"] in {"HIGH", "EXTREME"}
    assert result["score_is_probability"] is False
    assert any("RVOL" in reason for reason in result["drivers_ar"])


def test_extended_bullish_catalyst_with_dilution_is_penalized():
    cluster = {
        "category": "MATERIAL_CONTRACT",
        "directional_bias": "bullish",
        "source_tier": "B_ISSUER_PRIMARY",
        "catalyst_quality": 80,
        "materiality": 80,
        "age_days": 1,
        "reaction_state": "EXTENDED_CHASING_RISK",
        "dilution_risk": 90,
    }
    stock = {
        "relative_volume": 2.5,
        "breakout_pressure_score": 75,
        "float_shares": 8_000_000,
        "avg_dollar_volume": 10_000_000,
        "gap_pct": 20,
    }

    result = score_catalyst_impact(cluster, stock)

    assert result["score"] < 80
    assert any("Dilution" in risk for risk in result["risks_ar"])
    assert any("Gap" in risk for risk in result["risks_ar"])
