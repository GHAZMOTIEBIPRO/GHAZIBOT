from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from options_radar.chart_first_consensus import build_chart_first_directional_signals
from options_radar.chart_strike_intelligence import (
    build_chart_context,
    enrich_contract_with_chart_and_strike,
)
from options_radar.hybrid_fetcher import DataFetcher
from options_radar.settings import Settings
from scripts import run_options_radar_independent as legacy

DEFAULT_INPUT = legacy.DEFAULT_INPUT
DEFAULT_OUTPUT = legacy.DEFAULT_OUTPUT


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _chart_symbols(payload: dict[str, Any], maximum: int) -> list[str]:
    gamma_maps = payload.get("gamma_maps") if isinstance(payload.get("gamma_maps"), dict) else {}
    symbols = [str(symbol).upper() for symbol in gamma_maps if str(symbol).strip()]
    if len(symbols) < maximum:
        contracts = [row for row in payload.get("contracts", []) if isinstance(row, dict)]
        contracts.sort(
            key=lambda row: (
                _number(row.get("flow_rank_score")),
                _number(row.get("flow_momentum_score")),
                _number(row.get("score")),
            ),
            reverse=True,
        )
        for row in contracts:
            symbol = str(row.get("symbol") or "").upper().strip()
            if symbol and symbol not in symbols:
                symbols.append(symbol)
            if len(symbols) >= maximum:
                break
    return symbols[:maximum]


def _build_charts(symbols: list[str], settings: Settings) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}

    def worker(symbol: str) -> tuple[str, dict[str, Any]]:
        fetcher = DataFetcher(settings)
        return symbol, build_chart_context(symbol, fetcher=fetcher)

    output: dict[str, dict[str, Any]] = {}
    workers = max(1, min(4, len(symbols)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(worker, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                resolved_symbol, chart = future.result()
                output[resolved_symbol] = chart
            except Exception as exc:
                output[symbol] = {
                    "symbol": symbol,
                    "score": 0.0,
                    "direction": "unavailable",
                    "available_timeframes": 0,
                    "timeframes": {},
                    "errors": {"chart": f"{type(exc).__name__}: {exc}"},
                    "institutional_activity_proxy_score": 50.0,
                    "institutional_activity_proxy_only": True,
                }
    return output


def _enrich_contracts(
    contracts: list[dict[str, Any]],
    *,
    charts: dict[str, dict[str, Any]],
    gamma_maps: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw in contracts:
        row = dict(raw)
        symbol = str(row.get("symbol") or "").upper().strip()
        chart = charts.get(
            symbol,
            {
                "symbol": symbol,
                "score": 0.0,
                "direction": "not_analyzed",
                "available_timeframes": 0,
                "timeframes": {},
                "institutional_activity_proxy_score": 50.0,
                "institutional_activity_proxy_only": True,
            },
        )
        gamma_map = gamma_maps.get(symbol, {})
        enriched = enrich_contract_with_chart_and_strike(
            row,
            chart=chart,
            gamma_map=gamma_map,
        )
        rationale = list(enriched.get("rationale_ar") or [])
        strike_reasons = list(enriched.get("strike_reasons_ar") or [])
        chart_reasons = list(chart.get("reasons_ar") or [])
        enriched["rationale_ar"] = [
            "أولاً: الشارت متعدد الفريمات ثم الجاما/السيولة ثم العقد.",
            *chart_reasons[:3],
            *strike_reasons[:5],
            *rationale,
        ][:14]
        output.append(enriched)
    return output


def run(
    *,
    universe_path: str | Path = DEFAULT_INPUT,
    output_path: str | Path = DEFAULT_OUTPUT,
    max_symbols: int = 80,
    top_per_side: int = 15,
) -> dict[str, Any]:
    payload = legacy.run(
        universe_path=universe_path,
        output_path=output_path,
        max_symbols=max_symbols,
        top_per_side=top_per_side,
    )
    settings = Settings()
    gamma_maps = (
        payload.get("gamma_maps")
        if isinstance(payload.get("gamma_maps"), dict)
        else {}
    )
    maximum = max(
        1,
        min(15, int(os.getenv("OPTIONS_CHART_FIRST_MAX_SYMBOLS", "10"))),
    )
    symbols = _chart_symbols(payload, maximum)
    charts = _build_charts(symbols, settings)
    contracts = _enrich_contracts(
        [row for row in payload.get("contracts", []) if isinstance(row, dict)],
        charts=charts,
        gamma_maps=gamma_maps,
    )

    strict_min = float(os.getenv("OPTIONS_STRICT_MIN_SCORE", "85"))
    side_edge = float(os.getenv("OPTIONS_STRICT_SIDE_EDGE", "6"))
    directional = build_chart_first_directional_signals(
        contracts,
        minimum_score=strict_min,
        minimum_side_edge=side_edge,
        max_signals=max(
            1,
            min(12, int(os.getenv("OPTIONS_STRICT_MAX_SIGNALS", "8"))),
        ),
    )
    # Keep the stable schema contract consumed by existing validation/UI while
    # exposing the stricter chart-first policy separately.
    for signal in directional:
        signal["chart_selection_policy"] = signal.get("selection_policy")
        signal["selection_policy"] = "one_side_one_contract_per_symbol_strict_consensus"

    calls = [
        row for row in contracts if str(row.get("option_type") or "").lower() == "call"
    ]
    puts = [
        row for row in contracts if str(row.get("option_type") or "").lower() == "put"
    ]

    def order_key(row: dict[str, Any]) -> tuple[float, float, float]:
        return (
            _number(row.get("strike_intelligence_score")),
            _number(row.get("flow_rank_score")),
            _number(row.get("score")),
        )

    calls.sort(key=order_key, reverse=True)
    puts.sort(key=order_key, reverse=True)

    payload["chart_architecture"] = "independent_options_chart_first_v4"
    payload["contracts"] = contracts
    payload["top_calls"] = calls
    payload["top_puts"] = puts
    payload["directional_signals"] = directional
    payload["chart_contexts"] = charts
    summary = payload.setdefault("summary", {})
    summary["chart_first_enabled"] = True
    summary["chart_symbols_analyzed"] = len(charts)
    summary["chart_first_directional_signals"] = len(directional)
    summary["directional_signals"] = len(directional)
    summary["free_alert_eligible"] = sum(
        1 for row in directional if row.get("free_alert_eligible") is True
    )
    summary["gamma_flip_symbols"] = sum(
        1
        for row in gamma_maps.values()
        if isinstance(row, dict) and row.get("gamma_flip") is not None
    )

    policy = payload.setdefault("flow_policy", {})
    policy.update(
        {
            "chart_first_required_for_strict_signal": True,
            "chart_timeframes": ["1D", "15m", "5m"],
            "chart_external_fetch_policy": "1D + 5m only; 15m resampled locally from 5m",
            "candlestick_pattern_is_context_not_proof": True,
            "institutional_activity_is_proxy_only": True,
            "institutional_proxy_is_verified_position": False,
            "gamma_flip_is_positioning_proxy": True,
            "strike_selection_policy": (
                "chart alignment + expected move + gamma wall/flip + OI/volume liquidity + existing strict execution gates"
            ),
        }
    )
    payload.setdefault("limitations", []).extend(
        [
            "Chart-first institutional activity is inferred from price/VWAP/relative-volume behavior; free data cannot verify institutional ownership or dealer hedging positions.",
            "Gamma flip, call wall and put wall are model-derived GEX/OI proxies, not observed dealer inventory.",
            "Yahoo/YFinance option quotes remain research-grade when no licensed OPRA source is active.",
        ]
    )

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(destination)
    return payload
