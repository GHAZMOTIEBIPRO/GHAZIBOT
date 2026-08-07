from options_radar.omega_catalyst_intelligence import build_catalyst_intelligence
from options_radar.omega_opportunity import build_omega_opportunities


def stock(**overrides):
    base = {
        "symbol": "XYZ",
        "setup_side": "call",
        "setup_status": "strong_setup",
        "entry_state": "confirmed",
        "price": 100,
        "entry_low": 99,
        "entry_high": 101,
        "invalidation": 96,
        "target_1": 103,
        "target_2": 106,
        "score": 88,
        "relative_volume": 2.2,
        "finviz_relative_volume": 2.2,
        "avg_dollar_volume": 80_000_000,
        "distance_to_trigger_atr": 0.2,
        "gap_pct": 3.0,
        "rejection_reason": "",
        "breakout": True,
    }
    base.update(overrides)
    return base


def option(**overrides):
    base = {
        "symbol": "XYZ",
        "contract_symbol": "XYZ260821C00100000",
        "option_type": "call",
        "bid": 2.00,
        "ask": 2.10,
        "spread_pct": 0.048,
        "volume": 900,
        "open_interest": 1200,
        "score": 82,
        "contract_score": 84,
        "flow_momentum_score": 75,
        "vol_to_oi_ratio": 0.75,
        "expiry_family": "WEEKLY",
        "last_trade_age_minutes": 2,
        "data_status": "fresh",
    }
    base.update(overrides)
    return base


def catalyst():
    return {
        "symbol": "XYZ",
        "event_date": "2026-08-07",
        "form": "8-K",
        "source": "SEC EDGAR",
        "headline": "Definitive merger agreement",
        "evidence": "merger agreement",
        "score": 24,
        "url": "https://example.test/sec",
    }


def test_explosion_radar_exposes_dimensions_and_never_probability():
    stocks = [stock()]
    intel = build_catalyst_intelligence([catalyst()], stocks)
    payload = {"stocks": stocks, "options": [option()], "top_calls": [], "top_puts": []}
    result = build_omega_opportunities(payload, intel)
    row = result["all_ranked"][0]
    assert set(row["dimensions"]) == {
        "catalyst",
        "participation",
        "supply_structure",
        "price_structure",
        "options_structure",
        "risk_penalty",
    }
    assert row["probability_of_profit"] is None
    assert "NOT PROBABILITY" in row["ranking_score_label"]
    assert row["best_expiry_family"] == "WEEKLY"


def test_good_stock_with_bad_option_can_say_no_good_option():
    stocks = [stock()]
    intel = build_catalyst_intelligence([catalyst()], stocks)
    bad = option(bid=0, ask=3, spread_pct=0.9, volume=0, open_interest=0)
    result = build_omega_opportunities(
        {"stocks": stocks, "options": [bad], "top_calls": [], "top_puts": []},
        intel,
    )
    row = result["all_ranked"][0]
    assert not row["tradable_contract"]
    assert row["opportunity_tier"] not in {"A+", "A"}
    assert row["no_trade_state"] == "GREAT STOCK — NO GOOD OPTION"


def test_low_float_without_liquidity_is_rejected():
    stocks = [stock(float_shares=10_000_000, avg_dollar_volume=1_000_000)]
    intel = build_catalyst_intelligence([catalyst()], stocks)
    result = build_omega_opportunities(
        {"stocks": stocks, "options": [option()], "top_calls": [], "top_puts": []},
        intel,
    )
    assert result["all_ranked"][0]["opportunity_tier"] == "X"
