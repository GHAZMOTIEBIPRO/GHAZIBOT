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

__version__ = "6.0.0"
