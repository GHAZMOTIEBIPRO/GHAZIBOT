from __future__ import annotations

import math
import os
import time
from typing import Any

from .expiry_radar import apply_expiry_radar as _apply_base_expiry_radar
from .occ_free_data import OccFreeVolumeClient, fetch_occ_contexts
from .settings import Settings


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _report_context(occ_item: dict[str, Any], bucket: str) -> dict[str, Any]:
    reports = occ_item.get("reports") or {}
    report = reports.get(bucket) or {}
    return report if isinstance(report, dict) else {}


def _report_bucket_for_contract(row: dict[str, Any], fallback: str = "") -> str:
    dte = int(_number(row.get("dte"), -1))
    family = str(row.get("expiry_family") or "").upper()
    if dte == 0 or family == "DAILY":
        return "daily"
    if family == "WEEKLY":
        return "weekly"
    if family in {"STANDARD_MONTHLY", "END_OF_MONTH", "QUARTERLY", "LEAPS"}:
        return "monthly"
    return fallback if fallback in {"daily", "weekly", "monthly"} else ""


def _required_occ_reports(radar: dict[str, Any]) -> dict[str, set[str]]:
    """Return the minimum OCC aggregate reports needed by published contracts.

    OCC is context-only. Fetching D/W/M for every scanned symbol wastes network
    calls and can dominate the expiry pipeline. The funnel is therefore driven
    by contracts that survived selection, with symbols/report families deduped.
    """

    required: dict[str, set[str]] = {}
    tabs = radar.get("tabs") or {}
    if isinstance(tabs, dict) and tabs:
        views = [("", item) for item in tabs.values() if isinstance(item, dict)]
    else:
        profiles = radar.get("profiles") or {}
        views = [
            (str(bucket), item)
            for bucket, item in profiles.items()
            if isinstance(item, dict)
        ]

    for fallback_bucket, view in views:
        for side_key in ("calls", "puts"):
            for row in view.get(side_key) or []:
                if not isinstance(row, dict):
                    continue
                symbol = str(row.get("symbol") or "").upper()
                bucket = _report_bucket_for_contract(row, fallback_bucket)
                if symbol and bucket:
                    required.setdefault(symbol, set()).add(bucket)
    return required


