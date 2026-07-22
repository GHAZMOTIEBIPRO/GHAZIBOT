from __future__ import annotations

import argparse
import logging
import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pandas as pd

from options_radar.catalysts import CatalystScanner
from options_radar.providers import load_universe
from options_radar.scanner import OptionsRadar
from options_radar.settings import Settings
from options_radar.stocks import StockRadar


class DashboardRequestHandler(SimpleHTTPRequestHandler):
    """Serve the generated public dashboard with fresh JSON responses."""

    def end_headers(self) -> None:
        if self.path.startswith("/data/") or self.path.endswith("latest.json"):
            self.send_header("Cache-Control", "no-store, max-age=0")
        else:
            self.send_header("Cache-Control", "public, max-age=300")
        super().end_headers()


def serve_dashboard() -> int:
    """Serve public/ on the host and port required by Render web services."""

    public_dir = Path(__file__).resolve().parent / "public"
    index_file = public_dir / "index.html"
    if not index_file.exists():
        raise FileNotFoundError(f"Dashboard entrypoint not found: {index_file}")

    raw_port = os.getenv("PORT", "10000")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError(f"PORT must be an integer, got {raw_port!r}") from exc

    handler = partial(DashboardRequestHandler, directory=str(public_dir))
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    logging.getLogger(__name__).info(
        "Serving GHAZI Market Radar from %s on 0.0.0.0:%s",
        public_dir,
        port,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Dashboard server stopped")
    finally:
        server.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Free-data scanner for US stocks, catalysts and options."
    )
    parser.add_argument("--symbols", nargs="*", help="Defaults to data/universe.txt")
    parser.add_argument("--universe", default="data/universe.txt")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument(
        "--mode", choices=["all", "stocks", "options", "catalysts"], default="all"
    )
    parser.add_argument("--verbose", action="store_true")
    return parser


def _print_frame(name: str, frame: pd.DataFrame, output: str) -> None:
    print(f"\n{name}")
    if frame.empty:
        print("No candidates passed the filters.")
        return
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 260)
    print(frame.head(20).to_string(index=False))
    print(f"CSV: {Path(output).resolve()}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    settings = Settings()
    settings.validate()
    symbols = args.symbols or load_universe(args.universe)
    catalysts = pd.DataFrame()
    stocks = pd.DataFrame()

    if args.mode in {"all", "catalysts", "stocks", "options"}:
        catalysts = CatalystScanner(settings).scan(symbols, lookback_days=7)
        if args.mode in {"all", "catalysts"}:
            _print_frame("CATALYSTS", catalysts, "results/catalysts_latest.csv")

    if args.mode in {"all", "stocks", "options"}:
        stock_result = StockRadar(settings).scan(
            symbols,
            catalysts=catalysts,
            top=max(args.top, 10),
            output_csv="results/stocks_latest.csv",
        )
        stocks = stock_result.opportunities
        if args.mode in {"all", "stocks"}:
            print(f"Market regime: {stock_result.regime}")
            _print_frame("TOP STOCKS", stocks, "results/stocks_latest.csv")

    if args.mode in {"all", "options"}:
        option_symbols = (
            stocks["symbol"].head(max(8, args.top)).tolist()
            if not stocks.empty
            else symbols[:12]
        )
        option_result = OptionsRadar(settings).scan(
            option_symbols,
            top=args.top,
            output_csv="results/options_latest.csv",
            catalysts=catalysts,
        )
        print(
            f"Options provider: {option_result.provider} | "
            f"Market regime: {option_result.regime}"
        )
        _print_frame("TOP OPTIONS", option_result.opportunities, "results/options_latest.csv")
        if option_result.alerts:
            print("\nNew dashboard setups:\n" + "\n\n".join(option_result.alerts))
        if option_result.errors:
            for symbol, error in option_result.errors.items():
                print(f"Option error {symbol}: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    if not sys.argv[1:] and os.getenv("PORT"):
        raise SystemExit(serve_dashboard())
    raise SystemExit(main())
