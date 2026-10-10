from options_radar.microcap_hunter import assess_microcap_candidate


def _strong(**updates):
    row = {
        "symbol": "MICR",
        "price": 4.25,
        "market_cap": 45_000_000,
        "float_shares": 2_000_000,
        "rvol": 3.8,
        "dollar_volume": 2_500_000,
        "day_move_pct": 5.0,
        "supply_score": 92,
        "catalyst_score": 82,
        "catalyst_headline": "FDA approval and strategic partnership",
        "official_catalyst_url": "https://www.sec.gov/Archives/edgar/data/123/abc.htm",
        "dilution_risk": 10,
    }
    row.update(updates)
    return row


def test_strong_early_low_float_candidate_becomes_research_priority():
    result = assess_microcap_candidate(_strong())
    assert result.stage == "PRIORITY"
    assert result.score >= 78
    assert result.research_only is True
    assert result.decision_authority is False
    assert result.score_is_probability is False
    assert result.official_sec_catalyst is True


def test_high_dilution_blocks_microcap_priority():
    result = assess_microcap_candidate(
        _strong(
            dilution_risk=90,
            catalyst_headline="At-the-market offering under S-3 and 424B5",
        )
    )
    assert result.stage == "AVOID_RISK"
    assert result.dilution_context is True
    assert "HIGH_DILUTION_RISK" in result.flags
    assert result.risk_penalty >= 34


def test_reverse_split_context_is_penalized_not_rewarded_as_low_float():
    clean = assess_microcap_candidate(_strong())
    split = assess_microcap_candidate(
        _strong(catalyst_headline="Company effects 1-for-20 reverse stock split")
    )
    assert split.reverse_split_context is True
    assert "REVERSE_SPLIT_CONTEXT" in split.flags
    assert split.score < clean.score


def test_missing_float_can_watch_for_research_but_never_becomes_priority():
    result = assess_microcap_candidate(_strong(float_shares=None))
    assert result.stage != "PRIORITY"
    assert "FLOAT_UNVERIFIED" in result.flags


def test_chasing_very_extended_move_is_penalized():
    early = assess_microcap_candidate(_strong(day_move_pct=6))
    late = assess_microcap_candidate(_strong(day_move_pct=62))
    assert "CHASE_RISK" in late.flags
    assert late.score < early.score

def test_sec_dilution_v2_high_risk_overrides_benign_catalyst_text():
    result = assess_microcap_candidate(
        _strong(
            dilution_risk=5,
            catalyst_headline="FDA approval and strategic partnership",
            sec_dilution_v2={
                "risk_score": 92,
                "risk_label": "HIGH",
                "reasons": ["reported shares +100.0% over 90d"],
            },
        )
    )
    assert result.stage == "AVOID_RISK"
    assert "SEC_DILUTION_V2_HIGH" in result.flags
    assert "HIGH_DILUTION_RISK" in result.flags

