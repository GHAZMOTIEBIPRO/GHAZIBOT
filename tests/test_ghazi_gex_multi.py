from datetime import date

import pytest

from options_radar.ghazi_gex_multi import build, contract_rows, parse_occ


def cboe_payload(spot=7600.0, iv=0.18):
    """Shape observed from the live Cboe delayed SPX JSON: identity lives only
    in the OCC symbol; no strike / expiration / type fields."""
    options = []
    for strike in range(7000, 8201, 50):
        for cp, oi in (("C", 1000), ("P", 900)):
            options.append({"option": f"SPXW261020{cp}{strike * 1000:08d}",
                            "iv": iv, "open_interest": oi, "gamma": 0.001,
                            "bid": 1.0, "ask": 1.2})
    return {"timestamp": "2026-10-20 03:52:21", "symbol": "_SPX",
            "data": {"current_price": spot, "last_trade_time": "2026-10-19T16:15:00",
                     "options": options}}


def test_parse_occ_reads_root_expiry_type_and_strike():
    assert parse_occ("SPXW261020C07700000") == {
        "root": "SPXW", "expiry": "2026-10-20", "type": "call", "strike": 7700.0}
    assert parse_occ("SPX261120P05512500")["strike"] == 5512.5
    assert parse_occ("SPX261120P05512500")["type"] == "put"


@pytest.mark.parametrize("bad", ["", "SPXW26102C07700000", "SPXW261320C07700000",
                                 "SPXW261020X07700000", "SPXW261020C00000000", None])
def test_parse_occ_rejects_malformed(bad):
    assert parse_occ(bad) is None


def test_cboe_shape_without_explicit_fields_is_usable():
    spot, rows = contract_rows(cboe_payload())
    assert spot == 7600.0
    assert len(rows) == 2 * 25
    call = next(r for r in rows if r["type"] == "call" and r["strike"] == 7700.0)
    assert call["expiry"] == "2026-10-20" and call["iv"] == pytest.approx(0.18)


def test_conflicting_explicit_fields_are_rejected_not_trusted():
    payload = cboe_payload()
    payload["data"]["options"][0]["strike"] = 9999
    payload["data"]["options"][1]["option_type"] = "call"  # symbol says P
    _, rows = contract_rows(payload)
    assert len(rows) == 2 * 25 - 2


def test_decimal_iv_above_one_is_not_divided():
    payload = cboe_payload(iv=1.4)
    _, rows = contract_rows(payload)
    assert rows[0]["iv"] == pytest.approx(1.4)
    payload = cboe_payload(iv=18)
    _, rows = contract_rows(payload)
    assert rows[0]["iv"] == pytest.approx(0.18)


def test_zero_iv_or_missing_oi_rows_are_skipped():
    payload = cboe_payload()
    payload["data"]["options"][0]["iv"] = 0
    payload["data"]["options"][1]["open_interest"] = None
    _, rows = contract_rows(payload)
    assert len(rows) == 2 * 25 - 2


def test_build_emits_levels_greeks_and_provenance_labels():
    out = build(payload=cboe_payload(), session_date=date(2026, 10, 20))
    assert out["available"] is True
    assert out["data_quality"]["has_spxw"] is True
    assert out["policy"] == "shadow_validation_never_signal_authority"
    assert set(out["greek_exposure_near_spot"]) == {"dex", "vanna", "charm", "vomma", "zomma"}
    assert out["put_call_oi_ratio"] == pytest.approx(0.9)
    assert 0 < out["gci"] <= 1
    prov = out["provenance"]
    assert prov["gamma_and_greeks"] == "MODEL_ESTIMATED"
    assert prov["levels"] == "MODEL_ESTIMATED"
    assert prov["open_interest"] == "HISTORICAL"
    assert prov["spot"] == "DELAYED"
    assert prov["dealer_positioning"] == "UNAVAILABLE"
    assert prov["execution_grade"] is False
    assert prov["provider_snapshot_time"] == "2026-10-20 03:52:21"
    assert 7000 <= out["call_wall"] <= 8200 and 7000 <= out["put_wall"] <= 8200
    assert out["front_expiry"] == "2026-10-20"


def test_empty_chain_still_fails_closed():
    with pytest.raises(ValueError):
        contract_rows({"data": {"current_price": 7600, "options": []}})
    payload = cboe_payload()
    payload["data"]["current_price"] = None
    with pytest.raises(ValueError):
        contract_rows(payload)
