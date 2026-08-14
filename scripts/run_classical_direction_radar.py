from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

from options_radar.classical_stock_direction import build_direction
from options_radar.optionable_universe import IndependentOptionableUniverse

DEFAULT_OUTPUT = Path("public/data/classical_direction_latest.json")

# Curated U.S. mega/large-cap operating companies with deep underlying liquidity.
# OCC verification is mandatory at runtime. ETFs and indexes are intentionally excluded.
DEFAULT_COMPANIES = (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "TSLA",
    "BRK.B", "JPM", "V", "MA", "WMT", "LLY", "XOM", "COST",
    "NFLX", "ORCL", "HD", "PG", "JNJ", "ABBV", "BAC", "CRM",
    "AMD", "KO", "PEP", "MRK", "CSCO", "ACN", "MCD", "GE",
    "CAT", "UNH", "CVX", "IBM", "QCOM", "TXN", "AMGN", "TMO",
    "LIN", "PM", "RTX", "GS", "MS", "BLK", "C", "AXP",
    "BA", "AMAT", "MU", "NOW", "PANW", "DIS", "UBER", "INTC",
)


def _symbols_from_env() -> list[str]:
    raw = str(os.getenv("CLASSICAL_DIRECTION_SYMBOLS") or "").strip()
    if not raw:
        return list(DEFAULT_COMPANIES)
    output: list[str] = []
    for item in raw.replace(";", ",").split(","):
        symbol = item.strip().upper()
        if symbol and symbol not in output:
            output.append(symbol)
    return output or list(DEFAULT_COMPANIES)


def _yf_symbol(symbol: str) -> str:
    # Yahoo uses dash notation for Berkshire class B while OCC may expose dot notation.
    return {"BRK.B": "BRK-B"}.get(symbol.upper(), symbol.upper())


