from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from . import sec_efts
from .settings import Settings

LOGGER = logging.getLogger(__name__)
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_INSTALLED = False
EFTS_CIRCUIT_PATH = Path(os.getenv("SEC_EFTS_CIRCUIT_PATH", "data/cache/sec_efts_circuit.json"))
_DEFAULT_403_COOLDOWN_MINUTES = 360


class SecEftsCircuitOpen(RuntimeError):
    def __init__(self, retry_after: datetime) -> None:
        self.retry_after = retry_after
        self.http_status = 403
        super().__init__(
            "SEC EFTS circuit is open after a previous 403; no HTTP request was sent. "
            f"Retry after {retry_after.isoformat()}. Official latest-form, submissions/Company Facts, "
            "and cached-event fallbacks remain active."
        )


def _headers(settings: Settings) -> dict[str, str]:
    user_agent = str(getattr(settings, "sec_user_agent", "GHAZI Market Radar")).strip()
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


def _status_code(response: Any) -> int:
    """Support real requests responses and minimal legacy test doubles."""

    value = getattr(response, "status_code", 200)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 200


def _retry_delay(response: Any, attempt: int) -> float:
    headers = getattr(response, "headers", {}) or {}
    retry_after = headers.get("Retry-After")
    if retry_after:
        try:
            return min(30.0, max(0.0, float(retry_after)))
        except ValueError:
            pass
    return min(8.0, 0.75 * (2**attempt))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _cooldown_minutes() -> int:
    raw = os.getenv("SEC_EFTS_403_COOLDOWN_MINUTES", str(_DEFAULT_403_COOLDOWN_MINUTES))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = _DEFAULT_403_COOLDOWN_MINUTES
    return max(30, min(1440, value))


def _circuit_path() -> Path:
    return EFTS_CIRCUIT_PATH


def _read_circuit() -> dict[str, Any]:
    path = _circuit_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_circuit(payload: dict[str, Any]) -> None:
    path = _circuit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _raise_if_circuit_open() -> None:
    circuit = _read_circuit()
    if circuit.get("state") != "open":
        return
    retry_after = _parse_timestamp(circuit.get("retry_after"))
    if retry_after is None or retry_after <= _utc_now():
        return
    raise SecEftsCircuitOpen(retry_after)


def _record_forbidden() -> None:
    now = _utc_now()
    previous = _read_circuit()
    previous_count = previous.get("consecutive_403", 0)
    try:
        previous_count = int(previous_count)
    except (TypeError, ValueError):
        previous_count = 0
    retry_after = now + timedelta(minutes=_cooldown_minutes())
    _write_circuit(
        {
            "schema_version": 1,
            "state": "open",
            "http_status": 403,
            "blocked_at": now.isoformat(),
            "retry_after": retry_after.isoformat(),
            "cooldown_minutes": _cooldown_minutes(),
            "consecutive_403": previous_count + 1,
            "reason": "SEC EFTS returned 403 from the current runner; suppress repeated requests until cooldown expires.",
            "fallbacks_active": True,
            "decision_authority": False,
        }
    )


def _record_recovery_if_needed() -> None:
    previous = _read_circuit()
    if not previous:
        return
    _write_circuit(
        {
            "schema_version": 1,
            "state": "closed",
            "http_status": 200,
            "recovered_at": _utc_now().isoformat(),
            "last_blocked_at": previous.get("blocked_at") or previous.get("last_blocked_at"),
            "consecutive_403": 0,
            "fallbacks_active": True,
            "decision_authority": False,
        }
    )


def request_efts_json(
    settings: Settings,
    params: dict[str, Any],
    *,
    max_attempts: int = 3,
    timeout: int = 30,
) -> dict[str, Any]:
    """Call SEC EFTS with bounded retries and a persistent 403 circuit breaker.

    A 403 is not retried. It opens a durable cooldown so later workflows can
    skip the same futile request while official latest-form feeds, Company
    Facts/submissions data, and the last valid EFTS cache remain active.
    """

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    _raise_if_circuit_open()

    response: Any = None
    for attempt in range(max_attempts):
        response = requests.get(
            sec_efts.EFTS_URL,
            params=params,
            headers=_headers(settings),
            timeout=timeout,
        )
        status_code = _status_code(response)
        if status_code == 403:
            _record_forbidden()
            raise requests.HTTPError(
                "SEC EFTS returned 403 Forbidden. The request is declared, but "
                "the shared runner IP may be blocked; a persistent cooldown was opened. "
                "Official latest-form, submissions/Company Facts, and cached-event fallbacks remain active.",
                response=response,
            )
        if status_code in _RETRYABLE_STATUSES and attempt + 1 < max_attempts:
            delay = _retry_delay(response, attempt)
            LOGGER.warning(
                "SEC EFTS returned HTTP %s; retrying in %.2fs (%s/%s)",
                status_code,
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
        _record_recovery_if_needed()
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
    requests_per_second = float(getattr(settings, "sec_requests_per_second", 8.0) or 8.0)
    request_interval = max(0.10, 1.0 / max(requests_per_second, 0.1))

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
