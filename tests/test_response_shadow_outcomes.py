from __future__ import annotations

from datetime import datetime, timedelta, timezone

from options_radar.response_shadow_outcomes import update_response_shadow_ab


START = datetime(2026, 10, 7, 14, 30, tzinfo=timezone.utc)


def _contract(symbol: str, bid: float, ask: float, timestamp: datetime) -> dict:
    return {
        "symbol": "XYZ",
        "contract_symbol": symbol,
        "option_type": "call",
        "side": "CALL",
        "bid": bid,
        "ask": ask,
        "mid": round((bid + ask) / 2.0, 4),
        "source": "licensed research feed",
        "quote_timestamp": timestamp.isoformat(),
        "timestamp_kind": "provider_quote",
        "underlying_response_grade": {
            "score": 70.0 if symbol.endswith("100") else 82.0,
            "research_only": True,
            "decision_authority": False,
        },
    }


def _payload(
    timestamp: datetime,
    *,
    primary_bid: float = 0.95,
    primary_ask: float = 1.00,
    shadow_bid: float = 0.95,
    shadow_ask: float = 1.00,
    same_contract: bool = False,
) -> dict:
    primary_symbol = "XYZ261016C00000100"
    shadow_symbol = primary_symbol if same_contract else "XYZ261016C00000105"
    primary = _contract(
        primary_symbol,
        primary_bid,
        primary_ask,
        timestamp,
    )
    shadow = (
        dict(primary)
        if same_contract
        else _contract(shadow_symbol, shadow_bid, shadow_ask, timestamp)
    )
    return {
        "expiry_radar": {
            "tabs": {
                "all_expirations": {
                    "calls": [primary, shadow],
                    "puts": [],
                }
            }
        },
        "option_contract_intelligence": {
            "by_symbol": {
                "XYZ": {
                    "primary": primary,
                    "response_shadow_best": shadow,
                    "response_shadow_changes_live_primary": False,
                }
            }
        },
    }


def test_response_ab_records_same_time_60m_comparison_without_promotion():
    first_report, state = update_response_shadow_ab(
        _payload(START),
        {},
        now=START,
        max_quote_age_minutes=10,
    )
    assert first_report["tracked_pairs"] == 1
    pair = next(iter(state["pairs"].values()))
    assert pair["primary_entry_ask"] == 1.0
    assert pair["shadow_entry_ask"] == 1.0
    assert pair["entry_verified"] is True

    later = START + timedelta(minutes=60)
    second_payload = _payload(
        later,
        primary_bid=1.10,
        primary_ask=1.15,
        shadow_bid=1.30,
        shadow_ask=1.35,
    )
    report, state = update_response_shadow_ab(
        second_payload,
        state,
        now=later,
        max_quote_age_minutes=10,
    )

    pair = next(iter(state["pairs"].values()))
    checkpoint = pair["checkpoints"]["60m"]
    assert checkpoint["primary_return_pct"] == 10.0
    assert checkpoint["shadow_return_pct"] == 30.0
    assert checkpoint["shadow_minus_primary_pct"] == 20.0
    assert report["checkpoints"]["60m"]["n"] == 1
    assert report["checkpoints"]["60m"]["shadow_win_rate_pct"] == 100.0
    assert report["promotion_gate"]["evidence_ready_for_manual_review"] is False
    assert report["promotion_gate"]["live_promotion_allowed"] is False
    assert report["policy"]["v11_unchanged"] is True


def test_stale_quotes_cannot_seed_response_ab_pair():
    stale = START - timedelta(hours=4)
    report, state = update_response_shadow_ab(
        _payload(stale),
        {},
        now=START,
        max_quote_age_minutes=10,
    )
    assert report["tracked_pairs"] == 0
    assert state["pairs"] == {}


def test_same_contract_is_not_counted_as_ab_evidence():
    report, state = update_response_shadow_ab(
        _payload(START, same_contract=True),
        {},
        now=START,
        max_quote_age_minutes=10,
    )
    assert report["tracked_pairs"] == 0
    assert report["same_choice_symbols_current_run"] == 1
    assert state["pairs"] == {}


def test_first_pair_per_symbol_session_is_frozen():
    _, state = update_response_shadow_ab(
        _payload(START),
        {},
        now=START,
        max_quote_age_minutes=10,
    )
    first = next(iter(state["pairs"].values()))

    later = START + timedelta(minutes=20)
    changed = _payload(later)
    item = changed["option_contract_intelligence"]["by_symbol"]["XYZ"]
    new_shadow = _contract("XYZ261016C00000110", 0.9, 1.0, later)
    changed["expiry_radar"]["tabs"]["all_expirations"]["calls"].append(new_shadow)
    item["response_shadow_best"] = new_shadow

    _, updated = update_response_shadow_ab(
        changed,
        state,
        now=later,
        max_quote_age_minutes=10,
    )
    assert len(updated["pairs"]) == 1
    frozen = next(iter(updated["pairs"].values()))
    assert frozen["shadow_contract"] == first["shadow_contract"]
