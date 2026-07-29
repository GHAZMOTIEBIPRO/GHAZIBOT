from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

import requests

from . import sec_efts
from .settings import Settings

LOGGER = logging.getLogger(__name__)
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_INSTALLED = False


def _headers(settings: Settings) -> dict[str, str]:
    user_agent = settings.sec_user_agent.strip()
    if "@" not in user_agent:
        LOGGER.warning(
            "SEC_USER_AGENT should identify the application and include a contact email"
        )
    return {
        "User-Agent": user_agent,
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }


def _retry_delay(response: requests.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return min(30.0, max(0.0, float(retry_after)))
        except ValueError:
            pass
    return min(8.0, 0.75 * (2**attempt))


def request_efts_json(
    settings: Settings,
    params: dict[str, Any],
    *,
    max_attempts: int = 3,
    timeout: int = 30,
) -> dict[str, Any]:
    """Call SEC EFTS with bounded retries and an explicit 403 diagnosis.

    A 403 is not retried because repeated requests can extend an IP-based SEC
    block. The radar continues through official latest-form feeds, Company
    Facts/submissions data, and the last valid EFTS cache.
    """

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    response: requests.Response | None = None
    for attempt in range(max_attempts):
        response = requests.get(
            sec_efts.EFTS_URL,
            params=params,
            headers=_headers(settings),
            timeout=timeout,
        )
        if response.status_code == 403:
            raise requests.HTTPError(
                "SEC EFTS returned 403 Forbidden. The request is declared, but "
                "the shared runner IP may be blocked; official latest-form, "
                "submissions/Company Facts, and cached-event fallbacks remain active.",
                response=response,
            )
        if response.status_code in _RETRYABLE_STATUSES and attempt + 1 < max_attempts:
            delay = _retry_delay(response, attempt)
            LOGGER.warning(
                "SEC EFTS returned HTTP %s; retrying in %.2fs (%s/%s)",
                response.status_code,
                delay,
                attempt + 1,
                max_attempts,
            )
            time.sleep(delay)
            continue

        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("SEC EFTS returned a non-object JSON payload")
        return payload

    if response is None:
        raise RuntimeError("SEC EFTS request did not execute")
    response.raise_for_status()
    raise RuntimeError("SEC EFTS exhausted retries without a response payload")


def _resilient_query_hits(
    settings: Settings,
    spec: sec_efts.EftsQuery,
    start_date: date,
    end_date: date,
    max_results: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    offset = 0
    request_interval = max(0.10, 1.0 / settings.sec_requests_per_second)

    while offset < max_results:
        payload = request_efts_json(
            settings,
            {
                "q": spec.query,
                "forms": spec.forms,
                "startdt": start_date.isoformat(),
                "enddt": end_date.isoformat(),
                "from": offset,
            },
        )
        if payload.get("timed_out"):
            raise RuntimeError(f"SEC EFTS timed out for {spec.name}")
        hits = ((payload.get("hits") or {}).get("hits") or [])
        if not hits:
            break
        results.extend(hit for hit in hits if isinstance(hit, dict))
        if len(hits) < 100:
            break
        offset += 100
        time.sleep(request_interval)

    return results[:max_results]


def install_sec_efts_resilience() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    sec_efts._query_hits = _resilient_query_hits
    _INSTALLED = True
