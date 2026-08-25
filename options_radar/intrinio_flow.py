from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests


INTRINIO_BASE = "https://api-v2.intrinio.com"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number


def _normalize_contract(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()
    if text.startswith("O") and len(text) > 10:
        text = text[1:]
    return text


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class IntrinioFlowConfig:
    api_key: str = os.getenv("INTRINIO_API_KEY", "").strip()
    source: str = os.getenv("INTRINIO_OPTIONS_SOURCE", "delayed").strip().lower() or "delayed"
    max_age_minutes: int = int(os.getenv("INTRINIO_FLOW_MAX_AGE_MINUTES", "90"))
    timeout_seconds: int = int(os.getenv("INTRINIO_TIMEOUT_SECONDS", "15"))


class IntrinioUnusualActivityClient:
    """Optional trade-level unusual-activity enrichment.

    The core radar remains fully functional without this client. When configured,
    it adds OPRA-derived unusual trade evidence (large/block/sweep, premium and
    bid/ask at execution). It never claims buy-to-open because that cannot be
    proven from execution side alone.
    """

    def __init__(self, config: IntrinioFlowConfig | None = None):
        self.config = config or IntrinioFlowConfig()
        self.session = requests.Session()

    @property
    def enabled(self) -> bool:
        return bool(self.config.api_key)

    def fetch_symbol(self, symbol: str) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        response = self.session.get(
            f"{INTRINIO_BASE}/options/unusual_activity/{symbol.upper()}",
            params={"source": self.config.source, "page_size": 100},
            auth=(self.config.api_key, ""),
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("trades") if isinstance(payload, dict) else []
        return [row for row in (rows or []) if isinstance(row, dict)]

    def recent_by_contract(self, symbol: str) -> dict[str, list[dict[str, Any]]]:
        now = datetime.now(timezone.utc)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in self.fetch_symbol(symbol):
            contract = _normalize_contract(row.get("contract"))
            if not contract:
                continue
            timestamp = _parse_ts(row.get("timestamp"))
            if timestamp is not None:
                age = (now - timestamp).total_seconds() / 60.0
                if age < 0 or age > self.config.max_age_minutes:
                    continue
            grouped.setdefault(contract, []).append(row)
        return grouped


def _activity_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    ranked = sorted(
        rows,
        key=lambda row: (_number(row.get("total_value")), _number(row.get("total_size"))),
        reverse=True,
    )
    primary = ranked[0]
    total_value = sum(max(0.0, _number(row.get("total_value"))) for row in rows)
    total_size = sum(max(0.0, _number(row.get("total_size"))) for row in rows)
    sentiments = [str(row.get("sentiment") or "").strip().lower() for row in rows]
    bullish = sum(1 for value in sentiments if value == "bullish")
    bearish = sum(1 for value in sentiments if value == "bearish")
    sentiment = "bullish" if bullish > bearish else "bearish" if bearish > bullish else "neutral"
    types = [str(row.get("type") or "").strip().lower() for row in rows]
    confirmed_sweep = "sweep" in types
    confirmed_block = "block" in types
    return {
        "verified_trade_flow": True,
        "verified_flow_source": "Intrinio unusual activity / OPRA",
        "verified_flow_source_url": "https://docs.intrinio.com/documentation/web_api/get_unusual_activity_v2",
        "verified_unusual_type": "sweep" if confirmed_sweep else "block" if confirmed_block else (types[0] if types else "large"),
        "verified_unusual_sentiment": sentiment,
        "verified_unusual_total_value": round(total_value, 2),
        "verified_unusual_total_size": int(total_size),
        "verified_unusual_print_count": len(rows),
        "verified_ask_at_execution": _number(primary.get("ask_at_execution")),
        "verified_bid_at_execution": _number(primary.get("bid_at_execution")),
        "verified_average_price": _number(primary.get("average_price")),
        "verified_underlying_price_at_execution": _number(primary.get("underlying_price_at_execution")),
        "verified_flow_timestamp": str(primary.get("timestamp") or ""),
        "sweep_confirmed": confirmed_sweep,
        "block_confirmed": confirmed_block,
        "opening_position_confirmed": False,
        "buy_to_open_confirmed": False,
        "flow_semantics_ar": "جهة التنفيذ والسويب/البلوك موثقة من بيانات تداول/عرض، لكن فتح مركز جديد لا يتأكد إلا من تغير OI بعد التسوية.",
    }


def enrich_with_intrinio_flow(
    contracts: list[dict[str, Any]],
    *,
    client: IntrinioUnusualActivityClient | None = None,
    max_symbols: int = 12,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    client = client or IntrinioUnusualActivityClient()
    if not client.enabled or not contracts:
        return [dict(row) for row in contracts], {}

    symbols: list[str] = []
    for row in contracts:
        symbol = str(row.get("symbol") or "").upper().strip()
        if symbol and symbol not in symbols:
            symbols.append(symbol)
        if len(symbols) >= max(1, max_symbols):
            break

    by_symbol: dict[str, dict[str, list[dict[str, Any]]]] = {}
    errors: dict[str, str] = {}
    for symbol in symbols:
        try:
            by_symbol[symbol] = client.recent_by_contract(symbol)
        except Exception as exc:
            errors[symbol] = f"{type(exc).__name__}: {exc}"

    output: list[dict[str, Any]] = []
    for raw in contracts:
        row = dict(raw)
        symbol = str(row.get("symbol") or "").upper().strip()
        contract = _normalize_contract(row.get("contract_symbol"))
        matches = by_symbol.get(symbol, {}).get(contract, [])
        if matches:
            summary = _activity_summary(matches)
            row.update(summary)
            evidence = row.get("flow_evidence") if isinstance(row.get("flow_evidence"), dict) else {}
            evidence = dict(evidence)
            evidence.update(
                {
                    "trade_quote_level_evidence": True,
                    "execution_side_observed": True,
                    "sweep_confirmed": summary.get("sweep_confirmed") is True,
                    "block_confirmed": summary.get("block_confirmed") is True,
                    "opening_position_confirmed": False,
                    "buy_to_open_confirmed": False,
                    "verified_flow_source": summary.get("verified_flow_source"),
                    "verified_flow_source_url": summary.get("verified_flow_source_url"),
                }
            )
            row["flow_evidence"] = evidence
        output.append(row)
    return output, errors
