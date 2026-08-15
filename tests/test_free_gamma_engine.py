import numpy as np
import pandas as pd

from options_radar.free_gamma_engine import build_gamma_map, prepare_gamma_chain
from options_radar.settings import Settings


def _expiry(days: int = 30) -> pd.Timestamp:
    return pd.Timestamp.now().normalize() + pd.Timedelta(days=days)


def test_gamma_map_finds_call_and_put_walls_without_claiming_dealer_inventory():
    settings = Settings(min_dte=7, max_dte=60)
    chain = pd.DataFrame(
        [
            {"contract_symbol": "X1", "option_type": "call", "strike": 100, "expiration": _expiry(), "open_interest": 1000, "gamma": 0.030, "delta": 0.50, "iv": 0.35, "underlying_price": 100, "source": "yahoo/yfinance"},
            {"contract_symbol": "X2", "option_type": "call", "strike": 105, "expiration": _expiry(), "open_interest": 4000, "gamma": 0.040, "delta": 0.40, "iv": 0.36, "underlying_price": 100, "source": "yahoo/yfinance"},
            {"contract_symbol": "X3", "option_type": "put", "strike": 95, "expiration": _expiry(), "open_interest": 2200, "gamma": 0.028, "delta": -0.38, "iv": 0.38, "underlying_price": 100, "source": "yahoo/yfinance"},
            {"contract_symbol": "X4", "option_type": "put", "strike": 90, "expiration": _expiry(), "open_interest": 500, "gamma": 0.018, "delta": -0.25, "iv": 0.40, "underlying_price": 100, "source": "yahoo/yfinance"},
        ]
    )
    gamma_map = build_gamma_map("XYZ", chain, settings)
    assert gamma_map.call_wall == 105
    assert gamma_map.put_wall == 95
    assert gamma_map.call_gex_proxy > gamma_map.put_gex_proxy
    assert gamma_map.context == "CALL_HEAVY_PROXY"
    assert gamma_map.data_tier == "research"
    assert gamma_map.estimated_gamma_pct == 0
    assert "not verified dealer inventory" in gamma_map.source_note


def test_missing_gamma_is_estimated_but_missing_oi_is_never_invented():
    settings = Settings(min_dte=7, max_dte=60)
    chain = pd.DataFrame(
        [
            {"contract_symbol": "A", "option_type": "call", "strike": 100, "expiration": _expiry(), "open_interest": 900, "gamma": np.nan, "delta": np.nan, "iv": 0.30, "underlying_price": 100, "source": "yahoo/yfinance"},
            {"contract_symbol": "B", "option_type": "put", "strike": 95, "expiration": _expiry(), "open_interest": np.nan, "gamma": np.nan, "delta": np.nan, "iv": 0.32, "underlying_price": 100, "source": "yahoo/yfinance"},
        ]
    )
    prepared = prepare_gamma_chain(chain, settings)
    assert prepared["gamma"].notna().all()
    assert prepared["gamma_estimated"].all()
    assert prepared.loc[prepared["contract_symbol"] == "B", "open_interest"].iloc[0] == 0
    assert prepared.loc[prepared["contract_symbol"] == "B", "gex_proxy"].iloc[0] == 0

    gamma_map = build_gamma_map("XYZ", prepared, settings)
    assert gamma_map.estimated_gamma_pct == 100
    assert "estimated gamma share 100%" in gamma_map.source_note


def test_contracts_outside_configured_dte_do_not_enter_gamma_map():
    settings = Settings(min_dte=14, max_dte=60)
    chain = pd.DataFrame(
        [
            {"contract_symbol": "NEAR", "option_type": "call", "strike": 100, "expiration": _expiry(3), "open_interest": 1000, "gamma": 0.04, "delta": 0.5, "iv": 0.3, "underlying_price": 100, "source": "yahoo"},
            {"contract_symbol": "VALID", "option_type": "call", "strike": 105, "expiration": _expiry(30), "open_interest": 1000, "gamma": 0.04, "delta": 0.5, "iv": 0.3, "underlying_price": 100, "source": "yahoo"},
        ]
    )
    prepared = prepare_gamma_chain(chain, settings)
    assert prepared["contract_symbol"].tolist() == ["VALID"]


def test_tradier_sandbox_is_never_classified_as_strong_gamma_data():
    settings = Settings(min_dte=7, max_dte=60)
    chain = pd.DataFrame(
        [
            {
                "contract_symbol": "T1",
                "option_type": "call",
                "strike": 100,
                "expiration": _expiry(),
                "open_interest": 1800,
                "gamma": 0.03,
                "delta": 0.50,
                "iv": 0.32,
                "underlying_price": 100,
                "source": "tradier",
                "freshness_label": "Tradier sandbox: delayed; Greeks unavailable",
            }
        ]
    )
    gamma_map = build_gamma_map("XYZ", chain, settings)
    assert gamma_map.data_tier == "research_plus"
    assert gamma_map.data_tier != "strong"
