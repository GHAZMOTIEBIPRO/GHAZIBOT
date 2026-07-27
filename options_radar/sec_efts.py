from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from .settings import Settings

LOGGER = logging.getLogger(__name__)
EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
CACHE_PATH = Path("data/cache/sec_efts_events.json")
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,6}$")


@dataclass(frozen=True)
class EftsQuery:
    name: str
    query: str
    forms: str
    score: int
    category: str
    purpose: str
    confidence: float


# Separate searches preserve event meaning and prevent a generic word such as
# "acquisition" from overpowering a precise FDA or merger phrase.
EFTS_QUERIES: tuple[EftsQuery, ...] = (
    EftsQuery(
        "fda_material",
        '"FDA approval" OR "approved by the FDA" OR "breakthrough therapy designation" '
        'OR "clinical hold lifted" OR "met its primary endpoint" OR "positive topline" '
        'OR "positive top-line"',
        "8-K,6-K",
        24,
        "FDA / clinical milestone",
        "fda_or_clinical_milestone",
        0.90,
    ),
    EftsQuery(
        "merger_acquisition",
        '"definitive merger agreement" OR "merger agreement" OR "tender offer" '
        'OR "to acquire" OR "acquisition of"',
        "8-K,6-K,SC 13D,SC 13D/A",
        23,
        "Merger / acquisition",
        "merger_or_acquisition",
        0.90,
    ),
    EftsQuery(
        "strategic_commercial",
        '"strategic partnership" OR "collaboration agreement" OR "license agreement" '
        'OR "government contract" OR "contract award"',
        "8-K,6-K",
        18,
        "Strategic / commercial agreement",
        "strategic_commercial_event",
        0.84,
    ),
    EftsQuery(
        "capital_return",
        '"share repurchase" OR "stock repurchase" OR "accelerated share repurchase"',
        "8-K,6-K",
        15,
        "Capital return",
        "share_repurchase",
        0.82,
    ),
    EftsQuery(
        "material_risk",
        '"registered direct offering" OR "at-the-market offering" OR "public offering" '
        'OR "clinical hold" OR "failed to meet the primary endpoint" OR "going concern" '
        'OR "delisting notice" OR "termination of the merger agreement"',
        "8-K,6-K,S-1,S-1/A,S-3,S-3/A,424B5",
        -24,
        "Material risk / dilution",
        "material_risk_or_dilution",
        0.90,
    ),
)


def _headers(settings: Settings) -> dict[str, str]:
    return {
        "User-Agent": settings.sec_user_agent,
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
    }


def _display_identity(source: dict[str, Any]) -> tuple[str, str, str]:
    names = source.get("display_names") or []
    display = str(names[0] if names else "").strip()
    ciks = source.get("ciks") or []
    cik = str(ciks[0] if ciks else "").zfill(10)

    symbol = ""
    # EDGAR display names normally look like: Company Name (TICKER) (CIK 000...).
    for token in re.findall(r"\(([^()]*)\)", display):
        candidate = token.strip().upper()
        if candidate.startswith("CIK"):
            continue
        if _SYMBOL.fullmatch(candidate):
            symbol = candidate
            break

    company = re.sub(r"\s*\([^()]*\)\s*", " ", display).strip()
    company = re.sub(r"\s+", " ", company)
    return symbol, company, cik


def _document_url(hit: dict[str, Any]) -> str:
    source = hit.get("_source") or {}
    identifier = str(hit.get("_id") or "")
    adsh = str(source.get("adsh") or "")
    filename = ""
    if ":" in identifier:
        hit_adsh, filename = identifier.split(":", 1)
        adsh = adsh or hit_adsh
    ciks = source.get("ciks") or []
    cik = str(ciks[0] if ciks else "").lstrip("0") or "0"
    if not adsh or not filename:
        return ""
    folder = adsh.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{filename}"


def _cache_write(events: list[dict[str, Any]]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events": events,
    }
    temporary = CACHE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(CACHE_PATH)


