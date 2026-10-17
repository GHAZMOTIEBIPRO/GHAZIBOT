"""Optional GammaGrid research snapshot bridge.

This reads an operator-provided *normalized* JSON export, not a GammaGrid API.
No upstream code is copied. GammaGrid data is Yahoo-derived and is NEVER
counted as independent confirmation or execution-grade options evidence.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.]{0,9}$")
_MAX_BYTES = 262_144
_MAX_SYMBOLS = 40


def _unavailable(reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "reason": reason,
        "source": "GammaGrid",
        "source_family": "yahoo",
        "data_tier": "DELAYED_OR_INDICATIVE",
        "research_only": True,
        "affects_signal_score": False,
        "execution_grade": False,
        "independent_confirmation": False,
        "quote_timestamp_verified": False,
        "symbols": {},
    }


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _finite_number(value: Any, *, positive: bool = False) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        return None
    return number


def load_gammagrid_research_snapshot(
    path: str | Path | None, *, now: datetime | None = None,
    max_export_age: timedelta = timedelta(hours=24),
) -> dict[str, Any]:
    """Load a manually normalized, local research snapshot; fail closed.

    exported_at is the operator's export timestamp, not a quote timestamp.
    It cannot establish freshness of the underlying options data.
    """
    if not path:
        return _unavailable("not_configured")
    file = Path(path)
    try:
        if not file.is_file() or file.stat().st_size > _MAX_BYTES:
            return _unavailable("missing_or_oversized_file")
        payload = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return _unavailable("unreadable_json")
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return _unavailable("unsupported_schema")
    if str(payload.get("source", "")).lower() != "gammagrid":
        return _unavailable("wrong_source")
    exported_at = _timestamp(payload.get("exported_at"))
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must have a timezone")
    current = current.astimezone(timezone.utc)
    if exported_at is None:
        return _unavailable("missing_export_timestamp")
    age = current - exported_at
    if age < timedelta(minutes=-5) or age > max_export_age:
        return _unavailable("export_outside_age_window")
    raw = payload.get("symbols")
    if not isinstance(raw, list) or not 1 <= len(raw) <= _MAX_SYMBOLS:
        return _unavailable("invalid_symbol_count")

    clean: dict[str, dict[str, Any]] = {}
    for row in raw:
        if not isinstance(row, dict):
            return _unavailable("invalid_symbol_record")
        symbol = row.get("symbol")
        if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
            return _unavailable("invalid_symbol")
        if symbol in clean:
            return _unavailable("duplicate_symbol")
        spot = _finite_number(row.get("spot"), positive=True)
        if spot is None:
            return _unavailable("invalid_spot")
        levels: dict[str, float | None] = {}
        for field in ("call_wall", "put_wall", "gamma_flip"):
            val = row.get(field)
            parsed = _finite_number(val, positive=True) if val is not None else None
            if val is not None and parsed is None:
                return _unavailable("invalid_" + field)
            levels[field] = parsed
        gex = row.get("net_gex")
        net_gex = _finite_number(gex) if gex is not None else None
        if gex is not None and net_gex is None:
            return _unavailable("invalid_net_gex")
        clean[symbol] = {
            "symbol": symbol,
            "spot": spot,
            **levels,
            "net_gex": net_gex,
            "research_only": True,
        }

    return {
        "available": True,
        "source": "GammaGrid",
        "source_family": "yahoo",
        "source_url": "https://github.com/gammagrid/gammagrid",
        "data_tier": "DELAYED_OR_INDICATIVE",
        "research_only": True,
        "affects_signal_score": False,
        "execution_grade": False,
        "independent_confirmation": False,
        "quote_timestamp_verified": False,
        "exported_at": exported_at.isoformat(),
        "note_ar": (
            "نسخة بحثية يدوية؛ وقت التصدير ليس وقت التسعير. "
            "GammaGrid وYahoo عائلة مصدر واحدة، ولا تستخدم هذه البيانات للتنفيذ."
        ),
        "symbols": clean,
    }
