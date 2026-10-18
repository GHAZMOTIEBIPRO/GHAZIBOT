"""Public-domain GitHub-listed issuer name discovery for research-only news.

Source datasets (ODC-PDDL-1.0):
https://github.com/datasets/nasdaq-listings
https://github.com/datasets/nyse-other-listings

This is a name lookup, NOT market-data entitlement, SEC authentication, a
live listing confirmation, or independent news/price confirmation.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

LISTINGS = (
    ("nasdaq", "https://raw.githubusercontent.com/datasets/nasdaq-listings/main/data/nasdaq-listed.csv",
     "Symbol", "Security Name"),
    ("nyse", "https://raw.githubusercontent.com/datasets/nyse-other-listings/main/data/nyse-listed.csv",
     "ACT Symbol", "Company Name"),
)
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z])?$")
_BAD_SECURITY = re.compile(
    r"\b(?:ETF|ETN|Warrant(?:s)?|Right(?:s)?|Units?|Depositary Shares? "
    r"representing preferred|Preferred Stock|Trust Units|Notes Due|Debt Securities)\b",
    re.IGNORECASE,
)
_SECURITY_SUFFIX = re.compile(
    r"\s+(?:Class\s+[A-Z]\s+)?(?:Common Stock|Ordinary Shares?|"
    r"American Depositary Shares?|ADR|Class A Shares?).*$",
    re.IGNORECASE,
)
_CORPORATE_SUFFIX = re.compile(
    r"[, ]+(?:Inc\.?|Incorporated|Corporation|Corp\.?|"
    r"Ltd\.?|Limited|PLC|Co\.?)$", re.IGNORECASE,
)
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 &'.,/()-]{4,105}$")
_MAX_BYTES = 650_000
_MIN_SOURCE_ROWS = 100
_MAX_DISCOVERIES = 24


def _utc(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def _symbol(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    name = value.strip().upper()
    return name if _SYMBOL.fullmatch(name) else None


def clean_issuer_name(value: Any) -> str | None:
    """Reject fund/derivative listings and normalize a single clear issuer name."""
    if not isinstance(value, str) or _BAD_SECURITY.search(value):
        return None
    name = re.sub(r"\s+", " ", value).strip()
    # Nasdaq often formats the instrument as "Issuer - Class A Common Stock".
    # A security suffix cannot be used as the issuer's news-search name.
    if " - " in name:
        left, right = name.split(" - ", 1)
        if re.search(
            r"\b(?:Common Stock|Common Shares?|Ordinary Shares?|"
            r"Class [A-Z]|American Depositary)\b", right, re.IGNORECASE,
        ):
            name = left
    name = _SECURITY_SUFFIX.sub("", name)
    name = _CORPORATE_SUFFIX.sub("", name).strip(" ,.-")
    if not _NAME.fullmatch(name) or len(name) < 6:
        return None
    if len(name.split()) == 1 and name.lower() in {
        "global", "holdings", "financial", "technology", "international", "company",
    }:
        return None
    return name


def symbols_from_brief(path: Path | None, *, now: datetime) -> tuple[str, ...]:
    """Consider only timestamped real radar rows, not arbitrary untrusted URLs."""
    if path is None or now.tzinfo is None:
        return ()
    try:
        if not path.is_file() or path.stat().st_size > 180_000:
            return ()
        payload = json.loads(path.read_text(encoding="utf-8"))
        stamp = _utc(payload.get("source_generated_at") or payload.get("generated_at"))
        if (payload.get("schema") != "ghazi.public_decision.v1"
                or stamp is None or not timedelta(0) <= now - stamp <= timedelta(hours=72)
                or not isinstance(payload.get("stocks"), list)):
            return ()
        candidates = []
        for row in payload["stocks"][:120]:
            if not isinstance(row, dict):
                continue
            symbol = _symbol(row.get("symbol"))
            if symbol and symbol not in candidates:
                candidates.append(symbol)
        return tuple(candidates[:60])
    except (OSError, ValueError, TypeError, AttributeError):
        return ()


def _parse_source(raw: bytes, symbol_column: str, name_column: str) -> dict[str, str]:
    if not isinstance(raw, bytes) or len(raw) > _MAX_BYTES:
        raise ValueError("Oversized or invalid public listing CSV")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        if not reader.fieldnames or not {symbol_column, name_column}.issubset(reader.fieldnames):
            raise ValueError("Listing CSV schema changed")
        mapped: dict[str, str] = {}
        rows = 0
        for row in reader:
            rows += 1
            if rows > 15000:
                raise ValueError("Listing CSV too large")
            symbol = _symbol(row.get(symbol_column))
            name = clean_issuer_name(row.get(name_column))
            if symbol and name:
                mapped.setdefault(symbol, name)
        if rows < _MIN_SOURCE_ROWS:
            raise ValueError("Incomplete exchange listing")
        return mapped
    except UnicodeError as exc:
        raise ValueError("Listing CSV decode failed") from exc


def _saved(previous: dict, *, now: datetime) -> dict | None:
    if not isinstance(previous, dict) or previous.get("schema") != "free_public_intelligence_v1":
        return None
    obj = previous.get("issuer_directory")
    if not isinstance(obj, dict) or obj.get("source_family") != "github_public_listing_mirrors":
        return None
    stamp = _utc(obj.get("downloaded_at"))
    if stamp is None or not timedelta(0) <= now - stamp <= timedelta(hours=72):
        return None
    raw = obj.get("issuers")
    if not isinstance(raw, dict) or len(raw) > 120:
        return None
    valid = {s: name for s, name in raw.items()
             if _symbol(s) == s and clean_issuer_name(name) == name}
    return {**obj, "issuers": valid}


def resolve_public_issuers(
    symbols: tuple[str, ...] | list[str], *, now: datetime,
    previous: dict | None = None, session: Any = requests,
) -> dict[str, Any]:
    """At most TWO GitHub raw CSV requests once/day, with bounded failure cache.

    A missing listing never authorizes fuzzy ticker headlines or fabricates news.
    Previously saved names are shown only as stale metadata for up to 72 hours.
    """
    current = now.astimezone(timezone.utc)
    requested = []
    for value in symbols:
        name = _symbol(value)
        if name and name not in requested:
            requested.append(name)
    requested = requested[:_MAX_DISCOVERIES]
    cache = _saved(previous or {}, now=current)
    checked = _utc(cache.get("downloaded_at")) if cache else None
    if checked is not None and current - checked < timedelta(hours=24):
        return {**cache, "status": "CACHED_GITHUB_LISTINGS",
                "issuers": {s: cache["issuers"][s] for s in requested if s in cache["issuers"]}}
    found: dict[str, str] = {}
    errors: dict[str, str] = {}
    sources = []
    for exchange, url, ticker_col, name_col in LISTINGS:
        try:
            response = session.get(url, timeout=12, headers={
                "User-Agent": "GHAZIBOT-Open-Listing-Research/1.0",
                "Accept": "text/csv",
            })
            response.raise_for_status()
            contents = getattr(response, "content", b"")
            items = _parse_source(contents, ticker_col, name_col)
            sources.append({"exchange": exchange, "url": url, "status": "PARSED"})
            for symbol in requested:
                if symbol in items:
                    found.setdefault(symbol, items[symbol])
        except (requests.RequestException, ValueError, TypeError) as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            errors[exchange] = f"HTTP_{code}" if isinstance(code, int) else type(exc).__name__
            sources.append({"exchange": exchange, "url": url, "status": "UNAVAILABLE"})
    if not found and cache:
        return {**cache, "status": "STALE_LISTING_METADATA_ONLY", "errors": errors,
                "issuers": {s: cache["issuers"][s] for s in requested if s in cache["issuers"]}}
    return {
        "source_family": "github_public_listing_mirrors",
        "source_license": "ODC-PDDL-1.0",
        "source_of_truth": "NASDAQ Trader derived public listing snapshots",
        "downloaded_at": current.isoformat(),
        "status": "AVAILABLE_CONTEXT" if not errors else "PARTIAL_CONTEXT",
        "issuers": found,
        "source_checks": sources,
        "errors": errors,
        "research_only": True,
        "not_sec_authenticated": True,
        "not_live_listing_or_price": True,
    }
