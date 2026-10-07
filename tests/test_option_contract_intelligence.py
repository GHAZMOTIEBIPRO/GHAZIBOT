from datetime import datetime, timezone

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
        "source": "polygon_options brokerage feed",
        "primary_or_licensed_quote": True,
        "flow_sources": ["tradier"],
        "liquidity_grade": "PASS",
        "freshness_label": "real-time",
        "quote_timestamp": datetime.now(timezone.utc).isoformat(),
        "fabric_independent_source_count": 2,
        "fabric_source_count": 2,
        "fabric_consensus_pass": True,
        "fabric_quote_divergence_pct": 0.01,
        "strict_score": 94,
        "strict_blockers": [],
        "flow_momentum_score": 82,
        "data_quality": 0.96,
        "gamma_context_alignment": 0.30,
        "occ_side_context": {"aligned": True, "opposed": False},
        "gamma_coverage_pct": 90,
        "oi_coverage_pct": 90,
        "occ_side_context": {"aligned": True, "opposed": False},
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
        "stocks": [{
            "symbol": "TEST",
            "setup_side": "call",
            "technical_direction": "bullish",
            "price": 10.0,
            "entry_low": 9.8,
            "entry_high": 10.1,
            "target_1": 10.8,
            "target_2": 11.6,
            "target_3": 12.5,
            "invalidation": 9.3,
        }],
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
    assert primary["premium_targets"]["available"] is True
    assert primary["premium_targets"]["targets"]["t1"]["premium_base"] > 0


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


def test_far_expiry_cannot_win_only_because_flow_is_huge():
    payload = _payload("bullish")
    payload["omega"]["catalyst_intelligence"]["by_symbol"]["TEST"]["official_confirmed"] = False
    payload["omega"]["catalyst_intelligence"]["by_symbol"]["TEST"]["primary_cause_eligible"] = False
    payload["expiry_radar"]["tabs"]["all_expirations"]["calls"].append(
        _contract("call", 100, 11.0, 99, delta=0.48, vol_oi=9.5, spread=0.02)
    )
    intel = build_option_contract_intelligence(payload)
    item = intel["by_symbol"]["TEST"]
    assert item["primary"]["dte"] != 100
    assert item["allowed_dte_window"] == [7.0, 45.0]
    assert item["contracts_rejected_for_horizon"] >= 1


def test_only_far_expiries_means_no_contract_choice():
    payload = _payload("bullish")
    payload["omega"]["catalyst_intelligence"]["by_symbol"]["TEST"]["official_confirmed"] = False
    payload["omega"]["catalyst_intelligence"]["by_symbol"]["TEST"]["primary_cause_eligible"] = False
    payload["expiry_radar"]["tabs"]["all_expirations"]["calls"] = [
        _contract("call", 100, 11.0, 99, delta=0.48, vol_oi=9.5, spread=0.02)
    ]
    intel = build_option_contract_intelligence(payload)
    assert "TEST" not in intel["by_symbol"]
    assert intel["rejected_for_horizon"]["TEST"] == 1


def test_primary_contract_exposes_v11_production_readiness():
    intel = build_option_contract_intelligence(_payload("bullish"))
    primary = intel["by_symbol"]["TEST"]["primary"]
    assert primary["v11_decision"]["version"] == "OMEGA_V11"
    assert primary["production_alert_eligible"] is True


def test_primary_contract_fails_closed_when_source_quorum_is_missing():
    payload = _payload("bullish")
    for row in payload["expiry_radar"]["tabs"]["all_expirations"]["calls"]:
        row["fabric_independent_source_count"] = 1
    intel = build_option_contract_intelligence(payload)
    primary = intel["by_symbol"]["TEST"]["primary"]
    assert primary["production_alert_eligible"] is False
    assert "v11_independent_source_quorum_not_met" in primary["v11_decision"]["blockers"]


def test_target_horizon_controls_preferred_expiry_band():
    payload = _payload("bullish")
    payload["omega"]["opportunities"][0]["target_horizon"] = {
        "primary_horizon": "INTRADAY_1D",
        "primary_time_ar": "نفس الجلسة إلى جلسة",
    }
    payload["expiry_radar"]["tabs"]["all_expirations"]["calls"].append(
        _contract("call", 7, 10.5, 82, delta=0.46, vol_oi=1.9)
    )
    intel = build_option_contract_intelligence(payload)
    item = intel["by_symbol"]["TEST"]
    assert item["target_dte"] == 7.0
    assert item["preferred_dte_band"] == [3.0, 7.0]
    assert item["primary"]["dte"] == 7
    assert "3–7" in item["primary"]["expiry_reason_ar"]


def test_position_horizon_prefers_30_to_60_dte_contract():
    payload = _payload("bullish")
    payload["omega"]["opportunities"][0]["target_horizon"] = {
        "primary_horizon": "POSITION_1_4W",
        "primary_time_ar": "1–4 أسابيع",
    }
    payload["expiry_radar"]["tabs"]["all_expirations"]["calls"].append(
        _contract("call", 45, 10.5, 82, delta=0.46, vol_oi=1.9)
    )
    intel = build_option_contract_intelligence(payload)
    item = intel["by_symbol"]["TEST"]
    assert item["target_dte"] == 45.0
    assert item["preferred_dte_band"] == [30.0, 60.0]
    assert item["primary"]["dte"] == 45


def test_watch_stage_surfaces_research_candidate_without_weakening_v11():
    payload = _payload("bullish")
    for row in payload["expiry_radar"]["tabs"]["all_expirations"]["calls"]:
        row["fabric_independent_source_count"] = 1
    intel = build_option_contract_intelligence(payload)
    primary = intel["by_symbol"]["TEST"]["primary"]
    assert primary["production_alert_eligible"] is False
    assert primary["watch_alert_eligible"] is True
    assert primary["alert_stage"] == "WATCH"
    assert primary["watch_decision"]["production_claim"] is False


def test_confirmed_stage_wins_over_watch_when_v11_approves():
    intel = build_option_contract_intelligence(_payload("bullish"))
    primary = intel["by_symbol"]["TEST"]["primary"]
    assert primary["production_alert_eligible"] is True
    assert primary["watch_alert_eligible"] is False
    assert primary["alert_stage"] == "CONFIRMED"
