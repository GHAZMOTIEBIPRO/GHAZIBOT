from __future__ import annotations

import math
from typing import Any, Iterable


def _number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _first_number(row: dict[str, Any], names: Iterable[str]) -> tuple[float | None, str | None]:
    for name in names:
        value = _number(row.get(name))
        if value is not None:
            return value, name
    return None, None


def _candidate_level(
    value: float | None,
    label: str,
    source: str,
    modeled: bool = False,
) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "price": round(value, 4),
        "label": label,
        "source": source,
        "provenance": "MODELED" if modeled else "SOURCE_DERIVED",
    }


def build_target_map(stock: dict[str, Any]) -> dict[str, Any]:
    """Build an explainable underlying target map without pretending levels are guarantees."""

    symbol = str(stock.get("symbol") or "").upper()
    side = str(stock.get("setup_side") or "").lower()
    direction = 1 if side == "call" else -1 if side == "put" else 0
    price = _number(stock.get("price"))
    entry_low = _number(stock.get("entry_low"))
    entry_high = _number(stock.get("entry_high"))
    invalidation, invalidation_source = _first_number(stock, ("invalidation", "stop"))
    existing_t1, t1_source = _first_number(stock, ("target_1", "underlying_target_1"))
    existing_t2, t2_source = _first_number(stock, ("target_2", "underlying_target_2"))

    structural_specs = (
        ("pdh", "Previous Day High"),
        ("previous_day_high", "Previous Day High"),
        ("pdl", "Previous Day Low"),
        ("previous_day_low", "Previous Day Low"),
        ("previous_week_high", "Previous Week High"),
        ("pwh", "Previous Week High"),
        ("previous_week_low", "Previous Week Low"),
        ("pwl", "Previous Week Low"),
        ("premarket_high", "Premarket High"),
        ("pmh", "Premarket High"),
        ("premarket_low", "Premarket Low"),
        ("pml", "Premarket Low"),
        ("resistance20", "20D Resistance"),
        ("support20", "20D Support"),
        ("anchored_vwap", "Anchored VWAP"),
        ("vwap", "VWAP"),
        ("gap_fill", "Gap Fill"),
    )
    candidates: list[dict[str, Any]] = []
    seen: set[float] = set()
    for key, label in structural_specs:
        value = _number(stock.get(key))
        if value is None or value in seen:
            continue
        seen.add(value)
        candidates.append(
            {
                "price": round(value, 4),
                "label": label,
                "source": key,
                "provenance": "SOURCE_DERIVED",
            }
        )

    for value, label, source in (
        (existing_t1, "Existing T1", t1_source or "target_1"),
        (existing_t2, "Existing T2", t2_source or "target_2"),
    ):
        if value is not None and value not in seen:
            seen.add(value)
            candidates.append(
                {
                    "price": round(value, 4),
                    "label": label,
                    "source": source,
                    "provenance": "SOURCE_DERIVED",
                }
            )

    atr = _number(stock.get("atr"))
    atr_source = "atr"
    if atr is None:
        atr = _number(stock.get("atr14"))
        atr_source = "atr14"
    if atr is None and price is not None and existing_t1 is not None:
        implied = abs(existing_t1 - price) / 1.5
        if implied > 0:
            atr = implied
            atr_source = "implied_from_existing_target_1"

    if price is not None and atr is not None and atr > 0 and direction:
        for multiple, label in ((1.5, "ATR 1.5x"), (3.0, "ATR 3.0x"), (4.5, "ATR 4.5x")):
            value = price + direction * multiple * atr
            if value not in seen:
                candidates.append(
                    {
                        "price": round(value, 4),
                        "label": label,
                        "source": atr_source,
                        "provenance": "MODELED",
                    }
                )

    if price is not None and direction:
        directional = [
            row for row in candidates
            if (row["price"] - price) * direction > 0
        ]
        directional.sort(key=lambda row: abs(row["price"] - price))
    else:
        directional = []

    selected = directional[:3]
    while len(selected) < 3:
        selected.append({})

    missing_inputs: list[str] = []
    structural_keys = {key for key, _ in structural_specs}
    if not any(stock.get(key) is not None for key in structural_keys):
        missing_inputs.append("structural_levels")
    if atr is None:
        missing_inputs.append("atr")
    if entry_low is None or entry_high is None:
        missing_inputs.append("entry_zone")
    if invalidation is None:
        missing_inputs.append("invalidation")

    structural_count = sum(row.get("provenance") == "SOURCE_DERIVED" for row in directional)
    target_quality = min(
        100,
        35
        + (15 if entry_low is not None and entry_high is not None else 0)
        + (15 if invalidation is not None else 0)
        + min(25, structural_count * 8)
        + (10 if atr is not None else 0),
    )

    return {
        "symbol": symbol,
        "direction": side.upper() if side else "UNKNOWN",
        "entry": {
            "low": round(entry_low, 4) if entry_low is not None else None,
            "high": round(entry_high, 4) if entry_high is not None else None,
            "source": "stock_setup",
        },
        "invalidation": {
            "price": round(invalidation, 4) if invalidation is not None else None,
            "source": invalidation_source,
        },
        "t1": selected[0] or None,
        "t2": selected[1] or None,
        "t3": selected[2] or None,
        "candidate_levels": directional[:10],
        "target_map_quality": target_quality,
        "missing_inputs": missing_inputs,
        "statement": "Reference zones if the scenario continues; not a price forecast or guarantee.",
    }


def build_target_maps(stocks: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(stock.get("symbol") or "").upper(): build_target_map(stock)
        for stock in stocks
        if isinstance(stock, dict) and str(stock.get("symbol") or "").strip()
    }
