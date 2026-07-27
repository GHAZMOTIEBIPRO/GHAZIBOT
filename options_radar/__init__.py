"""Options Radar: source-aware US options screening and alerting."""

from . import catalysts as _catalysts
from . import sec_efts as _sec_efts
from .catalyst_selection import best_catalyst_map as _confidence_best_catalyst_map
from .sec_attention import precision_sec_symbols as _precision_sec_symbols

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

__version__ = "4.0.0"
