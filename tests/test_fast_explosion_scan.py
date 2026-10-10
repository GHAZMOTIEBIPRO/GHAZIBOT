from pathlib import Path

from scripts.fast_explosion_scan_runner import rank_market


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


def test_common_ticker_ending_r_is_not_dropped_only_for_suffix():
    rows = [
        {
            "symbol": "ABCR",
            "name": "ABC Research Common Stock",
            "lastsale": "$3.00",
            "marketCap": "40000000",
            "volume": "500000",
            "pctchange": "4.0%",
        }
    ]
    ranked = rank_market(rows, news_events=[], structural={})
    assert ranked and ranked[0].symbol == "ABCR"

def test_fast_radar_enables_free_autonomy_before_data_fabric():
    root = Path(__file__).resolve().parents[1]
    fabric = (root / "scripts/fast_explosion_scan_fabric.py").read_text(encoding="utf-8")
    runner = (root / "scripts/fast_explosion_scan_runner.py").read_text(encoding="utf-8")

    assert "enforce_free_autonomy_environment()\ninstall_data_fabric()" in fabric
    assert '"microcap_hunter"' in runner
    assert '"float_shares"' in runner
    assert '"official_catalyst_url"' in runner

