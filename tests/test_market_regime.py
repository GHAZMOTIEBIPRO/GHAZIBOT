from options_radar.market_regime import MarketRegimeEngine


def test_risk_off_when_vix_above_25():
    snapshot = MarketRegimeEngine.from_values(
        vix=26,
        spy_close=600,
        spy_ema50=590,
        spy_ema200=550,
        qqq_close=520,
        qqq_ema50=510,
        qqq_ema200=480,
    )
    assert snapshot.label == "risk_off"
    assert snapshot.prefer_side == "put"
    assert snapshot.call_min_score > snapshot.put_min_score


def test_risk_off_when_spy_below_ema200_even_with_low_vix():
    snapshot = MarketRegimeEngine.from_values(
        vix=16,
        spy_close=490,
        spy_ema50=510,
        spy_ema200=500,
        qqq_close=420,
        qqq_ema50=430,
        qqq_ema200=425,
    )
    assert snapshot.label == "risk_off"
    assert "SPY below EMA200" in snapshot.reasons


def test_risk_on_when_vix_below_18_and_spy_above_ema50():
    snapshot = MarketRegimeEngine.from_values(
        vix=17,
        spy_close=600,
        spy_ema50=580,
        spy_ema200=540,
        qqq_close=520,
        qqq_ema50=500,
        qqq_ema200=470,
    )
    assert snapshot.label == "risk_on"
    assert snapshot.prefer_side == "call"
    assert snapshot.call_score_adjustment > 0
