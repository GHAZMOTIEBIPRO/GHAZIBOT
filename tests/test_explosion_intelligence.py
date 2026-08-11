from options_radar.explosion_intelligence import STAGE_ORDER, build_delta_signals, effective_float_metrics


def test_effective_float_uses_most_constrained_observable_supply_and_penalizes_dilution():
    stock = {"float_shares": 2_000_000, "shares_outstanding": 10_000_000, "insider_ownership_pct": 70}
    clean = effective_float_metrics(stock, catalyst={"dilution_risk": 10})
    risky = effective_float_metrics(stock, catalyst={"dilution_risk": 90})

    assert clean.effective_float_estimate == 2_000_000
    assert clean.affiliate_adjusted_float == 3_000_000
    assert clean.supply_vacuum_score >= 85
    assert risky.supply_vacuum_score < clean.supply_vacuum_score
    assert risky.supply_overhang_estimate > clean.supply_overhang_estimate


def test_delta_engine_promotes_volume_before_price_pattern():
    payload = {
        "stocks": [
            {
                "symbol": "TEST",
                "price": 5.2,
                "performance_day": 4.0,
                "performance_week": 8.0,
                "relative_volume": 2.1,
                "volume": 1_000_000,
                "social_score": 20,
            }
        ],
        "omega": {
            "catalyst_intelligence": {
                "by_symbol": {
                    "TEST": {
                        "catalyst_quality": 82,
                        "materiality": 85,
                        "confidence": 0.9,
                        "directional_bias": "bullish",
                        "dilution_risk": 10,
                        "headline": "Material strategic contract",
                        "event_date": "2026-08-11",
                    }
                }
            }
        },
    }
    history = {
        "symbols": {
            "TEST": [
                {
                    "symbol": "TEST",
                    "stage": "PRESSURE_BUILDING",
                    "rvol": 0.9,
                    "volume": 200_000,
                    "day_move": 0.5,
                    "social_score": 5,
                    "catalyst_key": "",
                },
                {
                    "symbol": "TEST",
                    "stage": "PRESSURE_BUILDING",
                    "rvol": 1.1,
                    "volume": 350_000,
                    "day_move": 1.0,
                    "social_score": 8,
                    "catalyst_key": "",
                },
            ]
        }
    }
    structural = {
        "TEST": {
            "float_shares": 2_500_000,
            "shares_outstanding": 12_000_000,
            "insider_ownership_pct": 65,
            "structural_score": 90,
        }
    }

    signals, _ = build_delta_signals(payload, history_payload=history, structural_payload=structural)
    assert len(signals) == 1
    signal = signals[0]
    assert signal.score >= 63
    assert STAGE_ORDER[signal.stage] >= STAGE_ORDER["PRE_EXPLOSION"]
    assert signal.supply_vacuum_score >= 80
    assert any("RVOL" in reason or "Information Change" in reason for reason in signal.reasons)
