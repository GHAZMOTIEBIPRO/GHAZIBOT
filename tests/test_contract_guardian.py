from datetime import datetime, timezone

from options_radar.contract_guardian import update_contract_guardian


NOW = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)


def _payload(spot: float, bid: float = 2.2, iv: float = 0.40):
    contract = {
        "symbol": "XYZ",
        "contract_symbol": "XYZ261120C00100000",
        "option_type": "call",
        "expiration": "2026-11-20",
        "expiration_date": "2026-11-20",
        "dte": 44,
        "strike": 100,
        "underlying_price": spot,
        "bid": bid,
        "ask": bid + 0.10,
        "mid": bid + 0.05,
        "iv": iv,
        "source": "licensed_test",
        "freshness_label": "live",
        "quote_timestamp": NOW.isoformat(),
    }
    primary = {
        **contract,
        "side": "CALL",
        "alert_stage": "CONFIRMED",
        "contract_rank": 91,
        "strict_score": 93,
        "premium_targets": {
            "available": True,
            "targets": {
                "t1": {"premium_base": 3.0},
                "t2": {"premium_base": 4.0},
                "t3": {"premium_base": 6.0},
            },
        },
    }
    return {
        "stocks": [
            {
                "symbol": "XYZ",
                "price": spot,
                "quote_timestamp": NOW.isoformat(),
                "source": "licensed_test",
                "entry_low": 99,
                "entry_high": 101,
                "target_1": 104,
                "target_2": 108,
                "target_3": 112,
                "invalidation": 96,
            }
        ],
        "expiry_radar": {
            "tabs": {
                "all_expirations": {
                    "calls": [contract],
                    "puts": [],
                }
            }
        },
        "option_contract_intelligence": {
            "by_symbol": {
                "XYZ": {
                    "primary": primary,
                }
            }
        },
        "omega": {
            "opportunities": [
                {
                    "symbol": "XYZ",
                    "target_map": {
                        "entry": {"low": 99, "high": 101},
                        "invalidation": {"price": 96},
                        "t1": {"price": 104},
                        "t2": {"price": 108},
                        "t3": {"price": 112},
                    },
                }
            ],
            "catalyst_intelligence": {
                "by_symbol": {
                    "XYZ": {
                        "directional_bias": "bullish",
                        "verification_state": "OFFICIAL_CONFIRMED",
                        "cause_status_ar": "سبب مؤكد رسميًا",
                        "headline": "Material contract",
                        "primary_source": "SEC EDGAR",
                        "explosion_impact": {
                            "score": 88,
                            "label": "EXTREME",
                            "label_ar": "محفز شديد القوة",
                        },
                    }
                }
            },
        },
    }


def test_guardian_freezes_thesis_and_advances_targets():
    report, state = update_contract_guardian(_payload(100), {}, now=NOW)
    assert report["tracked_total"] == 1
    tracked = next(iter(state["contracts"].values()))
    assert tracked["stage"] == "ACTIVE"
    assert tracked["target_map"]["t1"]["price"] == 104
    assert tracked["entry_premium_reference"] == 2.3

    later = datetime(2026, 10, 7, 16, 0, tzinfo=timezone.utc)
    payload = _payload(108, bid=4.1)
    payload["expiry_radar"]["tabs"]["all_expirations"]["calls"][0]["quote_timestamp"] = later.isoformat()
    payload["option_contract_intelligence"]["by_symbol"]["XYZ"]["primary"]["quote_timestamp"] = later.isoformat()
    report, state = update_contract_guardian(payload, state, now=later)
    tracked = next(iter(state["contracts"].values()))

    assert tracked["stage"] == "T2_HIT"
    assert tracked["mfe_pct"] > 0
    assert tracked["target_map"]["t1"]["price"] == 104
    assert tracked["catalyst_health"]["impact_score"] == 88


def test_guardian_invalidates_without_promoting_v11():
    report, state = update_contract_guardian(_payload(95, bid=1.0), {}, now=NOW)
    tracked = next(iter(state["contracts"].values()))

    assert tracked["stage"] == "INVALIDATED"
    assert tracked["terminal"] is True
    assert report["can_promote_v11"] is False
