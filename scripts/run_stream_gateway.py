from __future__ import annotations

import argparse
import os

from options_radar.stream_gateway import configured_stream_symbols, run_alpaca_gateway


def main() -> None:
    parser = argparse.ArgumentParser(description="Run BLACK BOX Omega always-on Alpaca market-data gateway")
    parser.add_argument(
        "--snapshot",
        default=os.getenv("DATA_FABRIC_STREAM_SNAPSHOT", "data/live/stream_snapshot.json"),
    )
    parser.add_argument(
        "--seconds",
        type=int,
        default=int(os.getenv("STREAM_RUN_SECONDS", "0")),
        help="0 means run until stopped",
    )
    args = parser.parse_args()
    stocks, options = configured_stream_symbols()
    run_alpaca_gateway(
        stock_symbols=stocks,
        option_contracts=options,
        snapshot_path=args.snapshot,
        run_seconds=max(0, args.seconds),
    )


if __name__ == "__main__":
    main()
