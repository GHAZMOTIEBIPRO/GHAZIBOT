from options_radar.explosion_cause import (
    adaptive_dimension_weights,
    classify_explosion_cause,
    manipulation_risk,
)


def _dimensions(**overrides):
    base = {
        "catalyst": 55,
        "participation": 82,
        "supply_structure": 90,
        "price_structure": 76,
        "options_structure": 50,
        "risk_penalty": 10,
    }
    base.update(overrides)
    return base


def test_supply_vacuum_is_identified_from_low_supply_and_participation():
    stock = {
        "float_shares": 4_000_000,
        "relative_volume": 3.0,
        "performance_day": 4.0,
        "entry_state": "early",
        "distance_to_trigger_atr": 0.2,
    }
    result = classify_explosion_cause(stock, {}, _dimensions(catalyst=20))
    assert result["primary"] in {"SUPPLY_VACUUM", "MOMENTUM_IGNITION", "MULTI_FACTOR_EXPLOSION"}
    assert result["scores"]["SUPPLY_VACUUM"] >= 70
    assert result["causation_proven"] is False


def test_multi_factor_requires_several_strong_independent_drivers():
    stock = {
        "float_shares": 3_000_000,
        "short_float_pct": 0.25,
        "social_score": 80,
        "performance_day": 5.0,
        "entry_state": "early",
        "distance_to_trigger_atr": 0.1,
    }
    cluster = {
        "catalyst_quality": 92,
        "reaction_state": "NOT_YET_REPRICED",
        "headline": "Definitive merger agreement",
        "event_type": "merger",
    }
    result = classify_explosion_cause(
        stock,
        cluster,
        _dimensions(catalyst=92, participation=92, supply_structure=95, price_structure=88),
    )
    assert result["primary"] == "MULTI_FACTOR_EXPLOSION"
    assert result["strong_driver_count"] >= 3


def test_social_signal_cannot_dominate_without_market_confirmation():
    stock = {"social_score": 100, "performance_day": 1.0, "entry_state": "watch"}
    result = classify_explosion_cause(
        stock,
        {},
        _dimensions(catalyst=10, participation=20, supply_structure=20, price_structure=20),
    )
    assert result["scores"]["SOCIAL_ATTENTION_SHOCK"] < 60


def test_manipulation_risk_is_flag_not_accusation():
    stock = {
        "float_shares": 2_000_000,
        "performance_day": 55,
        "performance_week": 150,
        "social_score": 90,
    }
    cluster = {
        "catalyst_quality": 20,
        "dilution_risk": 80,
        "headline": "Reverse split and ATM financing",
        "form": "S-3",
    }
    cause = classify_explosion_cause(stock, cluster, _dimensions())
    risk = manipulation_risk(stock, cluster, cause)
    assert risk["score"] >= 70
    assert risk["label"] == "VERY_HIGH"
    assert risk["is_accusation"] is False
    assert "لا تثبت" in risk["disclaimer_ar"]


def test_adaptive_weights_sum_to_one_and_change_by_cause():
    supply = adaptive_dimension_weights({"primary": "SUPPLY_VACUUM"})
    event = adaptive_dimension_weights({"primary": "CORPORATE_EVENT"})
    assert abs(sum(supply.values()) - 1.0) < 1e-9
    assert abs(sum(event.values()) - 1.0) < 1e-9
    assert supply["supply_structure"] > event["supply_structure"]
    assert event["catalyst"] > supply["catalyst"]
