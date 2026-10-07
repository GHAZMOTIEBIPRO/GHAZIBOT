from __future__ import annotations

import math
import re
from datetime import date, timedelta
from typing import Any

import requests


CLINICALTRIALS_STUDIES = "https://clinicaltrials.gov/api/v2/studies"

_STOP = {
    "inc",
    "corp",
    "corporation",
    "company",
    "co",
    "ltd",
    "limited",
    "plc",
    "holdings",
    "holding",
    "group",
    "therapeutics",
    "pharmaceuticals",
    "pharmaceutical",
    "biotherapeutics",
    "biosciences",
    "sciences",
    "the",
}


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
        if len(token) > 2 and token not in _STOP
    }


def _similarity(left: str, right: str) -> float:
    a = _tokens(left)
    b = _tokens(right)
    if not a or not b:
        return 0.0
    overlap = len(a & b)
    union = len(a | b)
    jaccard = overlap / union if union else 0.0
    containment = overlap / min(len(a), len(b))
    return max(jaccard, containment * 0.90)


def _date_value(value: Any) -> date | None:
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _sponsor_names(protocol: dict[str, Any]) -> list[str]:
    module = protocol.get("sponsorCollaboratorsModule")
    module = module if isinstance(module, dict) else {}
    names: list[str] = []
    lead = module.get("leadSponsor")
    if isinstance(lead, dict) and str(lead.get("name") or "").strip():
        names.append(str(lead.get("name")).strip())
    for collaborator in module.get("collaborators") or []:
        if isinstance(collaborator, dict) and str(collaborator.get("name") or "").strip():
            names.append(str(collaborator.get("name")).strip())
    return list(dict.fromkeys(names))


def _best_symbol(
    sponsor_names: list[str],
    allowed_symbols: set[str],
    company_names: dict[str, str],
) -> tuple[str, float, str]:
    best_symbol = ""
    best_similarity = 0.0
    best_sponsor = ""
    for sponsor in sponsor_names:
        for symbol in allowed_symbols:
            company = str(company_names.get(symbol) or symbol)
            score = _similarity(sponsor, company)
            if score > best_similarity:
                best_symbol = symbol
                best_similarity = score
                best_sponsor = sponsor
    return best_symbol, best_similarity, best_sponsor


def scan_recent_clinicaltrials(
    *,
    session: requests.Session,
    allowed_symbols: set[str],
    company_names: dict[str, str],
    lookback_days: int = 7,
    page_size: int = 100,
    max_pages: int = 3,
) -> list[dict[str, Any]]:
    """Return recent industry registry updates mapped to tracked symbols.

    ClinicalTrials.gov is an official registry, but sponsors submit the records.
    A result being posted proves that registry results exist; it does not prove
    that the result was positive or negative. Direction is therefore never
    inferred from the registry event itself.
    """
    if not allowed_symbols:
        return []

    start = date.today() - timedelta(days=max(1, int(lookback_days)))
    query = (
        "AREA[LeadSponsorClass]INDUSTRY AND "
        f"AREA[LastUpdatePostDate]RANGE[{start.isoformat()},MAX]"
    )
    params: dict[str, Any] = {
        "format": "json",
        "query.term": query,
        "pageSize": max(1, min(1000, int(page_size))),
        "sort": "LastUpdatePostDate:desc",
    }

    events: list[dict[str, Any]] = []
    page_token = ""
    for _ in range(max(1, int(max_pages))):
        request_params = dict(params)
        if page_token:
            request_params["pageToken"] = page_token
        response = session.get(
            CLINICALTRIALS_STUDIES,
            params=request_params,
            timeout=25,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            break

        for study in payload.get("studies") or []:
            if not isinstance(study, dict):
                continue
            protocol = study.get("protocolSection")
            protocol = protocol if isinstance(protocol, dict) else {}
            sponsors = _sponsor_names(protocol)
            symbol, similarity, sponsor = _best_symbol(
                sponsors,
                allowed_symbols,
                company_names,
            )
            if not symbol or similarity < 0.72:
                continue

            identification = protocol.get("identificationModule")
            identification = identification if isinstance(identification, dict) else {}
            status = protocol.get("statusModule")
            status = status if isinstance(status, dict) else {}
            design = protocol.get("designModule")
            design = design if isinstance(design, dict) else {}

            nct_id = str(identification.get("nctId") or "").strip()
            title = str(
                identification.get("briefTitle")
                or identification.get("officialTitle")
                or nct_id
            ).strip()
            last_update = status.get("lastUpdatePostDateStruct")
            last_update = (
                last_update.get("date")
                if isinstance(last_update, dict)
                else ""
            )
            results_first = status.get("resultsFirstPostDateStruct")
            results_first = (
                results_first.get("date")
                if isinstance(results_first, dict)
                else ""
            )
            update_date = _date_value(last_update)
            results_date = _date_value(results_first)
            overall_status = str(status.get("overallStatus") or "UNKNOWN").upper()
            phases = design.get("phases") if isinstance(design.get("phases"), list) else []
            phase_text = "/".join(str(value) for value in phases if value)

            if results_date is not None and results_date >= start:
                event_date = results_date.isoformat()
                category = "ClinicalTrials results posted"
                headline = f"ClinicalTrials.gov results posted — {title}"
                score = 10
                form = "REGISTRY_RESULTS"
                evidence = (
                    f"Official registry results first posted; sponsor match {similarity:.0%}; "
                    "outcome direction is not inferred"
                )
            elif update_date is not None and update_date >= start:
                event_date = update_date.isoformat()
                category = "Clinical trial registry update"
                if overall_status in {"TERMINATED", "SUSPENDED", "WITHDRAWN"}:
                    headline = (
                        f"ClinicalTrials.gov status {overall_status} — {title}"
                    )
                    score = -8
                    form = "REGISTRY_STATUS"
                    evidence = (
                        f"Registry status={overall_status}; sponsor match {similarity:.0%}; "
                        "reason/effect on efficacy is not inferred"
                    )
                else:
                    headline = f"ClinicalTrials.gov registry update — {title}"
                    score = 4
                    form = "REGISTRY_UPDATE"
                    evidence = (
                        f"Registry updated; status={overall_status}; "
                        f"sponsor match {similarity:.0%}"
                    )
            else:
                continue

            if phase_text:
                evidence += f"; phase={phase_text}"

            events.append(
                {
                    "symbol": symbol,
                    "company": sponsor or company_names.get(symbol, symbol),
                    "event_date": event_date,
                    "category": category,
                    "headline": headline,
                    "score": score,
                    "source": "ClinicalTrials.gov",
                    "form": form,
                    "url": (
                        f"https://clinicaltrials.gov/study/{nct_id}"
                        if nct_id
                        else "https://clinicaltrials.gov/"
                    ),
                    "evidence": evidence,
                }
            )

        page_token = str(payload.get("nextPageToken") or "")
        if not page_token:
            break

    # Multiple fields in one record can produce equivalent observations across
    # pages after a concurrent registry update. Keep one event per trial/type.
    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for event in events:
        key = (
            str(event.get("symbol") or ""),
            str(event.get("form") or ""),
            str(event.get("url") or ""),
        )
        current = deduped.get(key)
        if current is None or str(event.get("event_date") or "") > str(
            current.get("event_date") or ""
        ):
            deduped[key] = event
    return list(deduped.values())
