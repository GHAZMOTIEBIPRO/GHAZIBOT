from options_radar.option_contract_intelligence import build_option_contract_intelligence


def _contract(side: str, dte: int, strike: float, rank: float, *, delta: float, vol_oi: float, spread: float = 0.08):
    return {
        "symbol": "TEST",
        "contract_symbol": f"TEST-{dte}-{side}-{strike}",
        "option_type": side,
        "expiration": "2026-08-27" if dte == 14 else "2026-09-03",
        "expiration_date": "2026-08-27" if dte == 14 else "2026-09-03",
        "dte": dte,
        "strike": strike,
        "underlying_price": 10.0,
        "moneyness_pct": (strike - 10.0) / 10.0,
        "rank_score": rank,
        "opportunity_tier": "A" if rank >= 80 else "B",
        "bid": 1.00,
        "ask": 1.10,
        "mid": 1.05,
        "delta": delta,
        "gamma": 0.05,
        "theta": -0.03,
        "vega": 0.04,
        "iv": 0.70,
        "volume": 900,
        "open_interest": 400,
        "vol_to_oi_ratio": vol_oi,
        "spread_pct": spread,
        "source": "tradier",
        "primary_or_licensed_quote": True,
        "flow_sources": ["tradier"],
        "liquidity_grade": "PASS",
    }


def _payload(bias: str = "bullish"):
    calls = [
        _contract("call", 14, 10.5, 88, delta=0.46, vol_oi=2.25),
        _contract("call", 21, 12.0, 92, delta=0.25, vol_oi=2.8, spread=0.14),
    ]
    puts = [
        _contract("put", 14, 9.5, 89, delta=-0.45, vol_oi=2.0),
    ]
    return {
        "stocks": [{"symbol": "TEST", "setup_side": "call", "technical_direction": "bullish"}],
        "expiry_radar": {"tabs": {"all_expirations": {"calls": calls, "puts": puts}}},
        "omega": {
            "opportunities": [{"symbol": "TEST", "direction": "UPSIDE"}],
            "catalyst_intelligence": {
                "by_symbol": {
                    "TEST": {
                        "directional_bias": bias,
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


def test_bullish_official_event_selects_call_and_balanced_strike_expiry():
    intel = build_option_contract_intelligence(_payload("bullish"))
    item = intel["by_symbol"]["TEST"]
    primary = item["primary"]
    assert item["preferred_side"] == "CALL"
    assert primary["side"] == "CALL"
    assert primary["dte"] == 14
    assert primary["strike"] == 10.5
    assert primary["contract_rank"] > 0
    assert "المحفز" in primary["side_reason_ar"]
    assert primary["flow_claim"] == "BUYING_PRESSURE_PROXY_NOT_SWEEP_PROOF"


def test_bearish_official_event_selects_put():
    payload = _payload("bearish")
    payload["stocks"][0]["setup_side"] = "put"
    payload["stocks"][0]["technical_direction"] = "bearish"
    payload["omega"]["opportunities"][0]["direction"] = "DOWNSIDE"
    intel = build_option_contract_intelligence(payload)
    primary = intel["by_symbol"]["TEST"]["primary"]
    assert primary["side"] == "PUT"
    assert primary["strike"] == 9.5


def test_volume_oi_does_not_become_sweep_claim():
    intel = build_option_contract_intelligence(_payload("bullish"))
    primary = intel["by_symbol"]["TEST"]["primary"]
    assert primary["vol_to_oi_ratio"] > 1.5
    assert primary["flow_claim"] != "SWEEP_CONFIRMED"
