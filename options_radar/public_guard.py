"""Public licence guard: nothing from a closed source reaches a public file.

Collection from Yahoo, Nasdaq.com and Cboe's delayed pages is gated in
source_permissions, but values collected before the gate (and values
derived from them) can still sit inside runtime files that are published
on bot-state and read by the site. This guard runs at the publication
boundary and removes them:

- any object whose source field names a closed source family is dropped
  and counted;
- Contract Guardian rows whose only price evidence comes from a closed
  source are reduced to the contract's identity (OCC terms are public
  facts) with stage LICENSE_BLOCKED, so no stale premium, IV, underlying
  price or derived target is shown as current;
- while no permitted price source exists, the price-driven sections of the
  radar export are emptied and marked, rather than left to age.

Standard library only. source_permissions is loaded by file path so the
guard also runs in dependency-free jobs.
"""
from __future__ import annotations

import importlib.util
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_spec = importlib.util.spec_from_file_location(
    "ghazi_source_permissions_guard", Path(__file__).with_name("source_permissions.py"))
_permissions = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_permissions)

FAMILY_TOKENS = {
    "yahoo": ("yahoo", "yfinance", "yahooquery"),
    "nasdaq_web": ("api.nasdaq.com", "nasdaq screener", "nasdaq us-listed full-market screener", "nasdaq.com"),
    "cboe_delayed": ("cboe delayed", "cdn.cboe.com", "delayed_quotes"),
    "community_gex": ("dhawalc/spx-gamma-levels", "alexduanran/spx-0dte-archive", "squawkflow"),
}
SOURCE_KEYS = ("source", "data_source", "price_source", "quote_source", "provider", "bar_source",
               "chain_source", "feed_source", "fundamental_source", "audit_source")
# Price-driven sections of the radar export (public/data/latest.json).
PRICE_SECTIONS = {
    "stocks": [], "charts": {}, "options": [], "top_calls": [], "top_puts": [], "rejected": [],
    "stock_recommendations": [], "contract_recommendations": [],
}
# Account APIs whose key lets the radar compute prices internally. Public
# display of their data is a separate right that none of them is verified
# for, so they only stop the sections from being emptied when a provider's
# public-display right is recorded here.
PUBLIC_DISPLAY_VERIFIED_KEYS: tuple[str, ...] = ()
# Lists inside these sections are emptied when their rows carry prices.
PRICED_LIST_PARENTS = ("omega", "intelligence", "expiry_radar", "spx_0dte")
PRICE_FIELDS = frozenset({"price", "last_price", "entry", "entry_price", "close", "spot", "underlying_price",
                          "target", "target_1", "target_2", "stop", "stop_price", "bid", "ask", "mark", "premium"})
CONTRACT_IDENTITY = ("contract_symbol", "symbol", "side", "strike", "expiration", "created_at",
                     "original_alert_stage")
NOTE_AR = ("أُزيلت من الملف العام كل قيمة مصدرها غير مسموح بنشره (Yahoo / Nasdaq.com / Cboe delayed) "
           "وكل ما اشتُق منها؛ لا تُعرض أسعار أو أهداف قديمة على أنها حالية.")


def closed_families() -> list[str]:
    return [name for name in FAMILY_TOKENS if not _permissions.allowed(name)]


def family_of(value: Any, families: list[str]) -> str | None:
    if not isinstance(value, str):
        return None
    lowered = value.lower()
    for family in families:
        if any(token in lowered for token in FAMILY_TOKENS[family]):
            return family
    return None


def _tagged_family(obj: dict[str, Any], families: list[str]) -> str | None:
    for key in SOURCE_KEYS:
        family = family_of(obj.get(key), families)
        if family:
            return family
    return None


def redact(obj: Any, families: list[str], counts: dict[str, int]) -> Any:
    """Drop every object tagged with a closed source; count what was dropped."""
    if isinstance(obj, dict):
        family = _tagged_family(obj, families)
        if family:
            counts[family] = counts.get(family, 0) + 1
            return None
        out = {}
        for key, value in obj.items():
            cleaned = redact(value, families, counts)
            if cleaned is None and value is not None and isinstance(value, dict):
                out[key] = {"status": "LICENSE_BLOCKED", "redacted": True}
            else:
                out[key] = cleaned
        return out
    if isinstance(obj, list):
        kept = []
        for item in obj:
            cleaned = redact(item, families, counts)
            if cleaned is None and isinstance(item, dict):
                continue
            kept.append(cleaned)
        return kept
    return obj


