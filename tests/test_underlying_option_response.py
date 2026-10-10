from options_radar.underlying_option_response import (
    grade_underlying_option_response,
)


def _contract(**updates):
    row = {
        "bid": 1.00,
        "ask": 1.10,
        "mid": 1.05,
        "underlying_price": 20.0,
        "delta": 0.52,
        "theta": -0.025,
        "dte": 21,
        "volume": 900,
        "open_interest": 1200,
        "spread_pct": 0.095,
        "iv_rank": 35,
        "iv_percentile": 40,
        "premium_targets": {
            "available": True,
            "targets": {
                "t1": {
                    "return_low_pct": 32.0,
                    "return_base_pct": 55.0,
                    "return_high_pct": 78.0,
                },
                "t2": {
                    "return_low_pct": 65.0,
                    "return_base_pct": 105.0,
                    "return_high_pct": 150.0,
                },
            },
            "invalidation": {"return_base_pct": -28.0},
        },
    }
    row.update(updates)
    return row


def test_response_grader_rewards_contract_that_reacts_to_underlying_targets():
    result = grade_underlying_option_response(_contract())

    assert result["score"] >= 70
    assert result["grade"] in {"A", "B", "C"}
    assert result["details"]["target_response"]["t1_return_base_pct"] == 55.0
    assert result["details"]["target_invalidation_asymmetry"][
        "reward_risk_to_t1"
    ] > 1.5
    assert result["details"]["underlying_responsiveness"][
        "elasticity_proxy"
    ] > 0
    assert result["research_only"] is True
    assert result["decision_authority"] is False
    assert result["score_is_probability"] is False


def test_wide_spread_or_thin_oi_hard_caps_response_grade():
    result = grade_underlying_option_response(
        _contract(spread_pct=0.22, open_interest=20)
    )

    assert result["liquidity_hard_cap_applied"] is True
    assert result["score"] <= 39
    assert result["grade"] == "F"


def test_missing_iv_history_is_neutral_not_fabricated():
    result = grade_underlying_option_response(
        _contract(iv_rank=None, iv_percentile=None)
    )

    vol = result["details"]["volatility_value"]
    assert vol["available"] is False
    assert result["components"]["volatility_value"]["score"] == 50.0


def test_bad_chart_asymmetry_is_penalized_even_with_liquidity():
    result = grade_underlying_option_response(
        _contract(
            premium_targets={
                "available": True,
                "targets": {
                    "t1": {
                        "return_low_pct": -12.0,
                        "return_base_pct": 5.0,
                        "return_high_pct": 22.0,
                    }
                },
                "invalidation": {"return_base_pct": -45.0},
            }
        )
    )

    assert result["components"]["target_response"]["score"] < 55
    assert result["components"]["target_invalidation_asymmetry"]["score"] < 45

def test_iv_below_realized_volatility_improves_buyer_value_context():
    cheap = grade_underlying_option_response(
        _contract(iv=0.30, realized_volatility_30d=0.55, iv_rank=35)
    )
    rich = grade_underlying_option_response(
        _contract(iv=0.80, realized_volatility_30d=0.35, iv_rank=35)
    )

    cheap_detail = cheap["details"]["volatility_value"]
    rich_detail = rich["details"]["volatility_value"]
    assert cheap_detail["iv_to_realized_vol_ratio"] < 1.0
    assert rich_detail["iv_to_realized_vol_ratio"] > 2.0
    assert cheap["components"]["volatility_value"]["score"] > rich[
        "components"
    ]["volatility_value"]["score"]

