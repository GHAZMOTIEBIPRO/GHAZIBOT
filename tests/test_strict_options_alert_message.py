from scripts.send_strict_options_alerts import _message


def _row():
    return {
        "symbol": "XYZ",
        "direction_label": "CALL",
        "expiration": "2026-10-02",
        "strike": 105.0,
        "dte": 27,
        "bid": 2.10,
        "ask": 2.20,
        "spread_pct": 0.045,
        "strict_score": 91.0,
        "signal_grade": "A+",
        "delta": 0.50,
        "iv": 0.42,
        "vol_to_oi_ratio": 2.4,
        "flow_momentum_score": 88.0,
        "reward_risk_1": 1.8,
        "gamma_context": "CALL_HEAVY_PROXY",
        "call_wall": 110.0,
        "put_wall": 95.0,
        "gamma_flip": 100.0,
        "liquidity_strike": 105.0,
        "gamma_coverage_pct": 91.0,
        "oi_coverage_pct": 95.0,
        "chart_direction": "bullish",
        "chart_score": 62.0,
        "chart_available_timeframes": 3,
        "institutional_activity_proxy_score": 71.0,
        "expected_move_1sigma": 8.25,
        "strike_intelligence_score": 84.0,
        "strike_reasons_ar": [
            "السترايك ضمن أعلى مراكز OI في السلسلة",
            "هذا هو Liquidity Strike الأعلى بمزيج OI+Volume",
            "السعر فوق Gamma Flip≈100",
        ],
        "strict_reasons": ["1D/15m/5m chart aligns with contract side"],
        "chart_context": {
            "timeframes": {
                "1d": {
                    "available": True,
                    "pattern": "bullish_engulfing",
                    "relative_volume": 1.7,
                    "close": 104.0,
                    "vwap": None,
                },
                "15m": {
                    "available": True,
                    "pattern": "hammer",
                    "relative_volume": 1.5,
                    "close": 104.2,
                    "vwap": 103.8,
                },
                "5m": {
                    "available": True,
                    "pattern": "bullish_body",
                    "relative_volume": 1.3,
                    "close": 104.3,
                    "vwap": 104.0,
                },
            }
        },
    }


def test_message_surfaces_chart_gamma_strike_and_proxy_disclaimer():
    text = _message(
        _row(),
        mode="free",
        readiness={"status": "FALLBACK_ONLY"},
    )
    assert "Chart" in text
    assert "TF <b>3/3</b>" in text
    assert "Bull Engulf" in text
    assert "Hammer" in text
    assert "RVOL 1.50×" in text
    assert "Flip <b>100</b>" in text
    assert "Liq <b>105</b>" in text
    assert "Strike Intel <b>84/100</b>" in text
    assert "Expected Move 1σ <b>$8.25</b>" in text
    assert "ليش هذا السترايك؟" in text
    assert "OI" in text
    assert "Inst Proxy <b>71/100</b>" in text
    assert "ليست مراكز ديلر/مؤسسات مؤكدة" in text
    assert "Research-grade" in text


def test_legacy_signal_without_chart_fields_still_formats():
    row = {
        "symbol": "ABC",
        "direction_label": "PUT",
        "expiration": "2026-10-02",
        "strike": 50,
        "dte": 27,
        "bid": 1.0,
        "ask": 1.1,
        "spread_pct": 0.09,
        "strict_score": 87,
        "signal_grade": "A",
        "delta": -0.45,
        "iv": 0.50,
        "vol_to_oi_ratio": 2.0,
        "flow_momentum_score": 80,
        "reward_risk_1": 1.3,
        "gamma_context": "PUT_HEAVY_PROXY",
        "gamma_coverage_pct": 80,
        "oi_coverage_pct": 80,
    }
    text = _message(row, mode="free", readiness={"status": "FALLBACK_ONLY"})
    assert "ABC PUT" in text
    assert "TF <b>0/3</b>" in text
    assert "Expected Move 1σ <b>—</b>" in text