def _extract_symbol(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    data = raw.copy()
    if not isinstance(data.columns, pd.MultiIndex):
        return data
    candidates = {symbol.upper(), _yf_symbol(symbol).upper()}
    level0 = [str(value).upper() for value in data.columns.get_level_values(0)]
    level1 = [str(value).upper() for value in data.columns.get_level_values(1)]
    for target in candidates:
        if target in level0:
            try:
                return data.xs(target, axis=1, level=0, drop_level=True)
            except KeyError:
                pass
        if target in level1:
            try:
                return data.xs(target, axis=1, level=1, drop_level=True)
            except KeyError:
                pass
    return pd.DataFrame()


def _download(symbols: list[str], *, period: str, interval: str) -> dict[str, pd.DataFrame]:
    if not symbols:
        return {}
    yahoo_symbols = [_yf_symbol(symbol) for symbol in symbols]
    try:
        raw = yf.download(
            tickers=" ".join(yahoo_symbols),
            period=period,
            interval=interval,
            auto_adjust=False,
            prepost=False,
            progress=False,
            threads=True,
            group_by="ticker",
        )
    except Exception:
        return {symbol: pd.DataFrame() for symbol in symbols}
    return {symbol: _extract_symbol(raw, symbol) for symbol in symbols}


def _avg_dollar_volume(frame: pd.DataFrame, lookback: int = 20) -> float:
    if frame is None or frame.empty or "Close" not in frame or "Volume" not in frame:
        return 0.0
    close = pd.to_numeric(frame["Close"], errors="coerce")
    volume = pd.to_numeric(frame["Volume"], errors="coerce")
    value = (close * volume).dropna().tail(lookback)
    if value.empty:
        return 0.0
    result = float(value.mean())
    return result if math.isfinite(result) else 0.0


def run(*, output_path: str | Path = DEFAULT_OUTPUT, max_symbols: int = 48) -> dict[str, Any]:
    requested = _symbols_from_env()[: max(12, int(max_symbols))]
    universe = IndependentOptionableUniverse().build(
        requested,
        max_symbols=len(requested),
        include_cboe_attention=False,
        priority_symbols=(),
    )

    official_set = set(universe.official_symbols)
    if universe.official_verified:
        symbols = [symbol for symbol in requested if symbol in official_set]
    else:
        symbols = []

    daily = _download(symbols, period="1y", interval="1d")
    hourly = _download(symbols, period="60d", interval="60m")
    intraday = _download(symbols, period="10d", interval="15m")
    min_dollar_volume = float(os.getenv("CLASSICAL_MIN_DOLLAR_VOLUME", "100000000"))

    signals: list[dict[str, Any]] = []
    waits: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for symbol in symbols:
        try:
            dollar_volume = _avg_dollar_volume(daily.get(symbol, pd.DataFrame()))
            if dollar_volume < min_dollar_volume:
                waits.append(
                    {
                        "symbol": symbol,
                        "decision": "WAIT",
                        "reason_ar": "تم استبعاده لأن متوسط سيولة السهم النقدية أقل من الحد المطلوب للمسار.",
                        "avg_dollar_volume_20d": dollar_volume,
                    }
                )
                continue
            result = build_direction(
                symbol,
                daily.get(symbol, pd.DataFrame()),
                hourly.get(symbol, pd.DataFrame()),
                intraday.get(symbol, pd.DataFrame()),
            ).as_dict()
            result["avg_dollar_volume_20d"] = dollar_volume
            result["optionability_verified_by_occ"] = True
            result["signal_source"] = "UNDERLYING_CLASSICAL_TECHNICALS_ONLY"
            result["uses_option_chain_data"] = False
            result["rank_score"] = abs(int(result.get("agreement_score") or 0)) * 10 + min(
                20.0,
                math.log10(max(dollar_volume, 1.0)) * 2,
            )
            if result.get("decision") in {"CALL", "PUT"}:
                signals.append(result)
            else:
                waits.append(result)
        except Exception as exc:
            errors[symbol] = f"{type(exc).__name__}: {exc}"

    signals.sort(
        key=lambda row: (
            1 if row.get("priority") == "HIGH" else 0,
            float(row.get("rank_score") or 0),
            float(row.get("avg_dollar_volume_20d") or 0),
        ),
        reverse=True,
    )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "path": "classical_direction",
        "architecture": "underlying_only_classical_direction_v2",
        "summary": {
            "companies_requested": len(requested),
            "occ_optionability_verified": universe.official_verified,
            "companies_verified": len(symbols),
            "signals": len(signals),
            "calls": sum(row.get("decision") == "CALL" for row in signals),
            "puts": sum(row.get("decision") == "PUT" for row in signals),
            "waits": len(waits),
            "minimum_avg_dollar_volume_20d": min_dollar_volume,
        },
        "policy": {
            "company_only": True,
            "occ_used_only_for_optionability_verification": True,
            "option_chain_data_used_for_direction": False,
            "options_flow_used": False,
            "greeks_used": False,
            "rsi_used": False,
            "macd_used": False,
            "vwap_used": False,
            "ict_smc_used": False,
            "news_used_for_direction": False,
            "fundamentals_used_for_direction": False,
            "classical_inputs": [
                "Dow trend structure: higher highs/lows or lower highs/lows",
                "completed swing support/resistance",
                "classical trendlines from swing points",
                "simple moving averages 20/50/200",
                "volume confirmation",
                "breakout/breakdown and retest",
                "double top/double bottom",
                "engulfing/hammer/shooting-star candles",
                "multi-timeframe agreement 1D/1H/15m",
            ],
            "decision_values": ["CALL", "PUT", "WAIT"],
            "wait_is_not_telegram_alert": True,
        },
        "universe": {
            "requested_symbols": requested,
            "verified_symbols": symbols,
            "occ_source": universe.source,
            "occ_cache_used": universe.cache_used,
            "occ_errors": universe.errors,
        },
        "signals": signals,
        "waits": waits,
        "errors": errors,
        "limitations_ar": [
            "CALL وPUT هنا يعبران عن اتجاه متوقع للسهم نفسه فقط؛ لا يتم اختيار عقد أو سترايك أو تاريخ انتهاء.",
            "وجود خيارات على الشركة يتم التحقق منه عبر OCC، لكن بيانات العقود نفسها لا تدخل في القرار.",
            "لا يستخدم هذا المسار RSI أو MACD أو VWAP أو ICT/SMC أو اليونانيات أو تدفق الأوبشن.",
            "إذا لم تتفق القراءة اليومية والساعة و15 دقيقة فالمخرَج WAIT ولا يرسل البوت تنبيه اتجاه.",
        ],
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(destination)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run underlying-only classical CALL/PUT direction radar")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=int(os.getenv("CLASSICAL_DIRECTION_MAX_SYMBOLS", "48")),
    )
    args = parser.parse_args()
    payload = run(output_path=args.output, max_symbols=args.max_symbols)
    summary = payload["summary"]
    print(
        "Classical direction radar: "
        f"verified={summary['companies_verified']} "
        f"calls={summary['calls']} puts={summary['puts']} waits={summary['waits']}"
    )


if __name__ == "__main__":
    main()
