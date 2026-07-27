from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import requests

from .sec_efts import _display_identity, _document_url
from .settings import Settings

LOGGER = logging.getLogger(__name__)
EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,6}$")


@dataclass(frozen=True)
class AttentionQuery:
    family: str
    query: str
    forms: str
    score: int
    category: str
    purpose: str
    confidence: float


# Phrase families mirror the SEC Advanced Search workflow requested by the owner,
# but avoid generic single words that create false positives.
ATTENTION_QUERIES: tuple[AttentionQuery, ...] = (
    AttentionQuery(
        "fda_decision",
        '"FDA approval" OR "approved by the FDA" OR "priority review" OR '
        '"breakthrough therapy designation" OR "clinical hold lifted" OR '
        '"new drug application has been accepted" OR "biologics license application has been accepted"',
        "8-K,6-K",
        25,
        "FDA decision / regulatory milestone",
        "fda_regulatory_decision",
        0.94,
    ),
    AttentionQuery(
        "clinical_readout",
        '"met its primary endpoint" OR "met the primary endpoint" OR '
        '"statistically significant" OR "positive topline results" OR '
        '"positive top-line results" OR "phase 3 trial"',
        "8-K,6-K",
        21,
        "Material clinical readout",
        "clinical_readout",
        0.88,
    ),
    AttentionQuery(
        "definitive_ma",
        '"entered into a definitive merger agreement" OR "definitive merger agreement" OR '
        '"will be acquired" OR "tender offer" OR "cash consideration" OR '
        '"agreement and plan of merger"',
        "8-K,6-K,SC 13D,SC 13D/A",
        24,
        "Definitive merger / acquisition",
        "definitive_merger_acquisition",
        0.95,
    ),
    AttentionQuery(
        "strategic_contract",
        '"strategic partnership" OR "material definitive agreement" OR '
        '"collaboration agreement" OR "license agreement" OR "contract award" OR '
        '"government contract" OR "purchase agreement"',
        "8-K,6-K",
        18,
        "Strategic agreement / contract",
        "strategic_contract",
        0.86,
    ),
    AttentionQuery(
        "activist_control",
        '"seek representation on the board" OR "board representation" OR '
        '"strategic alternatives" OR "change in control" OR "solicit proxies" OR '
        '"engage with management"',
        "SC 13D,SC 13D/A",
        18,
        "Active ownership / strategic pressure",
        "active_13d",
        0.91,
    ),
    AttentionQuery(
        "capital_return_guidance",
        '"accelerated share repurchase" OR "share repurchase program" OR '
        '"increased its guidance" OR "raised its guidance" OR "preliminary results" OR '
        '"record revenue"',
        "8-K,6-K",
        15,
        "Capital return / guidance improvement",
        "capital_return_or_guidance",
        0.82,
    ),
    AttentionQuery(
        "material_downside",
        '"registered direct offering" OR "at-the-market offering" OR "public offering" OR '
        '"clinical hold" OR "did not meet the primary endpoint" OR '
        '"failed to meet the primary endpoint" OR "going concern" OR '
        '"delisting notice" OR "termination of the merger agreement"',
        "8-K,6-K,S-1,S-1/A,S-3,S-3/A,424B5",
        -25,
        "Material downside / dilution",
        "material_downside",
        0.94,
    ),
)


def _headers(settings: Settings) -> dict[str, str]:
    return {
        "User-Agent": settings.sec_user_agent,
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
    }


def _item_materiality(items: list[str]) -> tuple[float, list[str]]:
    bonus = 0.0
    reasons: list[str] = []
    values = {str(item).strip() for item in items}
    if "1.01" in values:
        bonus += 2.0
        reasons.append("8-K Item 1.01 material agreement")
    if "2.01" in values:
        bonus += 3.0
        reasons.append("8-K Item 2.01 transaction completion")
    if "2.02" in values:
        bonus += 1.0
        reasons.append("8-K Item 2.02 financial results")
    if "5.02" in values:
        bonus += 1.0
        reasons.append("8-K Item 5.02 leadership change")
    if "7.01" in values or "8.01" in values:
        bonus += 1.0
        reasons.append("8-K public disclosure")
    return bonus, reasons


def discover_attention_events(
    settings: Settings,
    *,
    lookback_days: int = 30,
    max_results_per_query: int = 150,
) -> list[dict[str, Any]]:
    end_date = date.today()
    start_date = end_date - timedelta(days=max(1, lookback_days))
    events: dict[tuple[str, str], dict[str, Any]] = {}

    for spec in ATTENTION_QUERIES:
        offset = 0
        while offset < max_results_per_query:
            params = {
                "q": spec.query,
                "forms": spec.forms,
                "startdt": start_date.isoformat(),
                "enddt": end_date.isoformat(),
                "from": offset,
            }
            try:
                response = requests.get(
                    EFTS_URL,
                    params=params,
                    headers=_headers(settings),
                    timeout=35,
                )
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:
                LOGGER.warning("Precision SEC EFTS failed for %s: %s", spec.family, exc)
                break

            hits = ((payload.get("hits") or {}).get("hits") or [])
            if not hits:
                break
            for hit in hits:
                if not isinstance(hit, dict):
                    continue
                source = hit.get("_source") or {}
                symbol, company, cik = _display_identity(source)
                if not _SYMBOL.fullmatch(symbol):
                    continue
                adsh = str(source.get("adsh") or "")
                form = str(source.get("form") or "")
                file_date = str(source.get("file_date") or end_date.isoformat())
                items = [str(value) for value in (source.get("items") or []) if str(value)]
                item_bonus, item_reasons = _item_materiality(items)
                signed_bonus = item_bonus if spec.score > 0 else -item_bonus
                score = max(-25.0, min(25.0, float(spec.score) + signed_bonus))
                description = str(source.get("file_description") or source.get("file_type") or form)
                url = _document_url(hit)
                evidence = [f"precision EFTS family: {spec.family}"] + item_reasons
                event = {
                    "symbol": symbol,
                    "company": company or symbol,
                    "event_date": file_date,
                    "category": spec.category,
                    "headline": f"{description} — {company or symbol}",
                    "score": score,
                    "source": "SEC EDGAR Precision Full-Text",
                    "form": form,
                    "url": url,
                    "evidence": "; ".join(evidence),
                    "event_value": None,
                    "confidence": spec.confidence,
                    "purpose": spec.purpose,
                    "cik": cik,
                    "accession": adsh,
                    "items": items,
                    "query_family": spec.family,
                }
                key = (adsh or url or f"{symbol}:{file_date}", spec.family)
                previous = events.get(key)
                if previous is None or abs(score) > abs(float(previous.get("score", 0))):
                    events[key] = event
            if len(hits) < 100:
                break
            offset += 100
            time.sleep(0.18)

    return sorted(
        events.values(),
        key=lambda row: (str(row.get("event_date", "")), abs(float(row.get("score", 0)))),
        reverse=True,
    )


def precision_sec_symbols(settings: Settings, *, lookback_days: int = 30) -> list[str]:
    return list(
        dict.fromkeys(
            str(row.get("symbol", "")).upper()
            for row in discover_attention_events(settings, lookback_days=lookback_days)
            if _SYMBOL.fullmatch(str(row.get("symbol", "")).upper())
        )
    )
