import pandas as pd

from options_radar.phase51_export import (
    STOCK_RESEARCH_EXPORT_COLUMNS,
    _records,
)


def test_phase51_public_export_preserves_explosion_and_realized_vol_context():
    required = {
        "breakout_pressure_score",
        "explosion_setup_v3",
        "explosion_setup_v3_stage",
        "explosion_setup_v3_quality_count",
        "realized_volatility_30d",
    }
    assert required.issubset(set(STOCK_RESEARCH_EXPORT_COLUMNS))

    frame = pd.DataFrame(
        [
            {
                "symbol": "TEST",
                "breakout_pressure_score": 82.5,
                "explosion_setup_v3": {
                    "stage": "ARMED",
                    "quality_count": 6,
                    "research_only": True,
                    "live_score_adjustment": False,
                },
                "explosion_setup_v3_stage": "ARMED",
                "explosion_setup_v3_quality_count": 6,
                "realized_volatility_30d": {
                    "available": True,
                    "method": "YANG_ZHANG",
                    "annualized_volatility": 0.47,
                    "research_only": True,
                },
            }
        ]
    )

    rows = _records(
        frame,
        ["symbol", *STOCK_RESEARCH_EXPORT_COLUMNS],
    )
    row = rows[0]

    assert row["symbol"] == "TEST"
    assert row["explosion_setup_v3"]["stage"] == "ARMED"
    assert row["explosion_setup_v3"]["live_score_adjustment"] is False
    assert row["realized_volatility_30d"]["method"] == "YANG_ZHANG"
    assert row["realized_volatility_30d"]["annualized_volatility"] == 0.47
