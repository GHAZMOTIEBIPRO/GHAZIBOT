from scripts.fast_explosion_scan import rank_market


def test_microcap_ignition_ranks_above_quiet_mega_cap():
    rows = [
        {
            "symbol": "MICR",
            "name": "Micro Example Common Stock",
            "lastsale": "$4.00",
            "marketCap": "50000000",
            "volume": "1500000",
            "pctchange": "9.0%",
        },
        {
            "symbol": "MEGA",
            "name": "Mega Example Common Stock",
            "lastsale": "$200.00",
            "marketCap": "200000000000",
            "volume": "1500000",
            "pctchange": "0.5%",
        },
    ]
    structural = {
        "MICR": {
            "structural_score": 92,
            "float_shares": 2_000_000,
        }
    }
    ranked = rank_market(rows, news_events=[], structural=structural)
    assert ranked[0].symbol == "MICR"
    assert ranked[0].score > ranked[1].score
    assert ranked[0].stage in {"PRESSURE_BUILDING", "IGNITION", "EXPLOSION"}


def test_extended_move_is_not_treated_as_fresh_ignition():
    rows = [
        {
            "symbol": "LATE",
            "name": "Late Example Common Stock",
            "lastsale": "$8.00",
            "marketCap": "60000000",
            "volume": "7000000",
            "pctchange": "55.0%",
        }
    ]
    ranked = rank_market(rows, news_events=[], structural={"LATE": {"float_shares": 2_000_000, "structural_score": 95}})
    assert ranked[0].stage == "EXTENDED"
