"""Options Radar: source-aware US options screening and alerting."""

from . import catalysts as _catalysts
from .catalyst_selection import best_catalyst_map as _confidence_best_catalyst_map

# Modules importing best_catalyst_map after package initialization receive the
# confidence-aware selector without duplicating selection logic.
_catalysts.best_catalyst_map = _confidence_best_catalyst_map

__version__ = "2.0.1"
