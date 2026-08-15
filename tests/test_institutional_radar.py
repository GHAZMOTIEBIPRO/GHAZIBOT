from options_radar.institutional_radar import assess_candidate, should_promote


def _candidate(**overrides):
    row = {
        "score": 70,
        "move_pct": 4.5,
        "volume": 1_500_000,
        "turnover_pct": 1.7,
        "turnover_score": 82,
        "volume_score": 75,
        "supply_score": 88,
        "news_score": 78,
        "structural_score": 72,
        "price": 7.5,
        "market_cap": 150_000_000,
        "dollar_volume": 11_250_000,
    }
    row.update(overrides)
    return row


def test_early_accelerating_candidate_reaches_ignition_or_better():
    previous = {
        "base_score": 61,
        "score": 61,
        "move_pct": 1.2,
        "volume": 700_000,
        "turnover_pct": 0.7,
        "stage": "PRESSURE_BUILDING",
    }
    assessment = assess_candidate(_candidate(), previous)
    assert assessment.stage in {"IGNITION", "EXPLOSION"}
    assert assessment.earlyness >= 70
    assert assessment.acceleration >= 45
    assert assessment.confidence in {"A", "B"}


def test_late_extended_move_is_not_promoted_as_fresh_ignition():
    assessment = assess_candidate(
        _candidate(
            move_pct=44,
            score=90,
            turnover_score=100,
            volume_score=100,
            news_score=95,
        )
    )
    assert assessment.stage == "EXTENDED"
    assert assessment.send_priority <= 45
    assert assessment.risk_penalty > 0


def test_low_dollar_liquidity_is_penalized():
    liquid = assess_candidate(_candidate())
    thin = assess_candidate(_candidate(dollar_volume=250_000, market_cap=18_000_000, price=0.8))
    assert thin.score < liquid.score
    assert thin.risk_penalty >= 20
    assert thin.blockers


def test_state_transition_or_large_score_delta_is_required():
    assert should_promote("PRESSURE_BUILDING", "IGNITION", 1)
    assert should_promote("IGNITION", "IGNITION", 9)
    assert not should_promote("IGNITION", "IGNITION", 4)
