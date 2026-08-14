from __future__ import annotations

import argparse
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from options_radar.classical_stock_direction import build_direction
from options_radar.market_bars import fetch_bars
from options_radar.optionable_universe import IndependentOptionableUniverse
from options_radar.settings import Settings

DEFAULT_OUTPUT = Path("public/data/classical_direction_latest.json")

# Curated U.S. mega/large-cap operating companies with deep underlying liquidity.
# OCC verification is mandatory at runtime. ETFs and indexes are intentionally excluded.
DEFAULT_COMPANIES = (
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "AVGO",
    "TSLA",
    "PLTR",
    "JPM",
    "V",
    "MA",
    "WMT",
    "LLY",
    "XOM",
    "COST",
    "NFLX",
    "ORCL",
    "HD",
    "PG",
    "JNJ",
    "ABBV",
    "BAC",
    "CRM",
    "AMD",
    "KO",
    "PEP",
    "MRK",
    "CSCO",
    "ACN",
    "MCD",
    "GE",
    "CAT",
    "UNH",
    "CVX",
    "IBM",
    "QCOM",
    "TXN",
    "AMGN",
    "TMO",
    "LIN",
    "PM",
    "RTX",
    "GS",
    "MS",
    "BLK",
    "C",
    "AXP",
    "BA",
    "AMAT",
    "MU",
    "NOW",
    "PANW",
    "DIS",
    "UBER",
    "INTC",
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


def _resample_regular_session(frame: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Build completed New York regular-session bars from normalized 5-minute data."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    data = frame.copy()
    data.index = pd.to_datetime(data.index, utc=True, errors="coerce")
    data = data[~data.index.isna()]
    data = data[~data.index.duplicated(keep="last")].sort_index()
    data = data.tz_convert("America/New_York")
    data = data.between_time("09:30", "15:59", inclusive="both")
    if data.empty:
        return pd.DataFrame()

    rule = f"{int(minutes)}min"
    grouped = data.resample(
        rule,
        origin="start_day",
        offset="30min",
        label="left",
        closed="left",
    )
    bars = grouped.agg(
        {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }
    )
    counts = grouped["Close"].count()
    expected_rows = max(1, int(minutes) // 5)
    bars = bars[counts >= expected_rows]
    bars = bars.dropna(subset=["Open", "High", "Low", "Close"])

    # A signal may only use a closed 15-minute/hourly bar, never the live partial bar.
    now = pd.Timestamp.now(tz="America/New_York")
    bars = bars[(bars.index + pd.Timedelta(minutes=minutes)) <= now]
    return bars.tz_convert("UTC")


def _fetch_symbol_frames(
    symbol: str,
    settings: Settings,
    *,
    end: datetime,
) -> dict[str, Any]:
    daily_result = fetch_bars(
        settings,
        symbol,
        interval="1d",
        period="2y",
        end=end,
    )
    intraday_result = fetch_bars(
        settings,
        symbol,
        interval="5m",
        period="2mo",
        start=end - timedelta(days=60),
        end=end,
    )
    hourly = _resample_regular_session(intraday_result.frame, 60)
    intraday = _resample_regular_session(intraday_result.frame, 15)
    if len(daily_result.frame) < 220 or len(hourly) < 80 or len(intraday) < 80:
        raise ValueError(
            "insufficient valid bars after provider fallback: "
            f"daily={len(daily_result.frame)}, hourly={len(hourly)}, intraday={len(intraday)}"
        )
    return {
        "daily": daily_result.frame,
        "hourly": hourly,
        "intraday": intraday,
        "sources": {
            "daily": daily_result.source,
            "intraday": intraday_result.source,
        },
        "freshness": {
            "daily": daily_result.freshness,
            "intraday": intraday_result.freshness,
        },
    }


def _fetch_all_frames(
    symbols: list[str],
    settings: Settings,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    frames: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    workers = max(1, min(6, int(os.getenv("CLASSICAL_FETCH_WORKERS", "3"))))
    end = datetime.now(timezone.utc)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_fetch_symbol_frames, symbol, settings, end=end): symbol
            for symbol in symbols
        }
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                frames[symbol] = future.result()
            except Exception as exc:  # noqa: BLE001 - preserve failure evidence per symbol
                errors[symbol] = f"{type(exc).__name__}: {exc}"
    return frames, errors


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

    settings = Settings()
    settings.validate()
    frames, errors = _fetch_all_frames(symbols, settings)
    min_dollar_volume = float(os.getenv("CLASSICAL_MIN_DOLLAR_VOLUME", "100000000"))
    min_data_coverage = float(os.getenv("CLASSICAL_MIN_DATA_COVERAGE", "0.60"))

    signals: list[dict[str, Any]] = []
    waits: list[dict[str, Any]] = []
    for symbol in symbols:
        bundle = frames.get(symbol)
        if bundle is None:
            continue
        try:
            dollar_volume = _avg_dollar_volume(bundle["daily"])
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
                bundle["daily"],
                bundle["hourly"],
                bundle["intraday"],
            ).as_dict()
            result["avg_dollar_volume_20d"] = dollar_volume
            result["optionability_verified_by_occ"] = True
            result["signal_source"] = "UNDERLYING_CLASSICAL_TECHNICALS_ONLY"
            result["uses_option_chain_data"] = False
            result["market_data_sources"] = bundle["sources"]
            result["market_data_freshness"] = bundle["freshness"]
            result["rank_score"] = abs(int(result.get("agreement_score") or 0)) * 10 + min(
                20.0,
                math.log10(max(dollar_volume, 1.0)) * 2,
            )
            if result.get("decision") in {"CALL", "PUT"}:
                signals.append(result)
            else:
                waits.append(result)
        except Exception as exc:  # noqa: BLE001 - isolate one symbol from the remaining universe
            errors[symbol] = f"{type(exc).__name__}: {exc}"

    signals.sort(
        key=lambda row: (
            1 if row.get("priority") == "HIGH" else 0,
            float(row.get("rank_score") or 0),
            float(row.get("avg_dollar_volume_20d") or 0),
        ),
        reverse=True,
    )

    evaluated = len(signals) + len(waits)
    coverage = evaluated / len(symbols) if symbols else 0.0
    operational_status = (
        "READY"
        if universe.official_verified and coverage >= min_data_coverage
        else "DEGRADED"
        if evaluated
        else "FAILED"
    )
    source_counts: dict[str, int] = {}
    for bundle in frames.values():
        for source in set(bundle.get("sources", {}).values()):
            source_counts[str(source)] = source_counts.get(str(source), 0) + 1

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
            "data_errors": len(errors),
            "data_coverage_ratio": round(coverage, 4),
            "minimum_data_coverage_ratio": min_data_coverage,
            "operational_status": operational_status,
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
        "market_data": {
            "provider_order_daily": settings.daily_provider_order,
            "provider_order_intraday": settings.intraday_provider_order,
            "source_counts": source_counts,
            "fail_closed": True,
            "missing_data_is_wait": False,
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
    parser = argparse.ArgumentParser(
        description="Run underlying-only classical CALL/PUT direction radar"
    )
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
        f"calls={summary['calls']} puts={summary['puts']} waits={summary['waits']} "
        f"coverage={summary['data_coverage_ratio']:.0%} "
        f"status={summary['operational_status']}"
    )
    if summary["operational_status"] != "READY":
        raise RuntimeError(
            "Classical direction radar failed closed because valid market-data coverage "
            f"was {summary['data_coverage_ratio']:.0%}; required "
            f"{summary['minimum_data_coverage_ratio']:.0%}."
        )


if __name__ == "__main__":
    main()
