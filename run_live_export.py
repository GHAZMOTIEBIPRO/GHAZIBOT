from __future__ import annotations

import os

# The public page should always show a ranked watchlist. Strong alert thresholds
# remain unchanged; only display-level option filtering is relaxed for free data.
os.environ.setdefault("MIN_SCORE", "50")
os.environ.setdefault("MIN_OPTION_VOLUME", "25")
os.environ.setdefault("MAX_SPREAD_PCT", "0.25")

import options_radar.catalysts as catalyst_module
import options_radar.stocks as stock_module
from options_radar.live_scanners import PublicStockRadar
from options_radar.strict_catalysts import StrictCatalystScanner

catalyst_module.CatalystScanner = StrictCatalystScanner
stock_module.StockRadar = PublicStockRadar

from export_web import main


if __name__ == "__main__":
    raise SystemExit(main())
