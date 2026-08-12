from options_radar.option_contract_intelligence import build_option_contract_intelligence


def test_occ_context_is_used_as_context_not_sweep_proof():
    contract = {
        "symbol": "TEST",
        "contract_symbol": "TEST260827C00010500",
        "option_type": "call",
        "expiration": "2026-08-27",
        "expiration_date": "2026-08-27",
        "dte": 14,
        "strike": 10.5,
        "underlying_price": 10.0,
        "moneyness_pct": 0.05,
        "rank_score": 88,
        "opportunity_tier": "A",
        "bid": 1.0,
        "ask": 1.1,
        "mid": 1.05,
        "delta": 0.46,
        "gamma": 0.05,
        "theta": -0.03,
        "vega": 0.04,
        "iv": 0.70,
        "volume": 900,
        "open_interest": 400,
        "vol_to_oi_ratio": 2.25,
        "spread_pct": 0.08,
        "source": "tradier",
        "primary_or_licensed_quote": True,
        "flow_sources": ["tradier"],
        "liquidity_grade": "PASS",
        "occ_official_context": {
            "available": True,
            "official": True,
            "context_only": True,
            "call_volume": 12000,
            "put_volume": 5000,
            "side_dominance_ratio": 2.4,
            "aligned_with_contract_side": True,
        },
    }
    payload = {
        "stocks": [{"symbol": "TEST", "setup_side": "call", "technical_direction": "bullish"}],
        "expiry_radar": {"tabs": {"all_expirations": {"calls": [contract], "puts": []}}},
        "omega": {
            "opportunities": [{"symbol": "TEST", "direction": "UPSIDE"}],
            "catalyst_intelligence": {
                "by_symbol": {
                    "TEST": {
                        "directional_bias": "bullish",
                        "official_confirmed": True,
                        "primary_cause_eligible": True,
                        "materiality": 92,
                        "reaction_state": "REPRICING",
                        "verification_state": "OFFICIAL_CONFIRMED",
                        "cause_status_ar": "سبب مؤكد رسميًا",
                    }
                }
            },
        },
    }
    intel = build_option_contract_intelligence(payload)
    primary = intel["by_symbol"]["TEST"]["primary"]
    assert "OCC الرسمي" in primary["flow_reason_ar"]
    assert primary["flow_claim"] == "BUYING_PRESSURE_PROXY_NOT_SWEEP_PROOF"
    assert primary["occ_is_context_only"] is True
