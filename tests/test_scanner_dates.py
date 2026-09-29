from __future__ import annotations

import pandas as pd

from options_radar.scanner import OptionsRadar


def test_prepare_chain_dates_normalizes_timezone_aware_expiration() -> None:
    expiration = pd.Timestamp.now(tz="UTC").normalize() + pd.Timedelta(days=21)
    chain = pd.DataFrame(
        {
            "contract_symbol": ["SPY260101C00100000"],
            "expiration": [expiration],
        }
    )

    prepared = OptionsRadar._prepare_chain_dates(chain)

    assert prepared["expiration"].dt.tz is None
    assert int(prepared.loc[0, "dte"]) == 21