def _has_permitted_quote(row: dict[str, Any], families: list[str]) -> bool:
    snapshots = row.get("quote_snapshots")
    if not isinstance(snapshots, list):
        return False
    for snap in snapshots:
        if isinstance(snap, dict) and snap.get("source") and not family_of(snap.get("source"), families) \
                and snap.get("provider_quote_timestamp"):
            return True
    return False


def guard_contract_guardian(report: Any, families: list[str]) -> Any:
    if not isinstance(report, dict) or not families:
        return report
    out = dict(report)
    blocked = 0
    for key in ("active", "terminal_recent"):
        rows = report.get(key)
        if not isinstance(rows, list):
            continue
        guarded = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if _has_permitted_quote(row, families):
                guarded.append(redact(row, families, {}))
                continue
            blocked += 1
            stub = {k: row.get(k) for k in CONTRACT_IDENTITY if k in row}
            stub.update(stage="LICENSE_BLOCKED", terminal=True, data_state="LICENSE_BLOCKED",
                        reason_ar="أسعار هذا العقد من مصدر غير مسموح بنشره؛ توقفت متابعته علنًا.")
            guarded.append(stub)
        out[key] = guarded
    active = [r for r in out.get("active", []) if isinstance(r, dict) and r.get("stage") != "LICENSE_BLOCKED"]
    out["active_count"] = len(active)
    out["license_blocked_count"] = blocked
    if blocked:
        out["report_ar"] = NOTE_AR
    return out


def _empty_priced_lists(block: dict[str, Any], path: str, emptied: list[str], depth: int = 0) -> dict[str, Any]:
    """Empty every list of priced rows inside a section, at any nesting depth."""
    out = dict(block)
    for key, value in block.items():
        if isinstance(value, list) and any(isinstance(row, dict) and PRICE_FIELDS & set(row) for row in value):
            out[key] = []
            emptied.append(f"{path}.{key}")
        elif isinstance(value, dict) and value and all(isinstance(v, dict) for v in value.values()) \
                and any(PRICE_FIELDS & set(v) for v in value.values()):
            # A per-symbol map of priced rows, e.g. target_maps[SYMBOL].
            out[key] = {}
            emptied.append(f"{path}.{key}")
        elif isinstance(value, dict) and depth < 6:
            out[key] = _empty_priced_lists(value, f"{path}.{key}", emptied, depth + 1)
    return out


def _price_sections_allowed() -> bool:
    return any(os.getenv(key, "").strip() for key in PUBLIC_DISPLAY_VERIFIED_KEYS)


def guard_payload(payload: Any, *, kind: str, families: list[str] | None = None) -> Any:
    """Return the public form of a runtime file. kind: latest | guardian | generic."""
    families = closed_families() if families is None else families
    if not isinstance(payload, dict) or not families:
        return payload
    counts: dict[str, int] = {}
    blocked_sections: list[str] = []
    if kind == "guardian":
        result = guard_contract_guardian(payload, families)
    else:
        result = dict(payload)
        if isinstance(result.get("contract_guardian"), dict):
            result["contract_guardian"] = guard_contract_guardian(result["contract_guardian"], families)
        if kind == "latest" and not _price_sections_allowed():
            for section, empty in PRICE_SECTIONS.items():
                if result.get(section):
                    blocked_sections.append(section)
                if section in result:
                    result[section] = type(empty)()
            for parent in PRICED_LIST_PARENTS:
                if isinstance(result.get(parent), dict):
                    result[parent] = _empty_priced_lists(result[parent], parent, blocked_sections)
    result = redact(result, families, counts)
    result["public_license_guard"] = {
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "closed_families": families,
        "redacted_objects": counts,
        "price_sections_emptied": blocked_sections,
        "data_state": "LICENSE_BLOCKED" if (counts or blocked_sections) else "CLEAN",
        "note_ar": NOTE_AR,
    }
    return result
