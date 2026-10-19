"""Fail-closed, small-body semantics for public market-data health probes.

HTTP 200 means a server was reached, not that usable financial data exists.
This module never grants quote, market-flow, or signal authority.
"""
from __future__ import annotations

import csv
import io
import json
import math
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from typing import Any


def _date_status(value: Any, now: datetime, *, max_days: int) -> dict[str, Any]:
    try:
        if not isinstance(value, str):
            raise ValueError("not a date")
        day = date.fromisoformat(value)
    except ValueError:
        return {"ok": False, "content_status": "OBSERVATION_DATE_MISSING_OR_INVALID"}
    age = (now.astimezone(timezone.utc).date() - day).days
    return {
        "ok": 0 <= age <= max_days,
        "content_status": ("OBSERVATION_DATE_VALID" if 0 <= age <= max_days
                           else "STALE_OR_FUTURE_OBSERVATION"),
        "source_observation_date": day.isoformat(),
        "observation_age_days": age,
    }


def _positive(value: Any) -> bool:
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError, OverflowError):
        return False


def validate_source_payload(
    source: dict[str, Any], payload: bytes, content_type: str,
    *, now: datetime | None = None,
) -> dict[str, Any]:
    """Validate *content*, not just endpoint reachability (bounded caller body).

    A green health row is not a tradeable quote or a free redistribution grant.
    Unsupported roles fail closed rather than silently becoming healthy.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("timezone-aware now is required")
    role = source.get("role")
    if role == "options_volume_context_contract":
        # This is a documentation *webpage*, not an OCC observation endpoint.
        return {"ok": False, "content_status": "DOCUMENTATION_ONLY_NO_DATA"}

    if role == "macro_context":
        try:
            root = ET.fromstring(payload)
            tags = {node.tag.rsplit("}", 1)[-1].upper() for node in root.iter()}
            valid = ("NEW_DATE" in tags or "CLOSE_DATE" in tags) and any(
                x.startswith("BC_") for x in tags
            )
        except ET.ParseError:
            valid = False
        return {"ok": valid, "content_status": (
            "TREASURY_XML_OBSERVATIONS_VERIFIED" if valid else "NO_YIELD_OBSERVATIONS"
        )}

    if role == "gamma_history_validation":
        try:
            rows = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
            last = None
            for row in rows:
                if isinstance(row, dict) and row.get("date"):
                    last = row
            if not last or not _positive(last.get("spot")):
                raise ValueError("no spot observation")
            status = _date_status(last.get("date"), now, max_days=5)
        except (UnicodeDecodeError, ValueError, csv.Error):
            return {"ok": False, "content_status": "MALFORMED_GAMMA_HISTORY"}
        return {**status, "content_status": (
            "DATED_GAMMA_RESEARCH_ONLY" if status["ok"] else status["content_status"]
        )}

    if role == "daily_short_sale_volume_context" and "json" not in content_type.lower():
        return {"ok": False, "content_status": "FINRA_NON_JSON_RESPONSE"}

    try:
        data = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return {"ok": False, "content_status": "MALFORMED_JSON"}

    if role == "identity_and_filings_fallback":
        valid = (isinstance(data, dict)
                 and str(data.get("cik")) == "320193"
                 and isinstance(data.get("filings"), dict)
                 and isinstance(data["filings"].get("recent"), dict))
        return {"ok": valid, "content_status": (
            "SEC_ISSUER_IDENTITY_VERIFIED" if valid else "SEC_IDENTITY_INVALID"
        )}
    if role == "fundamentals_and_share_history":
        valid = (isinstance(data, dict)
                 and str(data.get("cik")) == "320193"
                 and isinstance(data.get("facts"), dict) and bool(data["facts"]))
        return {"ok": valid, "content_status": (
            "SEC_FACTS_STRUCTURE_VERIFIED" if valid else "SEC_FACTS_INVALID"
        )}
    if role == "daily_short_sale_volume_context":
        if not isinstance(data, list) or not data:
            return {"ok": False, "content_status": "NO_FINRA_OBSERVATIONS"}
        latest = None
        for row in data[:50]:
            if not isinstance(row, dict):
                continue
            if (isinstance(row.get("tradeReportDate"), str)
                    and _positive(row.get("totalParQuantity"))
                    and row.get("shortParQuantity") is not None):
                day = row["tradeReportDate"][:10]
                try:
                    value = date.fromisoformat(day)
                except ValueError:
                    continue
                if latest is None or value > latest:
                    latest = value
        status = _date_status(latest.isoformat() if latest else None, now, max_days=10)
        return {**status, "content_status": (
            "FINRA_DATED_RESEARCH_ONLY" if status["ok"] else status["content_status"]
        )}
    if role == "gamma_cross_validation":
        if not isinstance(data, dict) or not _positive(data.get("spot")):
            return {"ok": False, "content_status": "MALFORMED_GAMMA_SNAPSHOT"}
        status = _date_status(data.get("date"), now, max_days=5)
        return {**status, "content_status": (
            "DATED_GAMMA_RESEARCH_ONLY" if status["ok"] else status["content_status"]
        )}
    return {"ok": False, "content_status": "UNSUPPORTED_SOURCE_ROLE"}
