"""Fail-closed validation helpers for free official data feeds.

These checks classify transport payloads; they do not grant execution-grade
authority or create market timestamps.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class FeedValidation:
    accepted: bool
    reason: str
    retryable: bool = False


def classify_http_response(status: int, content_type: str, body: bytes | str) -> FeedValidation:
    """Reject access blocks, HTML error pages and empty official-feed payloads."""
    if status in (401, 403):
        return FeedValidation(False, "access_denied", False)
    if status == 429:
        return FeedValidation(False, "rate_limited", True)
    if status >= 500:
        return FeedValidation(False, "provider_server_error", True)
    if status < 200 or status >= 300:
        return FeedValidation(False, "http_error", False)
    if not body or not body.strip():
        return FeedValidation(False, "empty_payload", False)
    prefix = body[:1024].decode("utf-8", errors="replace") if isinstance(body, bytes) else body[:1024]
    mime = content_type.lower().split(";", 1)[0].strip()
    if mime in ("text/html", "application/xhtml+xml") or prefix.lstrip().lower().startswith(("<!doctype html", "<html")):
        return FeedValidation(False, "html_instead_of_data", False)
    return FeedValidation(True, "transport_valid")


def validate_csv_feed(
    status: int,
    content_type: str,
    body: bytes | str,
    required_columns: tuple[str, ...],
) -> FeedValidation:
    """Ensure an OCC/FINRA-style CSV is actually tabular and has required headers."""
    base = classify_http_response(status, content_type, body)
    if not base.accepted:
        return base
    data = body.decode("utf-8-sig", errors="replace") if isinstance(body, bytes) else body.lstrip("\ufeff")
    try:
        reader = csv.DictReader(io.StringIO(data))
        fields = reader.fieldnames or []
        if not set(required_columns).issubset(set(fields)):
            return FeedValidation(False, "missing_required_columns")
        if next(reader, None) is None:
            return FeedValidation(False, "no_data_rows")
    except (csv.Error, UnicodeError):
        return FeedValidation(False, "malformed_csv")
    return FeedValidation(True, "csv_valid")


def source_metadata(*, provider: str, source_url: str, observed_at: str,
                    quote_timestamp: str | None = None,
                    quote_timestamp_kind: str | None = None) -> dict[str, str | None]:
    """Preserve distinct observation and quote timestamps; never infer one from the other."""
    return {
        "provider": provider,
        "source_url": source_url,
        "observed_at": observed_at,
        "quote_timestamp": quote_timestamp,
        "quote_timestamp_kind": quote_timestamp_kind,
        "execution_grade": False,
    }
