"""GHAZI Market Radar: source-aware US stock and options screening."""

from . import catalysts as _catalysts
from . import sec_efts as _sec_efts
from .catalyst_selection import best_catalyst_map as _confidence_best_catalyst_map
from .flow_fetcher import install_trade_timestamp_normalizer
from .flow_scoring import install_ask_spread_scoring
from .phase60_sources import install_multi_source_fetching
from .sec_attention import precision_sec_symbols as _precision_sec_symbols

# Install data/scoring normalizers before scanner modules import provider helpers.
install_trade_timestamp_normalizer()
install_ask_spread_scoring()
install_multi_source_fetching()

# Import after Phase 6 installs its composite fetcher so Phase 6.1 wraps it
# instead of bypassing it.
from .phase61_sources import install_phase61_fetching

install_phase61_fetching()

# FINRA's production Reg SHO dataset uses SIP symbol and par-quantity fields.
from .phase61_finra import install_finra_reg_sho_fix

install_finra_reg_sho_fix()

# Daily short-sale volume is context only. It cannot validate direction or
# promote a research candidate without independent directional evidence.
from .phase61_policy import install_phase61_policy_fix

install_phase61_policy_fix()

# Yahoo/YFinance remain fallback sources. They may populate Tier B watchlists,
# but cannot promote a stock or option contract to Tier A.
from .phase62_quality import install_phase62_quality_policy

install_phase62_quality_policy()

# CALL and PUT lists must be built independently. OCC contract symbols are
# authoritative, opposite-direction contracts are removed, and one symbol
# cannot dominate both tables with mirrored strikes and expirations.
from .phase62_contract_separation import install_contract_separation_policy

install_contract_separation_policy()

# Modules importing best_catalyst_map after package initialization receive the
# confidence-aware selector without duplicating selection logic.
_catalysts.best_catalyst_map = _confidence_best_catalyst_map

_original_sec_fulltext_symbols = _sec_efts.sec_fulltext_symbols


def _combined_sec_symbols(settings, *, lookback_days: int = 14):
    broad = _original_sec_fulltext_symbols(settings, lookback_days=lookback_days)
    precision = _precision_sec_symbols(settings, lookback_days=max(lookback_days, 30))
    return list(dict.fromkeys(list(precision) + list(broad)))


# universe.py imports this function after package initialization, so precise
# event discoveries are placed ahead of general market movers.
_sec_efts.sec_fulltext_symbols = _combined_sec_symbols

__version__ = "6.2.2"