def _cache_read(start_date: date) -> list[dict[str, Any]]:
    if not CACHE_PATH.exists():
        return []
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    events = payload.get("events") if isinstance(payload, dict) else []
    if not isinstance(events, list):
        return []
    return [
        row for row in events
        if isinstance(row, dict) and str(row.get("event_date", "")) >= start_date.isoformat()
    ]


def _query_hits(
    settings: Settings,
    spec: EftsQuery,
    start_date: date,
    end_date: date,
    max_results: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    offset = 0
    while offset < max_results:
        params = {
            "q": spec.query,
            "forms": spec.forms,
            "startdt": start_date.isoformat(),
            "enddt": end_date.isoformat(),
            "from": offset,
        }
        response = requests.get(
            EFTS_URL,
            params=params,
            headers=_headers(settings),
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("timed_out"):
            raise RuntimeError(f"SEC EFTS timed out for {spec.name}")
        hits = ((payload.get("hits") or {}).get("hits") or [])
        if not hits:
            break
        results.extend(hit for hit in hits if isinstance(hit, dict))
        if len(hits) < 100:
            break
        offset += 100
        time.sleep(0.16)
    return results[:max_results]


def discover_sec_fulltext_events(
    settings: Settings,
    *,
    lookback_days: int = 14,
    max_results_per_query: int = 100,
) -> list[dict[str, Any]]:
    """Discover market-moving filings using the same EFTS index as SEC search.

    Results are deduplicated by accession and event family. The cache is used only
    when every live query fails, so a transient SEC block does not erase the most
    recent evidence from the dashboard.
    """

    end_date = date.today()
    start_date = end_date - timedelta(days=max(1, lookback_days))
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    live_successes = 0

    for spec in EFTS_QUERIES:
        try:
            hits = _query_hits(
                settings,
                spec,
                start_date,
                end_date,
                max_results_per_query,
            )
            live_successes += 1
        except Exception as exc:
            LOGGER.warning("SEC EFTS query failed for %s: %s", spec.name, exc)
            continue

        for hit in hits:
            source = hit.get("_source") or {}
            symbol, company, cik = _display_identity(source)
            if not symbol:
                continue
            adsh = str(source.get("adsh") or "")
            form = str(source.get("form") or "")
            file_date = str(source.get("file_date") or end_date.isoformat())
            items = [str(value) for value in (source.get("items") or []) if str(value)]
            description = str(source.get("file_description") or source.get("file_type") or form)
            url = _document_url(hit)
            evidence_parts = [f"EFTS phrase family: {spec.name}"]
            if items:
                evidence_parts.append(f"8-K items {', '.join(items[:6])}")
            if description:
                evidence_parts.append(description)

            event = {
                "symbol": symbol,
                "company": company or symbol,
                "event_date": file_date,
                "category": spec.category,
                "headline": f"{description} — {company or symbol}",
                "score": spec.score,
                "source": "SEC EDGAR Full-Text",
                "form": form,
                "url": url,
                "evidence": "; ".join(evidence_parts),
                "event_value": None,
                "confidence": spec.confidence,
                "purpose": spec.purpose,
                "cik": cik,
                "accession": adsh,
                "items": items,
                "query_family": spec.name,
            }
            key = (adsh or url or f"{symbol}:{file_date}:{description}", spec.name)
            previous = by_key.get(key)
            if previous is None or abs(int(event["score"])) > abs(int(previous["score"])):
                by_key[key] = event

    events = sorted(
        by_key.values(),
        key=lambda row: (str(row.get("event_date", "")), abs(int(row.get("score", 0)))),
        reverse=True,
    )
    if live_successes:
        _cache_write(events)
        return events

    cached = _cache_read(start_date)
    if cached:
        LOGGER.warning("SEC EFTS unavailable; using %d cached events", len(cached))
    return cached


def sec_fulltext_symbols(settings: Settings, *, lookback_days: int = 14) -> list[str]:
    return list(
        dict.fromkeys(
            str(row.get("symbol", "")).upper()
            for row in discover_sec_fulltext_events(settings, lookback_days=lookback_days)
            if _SYMBOL.fullmatch(str(row.get("symbol", "")).upper())
        )
    )