def _enrich_contract(row: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(row)
    if not report.get("success"):
        enriched["occ_official_context"] = {
            "available": False,
            "source": "OCC Volume Query",
            "context_only": True,
        }
        return enriched

    call_volume = int(_number(report.get("call_volume")))
    put_volume = int(_number(report.get("put_volume")))
    total_volume = int(_number(report.get("total_volume")))
    side = str(row.get("option_type") or "").lower()
    side_volume = call_volume if side == "call" else put_volume
    opposite_volume = put_volume if side == "call" else call_volume
    dominance = side_volume / max(opposite_volume, 1)
    aligned = side_volume > 0 and dominance >= 1.20

    context = {
        "available": True,
        "source": "OCC Volume Query",
        "official": True,
        "free_no_key": True,
        "context_only": True,
        "not_live_quote": True,
        "not_options_flow": True,
        "report_date": report.get("report_date"),
        "report_key": report.get("report_key"),
        "call_volume": call_volume,
        "put_volume": put_volume,
        "total_volume": total_volume,
        "put_call_ratio": report.get("put_call_ratio"),
        "side_volume": side_volume,
        "opposite_side_volume": opposite_volume,
        "side_dominance_ratio": round(dominance, 4),
        "aligned_with_contract_side": aligned,
    }
    enriched["occ_official_context"] = context

    reasons = list(enriched.get("reasons") or [])
    if aligned:
        reasons.append(
            f"OCC رسمي: حجم {side.upper()} {side_volume:,} مقابل {opposite_volume:,} للجهة المقابلة"
        )
        # Small ranking aid only. OCC aggregate volume is context, not a quote or
        # transaction-level flow source and therefore cannot promote a contract to A.
        bonus = min(4.0, 1.0 + max(0.0, dominance - 1.0) * 1.5)
        enriched["rank_score"] = round(
            min(100.0, _number(enriched.get("rank_score")) + bonus),
            2,
        )
        enriched["occ_context_bonus"] = round(bonus, 2)
    elif total_volume > 0:
        reasons.append(
            f"OCC رسمي: CALL {call_volume:,} / PUT {put_volume:,} — دون تفوق واضح للجهة"
        )
        enriched["occ_context_bonus"] = 0.0
    enriched["reasons"] = list(dict.fromkeys(reasons))
    return enriched


def _enrich_view(
    view: dict[str, Any],
    contexts: dict[str, dict[str, Any]],
    *,
    fallback_bucket: str = "",
) -> None:
    tier_order = {"A": 3, "B": 2, "C": 1}
    for side_key in ("calls", "puts"):
        rows = view.get(side_key) or []
        enriched_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").upper()
            bucket = _report_bucket_for_contract(row, fallback_bucket)
            report = _report_context(contexts.get(symbol, {}), bucket) if bucket else {}
            enriched_rows.append(_enrich_contract(row, report))
        enriched_rows.sort(
            key=lambda item: (
                tier_order.get(str(item.get("opportunity_tier") or "C"), 0),
                _number(item.get("rank_score")),
            ),
            reverse=True,
        )
        view[side_key] = enriched_rows


def apply_occ_to_expiry_radar(
    payload: dict[str, Any],
    *,
    client: OccFreeVolumeClient | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    radar = payload.get("expiry_radar") or {}
    profiles = radar.get("profiles") or {}
    tabs = radar.get("tabs") or {}
    required = _required_occ_reports(radar)
    symbols = list(required)

    enabled = os.getenv("OCC_FREE_ENABLED", "true").strip().lower() not in {"0", "false", "no"}
    contexts = fetch_occ_contexts(
        symbols,
        client=client,
        enabled=enabled,
        report_keys_by_symbol=required,
    )
    successful_symbols = 0
    successful_reports = 0
    for item in contexts.values():
        reports = item.get("reports") or {}
        count = sum(
            1
            for report in reports.values()
            if isinstance(report, dict) and report.get("success")
        )
        successful_reports += count
        if count:
            successful_symbols += 1

    for bucket, profile in profiles.items():
        if isinstance(profile, dict):
            _enrich_view(profile, contexts, fallback_bucket=bucket)

    for tab in tabs.values():
        if isinstance(tab, dict):
            _enrich_view(tab, contexts)

    requested_reports = sum(len(keys) for keys in required.values())
    occ_seconds = round(time.perf_counter() - started, 4)
    radar["occ_official_context"] = {
        "enabled": enabled,
        "source": "OCC Volume Query",
        "official": True,
        "free_no_key": True,
        "context_only": True,
        "not_live_quote": True,
        "not_options_flow": True,
        "request_funnel": "published_contracts_only",
        "requested_symbols": len(symbols),
        "requested_reports": requested_reports,
        "successful_symbols": successful_symbols,
        "successful_reports": successful_reports,
        "elapsed_seconds": occ_seconds,
        "audit": contexts,
    }
    summary = radar.setdefault("summary", {})
    summary["occ_requested_symbols"] = len(symbols)
    summary["occ_requested_reports"] = requested_reports
    summary["occ_successful_symbols"] = successful_symbols
    summary["occ_successful_reports"] = successful_reports
    policy = radar.setdefault("policy", {})
    policy["occ_is_official_market_context_only"] = True
    policy["occ_cannot_create_tier_a"] = True
    policy["occ_does_not_replace_live_quote_or_flow"] = True
    policy["occ_fetch_funnel"] = "published contracts / needed report families only"

    payload["expiry_radar"] = radar
    payload.setdefault("free_source_status", {})["occ"] = {
        "enabled": enabled,
        "requested_symbols": len(symbols),
        "requested_reports": requested_reports,
        "successful_symbols": successful_symbols,
        "successful_reports": successful_reports,
        "elapsed_seconds": occ_seconds,
        "source": "OCC Volume Query",
        "requires_api_key": False,
        "role": "official aggregate options volume context",
    }
    payload.setdefault("summary", {})["occ_successful_symbols"] = successful_symbols
    return payload


def apply_expiry_radar_with_occ(
    payload: dict[str, Any],
    settings: Settings | None = None,
    *,
    client: OccFreeVolumeClient | None = None,
) -> dict[str, Any]:
    payload = _apply_base_expiry_radar(payload, settings)
    return apply_occ_to_expiry_radar(payload, client=client)
