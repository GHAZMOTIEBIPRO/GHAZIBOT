from __future__ import annotations

import math
import os
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
        enriched["rank_score"] = round(min(100.0, _number(enriched.get("rank_score")) + bonus), 2)
        enriched["occ_context_bonus"] = round(bonus, 2)
    elif total_volume > 0:
        reasons.append(f"OCC رسمي: CALL {call_volume:,} / PUT {put_volume:,} — دون تفوق واضح للجهة")
        enriched["occ_context_bonus"] = 0.0
    enriched["reasons"] = list(dict.fromkeys(reasons))
    return enriched


def apply_occ_to_expiry_radar(
    payload: dict[str, Any],
    *,
    client: OccFreeVolumeClient | None = None,
) -> dict[str, Any]:
    radar = payload.get("expiry_radar") or {}
    profiles = radar.get("profiles") or {}
    symbols = list((radar.get("provider_audit") or {}).keys())
    if not symbols:
        symbols = [str(row.get("symbol") or "").upper() for row in payload.get("stocks", []) if isinstance(row, dict)]

    enabled = os.getenv("OCC_FREE_ENABLED", "true").strip().lower() not in {"0", "false", "no"}
    contexts = fetch_occ_contexts(symbols, client=client, enabled=enabled)
    successful_symbols = 0
    successful_reports = 0
    for item in contexts.values():
        reports = item.get("reports") or {}
        count = sum(1 for report in reports.values() if isinstance(report, dict) and report.get("success"))
        successful_reports += count
        if count:
            successful_symbols += 1

    tier_order = {"A": 3, "B": 2, "C": 1}
    for bucket, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        for side_key in ("calls", "puts"):
            rows = profile.get(side_key) or []
            enriched_rows: list[dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                symbol = str(row.get("symbol") or "").upper()
                report = _report_context(contexts.get(symbol, {}), bucket)
                enriched_rows.append(_enrich_contract(row, report))
            enriched_rows.sort(
                key=lambda item: (
                    tier_order.get(str(item.get("opportunity_tier") or "C"), 0),
                    _number(item.get("rank_score")),
                ),
                reverse=True,
            )
            profile[side_key] = enriched_rows

    radar["occ_official_context"] = {
        "enabled": enabled,
        "source": "OCC Volume Query",
        "official": True,
        "free_no_key": True,
        "context_only": True,
        "not_live_quote": True,
        "not_options_flow": True,
        "successful_symbols": successful_symbols,
        "successful_reports": successful_reports,
        "audit": contexts,
    }
    summary = radar.setdefault("summary", {})
    summary["occ_successful_symbols"] = successful_symbols
    summary["occ_successful_reports"] = successful_reports
    policy = radar.setdefault("policy", {})
    policy["occ_is_official_market_context_only"] = True
    policy["occ_cannot_create_tier_a"] = True
    policy["occ_does_not_replace_live_quote_or_flow"] = True

    payload["expiry_radar"] = radar
    payload.setdefault("free_source_status", {})["occ"] = {
        "enabled": enabled,
        "successful_symbols": successful_symbols,
        "successful_reports": successful_reports,
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
