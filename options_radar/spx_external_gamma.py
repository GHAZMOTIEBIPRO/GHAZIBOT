from __future__ import annotations

import csv
import io
import json
import math
import os
import urllib.request
from datetime import datetime, timezone
from typing import Any


SQUAWKFLOW_URL = os.getenv(
    "SPX_GAMMA_LEVELS_URL",
    "https://raw.githubusercontent.com/dhawalc/spx-gamma-levels/main/data/latest.json",
)
ARCHIVE_URL = os.getenv(
    "SPX_0DTE_ARCHIVE_URL",
    "https://raw.githubusercontent.com/Alexduanran/spx-0dte-archive/main/gex/summary.csv",
)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _get(url: str, timeout: int = 12) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "GHAZI-Black-Box/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _distance_pct(spot: float, level: float | None) -> float | None:
    if spot <= 0 or level is None or level <= 0:
        return None
    return round((level - spot) / spot * 100.0, 4)


def fetch_daily_gamma(timeout: int = 12) -> dict[str, Any]:
    raw = json.loads(_get(SQUAWKFLOW_URL, timeout).decode("utf-8"))
    if not isinstance(raw, dict) or str(raw.get("symbol", "")).upper() != "SPX":
        raise ValueError("Unexpected SPX gamma-levels payload")
    spot = _number(raw.get("spot"))
    return {
        "available": True,
        "source": "dhawalc/spx-gamma-levels",
        "source_url": SQUAWKFLOW_URL,
        "date": raw.get("date"),
        "spot": spot,
        "net_gex_dollars": _number(raw.get("net_gex_dollars")),
        "zero_gamma_flip": raw.get("zero_gamma_flip"),
        "call_wall": raw.get("call_wall"),
        "put_wall": raw.get("put_wall"),
        "vol_trigger": raw.get("vol_trigger"),
        "abs_gamma_strike": raw.get("abs_gamma_strike"),
        "gamma_regime": raw.get("gamma_regime"),
        "oi_settle_date": raw.get("oi_settle_date"),
        "contracts_analyzed": int(_number(raw.get("contracts_analyzed"))),
        "dist_to_zero_gamma_pct": _distance_pct(spot, _number(raw.get("zero_gamma_flip"))),
        "dist_to_call_wall_pct": _distance_pct(spot, _number(raw.get("call_wall"))),
        "dist_to_put_wall_pct": _distance_pct(spot, _number(raw.get("put_wall"))),
        "dist_to_vol_trigger_pct": _distance_pct(spot, _number(raw.get("vol_trigger"))),
    }


def _archive_rows(timeout: int = 12) -> list[dict[str, Any]]:
    text = _get(ARCHIVE_URL, timeout).decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def fetch_latest_0dte_snapshot(timeout: int = 12) -> dict[str, Any]:
    rows = _archive_rows(timeout)
    if not rows:
        raise ValueError("Empty SPX 0DTE archive")
    row = rows[-1]
    spot = _number(row.get("spot"))
    date_text = str(row.get("date") or "")
    time_text = str(row.get("time") or "")
    timestamp = f"{date_text}T{time_text}:00"
    return {
        "available": True,
        "source": "Alexduanran/spx-0dte-archive",
        "source_url": ARCHIVE_URL,
        "timestamp": timestamp,
        "spot": spot,
        "net_0dte_gex": _number(row.get("net_0dte_gex")),
        "call_gex": _number(row.get("call_gex")),
        "put_gex": _number(row.get("put_gex")),
        "peak_gamma_strike": _number(row.get("peak_gamma_strike")),
        "call_wall": _number(row.get("call_wall")),
        "put_wall": _number(row.get("put_wall")),
        "gamma_flip_proxy": _number(row.get("gamma_flip_proxy")),
        "spot_distance_to_peak": _number(row.get("spot_distance_to_peak")),
        "spot_distance_to_flip": _number(row.get("spot_distance_to_flip")),
        "call_oi": int(_number(row.get("call_oi"))),
        "put_oi": int(_number(row.get("put_oi"))),
        "call_volume": int(_number(row.get("call_volume"))),
        "put_volume": int(_number(row.get("put_volume"))),
        "contracts": int(_number(row.get("contracts"))),
        "delayed": True,
        "note_ar": "بيانات CBOE العامة المؤخرة؛ تصلح كسياق تحقق وليست تغذية تنفيذ لحظية.",
    }


def build_spx_external_context(timeout: int = 12) -> dict[str, Any]:
    context: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": "shadow_context_only",
        "affects_signal_score": False,
        "sources": [],
        "errors": {},
        "research_note_ar": (
            "تمت إضافة طبقة GEX خارجية مستقلة. لا تغيّر الإشارة تلقائياً حتى يثبت "
            "أداؤها عبر outcome learning وwalk-forward validation."
        ),
    }
    try:
        context["daily_gamma"] = fetch_daily_gamma(timeout)
        context["sources"].append("dhawalc/spx-gamma-levels")
    except Exception as exc:
        context["daily_gamma"] = {"available": False}
        context["errors"]["daily_gamma"] = f"{type(exc).__name__}: {exc}"
    try:
        context["intraday_0dte"] = fetch_latest_0dte_snapshot(timeout)
        context["sources"].append("Alexduanran/spx-0dte-archive")
    except Exception as exc:
        context["intraday_0dte"] = {"available": False}
        context["errors"]["intraday_0dte"] = f"{type(exc).__name__}: {exc}"
    context["available"] = bool(context["sources"])
    return context
