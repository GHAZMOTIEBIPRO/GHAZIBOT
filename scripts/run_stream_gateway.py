from __future__ import annotations

import argparse
import os

from options_radar.free_autonomy import enforce_free_autonomy_environment
from options_radar.stream_gateway import configured_stream_symbols, run_alpaca_gateway


def main() -> None:
    parser = argparse.ArgumentParser(description="Run BLACK BOX Omega Alpaca market-data gateway")
    parser.add_argument(
        "--snapshot",
        default=os.getenv("DATA_FABRIC_STREAM_SNAPSHOT", "data/live/stream_snapshot.json"),
    )
    parser.add_argument(
        "--seconds",
        type=int,
        default=int(os.getenv("STREAM_RUN_SECONDS", "0")),
        help="0 means run until stopped when used on a suitable host",
    )
    args = parser.parse_args()

    # Never let a stale SIP/OPRA setting turn the no-cost autonomous mode into a
    # paid data dependency.  Indicative options remain context-grade downstream.
    enforce_free_autonomy_environment()

    stocks, options = configured_stream_symbols()
    run_alpaca_gateway(
        stock_symbols=stocks,
        option_contracts=options,
        snapshot_path=args.snapshot,
        run_seconds=max(0, args.seconds),
    )


if __name__ == "__main__":
    main()
